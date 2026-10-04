"""SQLite connection, DDL, and typed repository functions."""

import sqlite3
import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from policyfuzz.models import (
    Clause, ParserEnrichment, Case, InterpreterVerdict,
    Cluster, Ruling, PatchProposal, VerificationResult
)

def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_schema(conn: sqlite3.Connection) -> None:
    schema = """
    CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY,
        name TEXT,
        status TEXT,
        provider TEXT,
        round INTEGER DEFAULT 1,
        policy_path TEXT,
        metrics_json TEXT,
        error TEXT,
        created_at TEXT,
        updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS clauses (
        run_id TEXT,
        clause_id TEXT,
        section_id TEXT,
        section_title TEXT,
        text TEXT,
        PRIMARY KEY (run_id, clause_id)
    );
    CREATE TABLE IF NOT EXISTS enrichment (
        run_id TEXT PRIMARY KEY,
        json TEXT
    );
    CREATE TABLE IF NOT EXISTS cases (
        run_id TEXT,
        case_id TEXT,
        title TEXT,
        narrative TEXT,
        target_clauses_json TEXT,
        boundary_type TEXT,
        origin TEXT,
        sibling_round INTEGER,
        expected_verdict TEXT,
        PRIMARY KEY (run_id, case_id)
    );
    CREATE TABLE IF NOT EXISTS verdicts (
        run_id TEXT,
        policy_tag TEXT,
        case_id TEXT,
        interpreter TEXT,
        verdict TEXT,
        cited_json TEXT,
        confidence REAL,
        rationale TEXT,
        valid INTEGER,
        error TEXT,
        PRIMARY KEY (run_id, policy_tag, case_id, interpreter)
    );
    CREATE TABLE IF NOT EXISTS clusters (
        run_id TEXT,
        cluster_id TEXT,
        rank INTEGER,
        json TEXT,
        is_fallback INTEGER,
        PRIMARY KEY (run_id, cluster_id)
    );
    CREATE TABLE IF NOT EXISTS rulings (
        run_id TEXT,
        cluster_id TEXT,
        ruling TEXT,
        note TEXT,
        decided_at TEXT,
        PRIMARY KEY (run_id, cluster_id)
    );
    CREATE TABLE IF NOT EXISTS patches (
        run_id TEXT,
        round INTEGER,
        proposal_json TEXT,
        status TEXT,
        policy_v2_path TEXT,
        PRIMARY KEY (run_id, round)
    );
    CREATE TABLE IF NOT EXISTS patch_edits (
        run_id TEXT,
        round INTEGER,
        edit_id TEXT,
        approved INTEGER,
        decided_at TEXT,
        PRIMARY KEY (run_id, round, edit_id)
    );
    CREATE TABLE IF NOT EXISTS verifications (
        run_id TEXT,
        round INTEGER,
        json TEXT,
        PRIMARY KEY (run_id, round)
    );
    CREATE TABLE IF NOT EXISTS llm_calls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT,
        call_key TEXT,
        role TEXT,
        provider TEXT,
        model TEXT,
        attempt INTEGER,
        request_json TEXT,
        response_text TEXT,
        parsed_ok INTEGER,
        error TEXT,
        latency_ms INTEGER,
        ts TEXT
    );
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT,
        ts TEXT,
        stage TEXT,
        level TEXT,
        message TEXT,
        payload_json TEXT
    );
    """
    conn.executescript(schema)
    conn.commit()

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

# -- Runs --

def create_run(conn: sqlite3.Connection, run_id: str, name: str, status: str, provider: str, policy_path: str) -> None:
    conn.execute(
        "INSERT INTO runs (run_id, name, status, provider, policy_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (run_id, name, status, provider, policy_path, now_iso(), now_iso())
    )
    conn.commit()

