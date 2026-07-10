"""URL validation helpers for server-side outbound requests."""

from __future__ import annotations

import ipaddress
import socket
import ssl
from urllib.parse import urlparse

import httpcore
import httpx


_INTERNAL_HOSTNAMES = {
    "localhost",
    "metadata",
    "metadata.google.internal",
}

_INTERNAL_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
    ".lan",
    ".intranet",
)

_BLOCKED_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


def _resolve_hostname_ips(hostname: str) -> list[ipaddress._BaseAddress]:
    ips: list[ipaddress._BaseAddress] = []
    for family, _, _, _, sockaddr in socket.getaddrinfo(hostname, None):
        if family in (socket.AF_INET, socket.AF_INET6):
            ips.append(ipaddress.ip_address(sockaddr[0]))
    return ips


def _blocked_ip(addr: ipaddress._BaseAddress) -> bool:
    return (
        any(addr in net for net in _BLOCKED_NETWORKS)
        or addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_unspecified
        or addr.is_reserved
    )


def _host_resolves_publicly(hostname: str) -> bool:
    host = hostname.strip().lower()
    if host in _INTERNAL_HOSTNAMES or host.endswith(_INTERNAL_SUFFIXES):
        return False
    try:
        return not _blocked_ip(ipaddress.ip_address(host))
    except ValueError:
        pass
    try:
        addrs = _resolve_hostname_ips(host)
    except OSError:
        return False
    return bool(addrs) and all(not _blocked_ip(addr) for addr in addrs)


def is_public_http_url(url: str) -> bool:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    return _host_resolves_publicly(parsed.hostname)


def validate_public_http_url(url: str, *, max_length: int = 2048) -> str:
    """Validate a user/API-token supplied server-side HTTP(S) endpoint.

    This is for untrusted outbound URLs, not admin-created model endpoints
    that are intentionally allowed to point at private model providers. DNS
    failures fail closed. Call ``validated_public_ips`` plus
    ``PinnedAsyncTransport`` when a connection will be opened: that pair pins
    the validated address and closes the DNS-rebinding race between validation
    and connect.
    """
    cleaned = (url or "").strip()
    if len(cleaned) > max_length:
        raise ValueError("URL is too long")
    if not is_public_http_url(cleaned):
        raise ValueError("URL must point to a public HTTP(S) endpoint")
    return cleaned


def validated_public_ips(url: str) -> list[ipaddress._BaseAddress]:
    """Return public IPs for an already-approved outbound HTTP(S) URL.

    Validation based only on a hostname lookup is vulnerable to DNS rebinding:
    a later HTTP client lookup may get a different, internal address. This
    helper resolves the host immediately before a request and returns the
    concrete public address(es) that callers must pin for the socket connect.
    Every answer must be public; mixed DNS responses fail closed.
    """
    cleaned = validate_public_http_url(url)
    parsed = urlparse(cleaned)
    hostname = (parsed.hostname or "").strip()
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None:
        if _blocked_ip(literal):
            raise ValueError("URL must point to a public HTTP(S) endpoint")
        return [literal]

    try:
        addresses = _resolve_hostname_ips(hostname)
    except OSError as exc:
        raise ValueError("URL must point to a public HTTP(S) endpoint") from exc
    if not addresses or any(_blocked_ip(address) for address in addresses):
        raise ValueError("URL must point to a public HTTP(S) endpoint")
    return addresses


# httpcore raises its own exception hierarchy. Preserve httpx's public error
# contract for callers that already catch or sanitize httpx exceptions.
_HTTPCORE_TO_HTTPX_EXC = {
    httpcore.ConnectError: httpx.ConnectError,
    httpcore.ConnectTimeout: httpx.ConnectTimeout,
    httpcore.NetworkError: httpx.NetworkError,
    httpcore.PoolTimeout: httpx.PoolTimeout,
    httpcore.ProtocolError: httpx.ProtocolError,
    httpcore.ReadError: httpx.ReadError,
    httpcore.ReadTimeout: httpx.ReadTimeout,
    httpcore.RemoteProtocolError: httpx.RemoteProtocolError,
    httpcore.TimeoutException: httpx.TimeoutException,
    httpcore.WriteError: httpx.WriteError,
    httpcore.WriteTimeout: httpx.WriteTimeout,
}


class _PinnedAsyncBackend(httpcore.AsyncNetworkBackend):
    """Route every TCP connection to one validated IP address.

    The HTTP request URL is deliberately left unchanged, so its Host header
    and TLS SNI/certificate verification still identify the requested domain.
    Only the socket destination is fixed.
    """

    def __init__(self, ip: ipaddress._BaseAddress):
        self._ip = str(ip)
        self._real = httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None,
                          socket_options=None):
        return await self._real.connect_tcp(
            self._ip, port, timeout, local_address, socket_options
        )

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        return await self._real.connect_unix_socket(path, timeout, socket_options)

    async def sleep(self, seconds: float) -> None:
        return await self._real.sleep(seconds)


class _PinnedSyncBackend(httpcore.NetworkBackend):
    """Route synchronous TCP connections to one validated IP address."""

    def __init__(self, ip: ipaddress._BaseAddress):
        self._ip = str(ip)
        self._real = httpcore.SyncBackend()

    def connect_tcp(self, host, port, timeout=None, local_address=None,
                    socket_options=None):
        return self._real.connect_tcp(
            self._ip, port, timeout, local_address, socket_options
        )

    def connect_unix_socket(self, path, timeout=None, socket_options=None):
        return self._real.connect_unix_socket(path, timeout, socket_options)

    def sleep(self, seconds: float) -> None:
        return self._real.sleep(seconds)


class PinnedAsyncTransport(httpx.AsyncBaseTransport):
    """HTTP/1.1 transport that pins connects to a validated public IP.

    Use a short-lived client with ``follow_redirects=False``. Redirect targets
    are a separate outbound URL and must be validated/pinned afresh instead of
    inheriting this approval.
    """

    def __init__(self, ip: ipaddress._BaseAddress):
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(),
            http1=True,
            http2=False,
            network_backend=_PinnedAsyncBackend(ip),
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        try:
            core_response = await self._pool.handle_async_request(core_request)
            content = b"".join([chunk async for chunk in core_response.aiter_stream()])
            await core_response.aclose()
        except Exception as exc:
            mapped = _HTTPCORE_TO_HTTPX_EXC.get(type(exc))
            if mapped is not None:
                raise mapped(str(exc)) from exc
            raise
        return httpx.Response(
            status_code=core_response.status,
            headers=core_response.headers,
            content=content,
            extensions=core_response.extensions,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()


class PinnedTransport(httpx.BaseTransport):
    """Synchronous HTTP/1.1 transport that pins connects to a validated IP.

    Use a short-lived client with ``follow_redirects=False``. Redirect targets
    must be validated and pinned independently.
    """

    def __init__(self, ip: ipaddress._BaseAddress):
        self._pool = httpcore.ConnectionPool(
            ssl_context=ssl.create_default_context(),
            http1=True,
            http2=False,
            network_backend=_PinnedSyncBackend(ip),
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        try:
            core_response = self._pool.handle_request(core_request)
            content = b"".join(core_response.iter_stream())
            core_response.close()
        except Exception as exc:
            mapped = _HTTPCORE_TO_HTTPX_EXC.get(type(exc))
            if mapped is not None:
                raise mapped(str(exc)) from exc
            raise
        return httpx.Response(
            status_code=core_response.status,
            headers=core_response.headers,
            content=content,
            extensions=core_response.extensions,
        )

    def close(self) -> None:
        self._pool.close()
