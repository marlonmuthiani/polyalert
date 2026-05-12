from dataclasses import dataclass
from typing import Literal

Side = Literal["bid", "ask", "mid"]
Direction = Literal["above", "below"]


@dataclass(frozen=True)
class PriceTick:
    asset_id: str
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


@dataclass(frozen=True)
class Outcome:
    label: str
    token_id: str


@dataclass(frozen=True)
class Market:
    slug: str
    title: str
    outcomes: list[Outcome]
    closed: bool

    def token_for(self, label: str) -> str | None:
        for o in self.outcomes:
            if o.label == label:
                return o.token_id
        return None


@dataclass(frozen=True)
class Event:
    slug: str
    title: str
    markets: list[Market]


@dataclass(frozen=True)
class Alert:
    id: int
    user_id: int
    market_slug: str
    market_title: str
    asset_id: str
    outcome_label: str
    side: Side
    direction: Direction
    threshold: float
    created_at: str

    def describe(self) -> str:
        """Human-readable summary without a leading number.

        Per-user display position is decided at render time, so callers prepend
        it as f"#{i}: {alert.describe()}".
        """
        arrow = "↑" if self.direction == "above" else "↓"
        return (
            f"{self.market_title} · {self.outcome_label} · "
            f"{self.side} {arrow} {self.threshold:g}"
        )
