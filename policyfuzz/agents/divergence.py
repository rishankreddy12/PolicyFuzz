"""Divergence detection and clustering."""

import sqlite3
import json
from typing import List, Dict, Tuple
from pydantic import BaseModel

from policyfuzz import db, events
from policyfuzz.config import Settings
from policyfuzz.models import Case, Clause, InterpreterVerdict, Cluster, ClusterSet, RunStatus
from policyfuzz.llm.base import LLMProvider
from policyfuzz.llm.structured import structured_call, StructuredOutputError

class DivergenceReport(BaseModel):
    divergent_case_ids: List[str]
    unanimous_case_ids: List[str]
    insufficient_case_ids: List[str]
    divergence_rate: float

def compute_divergence(verdict_rows: List[InterpreterVerdict], case_ids: List[str]) -> DivergenceReport:
    valid_by_case: Dict[str, List[InterpreterVerdict]] = {cid: [] for cid in case_ids}
    for v in verdict_rows:
        if v.case_id in valid_by_case:
            valid_by_case[v.case_id].append(v)
            
    divergent = []
    unanimous = []
    insufficient = []
    
    for cid in case_ids:
        vlist = valid_by_case[cid]
        if len(vlist) < 2:
            insufficient.append(cid)
            continue
            
        verdicts = {v.verdict for v in vlist}
        if len(verdicts) > 1:
            divergent.append(cid)
        else:
            unanimous.append(cid)
            
    total_sufficient = len(divergent) + len(unanimous)
    rate = len(divergent) / total_sufficient if total_sufficient > 0 else 0.0
    
    return DivergenceReport(
        divergent_case_ids=divergent,
        unanimous_case_ids=unanimous,
        insufficient_case_ids=insufficient,
        divergence_rate=rate
    )

def validate_clusters(clusters: List[Cluster], divergent_cases: List[str], valid_clauses: set) -> List[str]:
    errors = []
    seen_cases = set()
    
    for c in clusters:
        for cid in c.case_ids:
            if cid not in divergent_cases:
                errors.append(f"Cluster {c.cluster_id} contains non-divergent case {cid}")
            if cid in seen_cases:
                errors.append(f"Case {cid} appears in multiple clusters")
            seen_cases.add(cid)
            
        for clid in c.involved_clauses:
            if clid not in valid_clauses:
                errors.append(f"Cluster {c.cluster_id} cites unknown clause {clid}")
                
    missing = set(divergent_cases) - seen_cases
    if missing:
        errors.append(f"Divergent cases missing from clusters: {missing}")
        
    return errors

def repair_clusters(clusters: List[Cluster], divergent_cases: List[str]) -> List[Cluster]:
    seen = {cid for c in clusters for cid in c.case_ids if cid in divergent_cases}
    missing = [cid for cid in divergent_cases if cid not in seen]
    
    # Remove bad ones
    for c in clusters:
        c.case_ids = [cid for cid in c.case_ids if cid in divergent_cases]
        
    clusters = [c for c in clusters if c.case_ids]
    
    if missing:
        clusters.append(Cluster(
            cluster_id="K_misc",
            label="Miscellaneous Unassigned",
            loophole_type="SCOPE_GAP",
            case_ids=missing,
            involved_clauses=["1.1"], # safe dummy
            summary="Cases that the LLM failed to group.",
            business_impact="LOW",
            impact_reason="Fallback cluster."
        ))
    return clusters

def fallback_clusters(divergent_cases: List[Case]) -> List[Cluster]:
    # Group by sorted target clauses
    groups = {}
    for c in divergent_cases:
        key = tuple(sorted(c.target_clauses))
        if key not in groups:
            groups[key] = []
        groups[key].append(c.case_id)
        
    clusters = []
    for i, (clauses, cids) in enumerate(groups.items()):
        clusters.append(Cluster(
            cluster_id=f"Kf_{i}",
            label=f"Cases on clauses {','.join(clauses)}",
            loophole_type="SCOPE_GAP",
            case_ids=cids,
            involved_clauses=list(clauses),
            summary="Deterministic fallback group.",
            business_impact="MEDIUM",
            impact_reason="Fallback."
        ))
    return clusters

