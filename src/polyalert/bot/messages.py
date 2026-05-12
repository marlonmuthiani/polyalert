WELCOME = (
    "👋 Send me a Polymarket link and I'll set up a price alert.\n\n"
    "Example:\n"
    "https://polymarket.com/event/will-the-us-confirm-that-aliens-exist-by-may-31\n\n"
    "Commands:\n"
    "/list — your active alerts\n"
    "/cancel — abort the current dialog\n"
    "/status — bot health (owner only)\n"
    "/help — this message"
)

INVALID_URL = (
    "That's not a valid Polymarket link. Send something like:\n"
    "https://polymarket.com/event/<event-slug>\n"
    "or\n"
    "https://polymarket.com/event/<event-slug>/<market-slug>"
)

MARKET_CLOSED = "This market is closed/resolved — alerts won't help here."

CHOOSE_MARKET = "This event has several markets. Pick one:"

CHOOSE_OUTCOME = "Pick the outcome to track:"

CHOOSE_SIDE = "Which book side?\n• bid (highest buy)\n• ask (lowest sell)\n• mid (midpoint)"

CHOOSE_DIRECTION = "Direction?"

ENTER_THRESHOLD = (
    "Current prices for {outcome}: bid={bid:.4f}, ask={ask:.4f}, mid={mid:.4f}.\n"
    "Send the threshold (a number between 0 and 1)."
)

THRESHOLD_INVALID = "That's not a valid number between 0 and 1."

THRESHOLD_ALREADY_CROSSED = (
    "Current {side} price is {current:.4f}, which already meets your threshold "
    "{threshold:g} ({direction}). Pick another threshold."
)

ALERT_CREATED = "✅ Alert {alert_id}: {description}"

ALERT_LIMIT = "You hit the limit of {limit} active alerts. Delete some via /list."

NO_ALERTS = "You have no active alerts."

ALERT_DELETED = "Deleted."

ALERT_DELETE_FAILED = "Couldn't delete that alert (maybe already gone)."

CANCEL_OK = "Cancelled."

ERROR_GENERIC = "Something went wrong. Try again later."
