from urllib.parse import urlparse


class InvalidURL(ValueError):
    pass


def parse_polymarket_url(raw: str) -> tuple[str | None, str | None]:
    """Parse Polymarket URL. Returns (event_slug, market_slug). At least one is non-None.

    Supported shapes:
      polymarket.com/event/<event-slug>
      polymarket.com/event/<event-slug>/<market-slug>
      polymarket.com/market/<market-slug>
    """
    if not raw or not isinstance(raw, str):
        raise InvalidURL("empty input")

    text = raw.strip()
    if "://" not in text:
        text = "https://" + text

    parsed = urlparse(text)
    host = (parsed.netloc or "").lower()
    if host != "polymarket.com" and not host.endswith(".polymarket.com"):
        raise InvalidURL(f"not a polymarket host: {host!r}")

    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        raise InvalidURL("no path")

    if parts[0] == "event":
        if len(parts) == 2:
            return parts[1], None
        if len(parts) >= 3:
            return parts[1], parts[2]
        raise InvalidURL("event without slug")

    if parts[0] == "market":
        if len(parts) >= 2:
            return None, parts[1]
        raise InvalidURL("market without slug")

    raise InvalidURL(f"unsupported path: /{parts[0]}")
