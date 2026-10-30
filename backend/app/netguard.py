"""SSRF guard for user-supplied database hosts.

A hosted deployment that lets visitors choose a host would otherwise let them probe the
server's own network (loopback services, cloud metadata at 169.254.169.254, internal
databases). The host is resolved here, every resolved address must be globally routable
unless ALLOW_PRIVATE_NETWORK=true, and the caller connects to the *returned address*, so a
DNS answer that changes between this check and the connect cannot redirect the connection.
"""
from __future__ import annotations

import ipaddress
import re
import socket

from .config import get_settings

_HOST_RE = re.compile(r"[A-Za-z0-9]([A-Za-z0-9._-]{0,251}[A-Za-z0-9])?|[0-9A-Fa-f:.]+")


class HostRejected(ValueError):
    """The host is malformed, unresolvable, or points at a non-public address."""


def resolve_host(host: str) -> str:
    """Return the IP address to connect to, or raise :class:`HostRejected`."""
    host = (host or "").strip()
    if not _HOST_RE.fullmatch(host):
        raise HostRejected("Enter a plain host name or IP address (no scheme, path, port or credentials).")
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise HostRejected("The host name could not be resolved.") from None
    addrs = sorted({i[4][0].split("%")[0] for i in infos}, key=lambda a: ":" in a)  # IPv4 first
    if not addrs:
        raise HostRejected("The host name could not be resolved.")
    if not get_settings().allow_private_network:
        for a in addrs:
            ip = ipaddress.ip_address(a)
            if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
                ip = ip.ipv4_mapped
            if not ip.is_global or ip.is_multicast:
                raise HostRejected(
                    "This host resolves to a private, loopback or reserved address, which is blocked. "
                    "The server operator can allow it with ALLOW_PRIVATE_NETWORK=true."
                )
    return addrs[0]
