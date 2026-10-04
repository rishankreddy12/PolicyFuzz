"""Clause Parser agent (deterministic parsing + LLM enrichment)."""

import re
import sqlite3
from typing import List, Tuple

from policyfuzz import db, events
from policyfuzz.config import Settings
from policyfuzz.models import Clause, ParserEnrichment, RunStatus
from policyfuzz.llm.base import LLMProvider
from policyfuzz.llm.structured import structured_call

class PolicyTooLargeError(Exception):
    pass

class PolicyFormatError(Exception):
    pass

def parse_policy(text: str, max_bytes: int = 20480) -> List[Clause]:
    """Parse policy text into numbered atomic clauses deterministically."""
    if len(text.encode("utf-8")) > max_bytes:
        raise PolicyTooLargeError(f"Policy exceeds maximum size of {max_bytes} bytes.")
        
    # Normalise newlines and strip control chars (keep printable and whitespace)
    text = "".join(c for c in text if c.isprintable() or c in ("\n", "\r", "\t"))
    lines = text.replace("\r\n", "\n").split("\n")
    
    section_re = re.compile(r"^\s*(\d+)\.\s+(\S.*)$")
    clause_re = re.compile(r"^\s*(\d+(?:\.\d+)+)\s+(\S.*)$")
    
    clauses: List[Clause] = []
    current_section_id = ""
    current_section_title = ""
    current_clause_id = ""
    current_clause_text = []
    
    seen_ids = set()
    
    def finish_clause():
        if current_clause_id:
            if current_clause_id in seen_ids:
                raise PolicyFormatError(f"Duplicate clause ID found: {current_clause_id}")
            seen_ids.add(current_clause_id)
            full_text = " ".join(current_clause_text)
            clauses.append(Clause(
                clause_id=current_clause_id,
                section_id=current_section_id,
                section_title=current_section_title,
                text=full_text
            ))
            current_clause_text.clear()

    for line in lines:
        if not line.strip():
            continue
            
        sec_match = section_re.match(line)
        if sec_match:
            finish_clause()
            current_section_id = sec_match.group(1)
            current_section_title = sec_match.group(2).strip()
            current_clause_id = ""
            continue
            
        cl_match = clause_re.match(line)
        if cl_match:
            if not current_section_id:
                # Ignore lines before first section heading
                continue
            finish_clause()
            current_clause_id = cl_match.group(1)
            current_clause_text = [cl_match.group(2).strip()]
            continue
            
        # Continuation
        if current_clause_id:
            current_clause_text.append(line.strip())
            
    finish_clause()
    
    if not clauses:
        raise PolicyFormatError("No numbered clauses found; expected format in README")
        
    return clauses

async def enrich(
    provider: LLMProvider,
    conn: sqlite3.Connection,
    run_id: str,
    clauses: List[Clause],
    model: str
) -> ParserEnrichment:
    """Enrich the policy with defined terms and ambiguity hints via LLM."""
    policy_str = "\n".join(f"{c.clause_id} {c.text}" for c in clauses)
    valid_ids = {c.clause_id for c in clauses}
    
    system = "You are a legal parsing assistant. Extract defined terms and ambiguity hints from the provided policy. Return a JSON object matching the ParserEnrichment schema."
    user = f"Policy:\n<policy>\n{policy_str}\n</policy>"
    
    def validator(enrichment: ParserEnrichment) -> List[str]:
        errors = []
        for t in enrichment.defined_terms:
            if t.clause_id not in valid_ids:
                errors.append(f"Defined term '{t.term}' cites unknown clause '{t.clause_id}'")
        for h in enrichment.ambiguity_hints:
            if h.clause_id not in valid_ids:
                errors.append(f"Ambiguity hint cites unknown clause '{h.clause_id}'")
        return errors

    try:
        res = await structured_call(
            provider=provider,
            conn=conn,
            run_id=run_id,
            role="parser",
            call_key="parser:enrich",
            system=system,
            user=user,
            schema=ParserEnrichment,
            model=model,
            validator=validator
        )
        
        # Filter valid ones just in case the validator was bypassed or we want to be safe
        res.defined_terms = [t for t in res.defined_terms if t.clause_id in valid_ids]
        res.ambiguity_hints = [h for h in res.ambiguity_hints if h.clause_id in valid_ids]
        return res
    except Exception as e:
        events.log_event(conn, run_id, "Parser", "WARN", f"Enrichment failed: {e}")
        return ParserEnrichment()

async def run_parser(
    conn: sqlite3.Connection,
    provider: LLMProvider,
    settings: Settings,
    run_id: str,
    policy_text: str
) -> None:
    events.log_event(conn, run_id, "Parser", "INFO", "Started parsing")
    
    try:
        from policyfuzz import config
        clauses = parse_policy(policy_text, config.MAX_POLICY_BYTES)
        db.save_clauses(conn, run_id, clauses)
        
        enrichment_data = await enrich(provider, conn, run_id, clauses, settings.model_strong)
        db.save_enrichment(conn, run_id, enrichment_data)
        
        db.set_status(conn, run_id, RunStatus.PARSED)
        events.log_event(conn, run_id, "Parser", "INFO", "Finished parsing", {"clauses": len(clauses)})
        
    except PolicyFormatError as e:
        db.set_error(conn, run_id, str(e))
        events.log_event(conn, run_id, "Parser", "ERROR", str(e))
        raise
    except PolicyTooLargeError as e:
        db.set_error(conn, run_id, str(e))
        events.log_event(conn, run_id, "Parser", "ERROR", str(e))
        raise
