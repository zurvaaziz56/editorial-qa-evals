"""Entry schema from docs/EVAL_SPEC.md section 3.1."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CheckResult = Literal["pass", "fail", "na"]
CheckId = Literal[
    "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "C11", "C12", "C13"
]
JudgmentId = Literal["J1", "J2", "J3", "J4", "J5", "J6", "J7"]


class SchemaModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Expert(SchemaModel):
    credential: str
    specialism: str


class Brief(SchemaModel):
    tips: list[str] = Field(max_length=7)
    domain: str | None = None
    noun_category: str | None = None
    headline_template: str | None = None
    voice_tier: Literal["clinical", "accessible_precise", "lifestyle"] | None = None
    hook: str
    tone: str
    expert: Expert


class HumanLabels(SchemaModel):
    checks: dict[CheckId, CheckResult]
    judgment: dict[JudgmentId, CheckResult]
    routing: Literal["escalate", "fix_direct", "none"]
    verdict: Literal["READY", "REVISE", "MAJOR"]
    notes: str
    labeled_at: datetime
    labeler: Literal["r1", "r2"]
    pass_number: int = Field(ge=1)


class Entry(SchemaModel):
    id: str = Field(pattern=r"^(syn|anon)-[0-9]{4,}$")
    source: Literal["synthetic", "anonymized"]
    piece_type: Literal["simple_pitch_list", "cpr", "qa"]
    region: Literal["UK", "US"]
    task_name: str
    brief: Brief
    approved_labels: list[str]
    body: str
    questions: list[str] = Field(default_factory=list)
    answers: list[str] = Field(default_factory=list)
    injected_faults: list[str] | None = None
    human: HumanLabels | None = None
