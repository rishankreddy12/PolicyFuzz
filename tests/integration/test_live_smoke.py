import pytest
import os
from pathlib import Path

from policyfuzz import db
from policyfuzz.config import Settings, make_provider
from policyfuzz.orchestrator import Orchestrator
from policyfuzz.models import RunStatus

pytestmark = pytest.mark.skipif(
    os.getenv("POLICYFUZZ_LIVE") != "1",
    reason="Live tests require POLICYFUZZ_LIVE=1"
)

@pytest.mark.live
@pytest.mark.asyncio
async def test_live_smoke(tmp_path):
    conn = db.connect(":memory:")
    db.init_schema(conn)
    
    settings = Settings(
        provider="ollama", db_path=":memory:", runs_dir=str(tmp_path), 
        ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        model_a=os.getenv("POLICYFUZZ_MODEL_A", "llama3.1:8b"),
        model_b=os.getenv("POLICYFUZZ_MODEL_B", "qwen2.5:7b"),
        model_c=os.getenv("POLICYFUZZ_MODEL_C", "mistral:7b"),
        model_strong=os.getenv("POLICYFUZZ_MODEL_STRONG", "llama3.1:8b")
    )
    provider = make_provider(settings)
    orch = Orchestrator(conn, provider, settings)
    
    base = Path(__file__).parent.parent.parent
    with open(base / "fixtures" / "demo" / "policy_v1.txt", "r", encoding="utf-8") as f:
        policy = f.read()
        
    run_id = await orch.create_run(policy, "Live Smoke", "ollama")
    status = await orch.run_until_gate(run_id)
    
    assert status in (RunStatus.AWAITING_RULINGS, RunStatus.COMPLETE_NO_DIVERGENCE, RunStatus.FAILED)
    
    if status == RunStatus.FAILED:
        run = db.get_run(conn, run_id)
        pytest.fail(f"Run failed: {run['error']}")
        
    # Structural invariants
    # 90 verdicts
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM verdicts WHERE run_id=? AND policy_tag='v1'", (run_id,))
    total = c.fetchone()[0]
    
    assert total == 90
    
    c.execute("SELECT COUNT(*) FROM verdicts WHERE run_id=? AND policy_tag='v1' AND valid=1", (run_id,))
    valid = c.fetchone()[0]
    
    assert valid / 90 >= 0.8
