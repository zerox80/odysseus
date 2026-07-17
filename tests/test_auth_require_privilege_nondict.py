import types

import pytest
from fastapi import HTTPException

from src import auth_helpers
from src.auth_helpers import require_privilege


class _Mgr:
    def __init__(self, privs):
        self._privs = privs

    def get_privileges(self, user):
        return self._privs


def _request(mgr):
    state = types.SimpleNamespace(auth_manager=mgr)
    return types.SimpleNamespace(app=types.SimpleNamespace(state=state))


def test_require_privilege_rejects_non_dict_privileges(monkeypatch):
    # Corrupt authorization data must fail closed instead of granting access.
    monkeypatch.setattr(auth_helpers, "require_user", lambda request: "bob")
    req = _request(_Mgr(["can_use_documents"]))

    with pytest.raises(HTTPException) as exc:
        require_privilege(req, "can_use_documents")

    assert exc.value.status_code == 503


def test_require_privilege_still_blocks_disallowed(monkeypatch):
    monkeypatch.setattr(auth_helpers, "require_user", lambda request: "bob")
    req = _request(_Mgr({"can_use_documents": False}))

    with pytest.raises(HTTPException) as exc:
        require_privilege(req, "can_use_documents")

    assert exc.value.status_code == 403


@pytest.mark.parametrize("privs", [{}, {"can_use_documents": "yes"}])
def test_require_privilege_rejects_missing_or_non_boolean_flag(monkeypatch, privs):
    monkeypatch.setattr(auth_helpers, "require_user", lambda request: "bob")

    with pytest.raises(HTTPException) as exc:
        require_privilege(_request(_Mgr(privs)), "can_use_documents")

    assert exc.value.status_code == 503


def test_require_privilege_rejects_lookup_failure(monkeypatch):
    monkeypatch.setattr(auth_helpers, "require_user", lambda request: "bob")
    mgr = _Mgr({})
    mgr.get_privileges = lambda user: (_ for _ in ()).throw(OSError("unreadable auth store"))

    with pytest.raises(HTTPException) as exc:
        require_privilege(_request(mgr), "can_use_documents")

    assert exc.value.status_code == 503


def test_require_privilege_rejects_unknown_policy_key(monkeypatch):
    monkeypatch.setattr(auth_helpers, "require_user", lambda request: "bob")

    with pytest.raises(HTTPException) as exc:
        require_privilege(_request(_Mgr({})), "unknown_privilege")

    assert exc.value.status_code == 500
