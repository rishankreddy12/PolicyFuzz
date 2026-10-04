import pytest
from pydantic import ValidationError
from policyfuzz.models import InterpreterVerdict

def test_interpreter_verdict_validation():
    # Valid
    v = InterpreterVerdict(
        case_id="C01",
        verdict="ALLOW",
        cited_clauses=["1.1"],
        confidence=0.9,
        rationale="Clear case." * 2  # min 10 chars
    )
    assert v.verdict == "ALLOW"

    # Bad verdict string
    with pytest.raises(ValidationError):
        InterpreterVerdict(
            case_id="C01",
            verdict="MAYBE",  # invalid literal
            cited_clauses=["1.1"],
            confidence=0.9,
            rationale="Clear case." * 2
        )

    # Empty citations
    with pytest.raises(ValidationError):
        InterpreterVerdict(
            case_id="C01",
            verdict="ALLOW",
            cited_clauses=[],  # min_length=1
            confidence=0.9,
            rationale="Clear case." * 2
        )

    # Bad confidence
    with pytest.raises(ValidationError):
        InterpreterVerdict(
            case_id="C01",
            verdict="ALLOW",
            cited_clauses=["1.1"],
            confidence=1.2,  # ge=0.0, le=1.0
            rationale="Clear case." * 2
        )

    # Short rationale
    with pytest.raises(ValidationError):
        InterpreterVerdict(
            case_id="C01",
            verdict="ALLOW",
            cited_clauses=["1.1"],
            confidence=0.9,
            rationale="Short"  # min_length=10
        )
