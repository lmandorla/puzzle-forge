import secrets
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1
PIPELINE_VERSION = "1.0.0"

Status = Literal["valid", "graveyard"]
Difficulty = Literal["easy", "medium", "hard"]
RejectionReason = Literal[
    "proposer_malformed_output",
    "code_execution_error",
    "code_timeout",
    "code_output_unparseable",
    "verifier_disagreement",
    "adversarial_ambiguity",
    "pipeline_error",
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return f"prob_{utcnow():%Y%m%d}_{secrets.token_hex(3)}"


class CallInfo(BaseModel):
    """One API call: which model actually answered, what it cost, how long it took."""
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    duration_s: float = 0.0
    timestamp: datetime = Field(default_factory=utcnow)


class Rejection(BaseModel):
    stage: str
    reason: RejectionReason
    detail: str
    reasoning_answer: float | None = None
    code_answer: float | None = None


class Statement(BaseModel):
    original: str
    final: str | None = None


class Answer(BaseModel):
    value: float
    format: Literal["integer", "fraction", "decimal"]
    decimal_places: int | None = None
    tolerance: float = 0.0
    expression: str | None = None


class ProposerRecord(BaseModel):
    call: CallInfo
    seed: str
    reasoning: str
    believed_answer: float | None = None


class ReasoningRecord(BaseModel):
    call: CallInfo
    reasoning: str
    answer: float | None = None
    answer_expression: str | None = None


class ExecutionResult(BaseModel):
    success: bool
    answer: float | None = None
    stdout: str = ""
    stderr: str = ""
    return_code: int | None = None
    timed_out: bool = False
    memory_exceeded: bool = False
    runtime_s: float = 0.0
    peak_memory_mb: float = 0.0
    error_kind: Literal["timeout", "memory", "crash", "no_answer"] | None = None
    error: str | None = None


class CodeAttempt(BaseModel):
    call: CallInfo
    approach: str = ""
    script: str
    execution: ExecutionResult


class CodeRecord(BaseModel):
    attempts: list[CodeAttempt] = []
    answer: float | None = None


class AdversarialRecord(BaseModel):
    call: CallInfo
    blocking: bool
    concerns: str
    alternate_interpretation: str | None = None
    alternate_answer: float | None = None


class Hint(BaseModel):
    level: int
    text: str


class Illustration(BaseModel):
    call: CallInfo | None = None
    svg: str | None = None
    skipped: bool = False
    skip_reason: str | None = None


class Metadata(BaseModel):
    created_at: datetime = Field(default_factory=utcnow)
    finalized_at: datetime | None = None
    pipeline_version: str = PIPELINE_VERSION
    cost_usd: float = 0.0
    stage_costs_usd: dict[str, float] = {}


class Problem(BaseModel):
    id: str = Field(default_factory=new_id)
    schema_version: int = SCHEMA_VERSION
    title: str
    category: str
    difficulty: Difficulty
    status: Status
    rejection: Rejection | None = None
    statement: Statement
    answer: Answer | None = None
    proposer: ProposerRecord | None = None
    reasoning_verifier: ReasoningRecord | None = None
    code_verifier: CodeRecord | None = None
    adversarial: AdversarialRecord | None = None
    hints: list[Hint] = []
    illustration: Illustration | None = None
    metadata: Metadata = Field(default_factory=Metadata)

    def summary(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "difficulty": self.difficulty,
            "status": self.status,
            "reason": self.rejection.reason if self.rejection else None,
            "has_illustration": bool(self.illustration and self.illustration.svg),
            "cost_usd": self.metadata.cost_usd,
            "created_at": self.metadata.created_at.isoformat(),
        }
