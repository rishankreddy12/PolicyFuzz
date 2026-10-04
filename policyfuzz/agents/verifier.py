"""Verifier agent."""

import sqlite3
from typing import List, Dict

from policyfuzz import db, events
from policyfuzz.config import Settings
from policyfuzz.models import Case, Clause, InterpreterVerdict, Ruling, Cluster, VerificationResult, RunStatus
from policyfuzz.agents.clause_parser import parse_policy
from policyfuzz.agents.interpreter import run_panel
from policyfuzz.agents.divergence import compute_divergence
from policyfuzz.patching import apply_edits
from policyfuzz.llm.base import LLMProvider

def compute_verification(
    v1_rows: List[InterpreterVerdict],
    v2_rows: List[InterpreterVerdict],
    cases: List[Case],
    siblings: List[Case],
    rulings: List[Ruling],
    clusters: List[Cluster],
    round_num: int
) -> VerificationResult:
    
    cases_ids = [c.case_id for c in cases]
    siblings_ids = [s.case_id for s in siblings]
    
    rep_v1 = compute_divergence(v1_rows, cases_ids)
    # v2 divergence for original cases
    v2_orig_rows = [r for r in v2_rows if r.case_id in cases_ids]
    rep_v2 = compute_divergence(v2_orig_rows, cases_ids)
    
    # v2 divergence for siblings
    v2_sib_rows = [r for r in v2_rows if r.case_id in siblings_ids]
    rep_sib = compute_divergence(v2_sib_rows, siblings_ids)
    
    # Per-cluster before/after
    # Only for cases that belong to a ruled cluster
    ruled_clusters = {r.cluster_id: r for r in rulings if r.ruling != "SKIPPED"}
    per_cluster = {}
    
    for c in clusters:
        if c.cluster_id not in ruled_clusters:
            continue
        c_cases = set(c.case_ids)
        c_before = sum(1 for cid in rep_v1.divergent_case_ids if cid in c_cases)
        c_after = sum(1 for cid in rep_v2.divergent_case_ids if cid in c_cases)
        per_cluster[c.cluster_id] = {"before": c_before, "after": c_after}
        
    # Conformance
    # All cases in ruled clusters (their unanimous verdict should equal ruling)
    # AND all siblings (their unanimous verdict should equal expected)
    conformance_cases = []
    
    # Add adjudicated cases
    for c in clusters:
        ruling = ruled_clusters.get(c.cluster_id)
        if not ruling:
            continue
        for cid in c.case_ids:
            conformance_cases.append((cid, ruling.ruling))
            
    # Add siblings
    for s in siblings:
        conformance_cases.append((s.case_id, s.expected_verdict))
        
    conformance_hits = 0
    valid_by_case = {cid: [] for cid in (cases_ids + siblings_ids)}
    for r in v2_rows:
        if r.case_id in valid_by_case:
            valid_by_case[r.case_id].append(r)
            
    for cid, expected in conformance_cases:
        vlist = valid_by_case[cid]
        verdicts = {v.verdict for v in vlist}
        # Conforming means it is unanimous AND matches expected
        if len(verdicts) == 1 and expected in verdicts:
            conformance_hits += 1
        else:
            print(f"MISS {cid}: expected {expected}, got {verdicts}")
            
    # New divergent
    v1_unanimous = set(rep_v1.unanimous_case_ids)
    v2_divergent = set(rep_v2.divergent_case_ids)
    new_div = sorted(list(v1_unanimous & v2_divergent))
    
    # Flipped
    # unanimous in both, but verdict changed (and case was not adjudicated)
    # wait, spec says "non-adjudicated unanimous-both cases whose verdict changed"
    adjudicated_cids = {cid for c in clusters if c.cluster_id in ruled_clusters for cid in c.case_ids}
    
    flipped = []
    v2_unanimous = set(rep_v2.unanimous_case_ids)
    both_unanimous = (v1_unanimous & v2_unanimous) - adjudicated_cids
    
    v1_by_case = {cid: [] for cid in cases_ids}
    for r in v1_rows:
        v1_by_case[r.case_id].append(r)
        
    for cid in both_unanimous:
        v1_verdict = v1_by_case[cid][0].verdict
        v2_verdict = valid_by_case[cid][0].verdict
        if v1_verdict != v2_verdict:
            flipped.append(cid)
            
    flipped.sort()
    
    # Outcome logic
    outcome = "REGRESSED"
    if new_div or flipped:
        outcome = "REGRESSED"
    else:
        # Improved if divergent cases decreased AND conformance >= 80% (actually A6 implies "conformance > threshold", let's say >= 80%)
        # Spec says: "IMPROVED, NO_IMPROVEMENT, REGRESSED via new divergence, REGRESSED via flip, conformance below threshold, edge before_divergent=1"
        # Let's say improvement requires after < before and conformance >= 0.8
        if len(rep_v2.divergent_case_ids) < len(rep_v1.divergent_case_ids):
            conf_rate = conformance_hits / len(conformance_cases) if conformance_cases else 1.0
            if conf_rate >= 0.8:
                outcome = "IMPROVED"
            else:
                outcome = "NO_IMPROVEMENT"
        else:
            outcome = "NO_IMPROVEMENT"
            
    return VerificationResult(
        round=round_num,
        before_divergent=len(rep_v1.divergent_case_ids),
        before_total=len(cases_ids) - len(rep_v1.insufficient_case_ids),
        after_divergent=len(rep_v2.divergent_case_ids),
        after_total=len(cases_ids) - len(rep_v2.insufficient_case_ids),
        sibling_divergent=len(rep_sib.divergent_case_ids),
        sibling_total=len(siblings_ids) - len(rep_sib.insufficient_case_ids),
        conformance_hits=conformance_hits,
        conformance_total=len(conformance_cases),
        new_divergent_case_ids=new_div,
        flipped_case_ids=flipped,
        per_cluster=per_cluster,
        outcome=outcome
    )

