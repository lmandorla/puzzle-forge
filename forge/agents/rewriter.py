import argparse
import asyncio

from pydantic import BaseModel

from forge.llm import call_structured, load_prompt
from forge.schema import CallInfo


class RewriteOutput(BaseModel):
    title: str
    statement: str


async def rewrite(statement: str) -> tuple[RewriteOutput, CallInfo]:
    return await call_structured("rewriter", load_prompt("rewriter"), f"Original puzzle:\n\n{statement}", RewriteOutput)


if __name__ == "__main__":
    from forge.agents._cli import BANANA, show

    parser = argparse.ArgumentParser()
    parser.add_argument("--statement", default=BANANA)
    args = parser.parse_args()
    show("rewriter", *asyncio.run(rewrite(args.statement)))
