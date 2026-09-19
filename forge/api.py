"""Local web server: REST API under /api, the web UI at /.

    python -m forge.api [--port 8765]        (serves http://127.0.0.1:8765)
"""

import asyncio
import secrets
from collections import Counter
from typing import Literal, get_args

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from forge import config
from forge.answers import answers_agree, display_answer, parse_number
from forge.llm import total_spend
from forge.pipeline import run_batch
from forge.schema import Problem, RejectionReason, utcnow
from forge.storage import ProblemStore

WEB_DIR = config.ROOT / "web"


class GenerateRequest(BaseModel):
    count: int = Field(ge=1)
    categories: list[str] | None = None
    difficulties: list[Literal["easy", "medium", "hard"]] | None = None
    concurrency: int | None = Field(default=None, ge=1, le=6)


class AnswerRequest(BaseModel):
    value: str


def public_view(p: Problem) -> dict:
    """What a solver may see before answering: no answer, solutions or verifier output."""
    return {
        "id": p.id, "title": p.title, "category": p.category, "difficulty": p.difficulty, "status": p.status,
        "statement": {"final": p.statement.final or p.statement.original, "original": p.statement.original},
        "answer_format": {"format": p.answer.format, "decimal_places": p.answer.decimal_places},
        "hints": [h.model_dump() for h in p.hints],
        "illustration_svg": p.illustration.svg if p.illustration else None,
        "created_at": p.metadata.created_at.isoformat(),
    }


def answer_reveal(p: Problem) -> dict:
    """Everything shown after a solver submits: the answer key, Fable's solution and the checking program."""
    a, r = p.answer, p.reasoning_verifier
    last_run = p.code_verifier.attempts[-1] if p.code_verifier.attempts else None
    return {
        "answer": {"display": display_answer(a.value, a.format, a.decimal_places), "value": a.value,
                   "expression": a.expression, "format": a.format, "tolerance": a.tolerance},
        "fable": {"solution": r.reasoning, "answer": r.answer, "expression": r.answer_expression, "model": r.call.model},
        "code": {"approach": last_run.approach, "script": last_run.script,
                 "stdout": last_run.execution.stdout, "answer": p.code_verifier.answer} if last_run else None,
    }


def config_payload() -> dict:
    cats = config.categories()["categories"]
    batch = config.pipeline()["batch"]
    return {
        "categories": [{"id": c["id"], "name": c["name"], "description": c["description"]} for c in cats],
        "difficulties": ["easy", "medium", "hard"],
        "reasons": list(get_args(RejectionReason)),
        "batch": {"default_count": batch["default_count"], "max_count": batch["max_problems_per_batch"],
                  "default_concurrency": batch["max_concurrent_problems"]},
    }


def create_app(store: ProblemStore | None = None) -> FastAPI:
    store = store or ProblemStore()
    store.reindex()
    app = FastAPI(title="Puzzle Forge")
    batches: dict[str, dict] = {}
    tasks: set[asyncio.Task] = set()

    @app.get("/api/config")
    def get_config():
        return config_payload()

    @app.post("/api/generate")
    async def generate(req: GenerateRequest):
        max_count = config.pipeline()["batch"]["max_problems_per_batch"]
        if req.count > max_count:
            raise HTTPException(400, f"At most {max_count} puzzles per batch.")
        known = {c["id"] for c in config.categories()["categories"]}
        unknown = set(req.categories or []) - known
        if unknown:
            raise HTTPException(400, f"Unknown categories: {', '.join(sorted(unknown))}")

        batch_id = f"batch_{utcnow():%H%M%S}_{secrets.token_hex(2)}"
        batch = {"id": batch_id, "requested": req.count, "created_at": utcnow().isoformat(),
                 "finished": False, "error": None, "items": {}}
        batches[batch_id] = batch

        def on_progress(event: dict) -> None:
            if "index" in event:
                item = batch["items"].setdefault(event["index"], {"index": event["index"]})
                item.update({k: v for k, v in event.items() if k != "index"})

        async def run():
            try:
                await run_batch(req.count, store, req.categories, req.difficulties, req.concurrency, on_progress)
            except Exception as e:
                batch["error"] = repr(e)[:500]
            finally:
                batch["finished"] = True

        task = asyncio.create_task(run())
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return {"batch_id": batch_id}

    def batch_view(batch: dict) -> dict:
        items = [batch["items"][i] for i in sorted(batch["items"])]
        done = [i for i in items if i.get("stage") == "done"]
        return {
            **{k: v for k, v in batch.items() if k != "items"}, "items": items,
            "completed": len(done), "valid": sum(i["status"] == "valid" for i in done),
            "graveyard": sum(i["status"] == "graveyard" for i in done),
            "cost_usd": round(sum(i.get("cost_usd", 0) for i in done), 4),
        }

    @app.get("/api/batches")
    def list_batches():
        return [batch_view(b) for b in sorted(batches.values(), key=lambda b: b["created_at"], reverse=True)]

    @app.get("/api/batches/{batch_id}")
    def get_batch(batch_id: str):
        if batch_id not in batches:
            raise HTTPException(404, "Unknown batch")
        return batch_view(batches[batch_id])

    @app.get("/api/problems")
    def list_problems(status: str | None = None, category: str | None = None,
                      difficulty: str | None = None, reason: str | None = None):
        return store.list(status=status, category=category, difficulty=difficulty, reason=reason)

    def load_or_404(problem_id: str) -> Problem:
        problem = store.load(problem_id)
        if problem is None:
            raise HTTPException(404, "Unknown puzzle")
        return problem

    @app.get("/api/problems/{problem_id}")
    def get_problem(problem_id: str):
        p = load_or_404(problem_id)
        return public_view(p) if p.status == "valid" else p.model_dump(mode="json")

    @app.post("/api/problems/{problem_id}/answer")
    def check_answer(problem_id: str, req: AnswerRequest):
        p = load_or_404(problem_id)
        if p.status != "valid":
            raise HTTPException(400, "This puzzle is in the graveyard and has no answer key.")
        value = parse_number(req.value)
        if value is None:
            raise HTTPException(400, "Please enter a number, like 42, 3/4 or 0.125.")
        return {
            "correct": answers_agree(value, p.answer.value, p.answer.tolerance),
            "submitted": req.value.strip(),
            **answer_reveal(p),
        }

    @app.get("/api/stats")
    def stats():
        rows = store.list()
        return {
            "total": len(rows),
            "by_status": Counter(r["status"] for r in rows),
            "by_category": Counter(r["category"] for r in rows),
            "by_reason": Counter(r["reason"] for r in rows if r["reason"]),
            "puzzles_cost_usd": round(sum(r.get("cost_usd", 0) for r in rows), 4),
            "total_spend_usd": round(total_spend(), 4),
        }

    WEB_DIR.mkdir(exist_ok=True)
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


if __name__ == "__main__":
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port)
