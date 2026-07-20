from scim_sync.logic.diff import diff_memberships
from scim_sync.models import MembershipChange


def test_diff_identifies_adds_and_removes():
    add, remove = diff_memberships(
        desired_user_ids=frozenset({"u1", "u2", "u3"}),
        actual_user_ids=frozenset({"u2", "u4"}),
        group_id="g1",
    )
    assert add == (
        MembershipChange("g1", "u1"),
        MembershipChange("g1", "u3"),
    )
    assert remove == (MembershipChange("g1", "u4"),)


def test_identical_sets_are_a_noop():
    add, remove = diff_memberships(
        desired_user_ids=frozenset({"u1", "u2"}),
        actual_user_ids=frozenset({"u1", "u2"}),
        group_id="g1",
    )
    assert add == ()
    assert remove == ()


def test_results_are_sorted_for_determinism():
    add, _ = diff_memberships(
        desired_user_ids=frozenset({"u3", "u1", "u2"}),
        actual_user_ids=frozenset(),
        group_id="g1",
    )
    assert [c.user_id for c in add] == ["u1", "u2", "u3"]