def get_run(conn: sqlite3.Connection, run_id: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()

def set_status(conn: sqlite3.Connection, run_id: str, status: str) -> None:
    conn.execute("UPDATE runs SET status=?, updated_at=? WHERE run_id=?", (status, now_iso(), run_id))
    conn.commit()

def set_metrics(conn: sqlite3.Connection, run_id: str, metrics: dict) -> None:
    conn.execute("UPDATE runs SET metrics_json=?, updated_at=? WHERE run_id=?", (json.dumps(metrics, sort_keys=True), now_iso(), run_id))
    conn.commit()

def set_error(conn: sqlite3.Connection, run_id: str, error: str) -> None:
    conn.execute("UPDATE runs SET error=?, status='FAILED', updated_at=? WHERE run_id=?", (error, now_iso(), run_id))
    conn.commit()

def list_runs(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return conn.execute("SELECT * FROM runs ORDER BY created_at DESC").fetchall()

# -- Clauses & Enrichment --

def save_clauses(conn: sqlite3.Connection, run_id: str, clauses: List[Clause]) -> None:
    with conn:
        for c in clauses:
            conn.execute(
                "INSERT OR REPLACE INTO clauses (run_id, clause_id, section_id, section_title, text) VALUES (?, ?, ?, ?, ?)",
                (run_id, c.clause_id, c.section_id, c.section_title, c.text)
            )

def get_clauses(conn: sqlite3.Connection, run_id: str) -> List[Clause]:
    rows = conn.execute("SELECT * FROM clauses WHERE run_id=? ORDER BY clause_id", (run_id,)).fetchall()
    return [Clause(**dict(row)) for row in rows]

def save_enrichment(conn: sqlite3.Connection, run_id: str, enrichment: ParserEnrichment) -> None:
    conn.execute("INSERT OR REPLACE INTO enrichment (run_id, json) VALUES (?, ?)", (run_id, enrichment.model_dump_json()))
    conn.commit()

def get_enrichment(conn: sqlite3.Connection, run_id: str) -> Optional[ParserEnrichment]:
    row = conn.execute("SELECT json FROM enrichment WHERE run_id=?", (run_id,)).fetchone()
    if row and row['json']:
        return ParserEnrichment.model_validate_json(row['json'])
    return None

# -- Cases --

def save_cases(conn: sqlite3.Connection, run_id: str, cases: List[Case], origin: str = 'generated', sibling_round: Optional[int] = None, expected_verdicts: Optional[Dict[str, str]] = None) -> None:
    with conn:
        for c in cases:
            expected = expected_verdicts.get(c.case_id) if expected_verdicts else None
            conn.execute(
                "INSERT OR REPLACE INTO cases (run_id, case_id, title, narrative, target_clauses_json, boundary_type, origin, sibling_round, expected_verdict) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, c.case_id, c.title, c.narrative, json.dumps(c.target_clauses, sort_keys=True), c.boundary_type, origin, sibling_round, expected)
            )

def get_cases(conn: sqlite3.Connection, run_id: str, origin: Optional[str] = None) -> List[Case]:
    query = "SELECT * FROM cases WHERE run_id=?"
    params = [run_id]
    if origin:
        query += " AND origin=?"
        params.append(origin)
    query += " ORDER BY case_id"
    rows = conn.execute(query, tuple(params)).fetchall()
    return [
        Case(
            case_id=row['case_id'], title=row['title'], narrative=row['narrative'],
            target_clauses=json.loads(row['target_clauses_json']), boundary_type=row['boundary_type'],
            expected_verdict=row['expected_verdict']
        )
        for row in rows
    ]

def get_case(conn: sqlite3.Connection, run_id: str, case_id: str) -> Optional[Case]:
    row = conn.execute("SELECT * FROM cases WHERE run_id=? AND case_id=?", (run_id, case_id)).fetchone()
    if not row:
        return None
    return Case(
        case_id=row['case_id'], title=row['title'], narrative=row['narrative'],
        target_clauses=json.loads(row['target_clauses_json']), boundary_type=row['boundary_type'],
        expected_verdict=row['expected_verdict']
    )

# -- Verdicts --

def upsert_verdict(conn: sqlite3.Connection, run_id: str, policy_tag: str, v: InterpreterVerdict, interpreter: str, valid: bool, error: Optional[str] = None) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO verdicts (run_id, policy_tag, case_id, interpreter, verdict, cited_json, confidence, rationale, valid, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, policy_tag, v.case_id, interpreter, v.verdict, json.dumps(v.cited_clauses, sort_keys=True), v.confidence, v.rationale, int(valid), error)
    )
    conn.commit()

def get_verdicts(conn: sqlite3.Connection, run_id: str, policy_tag: str) -> List[InterpreterVerdict]:
    rows = conn.execute("SELECT * FROM verdicts WHERE run_id=? AND policy_tag=? AND valid=1", (run_id, policy_tag)).fetchall()
    return [
        InterpreterVerdict(
            case_id=r['case_id'], verdict=r['verdict'], cited_clauses=json.loads(r['cited_json']),
            confidence=r['confidence'], rationale=r['rationale']
        )
        for r in rows
    ]

def has_valid_verdict(conn: sqlite3.Connection, run_id: str, policy_tag: str, case_id: str, interpreter: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM verdicts WHERE run_id=? AND policy_tag=? AND case_id=? AND interpreter=? AND valid=1",
        (run_id, policy_tag, case_id, interpreter)
    ).fetchone()
    return bool(row)

# -- Clusters & Rulings --

def save_clusters(conn: sqlite3.Connection, run_id: str, clusters: List[Cluster], is_fallback: bool = False) -> None:
    with conn:
        for i, c in enumerate(clusters):
            conn.execute(
                "INSERT OR REPLACE INTO clusters (run_id, cluster_id, rank, json, is_fallback) VALUES (?, ?, ?, ?, ?)",
                (run_id, c.cluster_id, i, c.model_dump_json(), int(is_fallback))
            )

def get_clusters(conn: sqlite3.Connection, run_id: str) -> List[Cluster]:
    rows = conn.execute("SELECT json FROM clusters WHERE run_id=? ORDER BY rank", (run_id,)).fetchall()
    return [Cluster.model_validate_json(r['json']) for r in rows]

def save_rulings(conn: sqlite3.Connection, run_id: str, rulings: List[Ruling]) -> None:
    with conn:
        for r in rulings:
            conn.execute(
                "INSERT OR REPLACE INTO rulings (run_id, cluster_id, ruling, note, decided_at) VALUES (?, ?, ?, ?, ?)",
                (run_id, r.cluster_id, r.ruling, r.note, now_iso())
            )

def get_rulings(conn: sqlite3.Connection, run_id: str) -> List[Ruling]:
    rows = conn.execute("SELECT * FROM rulings WHERE run_id=?", (run_id,)).fetchall()
    return [Ruling(cluster_id=r['cluster_id'], ruling=r['ruling'], note=r['note'] or "") for r in rows]

# -- Patches & Edits --

def save_patch(conn: sqlite3.Connection, run_id: str, round_num: int, proposal: PatchProposal, status: str) -> None:
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO patches (run_id, round, proposal_json, status) VALUES (?, ?, ?, ?)",
            (run_id, round_num, proposal.model_dump_json(), status)
        )
        for edit in proposal.edits:
            # Leave approved NULL
            conn.execute(
                "INSERT OR REPLACE INTO patch_edits (run_id, round, edit_id) VALUES (?, ?, ?)",
                (run_id, round_num, edit.edit_id)
            )

