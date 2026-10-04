"""Reporting and regression extraction."""

import sqlite3
import json
from pathlib import Path
from typing import List, Dict, Any

from policyfuzz import db
from policyfuzz.patching import unified_diff, decision_table_md
from policyfuzz.models import RunStatus

def build_regression_cases(conn: sqlite3.Connection, run_id: str) -> List[Dict[str, Any]]:
    """Return adjudicated divergent cases + sibling cases."""
    results = []
    
    # Siblings
    siblings = db.get_cases(conn, run_id, origin="sibling")
    for s in siblings:
        results.append({
            "case_id": s.case_id,
            "narrative": s.narrative,
            "expected_verdict": s.expected_verdict,
            "source_cluster": None,
            "ruling_note": "Generated sibling case"
        })
        
    # Adjudicated cases
    rulings = {r.cluster_id: r for r in db.get_rulings(conn, run_id) if r.ruling != "SKIPPED"}
    clusters = {c.cluster_id: c for c in db.get_clusters(conn, run_id)}
    
    # We only include divergent cases from ruled clusters
    for r in rulings.values():
        c = clusters.get(r.cluster_id)
        if not c:
            continue
            
        for cid in c.case_ids:
            case = db.get_case(conn, run_id, cid)
            if case:
                results.append({
                    "case_id": case.case_id,
                    "narrative": case.narrative,
                    "expected_verdict": r.ruling,
                    "source_cluster": r.cluster_id,
                    "ruling_note": r.note
                })
                
    return results

def build_report_md(conn: sqlite3.Connection, run_id: str) -> str:
    run = db.get_run(conn, run_id)
    
    lines = []
    lines.append(f"# PolicyFuzz Report: {run['name']}")
    lines.append(f"Provider: {run['provider']}  ")
    if run['provider'] == 'scripted':
        lines.append("> **Note**: This run used the deterministic scripted provider.")
        
    lines.append(f"Status: {run['status']}")
    
    round_num = run["round"] if run["round"] is not None else 1
    
    # Rulings
    rulings = db.get_rulings(conn, run_id)
    if rulings:
        lines.append("## Human Rulings")
        for r in rulings:
            lines.append(f"- Cluster {r.cluster_id}: {r.ruling} (Note: {r.note})")
            
    # Edits
    patch_row = db.get_patch(conn, run_id, round_num)
    if patch_row:
        from policyfuzz.models import PatchProposal
        patch = PatchProposal.model_validate_json(patch_row["proposal_json"])
        
        lines.append("## Approved Edits")
        
        c = conn.cursor()
        c.execute("SELECT edit_id FROM patch_edits WHERE run_id=? AND round=? AND approved=1", (run_id, round_num))
        approved_ids = {row[0] for row in c.fetchall()}
        
        for e in patch.edits:
            if e.edit_id in approved_ids:
                lines.append(f"### {e.edit_id} ({e.action} on {e.clause_id})")
                lines.append(f"Rationale: {e.rationale}")
                lines.append("```diff")
                
                # We could run unified_diff for each clause, but text is fine
                lines.append(f"+ {e.new_text}")
                lines.append("```")
                
        lines.append("## Decision Table")
        lines.append(decision_table_md(patch.decision_table))
        
        dt_path = Path(run["policy_path"]).parent / "decision_table.md"
        with open(dt_path, "w", encoding="utf-8") as f:
            f.write(decision_table_md(patch.decision_table))
            
    # Verification
    if run["status"] in [RunStatus.COMPLETE_IMPROVED, RunStatus.COMPLETE_NO_IMPROVEMENT, RunStatus.VERIFIED]:
        metrics = json.loads(run["metrics_json"])
        v_res = metrics.get(f"v2r{round_num}")
        if v_res:
            lines.append("## Verification")
            lines.append(f"Outcome: **{v_res['outcome']}**")
            lines.append("| Metric | Value |")
            lines.append("|---|---|")
            lines.append(f"| before (v1, originals) | {v_res['before_divergent']} / {v_res['before_total']} divergent |")
            lines.append(f"| after (v2r{round_num}, originals) | {v_res['after_divergent']} / {v_res['after_total']} divergent |")
            lines.append(f"| siblings (v2r{round_num}) | {v_res['sibling_divergent']} / {v_res['sibling_total']} divergent |")
            lines.append(f"| conformance | {v_res['conformance_hits']} / {v_res['conformance_total']} |")
            lines.append(f"| new_divergent / flipped | {len(v_res['new_divergent_case_ids'])} / {len(v_res['flipped_case_ids'])} |")
            
            cluster_strs = [f"{k}: {v['before']}→{v['after']}" for k, v in v_res['per_cluster'].items()]
            lines.append(f"| per_cluster | {', '.join(cluster_strs)} |")
            
            lines.append("## Regression Cases")
            reg = build_regression_cases(conn, run_id)
            lines.append(f"Extracted {len(reg)} regression cases.")
            
            reg_path = Path(run["policy_path"]).parent / "regression_cases.json"
            with open(reg_path, "w", encoding="utf-8") as f:
                json.dump(reg, f, indent=2)
                
    md = "\n\n".join(lines)
    rep_path = Path(run["policy_path"]).parent / "report.md"
    with open(rep_path, "w", encoding="utf-8") as f:
        f.write(md)
        
    return md
