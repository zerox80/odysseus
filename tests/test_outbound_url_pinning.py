"""Regression tests for DNS-rebinding-safe local-first outbound requests."""

import http.server
import ipaddress
import socketserver
import threading

import httpx
import pytest

from src.url_safety import validated_outbound_ips
from src.url_security import PinnedTransport


def test_validated_outbound_ips_returns_pin_and_rejects_mixed_dns_answers():
    assert validated_outbound_ips(
        "https://provider.test/v1/embeddings",
        resolver=lambda _host: ["93.184.216.34"],
    ) == [ipaddress.ip_address("93.184.216.34")]

    with pytest.raises(ValueError, match="link-local"):
        validated_outbound_ips(
            "https://provider.test/v1/embeddings",
            resolver=lambda _host: ["93.184.216.34", "169.254.169.254"],
        )


def test_pinned_sync_transport_uses_validated_ip_not_second_dns_lookup():
    hits = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            hits.append(self.path)
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with httpx.Client(
            transport=PinnedTransport(ipaddress.ip_address("127.0.0.1")),
            timeout=5,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = client.get(
                f"http://does-not-resolve.invalid:{server.server_address[1]}/health"
            )
        assert response.status_code == 204
        assert hits == ["/health"]
    finally:
        server.shutdown()
        server.server_close()
