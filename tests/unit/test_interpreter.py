import pytest
import sqlite3
from policyfuzz.agents.interpreter import build_interpreter_prompt, run_panel, PanelUnreliableError
from policyfuzz.models import Case, Clause, InterpreterVerdict
from policyfuzz.config import Settings
from policyfuzz import db

class MockProvider:
    name = "mock"
    async def complete_json(self, **kwargs):
        # We just need to check resume behavior, so we'll just return valid json
        ck = kwargs['call_key']
        cid = ck.split(":")[2]
        return f'{{"case_id": "{cid}", "verdict": "ALLOW", "cited_clauses": ["1.1"], "confidence": 0.9, "rationale": "Valid logic."}}'
        
@pytest.fixture
def conn():
    c = db.connect(":memory:")
    db.init_schema(c)
    yield c
    c.close()

def test_build_prompt():
    case = Case(case_id="C01", title="Title", narrative="Narrative content that is sufficiently long here", target_clauses=["1.1"], boundary_type="threshold")
    clauses = [Clause(clause_id="1.1", section_id="1", section_title="T", text="Text")]
    sys, usr = build_interpreter_prompt("Literalist", clauses, case)
    assert "Literalist" in sys
    assert "Narrative content" in usr
    assert "1.1 Text" in usr
    # Ensure no other case info
    assert "C02" not in usr

@pytest.mark.asyncio
async def test_panel_resume_and_unreliable(conn):
    settings = Settings("mock", ":memory:", "runs", "url", "a", "b", "c", "s")
    clauses = [Clause(clause_id="1.1", section_id="1", section_title="T", text="Text")]
    cases = [
        Case(case_id="C01", title="Title", narrative="N"*40, target_clauses=["1.1"], boundary_type="threshold"),
        Case(case_id="C02", title="Title", narrative="N"*40, target_clauses=["1.1"], boundary_type="threshold"),
    ]
    
    # Pre-seed a valid verdict for C01 / A
    v = InterpreterVerdict(case_id="C01", verdict="DENY", cited_clauses=["1.1"], confidence=0.8, rationale="x"*10)
    db.upsert_verdict(conn, "run1", "v1", v, "A", valid=True)
    
    provider = MockProvider()
    await run_panel(conn, provider, settings, "run1", "v1", clauses, cases)
    
    # Provider should only be called for the missing ones (C01 B/C, C02 A/B/C) => 5 calls total
    calls = db.list_llm_calls(conn, "run1")
    assert len(calls) == 5

@pytest.mark.asyncio
async def test_panel_unreliable_error(conn):
    settings = Settings("mock", ":memory:", "runs", "url", "a", "b", "c", "s")
    clauses = [Clause(clause_id="1.1", section_id="1", section_title="T", text="Text")]
    cases = [Case(case_id=f"C{i:02d}", title="Title", narrative="N"*40, target_clauses=["1.1"], boundary_type="threshold") for i in range(5)]
    
    # Make a provider that returns bad JSON for some cases so they are marked invalid
    class BadProvider:
        name = "bad"
        async def complete_json(self, **kwargs):
            return "bad json"
            
    with pytest.raises(PanelUnreliableError):
        await run_panel(conn, BadProvider(), settings, "run1", "v1", clauses, cases)
