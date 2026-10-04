"""Patching utilities (applying edits, diffing, tables)."""

import difflib
import re
from typing import List, Dict

from policyfuzz.models import ClauseEdit, DecisionRow
from policyfuzz.agents.clause_parser import parse_policy, PolicyFormatError

class PatchApplyError(Exception):
    pass

def apply_edits(policy_text: str, approved_edits: List[ClauseEdit]) -> str:
    """Apply approved edits line-by-line and verify post-conditions."""
    lines = policy_text.replace("\r\n", "\n").split("\n")
    
    # Helper to find where a clause starts and ends in the line array
    def find_clause_block(cid: str) -> tuple[int, int]:
        # Starts with: 1.1 text
        # Continues until next ^\d+\. or ^\d+\.\d+
        start_idx = -1
        end_idx = -1
        pattern = re.compile(rf"^\s*{re.escape(cid)}\s+(.*)$")
        next_pattern = re.compile(r"^\s*(\d+(?:\.\d+)*)\s+(.*)$")
        
        for i, line in enumerate(lines):
            if start_idx == -1:
                if pattern.match(line):
                    start_idx = i
            else:
                if next_pattern.match(line):
                    end_idx = i
                    break
                    
        if start_idx != -1 and end_idx == -1:
            end_idx = len(lines)
            
        return start_idx, end_idx
        
    new_lines = list(lines)
    
    # We apply replacements first, then additions.
    # Actually, simpler to apply them in reverse line order or carefully.
    # Since we only replace or add whole blocks, we can just build a new string.
    # Actually, replacing by line index is easier if we do it backwards.
    
    edits_to_apply = []
    for e in approved_edits:
        target_id = e.clause_id if e.action == "REPLACE" else e.anchor_clause_id
        if not target_id:
            raise PatchApplyError(f"Missing anchor_clause_id for ADD_AFTER edit {e.edit_id}")
            
        s, end = find_clause_block(target_id)
        if s == -1:
            raise PatchApplyError(f"Anchor clause {target_id} not found for edit {e.edit_id}")
        edits_to_apply.append((s, end, e))
        
    # Sort descending by start index
    edits_to_apply.sort(key=lambda x: x[0], reverse=True)
    
    for s, end, e in edits_to_apply:
        if e.action == "REPLACE":
            new_lines[s:end] = [f"{e.clause_id} {e.new_text}"]
        elif e.action == "ADD_AFTER":
            new_lines.insert(end, f"{e.clause_id} {e.new_text}")
            
    new_text = "\n".join(new_lines)
    
    # Verification
    try:
        new_clauses = parse_policy(new_text)
    except PolicyFormatError as err:
        raise PatchApplyError(f"Resulting policy format is invalid: {err}")
        
    new_ids = {c.clause_id for c in new_clauses}
    for e in approved_edits:
        if e.clause_id not in new_ids:
            raise PatchApplyError(f"New clause {e.clause_id} missing after {e.action}")
            
    # Check text matches (roughly, parser strips some whitespace)
    new_clauses_dict = {c.clause_id: c.text for c in new_clauses}
    for e in approved_edits:
        actual = new_clauses_dict[e.clause_id]
        expected = e.new_text.strip()
        if actual != expected:
            raise PatchApplyError(f"Text mismatch for {e.clause_id}: expected '{expected}', got '{actual}'")
            
    return new_text

def unified_diff(old_text: str, new_text: str) -> str:
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    diff = difflib.unified_diff(old_lines, new_lines, fromfile="v1", tofile="v2")
    return "".join(diff)

def decision_table_md(rows: List[DecisionRow]) -> str:
    if not rows:
        return ""
    lines = ["| Condition | Verdict | Clauses |", "|---|---|---|"]
    for r in rows:
        lines.append(f"| {r.condition} | {r.verdict} | {', '.join(r.clause_refs)} |")
    return "\n".join(lines)
