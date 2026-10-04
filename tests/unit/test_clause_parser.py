import pytest
from policyfuzz.agents.clause_parser import parse_policy, PolicyFormatError, PolicyTooLargeError
import os

def test_parse_policy_demo():
    # Load demo policy
    path = os.path.join(os.path.dirname(__file__), '..', '..', 'fixtures', 'demo', 'policy_v1.txt')
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
        
    clauses = parse_policy(text)
    
    # 13 clauses in sections 2-8, plus section-1 clauses. Total is 16.
    assert len(clauses) == 16
    assert clauses[0].clause_id == "1.1"
    assert clauses[-1].clause_id == "8.1"
    
def test_parse_policy_multiline():
    text = "1. Sec\n1.1 clause start\nand continuation"
    clauses = parse_policy(text)
    assert len(clauses) == 1
    assert clauses[0].text == "clause start and continuation"
    
def test_parse_policy_malformed():
    text = "Section 3(a) bad format"
    with pytest.raises(PolicyFormatError):
        parse_policy(text)
        
def test_parse_policy_too_large():
    text = "1. Sec\n" + "1.1 clause\n" * 2000
    with pytest.raises(PolicyTooLargeError):
        parse_policy(text, max_bytes=100)
