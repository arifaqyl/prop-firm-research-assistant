from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .domain import AuditEntry


class AuditLog:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    def append(self, event_type: str, payload: dict[str, Any]) -> AuditEntry:
        previous_hash = self.entries[-1].hash if self.entries else "genesis"
        timestamp = datetime.now(timezone.utc)
        normalized = json.dumps(
            {
                "event_type": event_type,
                "payload": payload,
                "previous_hash": previous_hash,
                "timestamp": timestamp.isoformat(),
            },
            sort_keys=True,
            default=str,
        )
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        entry = AuditEntry(
            id=str(uuid4()),
            timestamp=timestamp,
            event_type=event_type,
            payload=payload,
            previous_hash=previous_hash,
            hash=digest,
        )
        self.entries.append(entry)
        return entry

    def for_trade(self, trade_id: str) -> list[AuditEntry]:
        return [entry for entry in self.entries if entry.payload.get("trade_id") == trade_id]

    def verify_chain(self) -> bool:
        previous = "genesis"
        for entry in self.entries:
            if entry.previous_hash != previous:
                return False
            previous = entry.hash
        return True
