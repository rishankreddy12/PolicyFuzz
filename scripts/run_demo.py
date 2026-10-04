import argparse
import sys
import asyncio
import os
import json
from pathlib import Path
from policyfuzz.config import Settings, make_provider
from policyfuzz.orchestrator import Orchestrator
from policyfuzz import db
from policyfuzz.models import RunStatus

async def main():
    parser = argparse.ArgumentParser(description="Run PolicyFuzz Demo")
    parser.add_argument("--provider", choices=["scripted", "ollama"], default="scripted")
    parser.add_argument("--auto-gates", action="store_true", help="Auto-approve all gates using fixtures")
    parser.add_argument("--db", default="data/demo.db", help="Path to DB")
    args = parser.parse_args()
    
    os.environ["POLICYFUZZ_DB"] = args.db
    settings = Settings.from_env()
    settings.provider = args.provider
    settings.db_path = args.db
    
    conn = db.connect(settings.db_path)
    db.init_schema(conn)
    
    provider = make_provider(settings)
    orch = Orchestrator(conn, provider, settings)
    
    base = Path(__file__).parent.parent
    policy_path = base / "fixtures" / "demo" / "policy_v1.txt"
    with open(policy_path, "r", encoding="utf-8") as f:
        policy_text = f.read()
        
    print(f"Starting Demo Run (Provider: {args.provider})")
    run_id = await orch.create_run(policy_text, "Demo Run", args.provider)
    print(f"Run ID: {run_id}")
    
    # 1. Run until AWAITING_RULINGS
    status = await orch.run_until_gate(run_id)
    if status != RunStatus.AWAITING_RULINGS and not status.startswith("COMPLETE"):
        print(f"Run failed or stopped unexpectedly: {status}")
        sys.exit(1)
        
    if status == RunStatus.AWAITING_RULINGS:
        if args.auto_gates:
            rulings_path = base / "fixtures" / "demo" / "rulings.json"
            with open(rulings_path, "r", encoding="utf-8") as f:
                rulings_data = json.load(f)
                
            rulings_obj = {}
            for r in rulings_data:
                rulings_obj[r["cluster_id"]] = {
                    "ruling": r["ruling"],
                    "note": r.get("note", "")
                }
            
            # Since auto-gates uses the original K-ids, we need to map the actual cluster IDs
            # in the DB to the expected rulings based on label/summary if we want to be fully generic.
            # However, for demo, clusters are generated exactly the same every time in scripted.
            c = conn.cursor()
            c.execute("SELECT cluster_id, json FROM clusters WHERE run_id=?", (run_id,))
            cluster_rows = c.fetchall()
            
            from policyfuzz.models import Ruling
            ruling_objs = []
            for cid, cjson in cluster_rows:
                cluster_obj = json.loads(cjson)
                cases = cluster_obj["case_ids"]
                if "C27" in cases:
                    ruling_objs.append(Ruling(cluster_id=cid, ruling="DENY", note=""))
                elif "C24" in cases:
                    ruling_objs.append(Ruling(cluster_id=cid, ruling="ALLOW", note=""))
                else:
                    ruling_objs.append(Ruling(cluster_id=cid, ruling="ESCALATE", note=""))
                    
            orch.submit_rulings(run_id, ruling_objs)
            print("Auto-submitted rulings.")
            
            status = await orch.run_until_gate(run_id)
        else:
            print(f"Run paused at {status}. Please use the UI to continue.")
            sys.exit(0)
            
    if status == RunStatus.AWAITING_EDIT_DECISIONS:
        if args.auto_gates:
            patch = db.get_patch(conn, run_id, 1)
            from policyfuzz.models import PatchProposal
            proposal = PatchProposal.model_validate_json(patch["proposal_json"])
            approvals = {e.edit_id: True for e in proposal.edits}
            orch.decide_edits(run_id, 1, approvals)
            print("Auto-approved all edits.")
            await orch.apply_and_verify(run_id)
            status = await orch.run_until_gate(run_id)
        else:
            print(f"Run paused at {status}. Please use the UI to continue.")
            sys.exit(0)
            
    # Final status
    print(f"\nDemo finished with status: {status}")
    print(f"Run Directory: {Path(settings.runs_dir) / run_id}")
    
    # Summary Table
    # cases, divergent, clusters, rulings, edits applied, before/after, outcome
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM cases WHERE run_id=?", (run_id,))
    cases = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM clusters WHERE run_id=?", (run_id,))
    clusters = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM patch_edits WHERE run_id=? AND approved=1", (run_id,))
    edits = c.fetchone()[0]
    
    print("-" * 40)
    print("SUMMARY:")
    print(f"Cases Generated: {cases}")
    print(f"Clusters Discovered: {clusters}")
    print(f"Edits Applied: {edits}")
    
    c.execute("SELECT json FROM verifications WHERE run_id=? ORDER BY round DESC LIMIT 1", (run_id,))
    v_row = c.fetchone()
    if v_row:
        v_data = json.loads(v_row[0])
        print(f"Before Divergent: {v_data.get('before_divergent', '?')} / {v_data.get('before_total', '?')}")
        print(f"After Divergent: {v_data.get('after_divergent', '?')} / {v_data.get('after_total', '?')}")
        print(f"Outcome: {v_data.get('outcome', 'UNKNOWN')}")
        
    print("-" * 40)
    
    if args.provider == "scripted" and "COMPLETE_IMPROVED" not in status:
        sys.exit(1)
        
    sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())
