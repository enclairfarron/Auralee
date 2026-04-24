from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

UA_DESKTOP = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
UA_SAFARI_MAC = UA_DESKTOP


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=5.0),
        follow_redirects=True,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        transport=httpx.AsyncHTTPTransport(retries=2),
    )


@asynccontextmanager
async def http_client() -> AsyncIterator[httpx.AsyncClient]:
    client = make_client()
    try:
        yield client
    finally:
        await client.aclose()
