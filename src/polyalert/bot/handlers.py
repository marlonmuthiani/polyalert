import asyncio
import logging
import time

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from polyalert.bot import messages as msg
from polyalert.bot.fsm import (
    K_ASSET_ID,
    K_DIRECTION,
    K_EVENT_SLUG,
    K_MARKET_SLUG,
    K_MARKET_TITLE,
    K_OUTCOME_LABEL,
    K_OUTCOMES_PAGE,
    K_SIDE,
    AlertCreation,
)
from polyalert.bot.keyboards import (
    alert_list_kb,
    direction_kb,
    market_choice_kb,
    outcome_kb,
    side_kb,
)
from polyalert.config import Settings
from polyalert.db import AlertLimitExceeded, Database
from polyalert.engine import AlertEngine, current_price
from polyalert.models import PriceTick
from polyalert.polymarket.rest import EventNotFound, MarketNotFound, PolymarketRest
from polyalert.polymarket.url import InvalidURL, parse_polymarket_url
from polyalert.polymarket.wss import WSSManager

_started_monotonic = time.monotonic()

log = logging.getLogger(__name__)

router = Router()

# Stored at module-level once the application wires them in __main__.py
_db: Database | None = None
_engine: AlertEngine | None = None
_rest: PolymarketRest | None = None
_settings: Settings | None = None
_wss: WSSManager | None = None


def wire(
    *,
    db: Database,
    engine: AlertEngine,
    rest: PolymarketRest,
    settings: Settings,
    wss: WSSManager,
) -> None:
    global _db, _engine, _rest, _settings, _wss
    _db = db
    _engine = engine
    _rest = rest
    _settings = settings
    _wss = wss


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    assert _db is not None
    if not message.from_user:
        return
    await _db.upsert_user(message.from_user.id)
    await message.answer(msg.WELCOME)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(msg.WELCOME)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(msg.CANCEL_OK)


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    assert _engine is not None and _wss is not None and _settings is not None
    if not message.from_user:
        return
    if _settings.owner_user_id is None or message.from_user.id != _settings.owner_user_id:
        await message.answer("Команда /status доступна только владельцу бота.")
        return
    uptime_s = time.monotonic() - _started_monotonic
    h, rem = divmod(int(uptime_s), 3600)
    m, s = divmod(rem, 60)
    estats = _engine.stats()
    wstats = _wss.stats()
    last_age = wstats["last_message_age_seconds"]
    last_age_str = f"{last_age:.0f}s ago" if last_age is not None else "never"
    subs_lines = "\n".join(
        f"  • {aid[:16]}…  ref={ref}"
        for aid, ref in wstats["subscriptions"].items()
    ) or "  (none)"
    text = (
        f"🤖 PolyAlert status\n"
        f"uptime: {h:02d}:{m:02d}:{s:02d}\n"
        f"\nWSS\n"
        f"  connected: {'✅' if wstats['connected'] else '❌'}\n"
        f"  connects:  {wstats['connects_total']} (reconnects: {wstats['reconnects_total']})\n"
        f"  ticks rcvd: {wstats['ticks_total']}\n"
        f"  last msg:  {last_age_str}\n"
        f"  subs ({len(wstats['subscriptions'])}):\n{subs_lines}\n"
        f"\nEngine\n"
        f"  alerts in index: {estats['indexed_alerts']}\n"
        f"  fired total:     {estats['fired_total']}\n"
        f"  tick queue:      {estats['queue_size']}\n"
    )
    await message.answer(text)


@router.message(Command("list"))
async def cmd_list(message: Message) -> None:
    assert _db is not None and _engine is not None and _rest is not None
    if not message.from_user:
        return
    alerts = await _db.list_alerts(message.from_user.id)
    if not alerts:
        await message.answer(msg.NO_ALERTS)
        return

    # Resolve a current tick for every unique asset_id, in parallel:
    # WSS cache first (fast), REST fallback for cache misses (just-subscribed
    # markets that haven't ticked yet).
    unique_assets = {a.asset_id for a in alerts}
    ticks = await asyncio.gather(*(
        _resolve_tick(asset_id) for asset_id in unique_assets
    ))
    tick_by_asset: dict[str, PriceTick | None] = dict(zip(unique_assets, ticks, strict=True))

    lines = []
    for i, a in enumerate(alerts, start=1):
        line = f"#{i}: {a.describe()}"
        tick = tick_by_asset.get(a.asset_id)
        if tick is not None:
            cur = current_price(a.side, tick)
            lines.append(f"{line}  ·  now {a.side}={cur:.4f}")
        else:
            lines.append(f"{line}  ·  now {a.side}=…")
    text = "\n".join(lines)
    await message.answer(text, reply_markup=alert_list_kb([a.id for a in alerts]))


