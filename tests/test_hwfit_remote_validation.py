import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from core.platform_compat import _ssh_exec_argv
from routes.hwfit_routes import setup_hwfit_routes


def _endpoint(path: str):
    router = setup_hwfit_routes()
    for route in router.routes:
        if getattr(route, "path", "") == path:
            return route.endpoint
    raise AssertionError(f"{path} route not found")


@pytest.mark.parametrize(
    "path,kwargs",
    [
        ("/api/hwfit/system", {}),
        ("/api/hwfit/models", {"limit": 1}),
        ("/api/hwfit/profiles", {"model": "demo"}),
        ("/api/hwfit/image-models", {}),
    ],
)
def test_hwfit_routes_reject_ssh_option_host(path, kwargs):
    endpoint = _endpoint(path)

    with pytest.raises(HTTPException) as exc:
        endpoint(host="-oProxyCommand=sh", ssh_port="22", **kwargs)

    assert exc.value.status_code == 400


@pytest.mark.parametrize(
    "path,kwargs",
    [
        ("/api/hwfit/system", {}),
        ("/api/hwfit/models", {"limit": 1}),
        ("/api/hwfit/profiles", {"model": "demo"}),
        ("/api/hwfit/image-models", {}),
    ],
)
def test_hwfit_routes_reject_invalid_ssh_port(path, kwargs):
    endpoint = _endpoint(path)

    with pytest.raises(HTTPException) as exc:
        endpoint(host="alice@gpu-box", ssh_port="-oProxyCommand=sh", **kwargs)

    assert exc.value.status_code == 400


def test_hwfit_routes_reject_port_without_host():
    endpoint = _endpoint("/api/hwfit/system")

    with pytest.raises(HTTPException) as exc:
        endpoint(host="", ssh_port="2222")

    assert exc.value.status_code == 400


def test_remote_hwfit_probe_requires_explicit_opt_in_and_admin(monkeypatch):
    import routes.hwfit_routes as hwfit_routes

    monkeypatch.delenv("ODYSSEUS_ENABLE_HIGH_TRUST_COOKBOOK", raising=False)
    with pytest.raises(HTTPException) as exc:
        hwfit_routes._validate_detection_target("alice@gpu-box", "2222", object())
    assert exc.value.status_code == 403
    assert "ODYSSEUS_ENABLE_HIGH_TRUST_COOKBOOK=true" in str(exc.value.detail)

    calls = []
    request = object()
    monkeypatch.setenv("ODYSSEUS_ENABLE_HIGH_TRUST_COOKBOOK", "true")
    monkeypatch.setattr(hwfit_routes, "require_admin", lambda request: calls.append(request))
    assert hwfit_routes._validate_detection_target("alice@gpu-box", "2222", request) == (
        "alice@gpu-box",
        "2222",
    )
    assert calls == [request]


def test_remote_hwfit_probe_without_http_request_fails_closed(monkeypatch):
    import routes.hwfit_routes as hwfit_routes

    monkeypatch.setenv("ODYSSEUS_ENABLE_HIGH_TRUST_COOKBOOK", "true")
    with pytest.raises(HTTPException) as exc:
        hwfit_routes._validate_detection_target("gpu-box", "22")
    assert exc.value.status_code == 403


def test_remote_hwfit_endpoint_receives_request_and_fails_closed_by_default(monkeypatch):
    monkeypatch.delenv("ODYSSEUS_ENABLE_HIGH_TRUST_COOKBOOK", raising=False)
    app = FastAPI()
    app.include_router(setup_hwfit_routes())

    response = TestClient(app).get("/api/hwfit/system?host=gpu-box&ssh_port=22")

    assert response.status_code == 403
    assert "ODYSSEUS_ENABLE_HIGH_TRUST_COOKBOOK=true" in response.json()["detail"]


def test_ssh_argv_rejects_option_shaped_remote():
    with pytest.raises(ValueError):
        _ssh_exec_argv("-oProxyCommand=sh", "22", remote_cmd="true")
    with pytest.raises(ValueError):
        _ssh_exec_argv("alice@-oProxyCommand=sh", "22", remote_cmd="true")


def test_detect_system_option_host_never_starts_ssh(monkeypatch):
    from core import platform_compat
    from services.hwfit import hardware

    calls = []

    def _record_subprocess_run(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("ssh subprocess should not start")

    monkeypatch.setattr(platform_compat.subprocess, "run", _record_subprocess_run)
    hardware._cache_by_host.clear()

    try:
        result = hardware.detect_system(
            host="-oProxyCommand=sh",
            ssh_port="22",
            platform="linux",
            fresh=True,
        )
    finally:
        hardware._cache_by_host.clear()
        hardware._remote_host = None
        hardware._remote_port = None
        hardware._remote_platform = None

    assert result == {
        "error": "Cannot connect to -oProxyCommand=sh",
        "host": "-oProxyCommand=sh",
    }
    assert calls == []
