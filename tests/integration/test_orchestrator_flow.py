import pytest
import sqlite3
import os
from pathlib import Path

from policyfuzz import db
from policyfuzz.config import Settings
from policyfuzz.llm.scripted_provider import ScriptedProvider
from policyfuzz.orchestrator import Orchestrator, GateError
from policyfuzz.models import RunStatus, Ruling

@pytest.fixture
def test_conn():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    yield conn
    conn.close()

@pytest.fixture
def env_setup():
    base = Path(__file__).parent.parent.parent
    path = base / "fixtures" / "demo" / "scripted_responses.json"
    os.environ["POLICYFUZZ_SCRIPTED_PATH"] = str(path)
    yield
    if "POLICYFUZZ_SCRIPTED_PATH" in os.environ:
        del os.environ["POLICYFUZZ_SCRIPTED_PATH"]

@pytest.mark.asyncio
async def test_orchestrator_happy_path(test_conn, env_setup, tmp_path):
    settings = Settings(
        provider="scripted", db_path=":memory:", runs_dir=str(tmp_path), ollama_host="url",
        model_a="a", model_b="b", model_c="c", model_strong="strong"
    )
    provider = ScriptedProvider()
    orch = Orchestrator(test_conn, provider, settings)
    
    base = Path(__file__).parent.parent.parent
    with open(base / "fixtures" / "demo" / "policy_v1.txt", "r", encoding="utf-8") as f:
        policy = f.read()
    
    run_id = await orch.create_run(policy, "Test Run", "scripted")
    
    # Run until first gate
    status = await orch.run_until_gate(run_id)
    if status == RunStatus.FAILED:
        run_row = db.get_run(test_conn, run_id)
        pytest.fail(f"Run failed: {run_row['error']}")
        
    assert status == RunStatus.AWAITING_RULINGS
    
    # Submit rulings
    rulings = [
        Ruling(cluster_id="K1", ruling="ALLOW", note="n"),
        Ruling(cluster_id="K2", ruling="DENY", note="n"),
        Ruling(cluster_id="K3", ruling="ESCALATE", note="n")
    ]
    orch.submit_rulings(run_id, rulings)
    
    run = db.get_run(test_conn, run_id)
    assert run["status"] == RunStatus.RULED
    
    # Resume -> will successfully run patcher and stop at next gate
    status = await orch.run_until_gate(run_id)
    assert status == RunStatus.AWAITING_EDIT_DECISIONS
    

