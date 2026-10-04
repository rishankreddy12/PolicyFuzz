import pytest
from policyfuzz.agents.case_generator import validate_caseset, normalise_ids
from policyfuzz.models import Case, Clause
from policyfuzz.config import Settings

@pytest.fixture
def settings():
    return Settings(
        provider="scripted", db_path=":memory:", runs_dir="runs", ollama_host="url",
        model_a="a", model_b="b", model_c="c", model_strong="strong"
    )

def test_validate_caseset_valid(settings):
    clauses = [
        Clause(clause_id="1.1", section_id="1", section_title="A", text="a"),
        Clause(clause_id="2.1", section_id="2", section_title="B", text="b"),
    ]
    cases = []
    # Needs min 24 cases, >=15% control (4 control cases), >=80% coverage outside sec 1 (just 2.1)
    for i in range(24):
        cases.append(Case(
            case_id=f"c{i}", title=f"T{i} title", narrative="a"*40,
            target_clauses=["2.1"], boundary_type="control" if i < 4 else "threshold"
        ))
        
    errors = validate_caseset(cases, clauses, settings)
    assert not errors
    
def test_validate_caseset_errors(settings):
    clauses = [
        Clause(clause_id="1.1", section_id="1", section_title="A", text="a"),
        Clause(clause_id="2.1", section_id="2", section_title="B", text="b"),
    ]
    # Too few cases, bad targets, duplicates, low control, bad words in narrative
    cases = [
        Case(case_id="c1", title="Duplicate", narrative="allow this"*10, target_clauses=["9.9"], boundary_type="threshold"),
        Case(case_id="c2", title="Duplicate", narrative="a"*40, target_clauses=["2.1"], boundary_type="threshold"),
    ]
    
    errors = validate_caseset(cases, clauses, settings)
    assert any("24-36" in e for e in errors)
    assert any("duplicate title" in e for e in errors)
    assert any("unknown clauses" in e for e in errors)
    assert any("control" in e.lower() for e in errors)
    assert any("mentions a verdict" in e for e in errors)

def test_normalise_ids():
    cases = [
        Case(case_id="x", title="A title", narrative="a"*40, target_clauses=["1.1"], boundary_type="threshold"),
        Case(case_id="y", title="B title", narrative="a"*40, target_clauses=["1.1"], boundary_type="threshold"),
    ]
    normalise_ids(cases)
    assert cases[0].case_id == "C01"
    assert cases[1].case_id == "C02"
