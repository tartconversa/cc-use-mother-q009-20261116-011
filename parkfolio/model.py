from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


class DomainError(ValueError):
    pass


class MissingReference(DomainError):
    pass


class Conflict(DomainError):
    pass


def require_text(value: Any, name: str, *, limit: int = 120) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise DomainError(f"{name} must be nonempty text up to {limit} characters")
    return value.strip()


def timestamp(value: Any, name: str = "timestamp") -> str:
    if not isinstance(value, str):
        raise DomainError(f"{name} must be an ISO8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DomainError(f"{name} must be an ISO8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise DomainError(f"{name} needs an explicit timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def day(value: Any, name: str = "day") -> str:
    normalized = timestamp(value, name)
    return normalized[:10]


def month(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", value):
        raise DomainError("month must be YYYY-MM")
    return value


def decimal(value: Any, name: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise DomainError(f"{name} must be decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise DomainError(f"{name} must be decimal") from exc
    if not result.is_finite() or (positive and result <= 0) or (not positive and result < 0):
        raise DomainError(f"{name} is outside allowed range")
    return result


def money(value: Any, name: str = "amount") -> str:
    result = decimal(value, name)
    if result.as_tuple().exponent < -2:
        raise DomainError(f"{name} supports at most two decimal places")
    return format(result.quantize(Decimal("0.01")), "f")


def minutes(value: Any) -> int:
    if type(value) is not int or value <= 0 or value > 1440:
        raise DomainError("minutes must be an integer from 1 to 1440")
    return value


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Event:
    source: str
    external_id: str
    kind: str
    occurred_at: str
    received_at: str
    payload: dict[str, Any]

    @classmethod
    def parse(cls, data: dict[str, Any]) -> Event:
        if not isinstance(data, dict) or not isinstance(data.get("payload"), dict):
            raise DomainError("event needs an object payload")
        kind = require_text(data.get("kind"), "kind")
        if kind not in {"visit_open", "visit_close", "reading", "order", "refund", "attendance"}:
            raise DomainError(f"unsupported kind: {kind}")
        return cls(
            source=require_text(data.get("source"), "source"),
            external_id=require_text(data.get("external_id"), "external_id"),
            kind=kind,
            occurred_at=timestamp(data.get("occurred_at"), "occurred_at"),
            received_at=timestamp(data.get("received_at"), "received_at"),
            payload=data["payload"],
        )

    def data(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "external_id": self.external_id,
            "kind": self.kind,
            "occurred_at": self.occurred_at,
            "received_at": self.received_at,
            "payload": self.payload,
        }