async def _resolve_tick(asset_id: str) -> "PriceTick | None":
    """Engine cache first, REST fallback. Cache stays canonical — we don't
    write the REST result back, since WSS will populate naturally."""
    assert _engine is not None
    cached = _engine.get_latest_tick(asset_id)
    if cached is not None:
        return cached
    return await _fetch_current_tick(asset_id)


@router.callback_query(F.data.startswith("del:"))
async def cb_delete(query: CallbackQuery) -> None:
    assert _db is not None and _engine is not None
    if not query.from_user:
        return
    try:
        alert_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.answer("Invalid button data")
        return
    ok = await _engine.unregister(alert_id, user_id=query.from_user.id)
    await query.answer(msg.ALERT_DELETED if ok else msg.ALERT_DELETE_FAILED)


@router.message(F.text.regexp(r"https?://(?:www\.)?polymarket\.com/"))
async def msg_url(message: Message, state: FSMContext) -> None:
    assert _rest is not None
    try:
        event_slug, market_slug = parse_polymarket_url(message.text or "")
    except InvalidURL:
        await message.answer(msg.INVALID_URL)
        return

    try:
        if market_slug:
            market = await _rest.get_market(market_slug)
            if market.closed:
                await message.answer(msg.MARKET_CLOSED)
                return
            await state.update_data({
                K_EVENT_SLUG: event_slug,
                K_MARKET_SLUG: market_slug,
                K_MARKET_TITLE: market.title,
            })
            await _ask_outcome(message, state, market)
            return

        assert event_slug is not None
        event = await _rest.get_event(event_slug)
        open_markets = [m for m in event.markets if not m.closed]
        if not open_markets:
            await message.answer(msg.MARKET_CLOSED)
            return
        if len(open_markets) == 1:
            single = open_markets[0]
            await state.update_data({
                K_EVENT_SLUG: event_slug,
                K_MARKET_SLUG: single.slug,
                K_MARKET_TITLE: single.title,
            })
            await _ask_outcome(message, state, single)
            return

        await state.update_data({K_EVENT_SLUG: event_slug})
        await state.set_state(AlertCreation.waiting_market_choice)
        await message.answer(msg.CHOOSE_MARKET, reply_markup=market_choice_kb(open_markets))
    except (MarketNotFound, EventNotFound):
        await message.answer(msg.INVALID_URL)
    except Exception:
        log.exception("URL handler failed")
        await message.answer(msg.ERROR_GENERIC)


async def _ask_outcome(message_obj, state: FSMContext, market) -> None:
    await state.update_data({K_OUTCOMES_PAGE: 0})
    await state.set_state(AlertCreation.waiting_outcome)
    await message_obj.answer(msg.CHOOSE_OUTCOME, reply_markup=outcome_kb(market))


@router.callback_query(AlertCreation.waiting_market_choice, F.data.startswith("mkt:"))
async def cb_pick_market(query: CallbackQuery, state: FSMContext) -> None:
    assert _rest is not None
    await query.answer()
    try:
        idx = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.answer("Invalid button data")
        return
    data = await state.get_data()
    event_slug = data.get(K_EVENT_SLUG)
    if not event_slug:
        await query.message.answer(msg.ERROR_GENERIC)
        await state.clear()
        return
    try:
        event = await _rest.get_event(event_slug)
    except (MarketNotFound, EventNotFound):
        await query.message.answer(msg.INVALID_URL)
        await state.clear()
        return
    except Exception:
        log.exception("get_event failed in cb_pick_market")
        await query.message.answer(msg.ERROR_GENERIC)
        await state.clear()
        return
    open_markets = [m for m in event.markets if not m.closed]
    if idx < 0 or idx >= len(open_markets):
        await query.message.answer(msg.MARKET_CLOSED)
        await state.clear()
        return
    market = open_markets[idx]
    await state.update_data({
        K_MARKET_SLUG: market.slug,
        K_MARKET_TITLE: market.title,
    })
    await state.update_data({K_OUTCOMES_PAGE: 0})
    await state.set_state(AlertCreation.waiting_outcome)
    await query.message.answer(msg.CHOOSE_OUTCOME, reply_markup=outcome_kb(market))


@router.callback_query(AlertCreation.waiting_outcome, F.data.startswith("page:"))
async def cb_outcome_page(query: CallbackQuery, state: FSMContext) -> None:
    assert _rest is not None
    await query.answer()
    try:
        page = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.answer("Invalid button data")
        return
    data = await state.get_data()
    try:
        market = await _rest.get_market(data[K_MARKET_SLUG])
    except (MarketNotFound, EventNotFound):
        await query.message.answer(msg.INVALID_URL)
        await state.clear()
        return
    except Exception:
        log.exception("get_market failed in cb_outcome_page")
        await query.message.answer(msg.ERROR_GENERIC)
        await state.clear()
        return
    await state.update_data({K_OUTCOMES_PAGE: page})
    await query.message.edit_reply_markup(reply_markup=outcome_kb(market, page=page))


