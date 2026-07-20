"""AWS IAM Identity Center (Identity Store) client.

Reads (list groups/users/memberships) plus the three write verbs the poller is
allowed to perform: **create group**, **add member**, **remove member**. There
are deliberately no delete-group or delete-user methods — destructive cleanup is
the nightly reconciler's job, so the capability simply does not exist here.

Whether the writes actually fire is decided one layer up (``apply.py``), gated by
``NOT_DRY_RUN``. ``boto3`` is imported lazily so the pure logic core and its tests
never require it.
"""

from __future__ import annotations

from scim_sync.adapters.aws_errors import error_code
from scim_sync.adapters.metrics import CallCounter
from scim_sync.models import IdentityGroup


def discover_identity_store_id(region: str | None) -> str:
    """Look up the Identity Store id from the SSO instance in this account.

    Mirrors v1's ``aws sso-admin list-instances`` discovery so the id never has to
    be pasted by hand. Raises if no instance is found.
    """
    import boto3  # lazy: only needed for live runs

    client = boto3.client("sso-admin", region_name=region)
    instances = client.list_instances().get("Instances", [])
    if not instances:
        raise RuntimeError(
            "No IAM Identity Center instance found in this account/region. "
            "Set SSO_IDENTITY_STORE_ID explicitly or check AWS_REGION/credentials."
        )
    return instances[0]["IdentityStoreId"]


class IdentityStoreClient:
    def __init__(self, identity_store_id: str, region: str | None, counter: CallCounter) -> None:
        import boto3  # lazy: only needed for live runs

        self._store_id = identity_store_id
        self._counter = counter
        self._client = boto3.client("identitystore", region_name=region)

    def list_groups(self) -> list[IdentityGroup]:
        """List all groups (without members). Matching keys on DisplayName == slug."""
        groups: list[IdentityGroup] = []
        paginator = self._client.get_paginator("list_groups")
        for page in paginator.paginate(IdentityStoreId=self._store_id):
            self._counter.incr("identitystore.list_groups")
            for g in page.get("Groups", []):
                external = g.get("ExternalIds") or []
                external_id = external[0].get("Id") if external else None
                groups.append(
                    IdentityGroup(
                        group_id=g["GroupId"],
                        display_name=g.get("DisplayName", ""),
                        external_id=external_id,
                    )
                )
        return groups

    def group_member_user_ids(self, group_id: str) -> frozenset[str]:
        """Return the set of user-ids that are members of a group."""
        user_ids: set[str] = set()
        paginator = self._client.get_paginator("list_group_memberships")
        for page in paginator.paginate(IdentityStoreId=self._store_id, GroupId=group_id):
            self._counter.incr("identitystore.list_group_memberships")
            for m in page.get("GroupMemberships", []):
                member = m.get("MemberId", {})
                if "UserId" in member:
                    user_ids.add(member["UserId"])
        return frozenset(user_ids)

    def list_users(self) -> dict[str, str]:
        """Return a ``username -> user_id`` map for resolving GitHub logins."""
        mapping: dict[str, str] = {}
        paginator = self._client.get_paginator("list_users")
        for page in paginator.paginate(IdentityStoreId=self._store_id):
            self._counter.incr("identitystore.list_users")
            for u in page.get("Users", []):
                if "UserName" in u and "UserId" in u:
                    mapping[u["UserName"]] = u["UserId"]
        return mapping

    # --- writes (only the three verbs the poller is permitted) -----------------

    def create_group(self, display_name: str) -> str:
        """Create a group named ``display_name`` (== the team slug). Returns its id.

        Idempotent in effect: if the group already exists we surface its id rather
        than failing, so a retried poll converges instead of erroring.
        """
        self._counter.incr("identitystore.create_group")
        try:
            response = self._client.create_group(
                IdentityStoreId=self._store_id,
                DisplayName=display_name,
            )
            return response["GroupId"]
        except Exception as exc:
            if error_code(exc) != "ConflictException":
                raise
            # Already exists — look it up so the caller can proceed idempotently.
            self._counter.incr("identitystore.get_group_id")
            found = self._client.get_group_id(
                IdentityStoreId=self._store_id,
                AlternateIdentifier={
                    "UniqueAttribute": {
                        "AttributePath": "displayName",
                        "AttributeValue": display_name,
                    }
                },
            )
            return found["GroupId"]

    def add_member(self, group_id: str, user_id: str) -> None:
        """Add a user to a group. Already-a-member is treated as success."""
        self._counter.incr("identitystore.create_group_membership")
        try:
            self._client.create_group_membership(
                IdentityStoreId=self._store_id,
                GroupId=group_id,
                MemberId={"UserId": user_id},
            )
        except Exception as exc:
            if error_code(exc) != "ConflictException":
                raise  # already a member -> idempotent success

    def remove_member(self, group_id: str, user_id: str) -> None:
        """Remove a user from a group. Not-a-member is treated as success."""
        self._counter.incr("identitystore.get_group_membership_id")
        try:
            membership = self._client.get_group_membership_id(
                IdentityStoreId=self._store_id,
                GroupId=group_id,
                MemberId={"UserId": user_id},
            )
        except Exception as exc:
            if error_code(exc) == "ResourceNotFoundException":
                return  # not a member -> idempotent success
            raise
        self._counter.incr("identitystore.delete_group_membership")
        self._client.delete_group_membership(
            IdentityStoreId=self._store_id,
            MembershipId=membership["MembershipId"],
        )
