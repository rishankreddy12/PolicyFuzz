"""Event logging: log_event() and event types."""

import sqlite3
import json
from datetime import datetime, timezone
from typing import Optional, List, Any

# We must defer to db.py for SQL, but to avoid circular imports, db.py imports this, so let's import db inside the functions or use the connection directly if we assume db.py handles events too. Actually, the spec says "db.py is the only module containing SQL" and "events.py: log_event...".
# Let's move the SQL to db.py and have events.py call it.
from policyfuzz import db

def log_event(conn: sqlite3.Connection, run_id: str, stage: str, level: str, message: str, payload: Optional[Any] = None) -> None:
    """Log an event. Level should be one of INFO, WARN, ERROR, HUMAN."""
    payload_json = json.dumps(payload, sort_keys=True) if payload is not None else None
    ts = datetime.now(timezone.utc).isoformat()
    db.insert_event(conn, run_id, ts, stage, level, message, payload_json)

def list_events(conn: sqlite3.Connection, run_id: str, since_id: int = 0) -> List[sqlite3.Row]:
    """Retrieve events for a run, optionally filtering by id > since_id."""
    return db.get_events(conn, run_id, since_id)

