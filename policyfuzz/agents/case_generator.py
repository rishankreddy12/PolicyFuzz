"""Case Generator agent."""

import sqlite3
import json
from typing import List

from policyfuzz import db, events
from policyfuzz.config import Settings
from policyfuzz.models import Case, CaseSet, Clause, ParserEnrichment, RunStatus
from policyfuzz.llm.base import LLMProvider
from policyfuzz.llm.structured import structured_call, StructuredOutputError

from policyfuzz import config

def validate_caseset(cases: List[Case], clauses: List[Clause], settings: Settings) -> List[str]:
    errors = []
    
    # 1. Count range
    if not (config.MIN_CASES <= len(cases) <= config.MAX_CASES):
        errors.append(f"Expected {config.MIN_CASES}-{config.MAX_CASES} cases, got {len(cases)}.")
        
    # 2. Unique titles
    titles = set()
    for i, c in enumerate(cases):
        if c.title in titles:
            errors.append(f"Case at index {i} has duplicate title '{c.title}'")
        titles.add(c.title)
        
    valid_ids = {c.clause_id for c in clauses}
    targeted_outside_sec1 = set()
    total_outside_sec1 = {c.clause_id for c in clauses if c.section_id != "1"}
    control_count = 0
    
    for i, c in enumerate(cases):
        # 3. Clause ID validity
        invalid_targets = [tid for tid in c.target_clauses if tid not in valid_ids]
        if invalid_targets:
            errors.append(f"Case '{c.title}' targets unknown clauses: {invalid_targets}")
            
        for tid in c.target_clauses:
            if tid in total_outside_sec1:
                targeted_outside_sec1.add(tid)
                
        # 4. Control count
        if c.boundary_type == "control":
            control_count += 1
            
        # 5. Narrative shouldn't mention verdicts or ambiguous
        narr = c.narrative.lower()
        if any(w in narr for w in ["allow", "deny", "escalate", "ambiguous"]):
            errors.append(f"Case '{c.title}' mentions a verdict or 'ambiguous' in narrative.")
            
    # Coverage
    if total_outside_sec1:
        if len(total_outside_sec1) <= len(cases):
            cov = len(targeted_outside_sec1) / len(total_outside_sec1)
            if cov < 0.8:
                errors.append(f"Coverage of non-Section 1 clauses is {cov*100:.1f}%, required 80%.")
        else:
            min_required = min(len(total_outside_sec1), 10)
            if len(targeted_outside_sec1) < min_required:
                errors.append(f"Covered {len(targeted_outside_sec1)} non-Section 1 clauses, required at least {min_required}.")
            
    # 15% control
    if cases:
        control_ratio = control_count / len(cases)
        if control_ratio < 0.15:
            errors.append(f"Control cases represent {control_ratio*100:.1f}%, required 15%.")
            
    return errors

def normalise_ids(cases: List[Case]) -> None:
    for i, c in enumerate(cases):
        c.case_id = f"C{i+1:02d}"

async def run_case_generator(
    conn: sqlite3.Connection,
    provider: LLMProvider,
    settings: Settings,
    run_id: str,
    clauses: List[Clause],
    enrichment: ParserEnrichment
) -> None:
    events.log_event(conn, run_id, "CaseGen", "INFO", "Started case generation")
    
    policy_str = "\n".join(f"{c.clause_id} {c.text}" for c in clauses)
    
    system = "You are a QA analyst generating synthetic support requests based on a policy."
    user = f"Policy:\n<policy>\n{policy_str}\n</policy>\n\nTarget count: {config.TARGET_CASES}"
    if enrichment.defined_terms:
        user += "\nDefined terms: " + ", ".join(t.term for t in enrichment.defined_terms)
        
    def validator(caseset: CaseSet) -> List[str]:
        return validate_caseset(caseset.cases, clauses, settings)
        
    try:
        caseset = await structured_call(
            provider=provider,
            conn=conn,
            run_id=run_id,
            role="casegen",
            call_key="casegen:main",
            system=system,
            user=user,
            schema=CaseSet,
            model=settings.model_strong,
            validator=validator,
            max_retries=1
        )
        
        normalise_ids(caseset.cases)
        db.save_cases(conn, run_id, caseset.cases, origin="generated")
        db.set_status(conn, run_id, RunStatus.CASES_READY)
        events.log_event(conn, run_id, "CaseGen", "INFO", "Finished case generation", {"count": len(caseset.cases)})
        
    except StructuredOutputError as e:
        error_msg = f"Case generation validation failed: {e.last_error}"
        db.set_error(conn, run_id, error_msg)
        events.log_event(conn, run_id, "CaseGen", "ERROR", error_msg)
        raise
