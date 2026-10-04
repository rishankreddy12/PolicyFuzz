import pytest
import sqlite3
import os
import json
from pathlib import Path

from policyfuzz import db
from policyfuzz.config import Settings
from policyfuzz.llm.scripted_provider import ScriptedProvider
from policyfuzz.orchestrator import Orchestrator
from policyfuzz.models import RunStatus, Ruling, PatchProposal
from policyfuzz.report import build_report_md

@pytest.fixture
def env_setup():
    base = Path(__file__).parent.parent.parent
    path = base / "fixtures" / "demo" / "scripted_responses.json"
    os.environ["POLICYFUZZ_SCRIPTED_PATH"] = str(path)
    yield
    if "POLICYFUZZ_SCRIPTED_PATH" in os.environ:
        del os.environ["POLICYFUZZ_SCRIPTED_PATH"]

@pytest.mark.asyncio
async def test_e2e_scripted_demo(tmp_path, env_setup):
    conn = db.connect(":memory:")
    db.init_schema(conn)
    
    settings = Settings(
        provider="scripted", db_path=":memory:", runs_dir=str(tmp_path), ollama_host="url",
        model_a="a", model_b="b", model_c="c", model_strong="strong"
    )
    provider = ScriptedProvider()
    orch = Orchestrator(conn, provider, settings)
    
    base = Path(__file__).parent.parent.parent
    with open(base / "fixtures" / "demo" / "policy_v1.txt", "r", encoding="utf-8") as f:
        policy = f.read()
        
    run_id = await orch.create_run(policy, "Test E2E", "scripted")
    
    status = await orch.run_until_gate(run_id)
    if status == RunStatus.FAILED:
        pytest.fail(f"Run failed: {db.get_run(conn, run_id)['error']}")
        
    assert status == RunStatus.AWAITING_RULINGS
    
    # Debug
    c = conn.cursor()
    c.execute("SELECT message FROM events WHERE level='WARN'")
    for row in c.fetchall():
        print(f"WARN: {row[0]}")
        
    # We expect 3 clusters based on scripted demo
    clusters = db.get_clusters(conn, run_id)
    assert len(clusters) == 3
    
    # Rulings based on the actual cases in the clusters
    rulings = []
    for c in clusters:
        if "C27" in c.case_ids:
            rulings.append(Ruling(cluster_id=c.cluster_id, ruling="DENY", note=""))
        elif "C24" in c.case_ids:
            rulings.append(Ruling(cluster_id=c.cluster_id, ruling="ALLOW", note=""))
        else:
            rulings.append(Ruling(cluster_id=c.cluster_id, ruling="ESCALATE", note=""))
            
    orch.submit_rulings(run_id, rulings)
    
    # Gate 2
    status = await orch.run_until_gate(run_id)
    if status == RunStatus.FAILED:
        pytest.fail(f"Run failed: {db.get_run(conn, run_id)['error']}")
        
    assert status == RunStatus.AWAITING_EDIT_DECISIONS
    
    # Approve all edits
    patch_row = db.get_patch(conn, run_id, 1)
    patch_model = PatchProposal.model_validate_json(patch_row["proposal_json"])
    approvals = {e.edit_id: True for e in patch_model.edits}
    orch.decide_edits(run_id, 1, approvals)
    
    # Apply and verify
    await orch.apply_and_verify(run_id)
    
    # Check status
    run = db.get_run(conn, run_id)
    print("METRICS:", run["metrics_json"])
    assert run["status"] == RunStatus.COMPLETE_IMPROVED
    
    # Check metrics
    metrics = json.loads(run["metrics_json"])
    v_res = metrics["v2r1"]
    
    assert v_res["outcome"] == "IMPROVED"
    assert v_res["before_divergent"] == 7
    assert v_res["after_divergent"] == 1
    assert v_res["sibling_divergent"] == 0
    assert v_res["conformance_hits"] == 9
    assert v_res["conformance_total"] == 10
    
    # Report
    md = build_report_md(conn, run_id)
    assert "IMPROVED" in md
    
    conn.close()
