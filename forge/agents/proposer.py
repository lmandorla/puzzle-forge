import argparse
import asyncio
from typing import Literal

from pydantic import BaseModel

from forge import config
from forge.llm import call_structured, load_prompt
from forge.schema import CallInfo
from forge.seeds import random_seed


class ProposerOutput(BaseModel):
    title: str
    statement: str
    answer_format: Literal["integer", "fraction", "decimal"]
    decimal_places: int | None
    answer: float
    answer_expression: str
    solution: str


def category_info(category_id: str) -> dict:
    for cat in config.categories()["categories"]:
        if cat["id"] == category_id:
            return cat
    raise ValueError(f"unknown category {category_id!r}")


async def propose(
    category: str, difficulty: str, avoid_titles: list[str] = (), seed: str | None = None
) -> tuple[ProposerOutput, CallInfo, str]:
    cat = category_info(category)
    scale = config.categories()["global_difficulty"]
    seed = seed or random_seed()
    user = (
        f"Category: {cat['name']} - {cat['description']}\n"
        f"Difficulty: {difficulty}\n"
        f"General difficulty scale: easy = {scale['easy']} medium = {scale['medium']} hard = {scale['hard']}\n"
        f"For this category, {difficulty} means: {cat['difficulty'][difficulty]}\n"
        f"Inspiration seed: {seed}\n"
        f"Titles to avoid (already published): {'; '.join(avoid_titles) or 'none yet'}"
    )
    output, call = await call_structured("proposer", load_prompt("proposer"), user, ProposerOutput)
    return output, call, seed


if __name__ == "__main__":
    from forge.agents._cli import show

    parser = argparse.ArgumentParser()
    parser.add_argument("--category", default="probability")
    parser.add_argument("--difficulty", default="easy", choices=["easy", "medium", "hard"])
    args = parser.parse_args()
    output, call, seed = asyncio.run(propose(args.category, args.difficulty))
    print(f"seed: {seed}")
    show("proposer", output, call)