def get_patch(conn: sqlite3.Connection, run_id: str, round_num: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM patches WHERE run_id=? AND round=?", (run_id, round_num)).fetchone()

def set_edit_decision(conn: sqlite3.Connection, run_id: str, round_num: int, edit_id: str, approved: bool) -> None:
    conn.execute(
        "UPDATE patch_edits SET approved=?, decided_at=? WHERE run_id=? AND round=? AND edit_id=?",
        (int(approved), now_iso(), run_id, round_num, edit_id)
    )
    conn.commit()

def get_edit_decisions(conn: sqlite3.Connection, run_id: str, round_num: int) -> Dict[str, Optional[bool]]:
    rows = conn.execute("SELECT edit_id, approved FROM patch_edits WHERE run_id=? AND round=?", (run_id, round_num)).fetchall()
    res = {}
    for r in rows:
        val = r['approved']
        res[r['edit_id']] = bool(val) if val is not None else None
    return res

# -- Verification --

def save_verification(conn: sqlite3.Connection, run_id: str, round_num: int, vr: VerificationResult) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO verifications (run_id, round, json) VALUES (?, ?, ?)",
        (run_id, round_num, vr.model_dump_json())
    )
    conn.commit()

def get_verification(conn: sqlite3.Connection, run_id: str, round_num: int) -> Optional[VerificationResult]:
    row = conn.execute("SELECT json FROM verifications WHERE run_id=? AND round=?", (run_id, round_num)).fetchone()
    return VerificationResult.model_validate_json(row['json']) if row else None

# -- LLM Calls --

def log_llm_call(conn: sqlite3.Connection, run_id: str, call_key: str, role: str, provider: str, model: str, attempt: int, request_json: str, response_text: str, parsed_ok: bool, error: Optional[str], latency_ms: int) -> None:
    conn.execute(
        "INSERT INTO llm_calls (run_id, call_key, role, provider, model, attempt, request_json, response_text, parsed_ok, error, latency_ms, ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, call_key, role, provider, model, attempt, request_json, response_text, int(parsed_ok), error, latency_ms, now_iso())
    )
    conn.commit()

def list_llm_calls(conn: sqlite3.Connection, run_id: str) -> List[sqlite3.Row]:
    return conn.execute("SELECT * FROM llm_calls WHERE run_id=? ORDER BY id", (run_id,)).fetchall()

# -- Events --

def insert_event(conn: sqlite3.Connection, run_id: str, ts: str, stage: str, level: str, message: str, payload_json: Optional[str]) -> None:
    conn.execute(
        "INSERT INTO events (run_id, ts, stage, level, message, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, ts, stage, level, message, payload_json)
    )
    conn.commit()

def get_events(conn: sqlite3.Connection, run_id: str, since_id: int) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM events WHERE run_id=? AND id > ? ORDER BY id",
        (run_id, since_id)
    ).fetchall()

