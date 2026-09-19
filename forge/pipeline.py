"""Run puzzles through propose -> verify (x3, parallel) -> decide -> rewrite -> illustrate + hints."""

import asyncio
import itertools
import random
from collections.abc import Awaitable, Callable

from forge import config
from forge.agents import adversarial, code_verifier, hints, illustrator, proposer, reasoning_verifier, rewriter
from forge.llm import LLMError
from forge.schema import (
    AdversarialRecord, CallInfo, CodeRecord, Illustration, Problem, ProposerRecord, ReasoningRecord,
    Rejection, Statement, utcnow,
)
from forge.storage import ProblemStore
from forge.validity import decide

Progress = Callable[[dict], Awaitable[None] | None]


async def _emit(progress: Progress | None, **event) -> None:
    if progress:
        result = progress(event)
        if asyncio.iscoroutine(result):
            await result


def _charge(problem: Problem, stage: str, call: CallInfo | None) -> None:
    if call:
        costs = problem.metadata.stage_costs_usd
        costs[stage] = round(costs.get(stage, 0.0) + call.cost_usd, 6)
        problem.metadata.cost_usd = round(sum(costs.values()), 6)


def _finish(problem: Problem, rejection: Rejection | None = None) -> Problem:
    if rejection:
        problem.status, problem.rejection = "graveyard", rejection
    problem.metadata.finalized_at = utcnow()
    return problem


def _llm_rejection(stage: str, error: Exception) -> Rejection:
    if isinstance(error, LLMError) and error.kind == "malformed" and stage == "proposer":
        reason = "proposer_malformed_output"
    else:
        reason = "pipeline_error"
    kind = getattr(error, "kind", type(error).__name__)
    return Rejection(stage=stage, reason=reason, detail=f"{kind}: {error}")


def _format_answer(problem: Problem) -> str:
    a = problem.answer
    if a.expression:
        return f"{a.expression} (= {a.value:g})"
    return f"{a.value:g}"


async def run_problem(
    category: str, difficulty: str, avoid_titles: list[str] = (), progress: Progress | None = None
) -> Problem:
    await _emit(progress, stage="proposing")
    try:
        prop, call, seed = await proposer.propose(category, difficulty, list(avoid_titles))
    except LLMError as e:
        problem = Problem(title="(no puzzle)", category=category, difficulty=difficulty, status="graveyard",
                          statement=Statement(original=""))
        _charge(problem, "proposer", e.call)
        return _finish(problem, _llm_rejection("proposer", e))

    problem = Problem(
        title=prop.title, category=category, difficulty=difficulty, status="graveyard",
        statement=Statement(original=prop.statement),
        proposer=ProposerRecord(call=call, seed=seed, reasoning=prop.solution, believed_answer=prop.answer),
    )
    _charge(problem, "proposer", call)
    statement = prop.statement

    # The verifiers see only the statement, never the proposer's answer or solution.
    await _emit(progress, stage="verifying", title=problem.title)
    results = await asyncio.gather(
        reasoning_verifier.solve(statement), code_verifier.verify(statement), adversarial.review(statement),
        return_exceptions=True,
    )
    for stage, result in zip(("reasoning_verifier", "code_verifier", "adversarial_verifier"), results):
        if isinstance(result, BaseException):
            _charge(problem, stage, getattr(result, "call", None))
            partial = getattr(result, "partial", None)
            if isinstance(partial, CodeRecord):
                problem.code_verifier = partial
                for attempt in partial.attempts:
                    _charge(problem, stage, attempt.call)
    (reasoning_res, code_res, adversarial_res) = results

    if not isinstance(reasoning_res, BaseException):
        out, call = reasoning_res
        problem.reasoning_verifier = ReasoningRecord(
            call=call, reasoning=out.solution, answer=out.answer, answer_expression=out.answer_expression)
        _charge(problem, "reasoning_verifier", call)
    if not isinstance(code_res, BaseException):
        problem.code_verifier = code_res
        for attempt in code_res.attempts:
            _charge(problem, "code_verifier", attempt.call)
    if not isinstance(adversarial_res, BaseException):
        out, call = adversarial_res
        problem.adversarial = AdversarialRecord(call=call, **out.model_dump())
        _charge(problem, "adversarial_verifier", call)

    for stage, result in zip(("reasoning_verifier", "code_verifier", "adversarial_verifier"), results):
        if isinstance(result, BaseException):
            return _finish(problem, _llm_rejection(stage, result))

    answer, rejection = decide(
        problem.reasoning_verifier, problem.code_verifier, problem.adversarial, prop.answer_format, prop.decimal_places)
    if rejection:
        return _finish(problem, rejection)
    problem.status, problem.answer = "valid", answer

    # Presentation stages: a failure here degrades the puzzle but never rejects it.
    await _emit(progress, stage="polishing", title=problem.title)
    try:
        out, call = await rewriter.rewrite(statement)
        problem.title, problem.statement.final = out.title, out.statement
        _charge(problem, "rewriter", call)
    except LLMError as e:
        problem.statement.final = statement
        _charge(problem, "rewriter", e.call)

    ill_res, hints_res = await asyncio.gather(
        illustrator.illustrate(problem.statement.final),
        hints.generate(problem.statement.final, problem.reasoning_verifier.reasoning, _format_answer(problem)),
        return_exceptions=True,
    )
    if isinstance(ill_res, BaseException):
        problem.illustration = Illustration(skipped=True, skip_reason=f"illustrator failed: {ill_res}")
        _charge(problem, "illustrator", getattr(ill_res, "call", None))
    else:
        problem.illustration = ill_res
        _charge(problem, "illustrator", ill_res.call)
    if isinstance(hints_res, BaseException):
        _charge(problem, "hints", getattr(hints_res, "call", None))
    else:
        problem.hints, call = hints_res
        _charge(problem, "hints", call)
    return _finish(problem)


