"""
app/core/http_client.py
Shared async httpx clients.
  • fd_client()    → authenticated client for football-data.org
  • ss_client()    → browser-impersonating client for SofaScore
  • plain_client() → plain client for TheSportsDB / other sources
"""

import httpx
from app.core.config import FD_HEADERS, SS_HEADERS

_fd_client:    httpx.AsyncClient | None = None
_ss_client:    httpx.AsyncClient | None = None
_plain_client: httpx.AsyncClient | None = None

_LIMITS  = httpx.Limits(max_connections=10, max_keepalive_connections=5)
_TIMEOUT = httpx.Timeout(30.0, connect=15.0)

# Rotating user agents to help avoid SofaScore rate limiting
_SS_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]
_ss_ua_idx = 0


def fd_client() -> httpx.AsyncClient:
    global _fd_client
    if _fd_client is None or _fd_client.is_closed:
        _fd_client = httpx.AsyncClient(
            headers=FD_HEADERS,
            timeout=_TIMEOUT,
            follow_redirects=True,
            limits=_LIMITS,
        )
    return _fd_client


def ss_client() -> httpx.AsyncClient:
    global _ss_client, _ss_ua_idx
    if _ss_client is None or _ss_client.is_closed:
        # Rotate user agent on each new client creation
        ua = _SS_USER_AGENTS[_ss_ua_idx % len(_SS_USER_AGENTS)]
        _ss_ua_idx += 1
        headers = {**SS_HEADERS, "User-Agent": ua}
        _ss_client = httpx.AsyncClient(
            headers=headers,
            timeout=_TIMEOUT,
            follow_redirects=True,
            limits=_LIMITS,
            http2=False,
        )
    return _ss_client


def rotate_ss_client() -> httpx.AsyncClient:
    """Force creation of a new SS client with next User-Agent. Call on 403."""
    global _ss_client
    # Don't try to close the old client synchronously inside an async context
    # (loop.run_until_complete raises RuntimeError if loop is already running).
    # Just dereference it — the garbage collector and httpx's __del__ handle cleanup,
    # and a small fd leak on 403 rotation is far better than a crash.
    _ss_client = None
    return ss_client()


def plain_client() -> httpx.AsyncClient:
    global _plain_client
    if _plain_client is None or _plain_client.is_closed:
        _plain_client = httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=True,
            limits=_LIMITS,
        )
    return _plain_client


async def close_all() -> None:
    for c in [_fd_client, _ss_client, _plain_client]:
        if c and not c.is_closed:
            await c.aclose()
