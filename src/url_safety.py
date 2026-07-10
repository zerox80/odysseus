"""Outbound URL safety checks (SSRF hardening).

Run before the server makes a request to a *user-supplied* URL — e.g. the custom
embedding endpoint set via ``POST /api/embeddings/endpoint``, which then triggers
an outbound ``httpx`` call.

Odysseus is local-first: pointing the embedding endpoint at a loopback or LAN
address (a local vLLM / llama.cpp / Ollama server) is a normal, intended setup.
So this guard does **not** blanket-block private addresses by default — that would
break the primary use case. What it *always* rejects:

  - a non-HTTP(S) scheme (``file://``, ``gopher://``, ``ftp://`` …), and
  - the link-local range (``169.254.0.0/16`` / ``fe80::/10``), i.e. the cloud
    instance-metadata SSRF credential-exfil vector — nobody serves embeddings
    there — plus multicast / reserved / unspecified addresses.

For exposed multi-tenant deployments, set ``EMBEDDING_BLOCK_PRIVATE_IPS=true`` to
additionally reject all private and loopback targets (full SSRF lockdown).
"""

import ipaddress
import socket
from typing import Callable, List, Optional, Tuple
from urllib.parse import urlparse

ALLOWED_SCHEMES = ("http", "https")


def _default_resolver(host: str) -> List[str]:
    """Resolve a hostname to the list of IP strings it maps to (A + AAAA)."""
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


def _classify(ip: ipaddress._BaseAddress, *, block_private: bool) -> Optional[str]:
    """Return a rejection reason for an IP, or None if it is allowed."""
    # IPv4-mapped IPv6 (e.g. ::ffff:169.254.169.254) — judge the embedded v4.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_link_local:
        return f"link-local address blocked (SSRF metadata risk): {ip}"
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return f"disallowed address: {ip}"
    if block_private and (ip.is_private or ip.is_loopback):
        return f"private/loopback address blocked: {ip}"
    return None


def check_outbound_url(
    url: str,
    *,
    block_private: bool = False,
    resolver: Optional[Callable[[str], List[str]]] = None,
) -> Tuple[bool, str]:
    """Validate a user-supplied outbound URL.

    Returns ``(ok, reason)``. ``ok`` is True only when the URL is safe to fetch.
    ``resolver`` is injectable so callers/tests can avoid real DNS.
    """
    try:
        validated_outbound_ips(url, block_private=block_private, resolver=resolver)
    except ValueError as exc:
        return False, str(exc)
    return True, "ok"


def validated_outbound_ips(
    url: str,
    *,
    block_private: bool = False,
    resolver: Optional[Callable[[str], List[str]]] = None,
) -> List[ipaddress._BaseAddress]:
    """Resolve a safe URL to concrete addresses for DNS-rebinding-safe connects.

    Every DNS answer is inspected and a mixed safe/unsafe answer fails closed.
    Pass one returned address to a pinned HTTP transport; a normal HTTP client
    would resolve the hostname a second time after validation.
    """
    if not isinstance(url, str):
        raise ValueError("URL must be a string")
    if not url or not url.strip():
        raise ValueError("URL is required")
    try:
        parsed = urlparse(url.strip())
    except Exception as e:  # pragma: no cover - urlparse is very tolerant
        raise ValueError(f"unparseable URL: {e}") from e

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise ValueError(f"scheme must be http or https, got '{parsed.scheme or '(none)'}'")
    host = parsed.hostname
    if not host:
        raise ValueError("URL has no host")

    resolve = resolver or _default_resolver
    try:
        raw_ips = resolve(host)
    except Exception as e:
        raise ValueError(f"host does not resolve: {e}") from e
    if not raw_ips:
        raise ValueError("host does not resolve")

    ips: List[ipaddress._BaseAddress] = []
    for raw in raw_ips:
        if not isinstance(raw, str):
            continue
        try:
            ip = ipaddress.ip_address(raw.split("%")[0])  # strip IPv6 zone id
        except ValueError:
            continue
        reason = _classify(ip, block_private=block_private)
        if reason:
            raise ValueError(reason)
        ips.append(ip)
    if not ips:
        raise ValueError("host does not resolve to an IP")
    return ips
