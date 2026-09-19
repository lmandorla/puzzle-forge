import time

import pytest
from fastapi.testclient import TestClient

from forge import api
from forge.schema import (
    Answer, CallInfo, CodeAttempt, CodeRecord, ExecutionResult, Hint, Illustration, Problem, ReasoningRecord,
    Rejection, Statement,
)
from forge.storage import ProblemStore


def valid_problem() -> Problem:
    call = CallInfo(model="claude-fable-5-1")
    return Problem(
        title="Three Quarters", category="probability", difficulty="easy", status="valid",
        statement=Statement(original="Precise version?", final="Fun version?"),
        answer=Answer(value=0.75, format="fraction", expression="3/4"),
        reasoning_verifier=ReasoningRecord(call=call, reasoning="Fable's full solution", answer=0.75,
                                           answer_expression="3/4"),
        code_verifier=CodeRecord(answer=0.75, attempts=[CodeAttempt(
            call=call, approach="enumerate", script="print('ANSWER: 3/4')",
            execution=ExecutionResult(success=True, answer=0.75, stdout="ANSWER: 3/4\n"))]),
        hints=[Hint(level=1, text="h1"), Hint(level=2, text="h2"), Hint(level=3, text="h3")],
        illustration=Illustration(svg="<svg xmlns='http://www.w3.org/2000/svg'/>"),
    )


def graveyard_problem() -> Problem:
    return Problem(
        title="Ambiguous", category="geometry", difficulty="hard", status="graveyard",
        statement=Statement(original="Which way?"),
        rejection=Rejection(stage="adversarial_verifier", reason="adversarial_ambiguity", detail="two readings"),
    )


@pytest.fixture
def setup(tmp_path):
    store = ProblemStore(tmp_path)
    good, bad = valid_problem(), graveyard_problem()
    store.save(good)
    store.save(bad)
    with TestClient(api.create_app(store)) as client:
        yield client, store, good, bad


def test_config(setup):
    client, *_ = setup
    body = client.get("/api/config").json()
    assert len(body["categories"]) == 8 and "adversarial_ambiguity" in body["reasons"]


def test_lists_and_filters(setup):
    client, _, good, bad = setup
    assert [r["id"] for r in client.get("/api/problems?status=valid").json()] == [good.id]
    assert [r["id"] for r in client.get("/api/problems?status=graveyard&reason=adversarial_ambiguity").json()] == [bad.id]
    assert client.get("/api/problems?category=number_theory").json() == []


def test_valid_detail_hides_the_answer(setup):
    client, _, good, _ = setup
    body = client.get(f"/api/problems/{good.id}").json()
    assert body["statement"]["final"] == "Fun version?" and len(body["hints"]) == 3
    text = str(body)
    assert "0.75" not in text and "3/4" not in text and "Fable's full solution" not in text


def test_graveyard_detail_is_complete(setup):
    client, _, _, bad = setup
    body = client.get(f"/api/problems/{bad.id}").json()
    assert body["rejection"]["reason"] == "adversarial_ambiguity"


@pytest.mark.parametrize("value,correct", [("3/4", True), ("0.75", True), (" 6/8 ", True), ("0.7", False), ("1", False)])
def test_answer_check(setup, value, correct):
    client, _, good, _ = setup
    body = client.post(f"/api/problems/{good.id}/answer", json={"value": value}).json()
    assert body["correct"] is correct
    assert body["answer"]["display"] == "3/4" and body["fable"]["solution"] == "Fable's full solution"
    assert body["code"]["script"].startswith("print")


def test_answer_errors(setup):
    client, _, good, bad = setup
    assert client.post(f"/api/problems/{good.id}/answer", json={"value": "seventy"}).status_code == 400
    assert client.post(f"/api/problems/{bad.id}/answer", json={"value": "1"}).status_code == 400
    assert client.post("/api/problems/prob_missing/answer", json={"value": "1"}).status_code == 404


def test_generate_runs_in_background(setup, monkeypatch):
    client, store, *_ = setup

    async def fake_run_batch(count, store_, categories, difficulties, concurrency, progress):
        p = valid_problem()
        progress({"index": 0, "stage": "proposing", "category": "probability", "difficulty": "easy"})
        store_.save(p)
        progress({"index": 0, "stage": "done", "status": "valid", "problem_id": p.id, "title": p.title,
                  "cost_usd": 0.5, "reason": None})
        return [p]

    monkeypatch.setattr(api, "run_batch", fake_run_batch)
    batch_id = client.post("/api/generate", json={"count": 1}).json()["batch_id"]
    for _ in range(50):
        batch = client.get(f"/api/batches/{batch_id}").json()
        if batch["finished"]:
            break
        time.sleep(0.05)
    assert batch["finished"] and batch["valid"] == 1 and batch["cost_usd"] == 0.5
    assert len(client.get("/api/problems?status=valid").json()) == 2


def test_generate_validation(setup):
    client, *_ = setup
    assert client.post("/api/generate", json={"count": 999}).status_code == 400
    assert client.post("/api/generate", json={"count": 1, "categories": ["astrology"]}).status_code == 400
    assert client.post("/api/generate", json={"count": 0}).status_code == 422


def test_stats(setup):
    client, *_ = setup
    body = client.get("/api/stats").json()
    assert body["total"] == 2 and body["by_status"] == {"valid": 1, "graveyard": 1}
