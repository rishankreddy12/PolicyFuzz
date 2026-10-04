"""Patcher agent."""

import sqlite3
import json
from typing import List, Dict

from policyfuzz import db, events
from policyfuzz.config import Settings
from policyfuzz.models import Clause, Ruling, Cluster, PatchProposal, RunStatus
from policyfuzz.llm.base import LLMProvider
from policyfuzz.llm.structured import structured_call

def validate_patch(
    proposal: PatchProposal, 
    clauses: List[Clause], 
    rulings: List[Ruling], 
    clusters: List[Cluster], 
    round_num: int
) -> List[str]:
    errors = []
    
    # 1. Max 6 edits
    if len(proposal.edits) > 6:
        errors.append(f"Too many edits ({len(proposal.edits)}), maximum is 6.")
        
    valid_ids = {c.clause_id for c in clauses}
    
    ruled_clusters = {r.cluster_id: r for r in rulings if r.ruling != "SKIPPED"}
    addressed_clusters = set()
    
    for edit in proposal.edits:
        # 2. Check targets
        if edit.action == "REPLACE" and edit.clause_id not in valid_ids:
            errors.append(f"Edit {edit.edit_id} attempts to REPLACE unknown clause {edit.clause_id}")
            
        # 3. Addressed clusters
        for cid in edit.addresses_clusters:
            if cid not in ruled_clusters:
                errors.append(f"Edit {edit.edit_id} addresses non-existent or skipped cluster {cid}")
            addressed_clusters.add(cid)
            
    # 4. All ruled clusters must be addressed
    missing = set(ruled_clusters.keys()) - addressed_clusters
    if missing:
        errors.append(f"Ruled clusters not addressed by any edit: {missing}")
        
    # 5. Sibling cases coverage
    # The proposal must include a sibling expected verdict for every sibling case
    sibling_ids = {s.case_id for s in proposal.sibling_cases}
    missing_expected = sibling_ids - set(proposal.sibling_expected.keys())
    if missing_expected:
        errors.append(f"Missing expected verdicts for sibling cases: {missing_expected}")
        
    # Extra unexpected verdicts
    extra_expected = set(proposal.sibling_expected.keys()) - sibling_ids
    if extra_expected:
        errors.append(f"Expected verdicts provided for unknown siblings: {extra_expected}")
        
    return errors

def build_patcher_prompt(clauses: List[Clause], clusters: List[Cluster], rulings: List[Ruling]) -> tuple[str, str]:
    sys = (
        "You are an expert legal auditor and policy editor patching an SOP to resolve documented loopholes.\n"
        "Rules:\n"
        "1. Rewrite ONLY the specific conflicted clause; do not modify unrelated text.\n"
        "2. For each ClauseEdit, you MUST provide TWO distinct alternative rewrites:\n"
        "   - 'new_text' (Option 1): Strict / Direct clarification strictly enforcing policy rules.\n"
        "   - 'alt_text' (Option 2): Balanced / Conditional clarification offering reasonable exceptions or grace periods according to user guidance.\n"
        "3. Incorporate the human auditor's specific instructions and notes into both rewrites."
    )
    
    policy_str = "\n".join(f"{c.clause_id} {c.text}" for c in clauses)
    usr = f"Policy:\n<policy>\n{policy_str}\n</policy>\n\nLoopholes to fix based on human rulings and instructions:\n"
    
    for r in rulings:
        if r.ruling == "SKIPPED":
            continue
        # Find cluster
        cluster = next(c for c in clusters if c.cluster_id == r.cluster_id)
        usr += f"- Cluster {cluster.cluster_id}: {cluster.summary} (Involved: {cluster.involved_clauses})\n"
        usr += f"  Human Ruling: {r.ruling}\n"
        usr += f"  Auditor Instructions/Guidance: {r.note if r.note else 'Resolve ambiguity cleanly'}\n"
        
    usr += "\nProduce a PatchProposal with dual rewrites ('new_text' as Option 1 and 'alt_text' as Option 2) for each targeted clause."
    return sys, usr

async def run_patcher(
    conn: sqlite3.Connection,
    provider: LLMProvider,
    settings: Settings,
    run_id: str,
    round_num: int
) -> None:
    events.log_event(conn, run_id, "Patcher", "INFO", f"Starting patcher for round {round_num}")
    
    clauses = db.get_clauses(conn, run_id)
    clusters = db.get_clusters(conn, run_id)
    rulings = db.get_rulings(conn, run_id)
    
    sys, usr = build_patcher_prompt(clauses, clusters, rulings)
    
    def validator(prop: PatchProposal) -> List[str]:
        return validate_patch(prop, clauses, rulings, clusters, round_num)
        
    patch = await structured_call(
        provider, conn, run_id, "patcher", f"patcher:r{round_num}",
        sys, usr, PatchProposal, settings.model_strong,
        validator=validator, max_retries=1
    )
    
    # Save the patch
    db.save_patch(conn, run_id, round_num, patch, "PENDING")
    
    # Normalise sibling IDs to S01, S02...
    old_to_new = {}
    for i, s in enumerate(patch.sibling_cases):
        new_id = f"S{i+1:02d}"
        old_to_new[s.case_id] = new_id
        s.case_id = new_id
        
    new_expected = {}
    for old_id, v in patch.sibling_expected.items():
        if old_id in old_to_new:
            new_expected[old_to_new[old_id]] = v
            
    patch.sibling_expected = new_expected
    
    # Save sibling cases directly as 'sibling'
    for s in patch.sibling_cases:
        expected = patch.sibling_expected.get(s.case_id)
        # Store in db using expected_verdict column (which is implemented in db logic)
        db.save_cases(conn, run_id, [s], origin="sibling", sibling_round=round_num, expected_verdicts={s.case_id: expected})
        
    db.set_status(conn, run_id, RunStatus.AWAITING_EDIT_DECISIONS)
    events.log_event(conn, run_id, "Patcher", "INFO", f"Proposed patch with {len(patch.edits)} edits")
