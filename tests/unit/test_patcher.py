import pytest
from policyfuzz.agents.patcher import validate_patch
from policyfuzz.models import PatchProposal, ClauseEdit, Clause, Ruling, Cluster, Case

def test_validate_patch_happy():
    clauses = [Clause(clause_id="1.1", section_id="1", section_title="T", text="text")]
    rulings = [Ruling(cluster_id="K1", ruling="ALLOW", note="")]
    clusters = [Cluster(cluster_id="K1", label="L", loophole_type="SCOPE_GAP", case_ids=["C1"], involved_clauses=["1.1"], summary="S", business_impact="LOW", impact_reason="R")]
    
    prop = PatchProposal(
        edits=[ClauseEdit(edit_id="E1", action="REPLACE", clause_id="1.1", new_text="this is new text", addresses_clusters=["K1"], rationale="")],
        decision_table=[],
        sibling_cases=[Case(case_id="S1", title="Title", narrative="N"*40, target_clauses=["1.1"], boundary_type="threshold")],
        sibling_expected={"S1": "ALLOW"}
    )
    
    errors = validate_patch(prop, clauses, rulings, clusters, 1)
    assert not errors

def test_validate_patch_errors():
    clauses = [Clause(clause_id="1.1", section_id="1", section_title="T", text="text")]
    rulings = [Ruling(cluster_id="K1", ruling="ALLOW", note="")]
    clusters = [Cluster(cluster_id="K1", label="L", loophole_type="SCOPE_GAP", case_ids=["C1"], involved_clauses=["1.1"], summary="S", business_impact="LOW", impact_reason="R")]
    
    prop = PatchProposal(
        edits=[
            ClauseEdit(edit_id="E1", action="REPLACE", clause_id="9.9", new_text="this is new text", addresses_clusters=["K2"], rationale="")
        ],
        decision_table=[],
        sibling_cases=[Case(case_id="S1", title="Title", narrative="N"*40, target_clauses=["1.1"], boundary_type="threshold")],
        sibling_expected={"S2": "ALLOW"} # mismatch
    )
    
    errors = validate_patch(prop, clauses, rulings, clusters, 1)
    assert any("unknown clause 9.9" in e for e in errors)
    assert any("non-existent or skipped cluster K2" in e for e in errors)
    assert any("Ruled clusters not addressed" in e for e in errors)
    assert any("Missing expected verdicts" in e for e in errors)
    assert any("unknown siblings" in e for e in errors)
