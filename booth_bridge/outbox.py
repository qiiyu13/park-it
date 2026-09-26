"""File-backed outbox for e-money deduct results.

The card is debited before the result reaches the API. If the bridge dies
(or the API stays down) between those two points, an in-memory queue loses
the only record of the charge. Each result is therefore written to a file
before the first POST attempt and deleted only after a confirmed success;
anything left on disk after a crash is re-driven on the next boot by the
drain task in main.py.

One JSON file per payload, written atomically (tmp + rename) so a crash
mid-write never yields a truncated entry.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from shared.logging import get_logger

logger = get_logger("booth_outbox")


class ResultOutbox:
    def __init__(self, directory: str | Path) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, payload: dict) -> Path:
        # Identity of a deduct result: one file per card transaction.
        key = f"{payload.get('transaction_id', 'x')}_{payload.get('card_number', '')}_{payload.get('transaction_counter', 0)}_{payload.get('status', '')}"
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in key)
        return self.dir / f"{safe}.json"

    def put(self, payload: dict) -> Path:
        path = self._path_for(payload)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload))
        tmp.replace(path)
        return path

    def remove(self, payload: dict) -> None:
        path = self._path_for(payload)
        path.unlink(missing_ok=True)

    def pending(self, *, max_age_s: float = 86400.0) -> list[dict]:
        """Return payloads still awaiting delivery, oldest first.

        Entries older than ``max_age_s`` are dropped with a log line — after
        a day the parking transaction has long since resolved some other way
        and replaying a stale deduct would do more harm than good.
        """
        now = time.time()
        out: list[dict] = []
        for path in sorted(self.dir.glob("*.json")):
            try:
                if now - path.stat().st_mtime > max_age_s:
                    logger.warning("outbox_entry_expired", path=path.name)
                    path.unlink(missing_ok=True)
                    continue
                out.append(json.loads(path.read_text()))
            except (OSError, json.JSONDecodeError) as e:
                logger.error("outbox_entry_unreadable", path=path.name, error=str(e))
        return out
