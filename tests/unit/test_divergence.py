import pytest
from policyfuzz.agents.divergence import compute_divergence, validate_clusters, repair_clusters, fallback_clusters
from policyfuzz.models import InterpreterVerdict, Cluster, Case

def test_compute_divergence():
    # C1: unanimous ALLOW
    v1a = InterpreterVerdict(case_id="C1", verdict="ALLOW", cited_clauses=["1.1"], confidence=0.9, rationale="R"*10)
    v1b = InterpreterVerdict(case_id="C1", verdict="ALLOW", cited_clauses=["1.1"], confidence=0.9, rationale="R"*10)
    v1c = InterpreterVerdict(case_id="C1", verdict="ALLOW", cited_clauses=["1.1"], confidence=0.9, rationale="R"*10)
    
    # C2: divergent (ALLOW, DENY, ESCALATE)
    v2a = InterpreterVerdict(case_id="C2", verdict="ALLOW", cited_clauses=["1.1"], confidence=0.9, rationale="R"*10)
    v2b = InterpreterVerdict(case_id="C2", verdict="DENY", cited_clauses=["1.1"], confidence=0.9, rationale="R"*10)
    v2c = InterpreterVerdict(case_id="C2", verdict="ESCALATE", cited_clauses=["1.1"], confidence=0.9, rationale="R"*10)
    
    # C3: 2 valid (ALLOW, DENY) -> divergent
    v3a = InterpreterVerdict(case_id="C3", verdict="ALLOW", cited_clauses=["1.1"], confidence=0.9, rationale="R"*10)
    v3b = InterpreterVerdict(case_id="C3", verdict="DENY", cited_clauses=["1.1"], confidence=0.9, rationale="R"*10)
    
    # C4: 1 valid -> insufficient
    v4a = InterpreterVerdict(case_id="C4", verdict="ALLOW", cited_clauses=["1.1"], confidence=0.9, rationale="R"*10)
    
    report = compute_divergence([v1a, v1b, v1c, v2a, v2b, v2c, v3a, v3b, v4a], ["C1", "C2", "C3", "C4"])
    
    assert set(report.unanimous_case_ids) == {"C1"}
    assert set(report.divergent_case_ids) == {"C2", "C3"}
    assert set(report.insufficient_case_ids) == {"C4"}
    assert report.divergence_rate == 2 / 3

def test_validate_clusters():
    c1 = Cluster(cluster_id="K1", label="L", loophole_type="SCOPE_GAP", case_ids=["C1"], involved_clauses=["1.1"], summary="S", business_impact="LOW", impact_reason="R")
    
    errors = validate_clusters([c1], ["C1"], {"1.1"})
    assert not errors
    
    # Missing divergent case
    errors = validate_clusters([c1], ["C1", "C2"], {"1.1"})
    assert any("missing" in e for e in errors)
    
    # Unknown clause
    c1.involved_clauses = ["9.9"]
    errors = validate_clusters([c1], ["C1"], {"1.1"})
    assert any("unknown clause" in e for e in errors)

def test_repair_clusters():
    c1 = Cluster(cluster_id="K1", label="L", loophole_type="SCOPE_GAP", case_ids=["C1", "C2"], involved_clauses=["1.1"], summary="S", business_impact="LOW", impact_reason="R")
    
    repaired = repair_clusters([c1], ["C1", "C3"])
    
    # C2 should be stripped, C3 should be in K_misc
    assert repaired[0].case_ids == ["C1"]
    assert repaired[1].cluster_id == "K_misc"
    assert repaired[1].case_ids == ["C3"]

def test_fallback_clusters():
    cases = [
        Case(case_id="C1", title="Title", narrative="N"*40, target_clauses=["1.1", "2.1"], boundary_type="threshold"),
        Case(case_id="C2", title="Title", narrative="N"*40, target_clauses=["2.1", "1.1"], boundary_type="threshold"),
        Case(case_id="C3", title="Title", narrative="N"*40, target_clauses=["3.1"], boundary_type="threshold"),
    ]
    fb = fallback_clusters(cases)
    assert len(fb) == 2
    assert "C1" in fb[0].case_ids and "C2" in fb[0].case_ids
    assert "C3" in fb[1].case_ids
