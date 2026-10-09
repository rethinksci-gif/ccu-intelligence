"""Persist conservative token and spend reservations before every network attempt."""

import json
import math
from dataclasses import dataclass, fields
from decimal import ROUND_CEILING, Decimal
from pathlib import Path


@dataclass
class Budget:
    max_requests: int = 8
    max_tokens: int = 24000
    requests: int = 0
    charged_tokens: int = 0
    path: Path | None = None
    max_spend_usd: float | None = None
    # Charge every token at the higher peak rate, including cached input tokens.
    usd_per_million_tokens: float = 1.20
    reserved_cost_microusd: int = 0

    def __post_init__(self):
        if self.max_requests < 0 or self.max_tokens < 1 or self.requests < 0 or self.charged_tokens < 0:
            raise ValueError('Invalid request/token budget')
        if not math.isfinite(self.usd_per_million_tokens) or self.usd_per_million_tokens < 1.20:
            raise ValueError('Rate ceiling must be finite and at least USD 1.20 per million tokens')
        if self.max_spend_usd is not None and (
            not math.isfinite(self.max_spend_usd) or self.max_spend_usd < 0
        ):
            raise ValueError('Spend budget must be finite and non-negative')

    def cost(self, tokens):
        return int((Decimal(tokens) * Decimal(str(self.usd_per_million_tokens))).to_integral_value(
            rounding=ROUND_CEILING
        ))

    def save(self):
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps({f.name: getattr(self, f.name) for f in fields(self) if f.name != 'path'}))
            tmp.replace(self.path)

    def reserve(self, tokens: int) -> bool:
        if type(tokens) is not int or tokens < 1:
            raise ValueError('Invalid token reservation')
        cost = self.cost(tokens)
        if self.requests >= self.max_requests or self.charged_tokens + tokens > self.max_tokens:
            return False
        if self.max_spend_usd is not None and (
            Decimal(self.reserved_cost_microusd + cost) > Decimal(str(self.max_spend_usd)) * 1_000_000
        ):
            return False
        self.requests += 1
        self.charged_tokens += tokens
        self.reserved_cost_microusd += cost
        self.save()
        return True

    def settle(self, reserved: int, actual: int | None):
        # Unknown, malformed or implausible usage keeps the entire token reservation.
        # USD reservations are NEVER refunded: failed attempts and retries stay fully charged.
        if type(actual) is int and 0 < actual <= reserved:
            self.charged_tokens += actual - reserved
            self.save()
