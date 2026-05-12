from aiogram.fsm.state import State, StatesGroup


class AlertCreation(StatesGroup):
    waiting_market_choice = State()
    waiting_outcome = State()
    waiting_side = State()
    waiting_direction = State()
    waiting_threshold = State()


# Keys we put into FSM context (data dict)
K_EVENT_SLUG = "event_slug"
K_MARKET_SLUG = "market_slug"
K_MARKET_TITLE = "market_title"
K_ASSET_ID = "asset_id"
K_OUTCOME_LABEL = "outcome_label"
K_SIDE = "side"
K_DIRECTION = "direction"
K_OUTCOMES_PAGE = "outcomes_page"
