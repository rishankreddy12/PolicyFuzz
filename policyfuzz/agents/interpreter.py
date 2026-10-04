"""Interpreter panel (evaluating cases under personas)."""

import asyncio
import sqlite3
from typing import List

from policyfuzz import db, events
from policyfuzz.config import Settings
from policyfuzz.models import Case, Clause, InterpreterVerdict, RunStatus
from policyfuzz.llm.base import LLMProvider
from policyfuzz.llm.structured import structured_call, StructuredOutputError

class PanelUnreliableError(Exception):
    pass

def build_interpreter_prompt(persona: str, clauses: List[Clause], case: Case) -> tuple[str, str]:
    system = f"You are an interpreter analyzing a support request under the persona: {persona}.\nYour job is to read the policy strictly or leniently depending on your persona, then render a verdict.\nVERDICTS:\nALLOW: ordinary support agent may grant the request under the policy.\nDENY: policy forbids it.\nESCALATE: policy does not settle it or requires higher authority."
    
    policy_str = "\n".join(f"{c.clause_id} {c.text}" for c in clauses)
    user = f"Policy:\n<policy>\n{policy_str}\n</policy>\n\nRequest:\n<case>\n{case.narrative}\n</case>\n\nRender your verdict and cite the exact clause IDs."
    
    return system, user

async def run_panel(
    conn: sqlite3.Connection,
    provider: LLMProvider,
    settings: Settings,
    run_id: str,
    policy_tag: str,
    clauses: List[Clause],
    cases: List[Case]
) -> None:
    events.log_event(conn, run_id, "Interpreter", "INFO", f"Starting panel on {len(cases)} cases (tag: {policy_tag})")
    
    PERSONAS = {
        "A": ("Literalist", settings.model_a),
        "B": ("Customer Advocate", settings.model_b),
        "C": ("Risk Controller", settings.model_c)
    }
    
    valid_ids = {c.clause_id for c in clauses}
    
    def get_validator(case_id: str):
        def validator(verdict: InterpreterVerdict) -> List[str]:
            errors = []
            if verdict.case_id != case_id:
                errors.append(f"Expected case_id '{case_id}', got '{verdict.case_id}'")
            invalid_citations = [c for c in verdict.cited_clauses if c not in valid_ids]
            if invalid_citations:
                errors.append(f"Unknown clauses cited: {invalid_citations}")
            return errors
        return validator

    from policyfuzz import config
    sem = asyncio.Semaphore(config.PANEL_CONCURRENCY)
    tasks = []
    
    completed = 0
    total = len(cases) * 3
    
    async def process_one(case: Case, interp_key: str, persona_name: str, model: str):
        nonlocal completed
        
        # Check if already done
        if db.has_valid_verdict(conn, run_id, policy_tag, case.case_id, interp_key):
            completed += 1
            return
            
        system, user = build_interpreter_prompt(persona_name, clauses, case)
        call_key = f"interp:{interp_key}:{case.case_id}:{policy_tag}"
        
        async with sem:
            try:
                verdict = await structured_call(
                    provider=provider,
                    conn=conn,
                    run_id=run_id,
                    role=f"interp_{interp_key}",
                    call_key=call_key,
                    system=system,
                    user=user,
                    schema=InterpreterVerdict,
                    model=model,
                    validator=get_validator(case.case_id)
                )
                db.upsert_verdict(conn, run_id, policy_tag, verdict, interp_key, valid=True)
            except Exception as e:
                # Store invalid
                dummy = InterpreterVerdict(case_id=case.case_id, verdict="ESCALATE", cited_clauses=["1.1"], confidence=0.0, rationale="Failed to generate")
                db.upsert_verdict(conn, run_id, policy_tag, dummy, interp_key, valid=False, error=str(e))
            finally:
                completed += 1
                if completed % 10 == 0:
                    events.log_event(conn, run_id, "Interpreter", "INFO", f"Progress: {completed}/{total}")

    for case in cases:
        for k, (name, model) in PERSONAS.items():
            tasks.append(process_one(case, k, name, model))
            
    await asyncio.gather(*tasks)
    
    # Check reliability
    all_verdicts = db.get_verdicts(conn, run_id, policy_tag)
    # Count how many cases have < 2 valid verdicts
    case_valid_counts = {c.case_id: 0 for c in cases}
    for v in all_verdicts:
        case_valid_counts[v.case_id] += 1
        
    insufficient = sum(1 for count in case_valid_counts.values() if count < 2)
    
    if len(cases) > 0 and insufficient / len(cases) > 0.2:
        error_msg = f"Panel unreliable: {insufficient}/{len(cases)} cases had insufficient valid verdicts."
        db.set_error(conn, run_id, error_msg)
        events.log_event(conn, run_id, "Interpreter", "ERROR", error_msg)
        raise PanelUnreliableError(error_msg)
        
    if policy_tag == "v1":
        db.set_status(conn, run_id, RunStatus.PANEL_V1_DONE)
    events.log_event(conn, run_id, "Interpreter", "INFO", "Finished panel")
