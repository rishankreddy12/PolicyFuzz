import pytest
import json
from pathlib import Path
import tempfile
import sys

from policyfuzz.models import CaseSet, InterpreterVerdict, ClusterSet, PatchProposal, Ruling
import subprocess

@pytest.fixture
def temp_fixtures_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)

def test_fixtures_completeness_and_validation():
    # Build it in place to ensure it runs
    subprocess.run([sys.executable, "scripts/build_fixtures.py"], check=True)

    
    path = Path("fixtures/demo/scripted_responses.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    responses = data["responses"]
    
    # Check parser
    assert "parser:enrich" in responses
    
    # Check casegen
    caseset = CaseSet.model_validate(responses["casegen:main"])
    assert len(caseset.cases) == 30
    
    # Check analyst
    clusters = ClusterSet.model_validate(responses["analyst:cluster:v1"])
    assert len(clusters.clusters) == 3
    
    # Check patcher
    patch = PatchProposal.model_validate(responses["patcher:r1"])
    assert len(patch.edits) == 3
    
    # Check verdicts
    v1_count = 0
    v2_count = 0
    for k, v in responses.items():
        if k.startswith("interp:"):
            verdict = InterpreterVerdict.model_validate(v)
            if "v1" in k and "v2r1" not in k:
                v1_count += 1
            if "v2r1" in k:
                v2_count += 1
                
    assert v1_count == 90 # 30 cases * 3 interpreters
    assert v2_count == 99 # 33 cases (30 base + 3 sibling) * 3 interpreters
    
    # Semantic check: v1 divergent set == {C24..C30}
    # (Just verifying the JSON has the divergence where expected, logic is in spec)
    # The instructions say "Fixture semantic checks (implemented as tests)"
    
    v1_divergent_cases = set()
    for case_id in [f"C{i:02d}" for i in range(1, 31)]:
        verdicts = {v["verdict"] for k, v in responses.items() if k.startswith("interp:") and f":{case_id}:v1" in k}
        if len(verdicts) > 1:
            v1_divergent_cases.add(case_id)
            
    assert v1_divergent_cases == {"C24", "C25", "C26", "C27", "C28", "C29", "C30"}
    
    # v2r1 divergent set == {C26}
    v2_divergent_cases = set()
    for case_id in [f"C{i:02d}" for i in range(1, 31)] + ["S01", "S02", "S03"]:
        verdicts = {v["verdict"] for k, v in responses.items() if k.startswith("interp:") and f":{case_id}:v2r1" in k}
        if len(verdicts) > 1:
            v2_divergent_cases.add(case_id)
            
    assert v2_divergent_cases == {"C26"}
