import argparse
import asyncio
from typing import Annotated

from pydantic import BaseModel, Field

from forge.llm import call_structured, load_prompt
from forge.schema import CallInfo, Hint


class HintsOutput(BaseModel):
    hints: Annotated[list[str], Field(min_length=3, max_length=4)]


async def generate(statement: str, solution: str, answer: str) -> tuple[list[Hint], CallInfo]:
    user = (
        f"Puzzle (as the reader sees it):\n\n{statement}\n\n"
        f"Verified solution (for your eyes only):\n\n{solution}\n\n"
        f"Verified answer (never reveal it): {answer}"
    )
    output, call = await call_structured("hints", load_prompt("hints"), user, HintsOutput)
    return [Hint(level=i, text=text) for i, text in enumerate(output.hints, 1)], call


if __name__ == "__main__":
    from forge.agents._cli import BANANA, show

    parser = argparse.ArgumentParser()
    parser.add_argument("--statement", default=BANANA)
    parser.add_argument(
        "--solution",
        default="BANANA has 6 letters: A x3, N x2, B x1. Arrangements = 6!/(3!2!1!) = 720/12 = 60.",
    )
    parser.add_argument("--answer", default="60")
    args = parser.parse_args()
    hints, call = asyncio.run(generate(args.statement, args.solution, args.answer))
    show("hints", [h.model_dump() for h in hints], call)
