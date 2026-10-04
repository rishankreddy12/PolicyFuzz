import pytest
import os
import json
import sqlite3
from pathlib import Path
from streamlit.testing.v1 import AppTest

from policyfuzz import db
from policyfuzz.config import Settings
from policyfuzz.llm.scripted_provider import ScriptedProvider
from policyfuzz.orchestrator import Orchestrator
from policyfuzz.models import RunStatus, Ruling, PatchProposal

@pytest.mark.asyncio
async def test_shopright_complete_lifecycle(tmp_path):
    shopright_path = r"C:\Users\rishankreddy\Downloads\shopright_returns_terms_conditions.txt"
    assert os.path.exists(shopright_path), f"File {shopright_path} does not exist"
    
    with open(shopright_path, "r", encoding="utf-8") as f:
        policy_text = f.read()
        
    assert len(policy_text) > 1000
    
    # 1. Test Ingestion & Deterministic Parsing
    from policyfuzz.agents.clause_parser import parse_policy
    clauses = parse_policy(policy_text)
    assert len(clauses) == 60, f"Expected 60 clauses from ShopRight, got {len(clauses)}"
    
    # Verify clause IDs and text
    first_clause = clauses[0]
    assert first_clause.clause_id == "1.1"
    assert "30 days" in first_clause.text
    
    # 2. Test Full Orchestration with ShopRight Policy
    db_file = str(tmp_path / "shopright_test.db")
    conn = db.connect(db_file)
    db.init_schema(conn)
    
    settings = Settings(
        provider="scripted",
        db_path=db_file,
        runs_dir=str(tmp_path / "runs"),
        ollama_host="",
        model_a="a", model_b="b", model_c="c", model_strong="strong"
    )
    provider = ScriptedProvider()
    orch = Orchestrator(conn, provider, settings)
    
    # Create Run
    run_id = await orch.create_run(policy_text, "ShopRight Returns Terms Conditions", "scripted")
    assert run_id is not None
    
    # Run to Gate 1 (Parses, Generates Cases, Evaluates 3 Personas, Detects Divergence, Clusters Loopholes)
    s1 = await orch.run_until_gate(run_id)
    assert s1 == RunStatus.AWAITING_RULINGS
    
    # Verify cases in DB
    db_cases = db.get_cases(conn, run_id)
    assert len(db_cases) == 30, f"Expected 30 cases, got {len(db_cases)}"
    
    # Verify verdicts in DB (30 cases x 3 personas = 90 verdicts)
    v1_verdicts = db.get_verdicts(conn, run_id, "v1")
    assert len(v1_verdicts) == 90, f"Expected 90 verdicts, got {len(v1_verdicts)}"
    
    # Verify divergence detection
    c = conn.cursor()
    c.execute("SELECT case_id, COUNT(DISTINCT verdict) as div_count FROM verdicts WHERE run_id=? AND policy_tag='v1' GROUP BY case_id HAVING div_count > 1", (run_id,))
    div_rows = c.fetchall()
    assert len(div_rows) == 7, f"Expected 7 divergent cases, got {len(div_rows)}"
    div_ids = sorted([r[0] for r in div_rows])
    assert div_ids == ["C24", "C25", "C26", "C27", "C28", "C29", "C30"]
    
    # Verify clusters in DB (3 clusters: K1, K2, K3)
    clusters = db.get_clusters(conn, run_id)
    assert len(clusters) == 3, f"Expected 3 clusters, got {len(clusters)}"
    
    # 3. Gate 1: Submit Authoritative Rulings
    # Align rulings with the cases:
    # Cluster with C27 -> DENY
    # Cluster with C24 -> ALLOW
    # Remaining cluster -> ESCALATE
    rulings = []
    for cl in clusters:
        if "C27" in cl.case_ids:
            rulings.append(Ruling(cluster_id=cl.cluster_id, ruling="DENY", note="Items marked final sale cannot be returned"))
        elif "C24" in cl.case_ids:
            rulings.append(Ruling(cluster_id=cl.cluster_id, ruling="ALLOW", note="Returns within 30 days are accepted"))
        else:
            rulings.append(Ruling(cluster_id=cl.cluster_id, ruling="ESCALATE", note="Escalate hygiene or damaged items"))
            
    orch.submit_rulings(run_id, rulings)
    
    # Verify rulings in DB
    db_rulings = db.get_rulings(conn, run_id)
    assert len(db_rulings) == 3
    
    # Run to Gate 2 (Patcher generates proposal, sibling cases, decision table)
    s2 = await orch.run_until_gate(run_id)
    assert s2 == RunStatus.AWAITING_EDIT_DECISIONS
    
    patch_row = db.get_patch(conn, run_id, 1)
    assert patch_row is not None
    proposal = PatchProposal.model_validate_json(patch_row["proposal_json"])
    assert len(proposal.edits) > 0
    assert len(proposal.decision_table) > 0
    assert len(proposal.sibling_cases) == 3
    
    # 4. Gate 2: Approve Edits
    approvals = {e.edit_id: True for e in proposal.edits}
    orch.decide_edits(run_id, 1, approvals)
    
    # 5. Verification & Regression Analysis
    await orch.apply_and_verify(run_id)
    
    # Verify Final Status and Computed Metrics
    run = db.get_run(conn, run_id)
    assert run["status"] == RunStatus.COMPLETE_IMPROVED, f"Expected COMPLETE_IMPROVED, got {run['status']}"
    
    metrics = json.loads(run["metrics_json"])
    assert "v1" in metrics
    assert "v2r1" in metrics
    
    v1_m = metrics["v1"]
    assert v1_m["divergent"] == 7
    assert v1_m["total"] == 30
    assert abs(v1_m["rate"] - 7/30) < 1e-4
    
    v2_m = metrics["v2r1"]
    assert v2_m["outcome"] == "IMPROVED"
    assert v2_m["before_divergent"] == 7
    assert v2_m["after_divergent"] == 1 # Only C26 residual divergence
    assert v2_m["sibling_divergent"] == 0 # Sibling cases unanimous
    assert v2_m["conformance_hits"] == 9 # 9/10 conformance
    assert v2_m["conformance_total"] == 10
    assert len(v2_m["new_divergent_case_ids"]) == 0 # Zero regressions!
    
    # 6. Verify Artifacts Written
    run_dir = Path(settings.runs_dir) / run_id
    assert (run_dir / "policy_v1.txt").exists()
    assert (run_dir / "policy_v2_r1.txt").exists()
    assert (run_dir / "decision_table.md").exists()
    assert (run_dir / "regression_cases.json").exists()
    assert (run_dir / "report.md").exists()
    
    # 7. Verify UI AppTest Rendering with this Run
    os.environ["POLICYFUZZ_DB_PATH"] = db_file
    os.environ["POLICYFUZZ_PROVIDER"] = "scripted"
    
    app_path = Path(__file__).parent.parent.parent / "policyfuzz" / "ui" / "app.py"
    at = AppTest.from_file(str(app_path))
    at.session_state["run_id"] = run_id
    at.session_state["show_onboarding"] = False
    at.run(timeout=15)
    
    assert not at.exception
    
    conn.close()
