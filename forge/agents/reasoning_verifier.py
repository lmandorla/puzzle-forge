import argparse
import asyncio

from pydantic import BaseModel

from forge.llm import call_structured, load_prompt
from forge.schema import CallInfo


class ReasoningOutput(BaseModel):
    solution: str
    answer: float
    answer_expression: str


async def solve(statement: str) -> tuple[ReasoningOutput, CallInfo]:
    return await call_structured(
        "reasoning_verifier", load_prompt("reasoning_verifier"), f"Puzzle:\n\n{statement}", ReasoningOutput
    )


if __name__ == "__main__":
    from forge.agents._cli import BANANA, show

    parser = argparse.ArgumentParser()
    parser.add_argument("--statement", default=BANANA)
    args = parser.parse_args()
    show("reasoning verifier", *asyncio.run(solve(args.statement)))
