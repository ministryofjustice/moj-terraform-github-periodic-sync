"""Tests for the apply (write) path. A fake Identity Store records calls so we can
assert the gating: dry-run records intent but calls nothing; live performs the
exact three permitted verbs.
"""

import pytest

from scim_sync.apply import Applier, BlastRadiusError
from scim_sync.logic.plan import build_new_group_plan, build_team_plan
from scim_sync.models import GitHubTeam, IdentityGroup


class FakeIdentityStore:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.added: list[tuple[str, str]] = []
        self.removed: list[tuple[str, str]] = []

    def create_group(self, display_name: str) -> str:
        self.created.append(display_name)
        return f"grp-{display_name}"

    def add_member(self, group_id: str, user_id: str) -> None:
        self.added.append((group_id, user_id))

    def remove_member(self, group_id: str, user_id: str) -> None:
        self.removed.append((group_id, user_id))


def _existing_plan():
    team = GitHubTeam(42, "platform-team", "Platform Team", frozenset({"bob"}))
    group = IdentityGroup("g1", "platform-team", None, frozenset({"user-carol"}))
    return build_team_plan(team, group, {"bob": "user-bob", "carol": "user-carol"})


def _new_group_plan():
    team = GitHubTeam(9, "new-team", "New Team", frozenset({"bob"}))
    return build_new_group_plan(team, {"bob": "user-bob"})


def test_dry_run_records_intent_but_writes_nothing():
    fake = FakeIdentityStore()
    applier = Applier(fake, dry_run=True, log=lambda _m: None)

    result = applier.apply([_existing_plan(), _new_group_plan()])

    assert fake.created == [] and fake.added == [] and fake.removed == []
    assert result.dry_run is True
    assert result.groups_created == 1
    assert result.members_added == 2  # bob into platform-team + bob into new-team
    assert result.members_removed == 1  # carol out of platform-team


def test_live_performs_the_three_verbs():
    fake = FakeIdentityStore()
    applier = Applier(fake, dry_run=False, log=lambda _m: None)

    result = applier.apply([_existing_plan(), _new_group_plan()])

    assert result.dry_run is False
    # Existing group: add bob, remove carol against the real group id.
    assert ("g1", "user-bob") in fake.added
    assert ("g1", "user-carol") in fake.removed
    # New group: created, then bob added to the freshly created id.
    assert fake.created == ["new-team"]
    assert ("grp-new-team", "user-bob") in fake.added
    assert result.groups_created == 1
    assert result.members_added == 2
    assert result.members_removed == 1


def test_noop_plan_does_nothing():
    fake = FakeIdentityStore()
    team = GitHubTeam(1, "ops", "Ops", frozenset({"bob"}))
    group = IdentityGroup("g2", "ops", None, frozenset({"user-bob"}))
    noop = build_team_plan(team, group, {"bob": "user-bob"})

    result = Applier(fake, dry_run=False, log=lambda _m: None).apply([noop])

    assert fake.created == [] and fake.added == [] and fake.removed == []
    assert result.members_added == 0 and result.members_removed == 0


def _mass_removal_plan(count: int):
    # An existing group full of members whose team is now (erroneously) empty:
    # the diff wants to remove everyone — exactly what the cap guards against.
    actual = frozenset(f"user-{i}" for i in range(count))
    team = GitHubTeam(7, "big", "Big", frozenset())
    group = IdentityGroup("g-big", "big", None, actual)
    return build_team_plan(team, group, {})


def test_blast_radius_blocks_live_run_over_cap():
    fake = FakeIdentityStore()
    applier = Applier(fake, dry_run=False, log=lambda _m: None, max_changes=10)

    with pytest.raises(BlastRadiusError):
        applier.apply([_mass_removal_plan(25)])

    # Nothing was written — the tripwire fires before any mutation.
    assert fake.removed == [] and fake.added == [] and fake.created == []


def test_blast_radius_only_warns_in_dry_run():
    fake = FakeIdentityStore()
    msgs: list[str] = []
    applier = Applier(fake, dry_run=True, log=msgs.append, max_changes=10)

    result = applier.apply([_mass_removal_plan(25)])  # does not raise in dry-run

    assert any("BLAST-RADIUS" in m for m in msgs)
    assert result.members_removed == 25  # reported, but nothing written
    assert fake.removed == []


def test_under_cap_applies_normally():
    fake = FakeIdentityStore()
    applier = Applier(fake, dry_run=False, log=lambda _m: None, max_changes=10)

    applier.apply([_mass_removal_plan(3)])

    assert len(fake.removed) == 3

