"""Helpers for running a single agent from the command line during development."""

import json

from pydantic import BaseModel

from forge.schema import CallInfo

BANANA = "How many distinct arrangements of the letters of the word BANANA are there? Give your answer as an integer."


def show(title: str, output, call: CallInfo) -> None:
    data = output.model_dump(mode="json") if isinstance(output, BaseModel) else output
    print(f"== {title} ==")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    print(
        f"-- served by {call.model}: {call.input_tokens} in / {call.output_tokens} out tokens, "
        f"${call.cost_usd:.4f}, {call.duration_s}s"
    )
