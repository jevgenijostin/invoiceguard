"""Pure matching functions and tolerant CSV ingestion; no network access."""

import csv
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from itertools import combinations
from pathlib import Path


@dataclass(frozen=True)
class Invoice:
    invoice_id: str
    vendor: str
    amount: Decimal
    date: date
    description: str = ""
    source: str = ""
    row: int = 0

    def to_dict(self):
        result = asdict(self)
        result.update(amount=str(self.amount), date=self.date.isoformat())
        return result


def normalize_vendor(name: str) -> str:
    """Remove punctuation, collapse spaces, and repeatedly strip trailing legal suffixes."""
    name = "".join(c for c in name.lower() if not unicodedata.category(c).startswith("P"))
    words = name.split()
    suffixes = {"inc", "llc", "ltd", "gmbh", "co", "corp", "corporation", "ag", "kg"}
    while words and words[-1] in suffixes:
        words.pop()
    return " ".join(words)


def levenshtein_distance(left: str, right: str) -> int:
    """Dynamic programming edit distance, O(len(left)*len(right)) time and O(min) space."""
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def similarity(left: str, right: str) -> float:
    return 1.0 - levenshtein_distance(left, right) / max(len(left), len(right)) if left or right else 1.0


def duplicate_score(left: Invoice, right: Invoice, date_window: int = 14) -> float:
    """Weights: vendor 50%, amount 35%, date 15%. Amount decays to zero at 2%.

    Date decays linearly to zero just beyond the inclusive date window.
    Empty normalized vendors provide no similarity evidence.
    """
    if date_window < 0:
        raise ValueError("date window must be non-negative")
    a, b = normalize_vendor(left.vendor), normalize_vendor(right.vendor)
    vendor = similarity(a, b) if a and b else 0.0
    scale = max(abs(left.amount), abs(right.amount))
    relative = abs(left.amount - right.amount) / scale if scale else Decimal(0)
    amount = float(max(Decimal(0), Decimal(1) - relative / Decimal("0.02")))
    days = abs((left.date - right.date).days)
    proximity = max(0.0, 1.0 - days / (date_window + 1))
    return 0.50 * vendor + 0.35 * amount + 0.15 * proximity


def find_duplicates(invoices, threshold=0.75, date_window=14):
    if not 0.55 <= threshold <= 1.0:
        raise ValueError("threshold must be between 0.55 and 1.0")
    if date_window < 0:
        raise ValueError("date window must be non-negative")
    pairs = []
    for left, right in combinations(invoices, 2):
        score = duplicate_score(left, right, date_window)
        exact = left.invoice_id == right.invoice_id
        if exact or score >= 0.55:
            pairs.append({"severity": "HIGH" if exact or score >= threshold else "MEDIUM",
                          "reason": "exact-id" if exact else "fuzzy" if score >= threshold else "possible",
                          "score": score, "left": left.to_dict(), "right": right.to_dict()})
    # Exact IDs have effective confidence 1, but retain their actual fuzzy score for transparency.
    return sorted(pairs, key=lambda p: (p["reason"] == "exact-id", p["score"]), reverse=True)


def read_csv(path):
    """Return valid invoices and row errors. Rows use physical CSV line numbers.

    Broken CSV quoting stops that file because subsequent row boundaries are unknown.
    """
    invoices, errors = [], []
    source = str(Path(path))
    with open(path, encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, strict=True)
        try:
            header = next(reader, [])
            required = {"invoice_id", "vendor", "amount", "date"}
            if not required.issubset(header) or len(header) != len(set(header)):
                return [], [{"source": source, "row": 1, "error": "missing required columns or duplicate column names"}]
            for values in reader:
                line = reader.line_num
                try:
                    if len(values) != len(header):
                        raise ValueError("field count does not match header")
                    row = dict(zip(header, (value.strip() for value in values)))
                    if any(not row[key] for key in required):
                        raise ValueError("required field is empty")
                    amount = Decimal(row["amount"])
                    if not amount.is_finite() or abs(amount) > Decimal("1e15") or amount.as_tuple().exponent < -12:
                        raise ValueError("amount must be finite, at most 1e15 in magnitude, with at most 12 decimal places")
                    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["date"]):
                        raise ValueError("date must use YYYY-MM-DD")
                    parsed_date = date.fromisoformat(row["date"])
                    invoices.append(Invoice(row["invoice_id"], row["vendor"], amount, parsed_date,
                                            row.get("description", ""), source, line))
                except (ValueError, InvalidOperation) as exc:
                    errors.append({"source": source, "row": line, "error": str(exc) if not isinstance(exc, InvalidOperation) else "amount is not numeric"})
        except (csv.Error, UnicodeError) as exc:
            errors.append({"source": source, "row": reader.line_num + 1, "error": f"cannot continue parsing file: {exc}"})
    return invoices, errors
