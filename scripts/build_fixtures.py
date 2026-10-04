#!/usr/bin/env python3
"""Build scripted_responses.json from spec.py."""

import json
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fixtures.demo import spec

def build_fixtures():
    responses = {}
    
    # 1. parser:enrich
    responses["parser:enrich"] = spec.PARSER_ENRICHMENT
    
    # 2. casegen:main
    responses["casegen:main"] = {"cases": spec.CASES}
    
    # 3. analyst:cluster:v1
    responses["analyst:cluster:v1"] = {"clusters": spec.CLUSTERS}
    
    # 4. patcher:r1
    responses["patcher:r1"] = spec.PATCH_PROPOSAL
    
    # 5. interp:{A|B|C}:{Cxx}:v1
    for case in spec.CASES:
        cid = case["case_id"]
        target = case["target_clauses"]
        for interp in ["A", "B", "C"]:
            verdict = spec.VERDICTS_V1[cid][interp]
            rationale = f"Reading {target[0]} cautiously, this request is {verdict}."
            
            # Ensure it's >= 10 chars, add title if needed
            if len(rationale) < 20:
                rationale += " " * 20
                
            cited = target.copy()
            if verdict == "ESCALATE":
                cited.append("8.1")
                
            responses[f"interp:{interp}:{cid}:v1"] = {
                "case_id": cid,
                "verdict": verdict,
                "cited_clauses": cited,
                "confidence": 0.9,
                "rationale": rationale
            }
            
    # 6. interp:{A|B|C}:{Cxx|Sxx}:v2r1
    for case in spec.CASES + spec.SIBLINGS:
        cid = case["case_id"]
        target = case["target_clauses"]
        for interp in ["A", "B", "C"]:
            verdict = spec.VERDICTS_V2[cid][interp]
            rationale = f"Reading {target[0]} cautiously, this request is {verdict}."
            
            cited = target.copy()
            if verdict == "ESCALATE":
                cited.append("8.1")
                
            responses[f"interp:{interp}:{cid}:v2r1"] = {
                "case_id": cid,
                "verdict": verdict,
                "cited_clauses": cited,
                "confidence": 0.95,
                "rationale": rationale
            }
            
    output = {
        "meta": {"generated_by": "build_fixtures.py"},
        "responses": responses
    }
    
    out_dir = Path(__file__).parent.parent / "fixtures" / "demo"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    with open(out_dir / "scripted_responses.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, sort_keys=True)
        
    with open(out_dir / "rulings.json", "w", encoding="utf-8") as f:
        json.dump(spec.RULINGS, f, indent=2, sort_keys=True)
        
    print(f"Generated {len(responses)} keys in scripted_responses.json")

if __name__ == "__main__":
    build_fixtures()