async def verify(
    conn: sqlite3.Connection,
    provider: LLMProvider,
    settings: Settings,
    run_id: str,
    round_num: int
) -> VerificationResult:
    events.log_event(conn, run_id, "Verifier", "INFO", f"Starting verification round {round_num}")
    
    # 1. Load patched clauses
    run = db.get_run(conn, run_id)
    # We read the policy_v2_rX.txt
    from pathlib import Path
    policy_path = Path(run["policy_path"]).parent / f"policy_v2_r{round_num}.txt"
    with open(policy_path, "r", encoding="utf-8") as f:
        patched_text = f.read()
        
    from policyfuzz.config import MAX_POLICY_BYTES
    clauses = parse_policy(patched_text, MAX_POLICY_BYTES)
    
    cases = db.get_cases(conn, run_id, origin="generated")
    siblings = db.get_cases(conn, run_id, origin="sibling")
    # For a round, maybe we should only check siblings generated in this round?
    # Since we overwrite sibling origin, it's just all siblings.
    
    # 2. Run panel on v2
    policy_tag = f"v2r{round_num}"
    await run_panel(conn, provider, settings, run_id, policy_tag, clauses, cases + siblings)
    
    # 3. Compute metrics
    v1_rows = db.get_verdicts(conn, run_id, "v1")
    v2_rows = db.get_verdicts(conn, run_id, policy_tag)
    rulings = db.get_rulings(conn, run_id)
    clusters = db.get_clusters(conn, run_id)
    
    result = compute_verification(v1_rows, v2_rows, cases, siblings, rulings, clusters, round_num)
    
    # 4. Persist
    import json
    metrics = json.loads(run["metrics_json"])
    metrics[policy_tag] = result.model_dump()
    db.set_metrics(conn, run_id, metrics)
    
    db.set_status(conn, run_id, RunStatus.COMPLETE_IMPROVED if result.outcome == "IMPROVED" else RunStatus.COMPLETE_NO_IMPROVEMENT)
    events.log_event(conn, run_id, "Verifier", "INFO", f"Verification outcome: {result.outcome}")
    
    return result
