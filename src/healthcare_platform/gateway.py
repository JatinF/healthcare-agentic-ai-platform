"""Route a task to a mock provider using quality, cost, latency, and availability.

Latency and cost here are configured routing units. They are not measured
dollars and not a network round trip. A live model provider is not called.
"""

from dataclasses import dataclass

from healthcare_platform.errors import FlowError


@dataclass(frozen=True)
class ModelCard:
    model_id: str
    quality: float
    cost_units: int
    latency_units: int
    available: bool
    behavior: str


@dataclass(frozen=True)
class RouteDecision:
    model_id: str
    behavior: str
    quality: float
    cost_units: int
    latency_units: int
    failover: bool
    below_quality_floor: bool


class ModelGateway:
    def __init__(self) -> None:
        self.pinned_behavior: str | None = None
        self._cards: dict[str, ModelCard] = {
            "mock-governed": ModelCard("mock-governed", 0.95, 8, 30, True, "governed"),
            "mock-alternate": ModelCard("mock-alternate", 0.96, 12, 40, True, "governed"),
            "mock-cheap": ModelCard("mock-cheap", 0.78, 1, 5, True, "cheap"),
            "mock-down": ModelCard("mock-down", 0.99, 4, 10, False, "down"),
        }
        self.min_quality = 0.9

    def cards(self) -> tuple[ModelCard, ...]:
        return tuple(self._cards.values())

    def set_available(self, model_id: str, available: bool) -> None:
        current = self._cards[model_id]
        self._cards[model_id] = ModelCard(
            current.model_id,
            current.quality,
            current.cost_units,
            current.latency_units,
            available,
            current.behavior,
        )

    def choose(self) -> RouteDecision:
        if self.pinned_behavior is not None:
            return RouteDecision(
                model_id=f"mock-{self.pinned_behavior}",
                behavior=self.pinned_behavior,
                quality=0.1,
                cost_units=1,
                latency_units=1,
                failover=False,
                below_quality_floor=True,
            )
        available = [card for card in self._cards.values() if card.available]
        if not available:
            raise FlowError("no_provider", "no model provider is available", 503)
        eligible = [card for card in available if card.quality >= self.min_quality]
        failover = not eligible
        pool = eligible if eligible else available
        chosen = sorted(
            pool,
            key=lambda card: (card.cost_units, card.latency_units, card.model_id),
        )[0]
        if chosen.behavior == "down":
            raise FlowError("provider_down", "selected provider is unavailable", 503)
        return RouteDecision(
            model_id=chosen.model_id,
            behavior=chosen.behavior,
            quality=chosen.quality,
            cost_units=chosen.cost_units,
            latency_units=chosen.latency_units,
            failover=failover,
            below_quality_floor=chosen.quality < self.min_quality,
        )
