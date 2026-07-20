from scim_sync.logic.plan import build_new_group_plan, build_team_plan, render_plan
from scim_sync.models import GitHubTeam, IdentityGroup


def _team(*logins: str) -> GitHubTeam:
    return GitHubTeam(
        team_id=42,
        slug="platform-team",
        name="Platform Team",
        member_logins=frozenset(logins),
    )


def _group(*user_ids: str) -> IdentityGroup:
    return IdentityGroup(
        group_id="g1",
        display_name="Platform Team",
        external_id="42",
        member_user_ids=frozenset(user_ids),
    )


def test_build_team_plan_maps_logins_to_user_ids():
    plan = build_team_plan(
        team=_team("bob", "erin"),
        group=_group("user-carol"),
        login_to_user_id={"bob": "user-bob", "erin": "user-erin", "carol": "user-carol"},
    )
    assert {c.user_id for c in plan.add} == {"user-bob", "user-erin"}
    assert {c.user_id for c in plan.remove} == {"user-carol"}
    assert {c.label for c in plan.add} == {"bob", "erin"}
    assert {c.label for c in plan.remove} == {"carol"}
    assert not plan.is_noop


def test_logins_without_a_user_id_are_skipped():
    # 'newjoiner' has no Identity Store user yet -> not added by membership reconcile.
    plan = build_team_plan(
        team=_team("bob", "newjoiner"),
        group=_group("user-bob"),
        login_to_user_id={"bob": "user-bob"},
    )
    assert plan.is_noop


def test_new_group_plan_seeds_all_known_members():
    plan = build_new_group_plan(
        team=_team("bob", "newjoiner"),
        login_to_user_id={"bob": "user-bob"},
    )
    assert plan.is_new_group
    assert not plan.is_noop
    assert [c.label for c in plan.add] == ["bob"]  # newjoiner has no user-id yet
    assert plan.group_id == ""
    assert plan.group_display_name == "platform-team"  # new group is named by slug


def test_render_plan_summarises_noops_and_lists_changes():
    changed = build_team_plan(
        team=_team("bob"),
        group=_group(),
        login_to_user_id={"bob": "user-bob"},
    )
    noop = build_team_plan(
        team=GitHubTeam(1, "ops", "Ops", frozenset({"bob"})),
        group=IdentityGroup("g2", "Ops", "1", frozenset({"user-bob"})),
        login_to_user_id={"bob": "user-bob"},
    )
    created = build_new_group_plan(
        team=GitHubTeam(9, "new-team", "New Team", frozenset({"bob"})),
        login_to_user_id={"bob": "user-bob"},
    )
    text = render_plan([changed, noop, created])
    assert "1 group(s) to create, 1 team(s) to update, 1 unchanged" in text
    assert "+ add bob" in text
    assert "CREATE group 'new-team'" in text
    assert "ops" not in text  # the no-op team is not listed line by line
