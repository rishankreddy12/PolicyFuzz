import pytest
import sqlite3
import json
from policyfuzz import db
from policyfuzz.models import Clause, InterpreterVerdict, Case, ParserEnrichment, Cluster, Ruling, PatchProposal, ClauseEdit, VerificationResult

@pytest.fixture
def conn():
    c = db.connect(":memory:")
    db.init_schema(c)
    yield c
    c.close()

def test_schema_idempotency(conn):
    # Calling init_schema a second time should not fail
    db.init_schema(conn)
    # Check that tables exist
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    tables = {r['name'] for r in rows}
    assert 'runs' in tables
    assert 'verdicts' in tables

def test_run_repo(conn):
    db.create_run(conn, "run1", "Demo Run", "CREATED", "scripted", "policy.txt")
    
    run = db.get_run(conn, "run1")
    assert run['name'] == "Demo Run"
    assert run['status'] == "CREATED"
    
    db.set_status(conn, "run1", "PARSED")
    assert db.get_run(conn, "run1")['status'] == "PARSED"
    
    db.set_metrics(conn, "run1", {"test": 123})
    assert json.loads(db.get_run(conn, "run1")['metrics_json']) == {"test": 123}

def test_clauses_repo(conn):
    c1 = Clause(clause_id="1.1", section_id="1", section_title="Sec", text="text1")
    c2 = Clause(clause_id="1.2", section_id="1", section_title="Sec", text="text2")
    db.save_clauses(conn, "run1", [c1, c2])
    
    saved = db.get_clauses(conn, "run1")
    assert len(saved) == 2
    assert saved[0].clause_id == "1.1"

def test_verdicts_upsert_and_resume(conn):
    v1 = InterpreterVerdict(case_id="C01", verdict="ALLOW", cited_clauses=["1.1"], confidence=0.8, rationale="Ration12345")
    
    # First insert
    db.upsert_verdict(conn, "run1", "v1", v1, "A", valid=True)
    
    assert db.has_valid_verdict(conn, "run1", "v1", "C01", "A") is True
    assert db.has_valid_verdict(conn, "run1", "v1", "C01", "B") is False
    
    # Update same key
    v1_mod = InterpreterVerdict(case_id="C01", verdict="DENY", cited_clauses=["1.1"], confidence=0.9, rationale="Ration12345")
    db.upsert_verdict(conn, "run1", "v1", v1_mod, "A", valid=True)
    
    saved = db.get_verdicts(conn, "run1", "v1")
    assert len(saved) == 1
    assert saved[0].verdict == "DENY"

def test_patches_and_edits(conn):
    edit1 = ClauseEdit(edit_id="E1", action="REPLACE", clause_id="1.1", new_text="New text 123", addresses_clusters=["K1"], rationale="R1")
    edit2 = ClauseEdit(edit_id="E2", action="REPLACE", clause_id="1.2", new_text="New text 123", addresses_clusters=["K1"], rationale="R2")
    proposal = PatchProposal(edits=[edit1, edit2], decision_table=[], sibling_cases=[], sibling_expected={})
    
    db.save_patch(conn, "run1", round_num=1, proposal=proposal, status="DRAFT")
    
    # Edits should start with approved=NULL
    decisions = db.get_edit_decisions(conn, "run1", round_num=1)
    assert decisions["E1"] is None
    
    db.set_edit_decision(conn, "run1", round_num=1, edit_id="E1", approved=True)
    db.set_edit_decision(conn, "run1", round_num=1, edit_id="E2", approved=False)
    
    decisions = db.get_edit_decisions(conn, "run1", round_num=1)
    assert decisions["E1"] is True
    assert decisions["E2"] is False
