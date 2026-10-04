import pytest
from policyfuzz.agents.verifier import compute_verification
from policyfuzz.models import Case, InterpreterVerdict, Ruling, Cluster, VerificationResult

def test_compute_verification_improved():
    cases = [Case(case_id="C1", title="Title", narrative="N"*40, target_clauses=["1.1"], boundary_type="threshold")]
    siblings = [Case(case_id="S1", title="Title", narrative="N"*40, target_clauses=["1.1"], boundary_type="threshold", expected_verdict="ALLOW")]
    
    # v1: C1 divergent (ALLOW, DENY)
    v1_rows = [
        InterpreterVerdict(case_id="C1", verdict="ALLOW", cited_clauses=["1.1"], confidence=0.9, rationale="rationale here"),
        InterpreterVerdict(case_id="C1", verdict="DENY", cited_clauses=["1.1"], confidence=0.9, rationale="rationale here")
    ]
    
    # v2: C1 ALLOW, S1 ALLOW
    v2_rows = [
        InterpreterVerdict(case_id="C1", verdict="ALLOW", cited_clauses=["1.1"], confidence=0.9, rationale="rationale here"),
        InterpreterVerdict(case_id="C1", verdict="ALLOW", cited_clauses=["1.1"], confidence=0.9, rationale="rationale here"),
        InterpreterVerdict(case_id="S1", verdict="ALLOW", cited_clauses=["1.1"], confidence=0.9, rationale="rationale here"),
        InterpreterVerdict(case_id="S1", verdict="ALLOW", cited_clauses=["1.1"], confidence=0.9, rationale="rationale here")
    ]
    
    rulings = [Ruling(cluster_id="K1", ruling="ALLOW", note="")]
    clusters = [Cluster(cluster_id="K1", label="L", loophole_type="SCOPE_GAP", case_ids=["C1"], involved_clauses=["1.1"], summary="S", business_impact="LOW", impact_reason="R")]
    
    res = compute_verification(v1_rows, v2_rows, cases, siblings, rulings, clusters, 1)
    
    assert res.before_divergent == 1
    assert res.after_divergent == 0
    assert res.conformance_hits == 2 # C1 and S1 both unanimously ALLOW
    assert res.conformance_total == 2
    assert res.outcome == "IMPROVED"
    assert res.per_cluster["K1"] == {"before": 1, "after": 0}

def test_compute_verification_regressed_flip():
    cases = [
        Case(case_id="C1", title="Title", narrative="N"*40, target_clauses=["1.1"], boundary_type="threshold"),
        Case(case_id="C2", title="Title", narrative="N"*40, target_clauses=["1.1"], boundary_type="threshold")
    ]
    siblings = []
    
    # v1: C1 divergent, C2 unanimous DENY
    v1_rows = [
        InterpreterVerdict(case_id="C1", verdict="ALLOW", cited_clauses=["1.1"], confidence=0.9, rationale="rationale here"),
        InterpreterVerdict(case_id="C1", verdict="DENY", cited_clauses=["1.1"], confidence=0.9, rationale="rationale here"),
        InterpreterVerdict(case_id="C2", verdict="DENY", cited_clauses=["1.1"], confidence=0.9, rationale="rationale here"),
        InterpreterVerdict(case_id="C2", verdict="DENY", cited_clauses=["1.1"], confidence=0.9, rationale="rationale here")
    ]
    
    # v2: C1 ALLOW, C2 ALLOW (flipped!)
    v2_rows = [
        InterpreterVerdict(case_id="C1", verdict="ALLOW", cited_clauses=["1.1"], confidence=0.9, rationale="rationale here"),
        InterpreterVerdict(case_id="C1", verdict="ALLOW", cited_clauses=["1.1"], confidence=0.9, rationale="rationale here"),
        InterpreterVerdict(case_id="C2", verdict="ALLOW", cited_clauses=["1.1"], confidence=0.9, rationale="rationale here"),
        InterpreterVerdict(case_id="C2", verdict="ALLOW", cited_clauses=["1.1"], confidence=0.9, rationale="rationale here")
    ]
    
    rulings = [Ruling(cluster_id="K1", ruling="ALLOW", note="")]
    clusters = [Cluster(cluster_id="K1", label="L", loophole_type="SCOPE_GAP", case_ids=["C1"], involved_clauses=["1.1"], summary="S", business_impact="LOW", impact_reason="R")]
    
    res = compute_verification(v1_rows, v2_rows, cases, siblings, rulings, clusters, 1)
    
    assert res.before_divergent == 1
    assert res.after_divergent == 0
    assert "C2" in res.flipped_case_ids
    assert res.outcome == "REGRESSED"
