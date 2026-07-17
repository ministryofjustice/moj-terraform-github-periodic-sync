"""Tests for the SSM cursor store using an injected fake client (no boto3)."""

import json

import pytest

from scim_sync.adapters.cursor_store import SsmCursorStore
from scim_sync.logic.watermark import Watermark


class FakeNotFound(Exception):
    """Mimics botocore's ClientError shape for a missing parameter."""

    response = {"Error": {"Code": "ParameterNotFound"}}


class FakeSsm:
    def __init__(self, value: str | None = None) -> None:
        self._value = value
        self.put_calls: list[dict] = []

    def get_parameter(self, Name: str) -> dict:  # noqa: N803 (boto3 casing)
        if self._value is None:
            raise FakeNotFound()
        return {"Parameter": {"Value": self._value}}

    def put_parameter(self, **kwargs) -> None:
        self.put_calls.append(kwargs)
        self._value = kwargs["Value"]


def test_get_returns_none_when_parameter_missing():
    store = SsmCursorStore("/scim-sync/audit_cursor", client=FakeSsm(value=None))
    assert store.get() is None


def test_get_parses_stored_watermark():
    stored = json.dumps({"timestamp_ms": 1700000000000, "document_id": "abc"})
    store = SsmCursorStore("/scim-sync/audit_cursor", client=FakeSsm(value=stored))

    wm = store.get()

    assert wm == Watermark(timestamp_ms=1700000000000, document_id="abc")


def test_put_then_get_roundtrips():
    fake = FakeSsm(value=None)
    store = SsmCursorStore("/scim-sync/audit_cursor", client=fake)

    store.put(Watermark(timestamp_ms=42, document_id="doc-1"))

    assert fake.put_calls[0]["Type"] == "String"
    assert fake.put_calls[0]["Overwrite"] is True
    assert store.get() == Watermark(timestamp_ms=42, document_id="doc-1")


def test_get_reraises_unexpected_errors():
    class Boom(Exception):
        response = {"Error": {"Code": "AccessDeniedException"}}

    class Angry:
        def get_parameter(self, Name):  # noqa: N803
            raise Boom()

    store = SsmCursorStore("/scim-sync/audit_cursor", client=Angry())
    with pytest.raises(Boom):
        store.get()


def test_terraform_placeholder_reads_as_first_run():
    # Terraform seeds the parameter with a non-JSON placeholder before the first poll.
    store = SsmCursorStore("/scim-sync/audit_cursor", client=FakeSsm(value="uninitialised"))
    assert store.get() is None
