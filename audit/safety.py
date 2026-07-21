"""
safety.py — SSRF guard.

Once this tool is deployed publicly, it becomes a URL-fetcher anyone on the
internet can point at any address. Without a check like this, someone could
hand it a hostname that resolves to an internal IP (e.g. a cloud metadata
endpoint at 169.254.169.254, or another service on your private network) and
use the audit report to see the response.

This resolves the hostname and rejects anything that isn't a public,
routable address before a request is made.

Known limitation: this checks the resolved IP at call time, which doesn't
fully defend against DNS rebinding (a hostname that resolves safely here but
is re-pointed to an internal IP by the time the actual TCP connection opens).
For most audit-tool use this is a reasonable bar; if you need airtight
protection, pin the resolved IP and connect to it directly rather than
re-resolving, or run this behind a network egress policy that blocks private
ranges at the firewall level.
"""

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeURLError(ValueError):
    pass


_BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal"}


def _is_blocked_ip(ip_str):
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparsable -> treat as unsafe
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


def assert_safe_url(url):
    """Raises UnsafeURLError if the URL targets a non-public address. Returns True otherwise."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError(f"Unsupported scheme: {parsed.scheme!r}")

    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL has no hostname.")
    if host.lower() in _BLOCKED_HOSTNAMES:
        raise UnsafeURLError(f"{host} is not permitted.")

    try:
        addr_infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Could not resolve host: {host}") from exc

    for info in addr_infos:
        ip_str = info[4][0]
        if _is_blocked_ip(ip_str):
            raise UnsafeURLError(f"{host} resolves to a non-public address and can't be audited.")

    return True


def is_safe_url(url):
    try:
        return assert_safe_url(url)
    except UnsafeURLError:
        return False
