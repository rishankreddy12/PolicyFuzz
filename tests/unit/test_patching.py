import pytest
import hashlib
from policyfuzz.patching import apply_edits, PatchApplyError, unified_diff, decision_table_md
from policyfuzz.models import ClauseEdit, DecisionRow

def test_apply_edits_replace_and_add():
    old = "1. Sec\n1.1 old text\n2. Sec 2\n2.1 sec 2 text\n"
    edits = [
        ClauseEdit(edit_id="E1", action="REPLACE", clause_id="1.1", new_text="new text here", addresses_clusters=["K1"], rationale="rationale"),
        ClauseEdit(edit_id="E2", action="ADD_AFTER", clause_id="1.2", anchor_clause_id="1.1", new_text="added text", addresses_clusters=["K1"], rationale="rationale")
    ]
    
    new = apply_edits(old, edits)
    assert "1.1 new text here" in new
    assert "1.2 added text" in new
    assert "2.1 sec 2 text" in new

def test_apply_edits_errors():
    old = "1. Sec\n1.1 old text\n"
    edits = [
        ClauseEdit(edit_id="E1", action="REPLACE", clause_id="9.9", new_text="new text here", addresses_clusters=["K1"], rationale="rationale")
    ]
    with pytest.raises(PatchApplyError, match="not found"):
        apply_edits(old, edits)
        
    edits2 = [
        ClauseEdit(edit_id="E1", action="ADD_AFTER", clause_id="1.1", anchor_clause_id="1.1", new_text="duplicate text here", addresses_clusters=["K1"], rationale="rationale")
    ]
    with pytest.raises(PatchApplyError, match="Duplicate clause ID"):
        apply_edits(old, edits2)

def test_diff_and_table():
    diff = unified_diff("A\nB\n", "A\nC\n")
    assert "-B" in diff and "+C" in diff
    
    table = decision_table_md([DecisionRow(condition="X", verdict="ALLOW", clause_refs=["1.1"])])
    assert "| X | ALLOW | 1.1 |" in table
    
def test_apply_does_not_mutate_original():
    old = "1. Sec\n1.1 old text\n"
    h1 = hashlib.sha256(old.encode("utf-8")).hexdigest()
    
    edits = [ClauseEdit(edit_id="E1", action="REPLACE", clause_id="1.1", new_text="this is new text", addresses_clusters=["K1"], rationale="rationale")]
    new = apply_edits(old, edits)
    
    h2 = hashlib.sha256(old.encode("utf-8")).hexdigest()
    assert h1 == h2
