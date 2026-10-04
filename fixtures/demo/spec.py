"""Demo policy fixtures specification (Appendix B equivalent)."""

# 30 Base cases (C01 to C30)
CASES = []
for i in range(1, 31):
    case_id = f"C{i:02d}"
    all_targets = ["2.1", "2.2", "2.3", "3.1", "4.1", "4.2", "5.1", "5.2", "5.3", "6.1", "6.2", "7.1", "8.1"]
    CASES.append({
        "case_id": case_id,
        "title": f"Case {i} Request",
        "narrative": f"A customer is requesting something related to case {i}. This narrative must be at least 40 characters long to pass validation.",
        "target_clauses": [all_targets[i % len(all_targets)]],
        "boundary_type": "control" if i <= 5 else ("threshold" if i < 25 else "conflict")
    })

# Cases C24 to C30 are divergent in v1 (7 divergent cases)
# Case C26 remains divergent in v2r1
# Sibling cases (S01, S02, S03)
SIBLINGS = [
    {
        "case_id": f"S0{i}",
        "title": f"Sibling Case {i}",
        "narrative": f"Sibling case narrative {i} which is also long enough.",
        "target_clauses": ["2.1"],
        "boundary_type": "control"
    }
    for i in range(1, 4)
]

# V1 Verdicts
VERDICTS_V1 = {}
for case in CASES:
    cid = case["case_id"]
    if cid in ["C24", "C25", "C26", "C27", "C28", "C29", "C30"]:
        # Divergent
        VERDICTS_V1[cid] = {"A": "ALLOW", "B": "DENY", "C": "ESCALATE"}
    else:
        # Unanimous
        VERDICTS_V1[cid] = {"A": "ALLOW", "B": "ALLOW", "C": "ALLOW"}

# V2R1 Verdicts
VERDICTS_V2 = {}
for case in CASES:
    cid = case["case_id"]
    if cid == "C26":
        # Still divergent
        VERDICTS_V2[cid] = {"A": "ALLOW", "B": "DENY", "C": "ESCALATE"}
    elif cid in ["C24", "C25"]:
        VERDICTS_V2[cid] = {"A": "ALLOW", "B": "ALLOW", "C": "ALLOW"}
    elif cid in ["C27", "C28"]:
        VERDICTS_V2[cid] = {"A": "DENY", "B": "DENY", "C": "DENY"}
    elif cid in ["C29", "C30"]:
        VERDICTS_V2[cid] = {"A": "ESCALATE", "B": "ESCALATE", "C": "ESCALATE"}
    else:
        # Now unanimous control cases
        verdict = "ALLOW" if VERDICTS_V1[cid]["A"] == "ALLOW" else "DENY"
        VERDICTS_V2[cid] = {"A": verdict, "B": verdict, "C": verdict}

for sib in SIBLINGS:
    # sibling expected verdicts from patch: S01: ALLOW, S02: ALLOW, S03: ALLOW
    VERDICTS_V2[sib["case_id"]] = {"A": "ALLOW", "B": "ALLOW", "C": "ALLOW"}

RULINGS = [
    {"cluster_id": "K1", "ruling": "ALLOW", "note": "Allowed by manager"},
    {"cluster_id": "K2", "ruling": "DENY", "note": "Strict policy"},
    {"cluster_id": "K3", "ruling": "ESCALATE", "note": "Escalate to legal"}
]

CLUSTERS = [
    {
        "cluster_id": "K1",
        "label": "First Divergence Cluster",
        "loophole_type": "SCOPE_GAP",
        "case_ids": ["C24", "C25", "C26"],
        "involved_clauses": ["2.1", "2.2"],
        "summary": "Cases around clause 2 missing context.",
        "business_impact": "MEDIUM",
        "impact_reason": "Moderate volume"
    },
    {
        "cluster_id": "K2",
        "label": "Second Divergence Cluster",
        "loophole_type": "CONTRADICTORY",
        "case_ids": ["C27", "C28"],
        "involved_clauses": ["3.1", "4.1"],
        "summary": "Conflict between sections 3 and 4.",
        "business_impact": "HIGH",
        "impact_reason": "High cost"
    },
    {
        "cluster_id": "K3",
        "label": "Third Divergence Cluster",
        "loophole_type": "SILENT",
        "case_ids": ["C29", "C30"],
        "involved_clauses": ["5.1"],
        "summary": "Ambiguous final sale.",
        "business_impact": "LOW",
        "impact_reason": "Low volume"
    }
]

PATCH_PROPOSAL = {
    "edits": [
        {
            "edit_id": "E1",
            "action": "REPLACE",
            "clause_id": "2.1",
            "new_text": "Customers may return items within 30 days. No exceptions.",
            "addresses_clusters": ["K1"],
            "rationale": "Clarified 2.1"
        },
        {
            "edit_id": "E2",
            "action": "REPLACE",
            "clause_id": "3.1",
            "new_text": "Items purchased between November 15 and December 24 may be returned until January 31, unless final sale.",
            "addresses_clusters": ["K2"],
            "rationale": "Clarified 3.1"
        },
        {
            "edit_id": "E3",
            "action": "REPLACE",
            "clause_id": "5.1",
            "new_text": "Items marked Final Sale cannot be returned.",
            "addresses_clusters": ["K3"],
            "rationale": "Clarified 5.1"
        }
    ],
    "decision_table": [
        {"condition": "Item is old", "verdict": "DENY", "clause_refs": ["2.1"]}
    ],
    "sibling_cases": SIBLINGS,
    "sibling_expected": {"S01": "ALLOW", "S02": "ALLOW", "S03": "ALLOW"}
}

PARSER_ENRICHMENT = {
    "defined_terms": [],
    "ambiguity_hints": []
}
