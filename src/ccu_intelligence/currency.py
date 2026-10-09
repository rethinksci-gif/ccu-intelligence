"""Currency sanity check: flag "X (Y)" pairs whose two currencies disagree at a reference rate. Never corrects."""

import re

# Approximate USD per unit, used only to spot gross mismatches (tolerance 20%). Not market data; never published.
REFERENCE_USD = {"USD": 1.0, "EUR": 1.10, "GBP": 1.30, "CHF": 1.20, "SEK": 0.10, "DKK": 0.15, "NOK": 0.095,
                 "ZAR": 0.056, "INR": 0.012, "CNY": 0.14, "JPY": 0.0068, "AUD": 0.66, "CAD": 0.73}
TOLERANCE = 1.2
SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "mln": 1e6, "million": 1e6, "bn": 1e9, "b": 1e9,
         "billion": 1e9, "tn": 1e12, "trillion": 1e12, "lakh": 1e5, "crore": 1e7, "cr": 1e7}
PREFIX = {"us$": "USD", "$": "USD", "usd": "USD", "€": "EUR", "eur": "EUR", "£": "GBP", "gbp": "GBP", "r": "ZAR",
          "zar": "ZAR", "rs": "INR", "rs.": "INR", "₹": "INR", "inr": "INR", "sek": "SEK", "dkk": "DKK", "nok": "NOK",
          "chf": "CHF", "cny": "CNY", "rmb": "CNY", "jpy": "JPY", "a$": "AUD", "aud": "AUD", "c$": "CAD", "cad": "CAD"}
SUFFIX = {"euros": "EUR", "euro": "EUR", "rand": "ZAR", "rupees": "INR", "kronor": "SEK", "kroner": "DKK",
          "yuan": "CNY", "dollars": "USD"}
_CUR = r"(?P<{0}cur>US\$|A\$|C\$|\$|€|£|₹|Rs\.?|R(?=\s?\d)|USD|EUR|GBP|ZAR|INR|SEK|DKK|NOK|CHF|CNY|RMB|JPY|AUD|CAD)"
_NUM = r"(?P<{0}num>\d[\d,]*(?:\.\d+)?)"
_SCALE = r"(?:[\s-]?(?P<{0}scale>thousand|million|billion|trillion|mln|mn|bn|tn|lakh|crore|cr|k|m|b)\b)?"
_SUF = r"(?:\s(?P<{0}suf>euros?|rand|rupees|kronor|kroner|yuan|dollars)\b)?"


def _money(tag: str) -> str:
    return (r"(?:" + _CUR.format(tag) + r"\s?)?" + _NUM.format(tag) + _SCALE.format(tag) + _SUF.format(tag))


PAIR = re.compile(_money("a") + r"\s*\(\s*(?:about|approx\.?|approximately|around|roughly|some|~|≈|c\.)?\s*"
                  + _money("b") + r"\s*\)", re.I)


def _value(match, tag) -> tuple[str, float] | None:
    cur, suffix = match.group(tag + "cur"), (match.group(tag + "suf") or "").lower()
    code = PREFIX.get(cur.lower()) if cur else SUFFIX.get(suffix)
    if not code:
        return None
    amount = float(match.group(tag + "num").replace(",", ""))
    scale = SCALE.get((match.group(tag + "scale") or "").lower(), 1)
    return code, amount * scale


def mismatches(text: str) -> list[dict]:
    """Two-currency pairs ("R12bn ($73m)") whose amounts differ by more than 20% at the reference rates."""
    found = []
    for match in PAIR.finditer(text or ""):
        a, b = _value(match, "a"), _value(match, "b")
        if not a or not b or a[0] == b[0] or a[0] not in REFERENCE_USD or b[0] not in REFERENCE_USD:
            continue
        usd_a, usd_b = a[1] * REFERENCE_USD[a[0]], b[1] * REFERENCE_USD[b[0]]
        if min(usd_a, usd_b) <= 0:
            continue
        ratio = max(usd_a, usd_b) / min(usd_a, usd_b)
        if ratio > TOLERANCE:
            found.append({"text": match.group(0), "from": a[0], "to": b[0], "expected_usd": usd_a,
                          "stated_usd": usd_b, "ratio": round(ratio, 1)})
    return found


def _usd(value: float) -> str:
    for size, unit in ((1e9, "bn"), (1e6, "m"), (1e3, "k")):
        if value >= size:
            return f"USD {value / size:.3g}{unit}"
    return f"USD {value:.3g}"


def note(headline: str, issue: dict) -> str:
    return (f"Currency check in '{headline}': '{issue['text']}' — at a reference rate the {issue['from']} amount is about "
            f"{_usd(issue['expected_usd'])}, but the {issue['to']} figure is {_usd(issue['stated_usd'])} "
            f"(x{issue['ratio']}). Not corrected; verify against the original source.")