@router.callback_query(AlertCreation.waiting_outcome, F.data.startswith("out:"))
async def cb_pick_outcome(query: CallbackQuery, state: FSMContext) -> None:
    assert _rest is not None
    await query.answer()
    try:
        idx = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.answer("Invalid button data")
        return
    data = await state.get_data()
    try:
        market = await _rest.get_market(data[K_MARKET_SLUG])
    except (MarketNotFound, EventNotFound):
        await query.message.answer(msg.INVALID_URL)
        await state.clear()
        return
    except Exception:
        log.exception("get_market failed in cb_pick_outcome")
        await query.message.answer(msg.ERROR_GENERIC)
        await state.clear()
        return
    if idx < 0 or idx >= len(market.outcomes):
        await query.message.answer(msg.ERROR_GENERIC)
        await state.clear()
        return
    outcome = market.outcomes[idx]
    await state.update_data({K_ASSET_ID: outcome.token_id, K_OUTCOME_LABEL: outcome.label})
    await state.set_state(AlertCreation.waiting_side)
    await query.message.answer(msg.CHOOSE_SIDE, reply_markup=side_kb())


@router.callback_query(AlertCreation.waiting_side, F.data.startswith("side:"))
async def cb_pick_side(query: CallbackQuery, state: FSMContext) -> None:
    await query.answer()
    side = query.data.split(":", 1)[1]
    await state.update_data({K_SIDE: side})
    await state.set_state(AlertCreation.waiting_direction)
    await query.message.answer(msg.CHOOSE_DIRECTION, reply_markup=direction_kb())


@router.callback_query(AlertCreation.waiting_direction, F.data.startswith("dir:"))
async def cb_pick_direction(query: CallbackQuery, state: FSMContext) -> None:
    assert _rest is not None
    await query.answer()
    direction = query.data.split(":", 1)[1]
    await state.update_data({K_DIRECTION: direction})
    data = await state.get_data()
    tick = await _fetch_current_tick(data[K_ASSET_ID])
    if tick is None:
        await query.message.answer(msg.ERROR_GENERIC)
        await state.clear()
        return
    await state.set_state(AlertCreation.waiting_threshold)
    await query.message.answer(msg.ENTER_THRESHOLD.format(
        outcome=data[K_OUTCOME_LABEL], bid=tick.bid, ask=tick.ask, mid=tick.mid,
    ))


@router.message(AlertCreation.waiting_threshold)
async def msg_threshold(message: Message, state: FSMContext) -> None:
    assert _db is not None and _engine is not None and _settings is not None
    if not message.from_user:
        return
    raw = (message.text or "").strip().replace(",", ".")
    try:
        threshold = float(raw)
    except ValueError:
        await message.answer(msg.THRESHOLD_INVALID)
        return
    if not (0.0 < threshold < 1.0):
        await message.answer(msg.THRESHOLD_INVALID)
        return

    data = await state.get_data()
    tick = await _fetch_current_tick(data[K_ASSET_ID])
    if tick is None:
        await message.answer(msg.ERROR_GENERIC)
        await state.clear()
        return
    side = data[K_SIDE]
    direction = data[K_DIRECTION]
    cur = current_price(side, tick)

    already = (direction == "above" and cur >= threshold) or \
              (direction == "below" and cur <= threshold)
    if already:
        await message.answer(msg.THRESHOLD_ALREADY_CROSSED.format(
            side=side, current=cur, threshold=threshold, direction=direction,
        ))
        return

    try:
        await _db.upsert_user(message.from_user.id)
        alert = await _db.create_alert(
            user_id=message.from_user.id,
            market_slug=data[K_MARKET_SLUG],
            market_title=data[K_MARKET_TITLE],
            asset_id=data[K_ASSET_ID],
            outcome_label=data[K_OUTCOME_LABEL],
            side=side,
            direction=direction,
            threshold=threshold,
            max_per_user=_settings.max_alerts_per_user,
        )
    except AlertLimitExceeded:
        await message.answer(msg.ALERT_LIMIT.format(limit=_settings.max_alerts_per_user))
        await state.clear()
        return

    await _engine.register(alert)
    await state.clear()
    # Display number = position in this user's current list (1..N).
    # AUTOINCREMENT ids are sorted ascending in list_alerts, so the alert we
    # just created is always last — its display number equals the list size.
    user_alerts = await _db.list_alerts(message.from_user.id)
    display_num = len(user_alerts)
    await message.answer(msg.ALERT_CREATED.format(
        alert_id=display_num, description=alert.describe(),
    ))


async def _fetch_current_tick(asset_id: str) -> "PriceTick | None":
    """Fetch a fresh tick from REST so we can show prices and validate threshold."""
    assert _rest is not None
    try:
        bid = await _rest.get_price(asset_id, "BUY")
        ask = await _rest.get_price(asset_id, "SELL")
    except Exception:
        log.exception("price fetch failed")
        return None
    if bid <= 0 or ask <= 0:
        return None
    return PriceTick(asset_id=asset_id, bid=bid, ask=ask)
