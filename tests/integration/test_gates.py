import pytest
import sqlite3
from policyfuzz import db
from policyfuzz.orchestrator import Orchestrator, GateError
from policyfuzz.config import Settings
from policyfuzz.models import RunStatus, Ruling, Cluster

@pytest.fixture
def test_conn():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    yield conn
    conn.close()

def test_submit_rulings_gate_errors(test_conn):
    settings = Settings("mock", ":memory:", "runs", "url", "a", "b", "c", "s")
    orch = Orchestrator(test_conn, None, settings)
    
    db.create_run(test_conn, "r1", "T", RunStatus.ANALYZED, "mock", "path")
    # Not awaiting rulings
    with pytest.raises(GateError):
        orch.submit_rulings("r1", [])
        
    db.set_status(test_conn, "r1", RunStatus.AWAITING_RULINGS)
    
    # Save some clusters
    c1 = Cluster(cluster_id="K1", label="L", loophole_type="SCOPE_GAP", case_ids=["C1"], involved_clauses=["1.1"], summary="S", business_impact="LOW", impact_reason="R")
    c2 = Cluster(cluster_id="K2", label="L", loophole_type="SCOPE_GAP", case_ids=["C2"], involved_clauses=["1.1"], summary="S", business_impact="LOW", impact_reason="R")
    db.save_clusters(test_conn, "r1", [c1, c2])
    
    # Missing K2
    with pytest.raises(GateError):
        orch.submit_rulings("r1", [Ruling(cluster_id="K1", ruling="ALLOW", note="")])
        
    # Extra K3
    with pytest.raises(GateError):
        orch.submit_rulings("r1", [
            Ruling(cluster_id="K1", ruling="ALLOW", note=""),
            Ruling(cluster_id="K2", ruling="ALLOW", note=""),
            Ruling(cluster_id="K3", ruling="ALLOW", note="")
        ])
        
    # Duplicates
    with pytest.raises(GateError):
        orch.submit_rulings("r1", [
            Ruling(cluster_id="K1", ruling="ALLOW", note=""),
            Ruling(cluster_id="K1", ruling="DENY", note="")
        ])
        
    # Valid submission
    orch.submit_rulings("r1", [
        Ruling(cluster_id="K1", ruling="ALLOW", note=""),
        Ruling(cluster_id="K2", ruling="DENY", note="")
    ])
    assert db.get_run(test_conn, "r1")["status"] == RunStatus.RULED

def test_all_skipped(test_conn):
    settings = Settings("mock", ":memory:", "runs", "url", "a", "b", "c", "s")
    orch = Orchestrator(test_conn, None, settings)
    db.create_run(test_conn, "r2", "T", RunStatus.AWAITING_RULINGS, "mock", "path")
    c1 = Cluster(cluster_id="K1", label="L", loophole_type="SCOPE_GAP", case_ids=["C1"], involved_clauses=["1.1"], summary="S", business_impact="LOW", impact_reason="R")
    db.save_clusters(test_conn, "r2", [c1])
    
    orch.submit_rulings("r2", [Ruling(cluster_id="K1", ruling="SKIPPED", note="")])
    assert db.get_run(test_conn, "r2")["status"] == RunStatus.COMPLETE_NO_RULINGS
