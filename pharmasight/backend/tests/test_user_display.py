"""Tests for user display name resolution."""
from types import SimpleNamespace
from uuid import uuid4

from app.utils.user_display import resolve_user_display_name


class _FakeQuery:
    def __init__(self, row):
        self._row = row

    def filter(self, *a, **k):
        return self

    def first(self):
        return self._row


class _FakeDb:
    def __init__(self, row):
        self._row = row

    def query(self, *a, **k):
        return _FakeQuery(self._row)


def test_resolve_from_full_user_object():
    db = _FakeDb(None)
    user = SimpleNamespace(id=uuid4(), full_name="Jackson Mwangi", username="J-MWANGI")
    assert resolve_user_display_name(db, user) == "Jackson Mwangi"


def test_resolve_stub_user_from_db_lookup():
    uid = uuid4()
    db = _FakeDb(SimpleNamespace(full_name="Jackson Mwangi", username="J-MWANGI"))
    user = SimpleNamespace(id=uid)
    assert resolve_user_display_name(db, user) == "Jackson Mwangi"
