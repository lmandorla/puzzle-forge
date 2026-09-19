import argparse
import asyncio

from pydantic import BaseModel

from forge.llm import call_structured, load_prompt
from forge.schema import CallInfo


class AdversarialOutput(BaseModel):
    blocking: bool
    concerns: str
    alternate_interpretation: str | None
    alternate_answer: float | None


async def review(statement: str) -> tuple[AdversarialOutput, CallInfo]:
    return await call_structured(
        "adversarial_verifier", load_prompt("adversarial_verifier"), f"Puzzle:\n\n{statement}", AdversarialOutput
    )


if __name__ == "__main__":
    from forge.agents._cli import BANANA, show

    parser = argparse.ArgumentParser()
    parser.add_argument("--statement", default=BANANA)
    args = parser.parse_args()
    show("adversarial verifier", *asyncio.run(review(args.statement)))
