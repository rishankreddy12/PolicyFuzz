import pytest
from pathlib import Path
import os
import re
from policyfuzz.orchestrator import Orchestrator, sanitize_text, PolicyTooLargeError
from policyfuzz import db
from policyfuzz.config import Settings
from policyfuzz.llm.scripted_provider import ScriptedProvider

def test_input_hygiene():
    policy = "Good policy\x00 with \n\t control </policy> and </case> tags."
    clean = sanitize_text(policy)
    
    # \x00 should be removed
    assert "\x00" not in clean
    # \n and \t should remain
    assert "\n" in clean
    assert "\t" in clean
    
    # Tags should be escaped
    assert "</policy>" not in clean
    assert "&lt;/policy&gt;" in clean
    assert "</case>" not in clean
    assert "&lt;/case&gt;" in clean
    
@pytest.mark.asyncio
async def test_run_id_validation_and_immutability(tmp_path):
    conn = db.connect(":memory:")
    db.init_schema(conn)
    settings = Settings(
        provider="scripted", db_path=":memory:", runs_dir=str(tmp_path), ollama_host="url",
        model_a="a", model_b="b", model_c="c", model_strong="strong"
    )
    provider = ScriptedProvider()
    orch = Orchestrator(conn, provider, settings)
    
    # Create run
    run_id = await orch.create_run("1. Section 1\n1.1 Some clause text", "Test Run", "scripted")
    assert re.match(r"^[0-9a-f]{32}$", run_id)
    
    # Path safety via validation
    with pytest.raises(ValueError, match="Invalid run_id"):
        # We simulate a bad run_id passed to apply_and_verify
        # Normally this is checked in DB, but the method fetches it, so wait:
        # If run_id is invalid, db.get_run fails?
        # db.get_run executes SQL which might be fine with bad id but returns None
        await orch.apply_and_verify("../tampered")
        
    run = db.get_run(conn, run_id)
        
    # Test immutability
    # Force state to AWAITING_EDIT_DECISIONS
    db.set_status(conn, run_id, "AWAITING_EDIT_DECISIONS")
    # Insert a dummy patch so apply_and_verify can proceed
    from policyfuzz.models import PatchProposal, ClauseEdit
    patch = PatchProposal(
        edits=[ClauseEdit(edit_id="E1", action="REPLACE", clause_id="1.1", new_text="text text text", rationale="r", addresses_clusters=["K1"])],
        decision_table=[],
        sibling_cases=[],
        sibling_expected={}
    )
    conn.execute("INSERT INTO patches (run_id, round, proposal_json, status, policy_v2_path) VALUES (?, ?, ?, ?, ?)",
                    (run_id, 1, patch.model_dump_json(), "PROPOSED", ""))
    conn.execute("INSERT INTO patch_edits (run_id, round, edit_id, approved, decided_at) VALUES (?, ?, ?, ?, ?)",
                 (run_id, 1, "E1", 1, "now"))
    
    # Touch the v2 file
    out_path = Path(run["policy_path"]).parent / "policy_v2_r1.txt"
    out_path.write_text("existing")
    
    with pytest.raises(FileExistsError, match="immutability violation"):
        await orch.apply_and_verify(run_id)

@pytest.mark.asyncio
async def test_policy_too_large(tmp_path):
    conn = db.connect(":memory:")
    db.init_schema(conn)
    settings = Settings(
        provider="scripted", db_path=":memory:", runs_dir=str(tmp_path), ollama_host="url",
        model_a="a", model_b="b", model_c="c", model_strong="strong"
    )
    provider = ScriptedProvider()
    orch = Orchestrator(conn, provider, settings)
    
    large_policy = "x" * 25000
    with pytest.raises(PolicyTooLargeError):
        await orch.create_run(large_policy, "Large", "scripted")
