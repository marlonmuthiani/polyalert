from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from polyalert.models import Market

PAGE_SIZE = 8


def market_choice_kb(markets: list[Market]) -> InlineKeyboardMarkup:
    # Telegram callback_data is capped at 64 bytes; market slugs can exceed that.
    # We pass the index into the open-markets list and re-resolve in the handler.
    open_markets = [m for m in markets if not m.closed]
    rows = [
        [InlineKeyboardButton(text=m.title, callback_data=f"mkt:{idx}")]
        for idx, m in enumerate(open_markets)
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def outcome_kb(market: Market, page: int = 0) -> InlineKeyboardMarkup:
    # Polymarket CLOB token_ids are uint256 decimals (~77 chars) — too long for
    # callback_data. Use absolute index into market.outcomes instead.
    start = page * PAGE_SIZE
    page_items = list(enumerate(market.outcomes))[start : start + PAGE_SIZE]
    rows = [
        [InlineKeyboardButton(text=o.label, callback_data=f"out:{idx}")]
        for idx, o in page_items
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⏮", callback_data=f"page:{page - 1}"))
    if start + PAGE_SIZE < len(market.outcomes):
        nav.append(InlineKeyboardButton(text="⏭", callback_data=f"page:{page + 1}"))
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def side_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="bid", callback_data="side:bid"),
        InlineKeyboardButton(text="ask", callback_data="side:ask"),
        InlineKeyboardButton(text="mid", callback_data="side:mid"),
    ]])


def direction_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📈 above", callback_data="dir:above"),
        InlineKeyboardButton(text="📉 below", callback_data="dir:below"),
    ]])


def alert_list_kb(alert_ids: list[int]) -> InlineKeyboardMarkup:
    """Render delete buttons. The label uses the display position (1..N)
    matching the order in which `/list` rendered the alerts; the callback_data
    still encodes the stable internal DB id for unambiguous deletion."""
    rows = [
        [InlineKeyboardButton(
            text=f"❌ delete #{display}",
            callback_data=f"del:{aid}",
        )]
        for display, aid in enumerate(alert_ids, start=1)
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
