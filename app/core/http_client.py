"""
app/core/http_client.py
Shared async httpx clients.
  • fd_client()  →  authenticated client for football-data.org
  • ss_client()  →  browser-impersonating client for SofaScore
  • plain_client()  →  plain client for fixturedownload.com
"""

import httpx
from app.core.config import FD_HEADERS, SS_HEADERS

_fd_client:    httpx.AsyncClient | None = None
_ss_client:    httpx.AsyncClient | None = None
_plain_client: httpx.AsyncClient | None = None

_LIMITS = httpx.Limits(max_connections=10, max_keepalive_connections=5)
_TIMEOUT = httpx.Timeout(25.0, connect=10.0)


def fd_client() -> httpx.AsyncClient:
    global _fd_client
    if _fd_client is None or _fd_client.is_closed:
        _fd_client = httpx.AsyncClient(
            headers=FD_HEADERS, timeout=_TIMEOUT,
            follow_redirects=True, limits=_LIMITS,
        )
    return _fd_client


def ss_client() -> httpx.AsyncClient:
    global _ss_client
    if _ss_client is None or _ss_client.is_closed:
        _ss_client = httpx.AsyncClient(
            headers=SS_HEADERS, timeout=_TIMEOUT,
            follow_redirects=True, limits=_LIMITS,
        )
    return _ss_client


def plain_client() -> httpx.AsyncClient:
    global _plain_client
    if _plain_client is None or _plain_client.is_closed:
        _plain_client = httpx.AsyncClient(
            timeout=_TIMEOUT, follow_redirects=True, limits=_LIMITS,
        )
    return _plain_client


async def close_all() -> None:
    for c in [_fd_client, _ss_client, _plain_client]:
        if c and not c.is_closed:
            await c.aclose()
