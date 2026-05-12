import json
from typing import Any

import httpx

from polyalert.models import Event, Market, Outcome


class MarketNotFound(Exception):
    pass


class EventNotFound(Exception):
    pass


class PolymarketRest:
    """Client for Polymarket public REST APIs.

    `base_url` (gamma-api.polymarket.com) hosts /markets and /events.
    `clob_url` (clob.polymarket.com) hosts /price and /book.
    """

    def __init__(
        self,
        base_url: str,
        clob_url: str = "https://clob.polymarket.com",
        timeout: float = 10.0,
    ):
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
        )
        self._clob = httpx.AsyncClient(
            base_url=clob_url.rstrip("/"),
            timeout=timeout,
        )

    async def close(self) -> None:
        await self._client.aclose()
        await self._clob.aclose()

    async def get_market(self, slug: str) -> Market:
        resp = await self._client.get("/markets", params={"slug": slug})
        resp.raise_for_status()
        data = resp.json()
        if not data:
            raise MarketNotFound(slug)
        return self._parse_market(data[0])

    async def get_price(self, token_id: str, side: str) -> float:
        """Best bid (side='BUY') or best ask (side='SELL') from CLOB."""
        resp = await self._clob.get(
            "/price", params={"token_id": token_id, "side": side}
        )
        resp.raise_for_status()
        return float(resp.json().get("price", 0))

    async def get_event(self, slug: str) -> Event:
        resp = await self._client.get("/events", params={"slug": slug})
        resp.raise_for_status()
        data = resp.json()
        if not data:
            raise EventNotFound(slug)
        item = data[0]
        markets = [self._parse_market(m) for m in item.get("markets", [])]
        return Event(
            slug=item.get("slug", slug),
            title=item.get("title", ""),
            markets=markets,
        )

    @staticmethod
    def _parse_market(item: dict[str, Any]) -> Market:
        labels = _maybe_json_list(item.get("outcomes"))
        token_ids = _maybe_json_list(item.get("clobTokenIds"))
        outcomes = [
            Outcome(label=str(label), token_id=str(tid))
            for label, tid in zip(labels, token_ids, strict=False)
        ]
        closed = bool(item.get("closed")) or not bool(item.get("active", True))
        return Market(
            slug=str(item.get("slug", "")),
            title=str(item.get("question") or item.get("title", "")),
            outcomes=outcomes,
            closed=closed,
        )


def _maybe_json_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []
