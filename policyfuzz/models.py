"""Pydantic contracts for all PolicyFuzz data models (§6)."""

from typing import Literal
from pydantic import BaseModel, Field, field_validator

Verdict = Literal["ALLOW", "DENY", "ESCALATE"]
RulingValue = Literal["ALLOW", "DENY", "ESCALATE", "SKIPPED"]
BoundaryType = Literal["threshold", "conflict", "silent", "definition", "control"]
LoopholeType = Literal["SILENT", "CONTRADICTORY", "SCOPE_GAP"]
Impact = Literal["HIGH", "MEDIUM", "LOW"]

class Clause(BaseModel):
    clause_id: str            # "2.1"
    section_id: str           # "2"
    section_title: str
    text: str                 # exact source text (verified to be a substring of the policy)

class DefinedTerm(BaseModel):
    term: str
    definition: str
    clause_id: str

class AmbiguityHint(BaseModel):
    clause_id: str
    hint: str = Field(max_length=200)

class ParserEnrichment(BaseModel):          # LLM output of ClauseParser
    defined_terms: list[DefinedTerm] = []
    ambiguity_hints: list[AmbiguityHint] = []

class Case(BaseModel):
    case_id: str                             # "C01".."C36" or "S01".. for siblings
    title: str = Field(min_length=5, max_length=100)
    narrative: str = Field(min_length=40, max_length=700)
    target_clauses: list[str] = Field(min_length=1)
    boundary_type: BoundaryType
    expected_verdict: Verdict | None = None

class CaseSet(BaseModel):
    cases: list[Case]

class InterpreterVerdict(BaseModel):
    case_id: str
    verdict: Verdict
    cited_clauses: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=10, max_length=400)

class Cluster(BaseModel):
    cluster_id: str                          # "K1"
    label: str = Field(max_length=80)
    loophole_type: LoopholeType
    case_ids: list[str] = Field(min_length=1)
    involved_clauses: list[str] = Field(min_length=1)
    summary: str = Field(max_length=400)
    business_impact: Impact
    impact_reason: str = Field(max_length=200)

class ClusterSet(BaseModel):
    clusters: list[Cluster]

class Ruling(BaseModel):                     # human input, not LLM
    cluster_id: str
    ruling: RulingValue
    note: str = Field(default="", max_length=500)

class ClauseEdit(BaseModel):
    edit_id: str                             # "E1"
    action: Literal["REPLACE", "ADD_AFTER"]
    clause_id: str                           # REPLACE: existing id. ADD_AFTER: the NEW id
    anchor_clause_id: str | None = None      # ADD_AFTER only: existing id to insert after
    new_text: str = Field(min_length=10, max_length=600)
    alt_text: str | None = Field(default=None, max_length=600)  # Alternative rewrite (Option 2)
    addresses_clusters: list[str] = Field(min_length=1)
    rationale: str = Field(max_length=300)

class DecisionRow(BaseModel):
    condition: str = Field(max_length=200)
    verdict: Verdict
    clause_refs: list[str]

class PatchProposal(BaseModel):
    edits: list[ClauseEdit] = Field(max_length=6)
    decision_table: list[DecisionRow]
    sibling_cases: list[Case]                # ids "S01".. ; one per ruled cluster
    sibling_expected: dict[str, Verdict]     # case_id -> expected verdict (from rulings)

class VerificationResult(BaseModel):
    round: int
    before_divergent: int
    before_total: int
    after_divergent: int
    after_total: int
    sibling_divergent: int
    sibling_total: int
    conformance_hits: int
    conformance_total: int
    new_divergent_case_ids: list[str]        # unanimous in v1, not unanimous in v2
    flipped_case_ids: list[str]              # unanimous in both but verdict changed (non-adjudicated)
    per_cluster: dict[str, dict]             # {"K1": {"before": 3, "after": 1}}
    outcome: Literal["IMPROVED", "NO_IMPROVEMENT", "REGRESSED"]

class RunStatus:
    CREATED = "CREATED"
    PARSED = "PARSED"
    CASES_READY = "CASES_READY"
    PANEL_V1_DONE = "PANEL_V1_DONE"
    ANALYZED = "ANALYZED"
    AWAITING_RULINGS = "AWAITING_RULINGS"
    RULED = "RULED"
    PATCH_PROPOSED = "PATCH_PROPOSED"
    AWAITING_EDIT_DECISIONS = "AWAITING_EDIT_DECISIONS"
    PATCH_APPLIED = "PATCH_APPLIED"
    VERIFIED = "VERIFIED"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    COMPLETE_NO_DIVERGENCE = "COMPLETE_NO_DIVERGENCE"
    COMPLETE_NO_RULINGS = "COMPLETE_NO_RULINGS"
    COMPLETE_IMPROVED = "COMPLETE_IMPROVED"
    COMPLETE_NO_IMPROVEMENT = "COMPLETE_NO_IMPROVEMENT"
    COMPLETE_NO_APPROVED_EDITS = "COMPLETE_NO_APPROVED_EDITS"