def plan_batch(count: int, categories: list[str] | None, difficulties: list[str] | None) -> list[tuple[str, str]]:
    """Spread a batch evenly over the requested categories and difficulties."""
    cats = categories or [c["id"] for c in config.categories()["categories"]]
    diffs = difficulties or ["easy", "medium", "hard"]
    combos = list(itertools.product(cats, diffs))
    random.shuffle(combos)
    return [combos[i % len(combos)] for i in range(count)]


async def run_batch(
    count: int,
    store: ProblemStore,
    categories: list[str] | None = None,
    difficulties: list[str] | None = None,
    concurrency: int | None = None,
    progress: Progress | None = None,
) -> list[Problem]:
    batch_cfg = config.pipeline()["batch"]
    count = max(1, min(count, batch_cfg["max_problems_per_batch"]))
    semaphore = asyncio.Semaphore(concurrency or batch_cfg["max_concurrent_problems"])
    avoid = [row["title"] for row in store.list()[:40] if row["title"] != "(no puzzle)"]

    async def one(index: int, category: str, difficulty: str) -> Problem:
        async def item_progress(event: dict) -> None:
            await _emit(progress, index=index, category=category, difficulty=difficulty, **event)

        async with semaphore:
            try:
                problem = await run_problem(category, difficulty, avoid, item_progress)
            except Exception as e:  # never let one puzzle take down the batch
                problem = Problem(title="(pipeline error)", category=category, difficulty=difficulty,
                                  status="graveyard", statement=Statement(original=""))
                _finish(problem, Rejection(stage="pipeline", reason="pipeline_error", detail=repr(e)[:500]))
            store.save(problem)
            avoid.append(problem.title)
            await _emit(item_progress, stage="done", problem_id=problem.id, title=problem.title,
                        status=problem.status, reason=problem.rejection.reason if problem.rejection else None,
                        cost_usd=problem.metadata.cost_usd)
            return problem

    await _emit(progress, stage="batch_started", count=count)
    specs = plan_batch(count, categories, difficulties)
    return await asyncio.gather(*(one(i, c, d) for i, (c, d) in enumerate(specs)))
