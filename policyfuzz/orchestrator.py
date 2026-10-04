"""Orchestrator and State Machine for PolicyFuzz runs."""

import os
import uuid
import sqlite3
import traceback
from typing import Dict, List, Optional
from pathlib import Path

from policyfuzz import db, events
from policyfuzz.config import Settings
from policyfuzz.models import RunStatus, Ruling
from policyfuzz.llm.base import LLMProvider
from policyfuzz.llm.structured import StructuredOutputError
from policyfuzz.agents.clause_parser import run_parser, PolicyFormatError, PolicyTooLargeError
from policyfuzz.agents.case_generator import run_case_generator
from policyfuzz.agents.interpreter import run_panel, PanelUnreliableError
from policyfuzz.agents.divergence import cluster_divergent

class GateError(Exception):
    pass

import re

def sanitize_text(text: str) -> str:
    # Strip control chars except \n\t
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    # Neutralise tag breakouts
    text = re.sub(r'(?i)</policy>', '&lt;/policy&gt;', text)
    text = re.sub(r'(?i)</case>', '&lt;/case&gt;', text)
    return text

class Orchestrator:
    def __init__(self, conn: sqlite3.Connection, provider: LLMProvider, settings: Settings):
        self.conn = conn
        self.provider = provider
        self.settings = settings

    async def create_run(self, policy_text: str, name: str, provider_name: str) -> str:
        from policyfuzz import config
        
        try:
            # If passed as bytes, decode check is needed, but we assume str.
            # We'll just enforce UTF-8 encodeability.
            policy_bytes = policy_text.encode("utf-8")
        except UnicodeEncodeError:
            raise PolicyFormatError("Policy text is not valid UTF-8.")
            
        if len(policy_bytes) > config.MAX_POLICY_BYTES:
            raise PolicyTooLargeError(f"Policy too large (>{config.MAX_POLICY_BYTES} bytes).")
            
        policy_text = sanitize_text(policy_text)
            
        run_id = uuid.uuid4().hex
        
        runs_dir = Path(self.settings.runs_dir) / run_id
        runs_dir.mkdir(parents=True, exist_ok=True)
        
        policy_path = runs_dir / "policy_v1.txt"
        with open(policy_path, "w", encoding="utf-8") as f:
            f.write(policy_text)
            
        db.create_run(self.conn, run_id, name, RunStatus.CREATED, provider_name, str(policy_path))
        events.log_event(self.conn, run_id, "Orchestrator", "INFO", f"Created run {name}")
        return run_id

    async def run_until_gate(self, run_id: str) -> str:
        """Advance automatic steps until human intervention or completion is required."""
        while True:
            run = db.get_run(self.conn, run_id)
            if not run:
                raise ValueError(f"Run {run_id} not found")
                
            status = run["status"]
            
            # Stop conditions
            if status in [RunStatus.AWAITING_RULINGS, RunStatus.AWAITING_EDIT_DECISIONS, RunStatus.FAILED] or status.startswith("COMPLETE"):
                return status
                
            try:
                if status == RunStatus.CREATED:
                    with open(run["policy_path"], "r", encoding="utf-8") as f:
                        text = f.read()
                    await run_parser(self.conn, self.provider, self.settings, run_id, text)
                    
                elif status == RunStatus.PARSED:
                    clauses = db.get_clauses(self.conn, run_id)
                    enrichment = db.get_enrichment(self.conn, run_id)
                    await run_case_generator(self.conn, self.provider, self.settings, run_id, clauses, enrichment)
                    
                elif status == RunStatus.CASES_READY:
                    clauses = db.get_clauses(self.conn, run_id)
                    cases = db.get_cases(self.conn, run_id, origin="generated")
                    await run_panel(self.conn, self.provider, self.settings, run_id, "v1", clauses, cases)
                    
                elif status == RunStatus.PANEL_V1_DONE:
                    clauses = db.get_clauses(self.conn, run_id)
                    cases = db.get_cases(self.conn, run_id, origin="generated")
                    verdicts = db.get_verdicts(self.conn, run_id, "v1")
                    await cluster_divergent(self.conn, self.provider, self.settings, run_id, clauses, cases, verdicts)
                    
                    # cluster_divergent sets to ANALYZED or COMPLETE_NO_DIVERGENCE
                    run2 = db.get_run(self.conn, run_id)
                    if run2["status"] == RunStatus.ANALYZED:
                        db.set_status(self.conn, run_id, RunStatus.AWAITING_RULINGS)
                        events.log_event(self.conn, run_id, "Orchestrator", "INFO", "Waiting for human rulings.")
                        
                elif status == RunStatus.RULED:
                    from policyfuzz.agents.patcher import run_patcher
                    round_num = run["round"] if run["round"] is not None else 1
                    await run_patcher(self.conn, self.provider, self.settings, run_id, round_num)
                    
                elif status == RunStatus.PATCH_APPLIED:
                    # After PATCH_APPLIED, verifier sets it to COMPLETE_IMPROVED or COMPLETE_NO_IMPROVEMENT
                    # But actually apply_and_verify already calls verify(). So we shouldn't even land here in run_until_gate
                    # unless it crashed after PATCH_APPLIED.
                    from policyfuzz.agents.verifier import verify
                    round_num = run["round"] if run["round"] is not None else 1
                    await verify(self.conn, self.provider, self.settings, run_id, round_num)
                    
                else:
                    db.set_error(self.conn, run_id, f"Unknown status {status}")
                    break
                    
            except (PolicyFormatError, PolicyTooLargeError, StructuredOutputError, PanelUnreliableError, GateError, NotImplementedError) as e:
                # Expected domain errors are already logged/set by agents where relevant, or we handle here
                # ensure FAILED status
                db.set_status(self.conn, run_id, RunStatus.FAILED)
                db.set_error(self.conn, run_id, str(e))
                events.log_event(self.conn, run_id, "Orchestrator", "ERROR", str(e))
                return RunStatus.FAILED
            except Exception as e:
                # Unhandled exception
                db.set_status(self.conn, run_id, RunStatus.FAILED)
                tb = traceback.format_exc()
                summary = f"Unhandled error: {e}\n{tb}"
                db.set_error(self.conn, run_id, summary)
                events.log_event(self.conn, run_id, "Orchestrator", "ERROR", summary)
                return RunStatus.FAILED

    def submit_rulings(self, run_id: str, rulings: List[Ruling]) -> None:
        run = db.get_run(self.conn, run_id)
        if run["status"] != RunStatus.AWAITING_RULINGS:
            raise GateError(f"Cannot submit rulings in status {run['status']}")
            
        clusters = db.get_clusters(self.conn, run_id)
        cluster_ids = {c.cluster_id for c in clusters}
        
        provided_ids = [r.cluster_id for r in rulings]
        
        # Exact match required
        if set(provided_ids) != cluster_ids:
            raise GateError(f"Must rule exactly on clusters {cluster_ids}, got {provided_ids}")
        if len(provided_ids) != len(set(provided_ids)):
            raise GateError("Duplicate rulings submitted.")
            
        for r in rulings:
            events.log_event(self.conn, run_id, "Human", "HUMAN", f"Ruled {r.ruling} on {r.cluster_id}", r.model_dump())
            
        db.save_rulings(self.conn, run_id, rulings)
        
        all_skipped = all(r.ruling == "SKIPPED" for r in rulings)
        if all_skipped:
            db.set_status(self.conn, run_id, RunStatus.COMPLETE_NO_RULINGS)
            events.log_event(self.conn, run_id, "Orchestrator", "INFO", "All rulings skipped. Run complete.")
        else:
            db.set_status(self.conn, run_id, RunStatus.RULED)
            events.log_event(self.conn, run_id, "Orchestrator", "INFO", "Rulings submitted.")

    def decide_edits(self, run_id: str, round_num: int, approvals: Dict[str, bool]) -> None:
        run = db.get_run(self.conn, run_id)
        if run["status"] != RunStatus.AWAITING_EDIT_DECISIONS:
            raise GateError(f"Cannot decide edits in status {run['status']}")
            
        patch_row = db.get_patch(self.conn, run_id, round_num)
        if not patch_row:
            raise GateError(f"No patch found for round {round_num}")
            
        from policyfuzz.models import PatchProposal
        patch = PatchProposal.model_validate_json(patch_row["proposal_json"])
        
        expected_edits = {e.edit_id for e in patch.edits}
        if set(approvals.keys()) != expected_edits:
            raise GateError(f"Must decide on exactly {expected_edits}")
            
        for edit_id, app in approvals.items():
            db.set_edit_decision(self.conn, run_id, round_num, edit_id, app)
            events.log_event(self.conn, run_id, "Human", "HUMAN", f"Edit {edit_id} {'APPROVED' if app else 'REJECTED'}")
            
        # Patcher status remains until apply_and_verify is called, but we could mark it ready.
        # Actually plan says apply_and_verify requires G2 satisfied. So G2 just saves approvals.
        # We can just leave status as AWAITING_EDIT_DECISIONS or move to a custom internal state, but
        # AWAITING_EDIT_DECISIONS is fine; apply_and_verify checks if they exist.

    async def apply_and_verify(self, run_id: str) -> None:
        import re
        if not re.match(r"^[0-9a-f]{32}$", run_id):
            raise ValueError(f"Invalid run_id: {run_id}")
        run = db.get_run(self.conn, run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")
        if run["status"] != RunStatus.AWAITING_EDIT_DECISIONS:
            raise GateError(f"Cannot apply edits in status {run['status']}")
            
        round_num = run["round"] if run["round"] is not None else 1
        patch_row = db.get_patch(self.conn, run_id, round_num)
        
        from policyfuzz.models import PatchProposal
        patch = PatchProposal.model_validate_json(patch_row["proposal_json"])
        
        # Get approved edits
        c = self.conn.cursor()
        c.execute("SELECT edit_id FROM patch_edits WHERE run_id=? AND round=? AND approved=1", (run_id, round_num))
        approved_ids = {row[0] for row in c.fetchall()}
        
        approved_edits = [e for e in patch.edits if e.edit_id in approved_ids]
        
        if not approved_edits:
            db.set_status(self.conn, run_id, RunStatus.COMPLETE_NO_APPROVED_EDITS)
            events.log_event(self.conn, run_id, "Orchestrator", "INFO", "No approved edits. Run complete.")
            return
            
        with open(run["policy_path"], "r", encoding="utf-8") as f:
            v1_text = f.read()
            
        # For round 2+, we should actually apply to v2_rX, but spec says "patch applies on top of previous round's policy text".
        # Let's read previous round if round > 1
        source_path = run["policy_path"]
        if round_num > 1:
            source_path = str(Path(run["policy_path"]).parent / f"policy_v2_r{round_num-1}.txt")
            
        with open(source_path, "r", encoding="utf-8") as f:
            source_text = f.read()
            
        from policyfuzz.patching import apply_edits as do_apply
        new_text = do_apply(source_text, approved_edits)
        
        if not re.match(r"^[0-9a-f]{32}$", run_id):
            raise ValueError(f"Invalid run_id: {run_id}")
            
        out_path = Path(run["policy_path"]).parent / f"policy_v2_r{round_num}.txt"
        if out_path.exists():
            raise FileExistsError(f"Target file {out_path} already exists; immutability violation.")
            
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(new_text)
            
        db.set_status(self.conn, run_id, RunStatus.PATCH_APPLIED)
        events.log_event(self.conn, run_id, "Orchestrator", "INFO", "Patch applied.")
        
        from policyfuzz.agents.verifier import verify
        await verify(self.conn, self.provider, self.settings, run_id, round_num)
        
        from policyfuzz.report import build_report_md
        build_report_md(self.conn, run_id)

    async def revise_patch(self, run_id: str) -> None:
        run = db.get_run(self.conn, run_id)
        
        round_num = run["round"] if run["round"] is not None else 1
        if round_num >= self.settings.MAX_PATCH_ROUNDS:
            raise GateError("Max patch rounds reached.")
            
        # Increment round
        c = self.conn.cursor()
        c.execute("UPDATE runs SET round = round + 1 WHERE run_id=?", (run_id,))
        self.conn.commit()
        
        db.set_status(self.conn, run_id, RunStatus.RULED)
        
        # In run_until_gate, it handles RULED by running patcher for the new round.
        await self.run_until_gate(run_id)
