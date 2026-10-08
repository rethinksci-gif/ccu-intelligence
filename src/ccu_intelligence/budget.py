"""Persist reservations before network calls; crashes cannot silently reset spending caps."""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Budget:
    max_requests: int = 8
    max_tokens: int = 24000
    requests: int = 0
    charged_tokens: int = 0
    path: Path | None = None

    def save(self):
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(
                    {
                        k: getattr(self, k)
                        for k in ("max_requests", "max_tokens", "requests", "charged_tokens")
                    }
                )
            )
            tmp.replace(self.path)

    def reserve(self, tokens: int) -> bool:
        if self.requests >= self.max_requests or self.charged_tokens + tokens > self.max_tokens:
            return False
        self.requests += 1
        self.charged_tokens += tokens
        self.save()
        return True

    def settle(self, reserved: int, actual: int | None):
        # Missing usage/network uncertainty keeps the full reservation charged.
        if actual is not None:
            self.charged_tokens += actual - reserved
            self.save()
