"""Pipeline and validity logic with every agent faked - no API calls."""

import pytest

from forge import pipeline
from forge.agents.adversarial import AdversarialOutput
from forge.agents.proposer import ProposerOutput
from forge.agents.reasoning_verifier import ReasoningOutput
from forge.agents.rewriter import RewriteOutput
from forge.llm import LLMError
from forge.schema import CallInfo, CodeAttempt, CodeRecord, ExecutionResult, Hint, Illustration
from forge.storage import ProblemStore


def call(cost=0.01, model="fake-model"):
    return CallInfo(model=model, cost_usd=cost)


def code_record(answer, error_kind=None):
    run = ExecutionResult(success=answer is not None, answer=answer, error_kind=error_kind,
                          error=None if answer is not None else f"{error_kind} failure")
    return CodeRecord(attempts=[CodeAttempt(call=call(), script="print('ANSWER: 1')", execution=run)], answer=answer)


@pytest.fixture
def fakes(monkeypatch):
    """Default fakes produce a valid puzzle; tests override individual agents."""
    state = {"proposer_statements": []}

    async def propose(category, difficulty, avoid_titles=(), seed=None):
        return ProposerOutput(title="Fake", statement="How many?", answer_format="fraction", decimal_places=None,
                              answer=0.75, answer_expression="3/4", solution="because"), call(), "seed"

    async def solve(statement):
        state["proposer_statements"].append(statement)
        return ReasoningOutput(solution="Fable's solution", answer=0.75, answer_expression="3/4"), call()

    async def verify(statement):
        return code_record(0.75)

    async def review(statement):
        return AdversarialOutput(blocking=False, concerns="none", alternate_interpretation=None,
                                 alternate_answer=None), call()

    async def rewrite(statement):
        return RewriteOutput(title="Fun Title", statement="A fun story. How many?"), call(0.001)

    async def illustrate(statement):
        return Illustration(call=call(0.002), svg="<svg/>")

    async def generate(statement, solution, answer):
        return [Hint(level=1, text="h1"), Hint(level=2, text="h2"), Hint(level=3, text="h3")], call(0.001)

    monkeypatch.setattr(pipeline.proposer, "propose", propose)
    monkeypatch.setattr(pipeline.reasoning_verifier, "solve", solve)
    monkeypatch.setattr(pipeline.code_verifier, "verify", verify)
    monkeypatch.setattr(pipeline.adversarial, "review", review)
    monkeypatch.setattr(pipeline.rewriter, "rewrite", rewrite)
    monkeypatch.setattr(pipeline.illustrator, "illustrate", illustrate)
    monkeypatch.setattr(pipeline.hints, "generate", generate)
    return state


async def test_valid_puzzle(fakes):
    p = await pipeline.run_problem("probability", "easy")
    assert p.status == "valid" and p.rejection is None
    assert p.answer.value == 0.75 and p.answer.format == "fraction" and p.answer.expression == "3/4"
    assert p.title == "Fun Title" and p.statement.final == "A fun story. How many?"
    assert len(p.hints) == 3 and p.illustration.svg == "<svg/>"
    assert p.metadata.cost_usd == pytest.approx(0.01 * 4 + 0.001 + 0.002 + 0.001)
    assert fakes["proposer_statements"] == ["How many?"]  # verifier saw only the statement


async def test_disagreement_goes_to_graveyard(fakes, monkeypatch):
    async def verify(statement):
        return code_record(0.8)
    monkeypatch.setattr(pipeline.code_verifier, "verify", verify)
    p = await pipeline.run_problem("probability", "easy")
    assert p.status == "graveyard" and p.rejection.reason == "verifier_disagreement"
    assert p.rejection.reasoning_answer == 0.75 and p.rejection.code_answer == 0.8
    assert p.hints == [] and p.statement.final is None


async def test_adversarial_block(fakes, monkeypatch):
    async def review(statement):
        return AdversarialOutput(blocking=True, concerns="c", alternate_interpretation="order matters",
                                 alternate_answer=1.5), call()
    monkeypatch.setattr(pipeline.adversarial, "review", review)
    p = await pipeline.run_problem("probability", "easy")
    assert p.rejection.reason == "adversarial_ambiguity" and "order matters" in p.rejection.detail


@pytest.mark.parametrize("kind,reason", [
    ("timeout", "code_timeout"), ("no_answer", "code_output_unparseable"),
    ("crash", "code_execution_error"), ("memory", "code_execution_error"),
])
async def test_code_failures(fakes, monkeypatch, kind, reason):
    async def verify(statement):
        return code_record(None, kind)
    monkeypatch.setattr(pipeline.code_verifier, "verify", verify)
    p = await pipeline.run_problem("probability", "easy")
    assert p.rejection.reason == reason


async def test_proposer_malformed(fakes, monkeypatch):
    async def propose(*args, **kwargs):
        raise LLMError("malformed", "bad json", call(0.05))
    monkeypatch.setattr(pipeline.proposer, "propose", propose)
    p = await pipeline.run_problem("probability", "easy")
    assert p.rejection.reason == "proposer_malformed_output" and p.metadata.cost_usd == pytest.approx(0.05)


async def test_verifier_refusal_is_pipeline_error_and_costs_are_kept(fakes, monkeypatch):
    async def solve(statement):
        raise LLMError("refusal", "declined", call(0.02))
    monkeypatch.setattr(pipeline.reasoning_verifier, "solve", solve)
    p = await pipeline.run_problem("probability", "easy")
    assert p.rejection.reason == "pipeline_error" and "refusal" in p.rejection.detail
    assert p.metadata.stage_costs_usd["reasoning_verifier"] == pytest.approx(0.02)


async def test_presentation_failures_do_not_reject(fakes, monkeypatch):
    async def fail(*args, **kwargs):
        raise LLMError("api", "HTTP 529", call(0.0))
    monkeypatch.setattr(pipeline.rewriter, "rewrite", fail)
    monkeypatch.setattr(pipeline.illustrator, "illustrate", fail)
    monkeypatch.setattr(pipeline.hints, "generate", fail)
    p = await pipeline.run_problem("probability", "easy")
    assert p.status == "valid"
    assert p.statement.final == "How many?" and p.title == "Fake"
    assert p.illustration.skipped and p.hints == []


async def test_batch_saves_everything_and_survives_crashes(fakes, monkeypatch, tmp_path):
    calls = {"n": 0}
    original = pipeline.run_problem

    async def flaky(category, difficulty, avoid_titles=(), progress=None):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("unexpected")
        return await original(category, difficulty, avoid_titles, progress)
    monkeypatch.setattr(pipeline, "run_problem", flaky)

    events = []
    store = ProblemStore(tmp_path)
    problems = await pipeline.run_batch(3, store, concurrency=2, progress=events.append)
    assert len(problems) == 3 and len(store.list()) == 3
    assert sum(p.rejection is not None and p.rejection.reason == "pipeline_error" for p in problems) == 1
    assert sum(e["stage"] == "done" for e in events) == 3


def test_plan_batch_spreads_evenly():
    specs = pipeline.plan_batch(6, ["geometry", "probability"], ["easy", "medium", "hard"])
    assert len(set(specs)) == 6
