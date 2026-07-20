"""Tests for the CloudWatch last-execution lookup (fake logs client, no AWS)."""

from scim_sync.adapters.cloudwatch import last_lambda_execution_ms


class FakeLogs:
    def __init__(self, streams=None, raise_exc=None) -> None:
        self._streams = streams or []
        self._raise = raise_exc
        self.calls: list[dict] = []

    def describe_log_streams(self, **kwargs):
        self.calls.append(kwargs)
        if self._raise:
            raise self._raise
        return {"logStreams": self._streams}


class NotFound(Exception):
    response = {"Error": {"Code": "ResourceNotFoundException"}}


def test_returns_last_event_timestamp():
    fake = FakeLogs(streams=[{"lastEventTimestamp": 1700000000000}])
    assert last_lambda_execution_ms("aws-sso-scim-github", client=fake) == 1700000000000
    # Queried newest-first for the right log group.
    assert fake.calls[0]["logGroupName"] == "/aws/lambda/aws-sso-scim-github"
    assert fake.calls[0]["orderBy"] == "LastEventTime"
    assert fake.calls[0]["descending"] is True


def test_missing_log_group_returns_none():
    fake = FakeLogs(raise_exc=NotFound())
    assert last_lambda_execution_ms("never-ran", client=fake) is None


def test_no_streams_returns_none():
    assert last_lambda_execution_ms("empty", client=FakeLogs(streams=[])) is None
