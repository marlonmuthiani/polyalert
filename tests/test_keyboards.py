from polyalert.bot.keyboards import (
    direction_kb,
    market_choice_kb,
    outcome_kb,
    side_kb,
)
from polyalert.models import Market, Outcome


def test_outcome_kb_yes_no():
    market = Market(slug="x", title="t", outcomes=[
        Outcome("Yes", "tok-y"), Outcome("No", "tok-n"),
    ], closed=False)
    kb = outcome_kb(market)
    labels = [btn.text for row in kb.inline_keyboard for btn in row]
    assert labels == ["Yes", "No"]


def test_outcome_kb_paginates_when_many():
    outcomes = [Outcome(f"opt-{i}", f"t-{i}") for i in range(20)]
    kb = outcome_kb(Market(slug="x", title="t", outcomes=outcomes, closed=False), page=0)
    rows = kb.inline_keyboard
    # 8 outcomes per page max + nav row
    flat = [btn for row in rows for btn in row]
    nav = [btn for btn in flat if btn.text in ("⏭", "⏮")]
    options = [btn for btn in flat if btn not in nav]
    assert len(options) <= 8
    assert any(btn.text == "⏭" for btn in flat)


def test_side_kb_three_buttons():
    kb = side_kb()
    labels = [btn.text for row in kb.inline_keyboard for btn in row]
    assert set(labels) == {"bid", "ask", "mid"}


def test_direction_kb_two_buttons():
    kb = direction_kb()
    labels = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "📈 above" in labels
    assert "📉 below" in labels


def test_market_choice_kb_lists_open_markets_only():
    market_a = Market("a", "A?", [], closed=False)
    market_b = Market("b", "B?", [], closed=True)
    kb = market_choice_kb([market_a, market_b])
    labels = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "A?" in labels
    assert "B?" not in labels


def test_callback_data_fits_telegram_64_byte_limit():
    # Polymarket CLOB token_ids are uint256 decimals (~77 chars). Long event/market
    # slugs also exist. Telegram rejects callback_data > 64 bytes (BUTTON_DATA_INVALID).
    long_token = "1" * 100  # simulate uint256 decimal
    long_slug = "a-very-long-polymarket-event-slug-with-many-words-for-padding-test-cases"
    market = Market(
        slug=long_slug,
        title="long",
        outcomes=[Outcome(label=f"opt-{i}", token_id=long_token + str(i)) for i in range(12)],
        closed=False,
    )

    out_kb = outcome_kb(market, page=0)
    for row in out_kb.inline_keyboard:
        for btn in row:
            assert btn.callback_data is not None
            assert len(btn.callback_data.encode("utf-8")) <= 64, (
                f"outcome callback_data too long: {btn.callback_data!r}"
            )

    mkt_kb = market_choice_kb([
        Market(slug=long_slug + str(i), title=f"M{i}?", outcomes=[], closed=False)
        for i in range(5)
    ])
    for row in mkt_kb.inline_keyboard:
        for btn in row:
            assert btn.callback_data is not None
            assert len(btn.callback_data.encode("utf-8")) <= 64, (
                f"market callback_data too long: {btn.callback_data!r}"
            )