def rank_clusters(clusters: List[Cluster], valid_by_case: Dict[str, List[InterpreterVerdict]]) -> List[Cluster]:
    impact_val = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    
    def sort_key(c: Cluster) -> Tuple[int, int, float]:
        # Sort by: impact desc, count desc, mean confidence asc (lower confidence is more ambiguous)
        # We negate the first two so default ascending sort works correctly
        confs = []
        for cid in c.case_ids:
            confs.extend([v.confidence for v in valid_by_case.get(cid, [])])
        mean_conf = sum(confs) / len(confs) if confs else 1.0
        
        return (-impact_val[c.business_impact], -len(c.case_ids), mean_conf)
        
    return sorted(clusters, key=sort_key)

async def cluster_divergent(
    conn: sqlite3.Connection,
    provider: LLMProvider,
    settings: Settings,
    run_id: str,
    clauses: List[Clause],
    cases: List[Case],
    verdicts: List[InterpreterVerdict]
) -> None:
    events.log_event(conn, run_id, "Analyst", "INFO", "Started clustering")
    
    report = compute_divergence(verdicts, [c.case_id for c in cases])
    
    metrics = {
        "v1": {
            "total": len(cases),
            "divergent": len(report.divergent_case_ids),
            "rate": report.divergence_rate,
            "insufficient": len(report.insufficient_case_ids)
        }
    }
    db.set_metrics(conn, run_id, metrics)
    
    if not report.divergent_case_ids:
        db.set_status(conn, run_id, RunStatus.COMPLETE_NO_DIVERGENCE)
        events.log_event(conn, run_id, "Analyst", "INFO", "No divergence found")
        return
        
    div_cases = [c for c in cases if c.case_id in report.divergent_case_ids]
    
    # Build prompt
    sys = "You are a policy analyst grouping contradictory LLM verdicts into clusters."
    user = "Here are the cases that caused divergence:\n\n"
    
    valid_by_case = {cid: [] for cid in report.divergent_case_ids}
    for v in verdicts:
        if v.case_id in valid_by_case:
            valid_by_case[v.case_id].append(v)
            
    for c in div_cases:
        user += f"Case {c.case_id}: {c.narrative}\n"
        for v in valid_by_case[c.case_id]:
            user += f"  - {v.verdict} (cited {v.cited_clauses}): {v.rationale}\n"
        user += "\n"
        
    valid_ids = {c.clause_id for c in clauses}
    
    def validator(cset: ClusterSet) -> List[str]:
        return validate_clusters(cset.clusters, report.divergent_case_ids, valid_ids)
        
    clusters = []
    is_fallback = False
    
    try:
        cset = await structured_call(
            provider, conn, run_id, "analyst", "analyst:cluster:v1",
            sys, user, ClusterSet, settings.model_strong,
            validator=validator, max_retries=1
        )
        clusters = cset.clusters
    except Exception as e:
        events.log_event(conn, run_id, "Analyst", "WARN", f"Clustering failed: {e}. Falling back.")
        clusters = fallback_clusters(div_cases)
        is_fallback = True
        
    if not is_fallback:
        clusters = repair_clusters(clusters, report.divergent_case_ids)
        
    clusters = rank_clusters(clusters, valid_by_case)
    
    # Enforce unique Kx IDs in case LLM gave duplicates or bad format
    for i, c in enumerate(clusters):
        c.cluster_id = f"K{i+1}"
        
    db.save_clusters(conn, run_id, clusters, is_fallback=is_fallback)
    db.set_status(conn, run_id, RunStatus.ANALYZED)
    events.log_event(conn, run_id, "Analyst", "INFO", "Finished clustering")
