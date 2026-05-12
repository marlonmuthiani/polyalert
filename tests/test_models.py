from polyalert.models import Alert, Market, Outcome, PriceTick


def test_pricetick_mid_is_average_of_bid_ask():
    tick = PriceTick(asset_id="t1", bid=0.4, ask=0.5)
    assert tick.mid == 0.45


def test_alert_describes_self_human_readable():
    alert = Alert(
        id=1,
        user_id=42,
        market_slug="x",
        market_title="Will it snow?",
        asset_id="tok1",
        outcome_label="Yes",
        side="mid",
        direction="above",
        threshold=0.55,
        created_at="2026-05-08T10:00:00Z",
    )
    assert "Will it snow?" in alert.describe()
    assert "Yes" in alert.describe()
    assert "0.55" in alert.describe()


def test_market_finds_token_for_outcome():
    market = Market(
        slug="m",
        title="t",
        outcomes=[
            Outcome(label="Yes", token_id="tok-yes"),
            Outcome(label="No", token_id="tok-no"),
        ],
        closed=False,
    )
    assert market.token_for("Yes") == "tok-yes"
    assert market.token_for("No") == "tok-no"
