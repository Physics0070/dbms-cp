"""SSRF guard: private/loopback/metadata targets are refused unless explicitly allowed."""
import pytest

from app.config import get_settings
from app.netguard import HostRejected, resolve_host


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch):
    monkeypatch.delenv("ALLOW_PRIVATE_NETWORK", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize("host", [
    "127.0.0.1", "localhost", "::1", "10.0.0.5", "192.168.1.10", "172.16.0.1",
    "169.254.169.254",          # cloud metadata
    "100.64.0.1",               # carrier-grade NAT
    "0.0.0.0", "::ffff:127.0.0.1", "224.0.0.1",
])
def test_non_public_hosts_blocked_by_default(host):
    with pytest.raises(HostRejected, match="private, loopback or reserved"):
        resolve_host(host)


@pytest.mark.parametrize("host", ["", "http://example.com", "user@host", "host/path", "a b", "host:5432", "x;y"])
def test_malformed_hosts_rejected(host):
    with pytest.raises(HostRejected):
        resolve_host(host)


def test_public_ip_allowed():
    assert resolve_host("93.184.216.34") == "93.184.216.34"


def test_private_network_can_be_enabled(monkeypatch):
    monkeypatch.setenv("ALLOW_PRIVATE_NETWORK", "true")
    get_settings.cache_clear()
    assert resolve_host("127.0.0.1") == "127.0.0.1"
    assert resolve_host("localhost") in ("127.0.0.1", "::1")
