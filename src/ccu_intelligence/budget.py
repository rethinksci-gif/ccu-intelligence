"""Persist conservative token and spend reservations before every network attempt."""

import json
import math
import threading
from dataclasses import dataclass, field, fields
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
    # Single-rate legacy reservations charge every token at the higher peak rate.
    usd_per_million_tokens: float = 1.20
    reserved_cost_microusd: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def __post_init__(self):
        if self.max_requests < 0 or self.max_tokens < 1 or self.requests < 0 or self.charged_tokens < 0:
            raise ValueError('Invalid request/token budget')
        if not math.isfinite(self.usd_per_million_tokens) or self.usd_per_million_tokens < 1.20:
            raise ValueError('Rate ceiling must be finite and at least USD 1.20 per million tokens')
        if self.max_spend_usd is not None and (
            not math.isfinite(self.max_spend_usd) or self.max_spend_usd < 0
        ):
            raise ValueError('Spend budget must be finite and non-negative')

    @staticmethod
    def priced(input_tokens: int, output_tokens: int, input_rate: float, output_rate: float) -> int:
        """Micro-USD for a call at per-million-token rates, rounded up."""
        value = Decimal(input_tokens) * Decimal(str(input_rate)) + Decimal(output_tokens) * Decimal(str(output_rate))
        return int(value.to_integral_value(rounding=ROUND_CEILING))

    def cost(self, tokens):
        return self.priced(tokens, 0, self.usd_per_million_tokens, 0)

    def save(self):
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix('.tmp')
            skip = {'path', 'lock'}
            tmp.write_text(json.dumps({f.name: getattr(self, f.name) for f in fields(self) if f.name not in skip}))
            tmp.replace(self.path)

    def _reserve(self, tokens: int, cost: int) -> bool:
        with self.lock:
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

    def reserve(self, tokens: int) -> bool:
        if type(tokens) is not int or tokens < 1:
            raise ValueError('Invalid token reservation')
        return self._reserve(tokens, self.cost(tokens))

    def reserve_priced(self, input_tokens: int, output_tokens: int, input_rate: float, output_rate: float) -> int:
        """Reserve a worst-case call at ceiling rates; returns the micro-USD reserved, or 0 if refused."""
        for value in (input_tokens, output_tokens):
            if type(value) is not int or value < 1:
                raise ValueError('Invalid token reservation')
        cost = self.priced(input_tokens, output_tokens, input_rate, output_rate)
        return cost if self._reserve(input_tokens + output_tokens, cost) else 0

    def settle(self, reserved: int, actual: int | None):
        # Unknown, malformed or implausible usage keeps the entire token reservation.
        # Legacy single-rate USD reservations are never refunded.
        if type(actual) is int and 0 < actual <= reserved:
            with self.lock:
                self.charged_tokens += actual - reserved
                self.save()

    def settle_priced(self, reserved_tokens: int, reserved_cost: int, usage: dict | None,
                      input_rate: float, output_rate: float):
        """Replace a reservation with the provider-reported usage, priced at the same ceiling rates.

        Missing, malformed or implausible usage (non-integers, negatives, or more than was reserved)
        keeps the whole reservation. Reported usage is what the provider bills, so the remaining
        reservation stays an upper bound on actual spend.
        """
        usage = usage or {}
        prompt, completion = usage.get('prompt_tokens'), usage.get('completion_tokens')
        if not all(type(v) is int and v >= 0 for v in (prompt, completion)):
            return
        total = prompt + completion
        actual_cost = self.priced(prompt, completion, input_rate, output_rate)
        if not 0 < total <= reserved_tokens or actual_cost > reserved_cost:
            return
        with self.lock:
            self.charged_tokens += total - reserved_tokens
            self.reserved_cost_microusd += actual_cost - reserved_cost
            self.save()
