"""Generate a batch of puzzles from the command line.

    python generate.py --count 3 [--category geometry] [--difficulty hard] [--concurrency 3]
"""

import argparse
import asyncio
import sys
import time

from forge import config
from forge.llm import total_spend
from forge.pipeline import run_batch
from forge.storage import ProblemStore

STAGE_LABELS = {"proposing": "proposing", "verifying": "verifying (3 checks)", "polishing": "rewriting, illustrating, hints"}


def print_progress(event: dict) -> None:
    stage = event["stage"]
    if stage == "batch_started":
        print(f"Starting a batch of {event['count']} puzzle(s)...")
        return
    tag = f"[{event['index'] + 1}] {event['category']}/{event['difficulty']}"
    if stage == "done":
        outcome = "VALID" if event["status"] == "valid" else f"graveyard ({event['reason']})"
        print(f"{tag}: {outcome} - {event['title']!r} - ${event['cost_usd']:.3f} - {event['problem_id']}")
    else:
        title = f" - {event['title']!r}" if event.get("title") else ""
        print(f"{tag}: {STAGE_LABELS.get(stage, stage)}{title}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    batch = config.pipeline()["batch"]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=batch["default_count"])
    parser.add_argument("--category", action="append", help="repeatable; default: all categories")
    parser.add_argument("--difficulty", action="append", choices=["easy", "medium", "hard"])
    parser.add_argument("--concurrency", type=int, default=batch["max_concurrent_problems"])
    args = parser.parse_args()

    spend_before = total_spend()
    start = time.monotonic()
    problems = asyncio.run(run_batch(
        args.count, ProblemStore(), args.category, args.difficulty, args.concurrency, print_progress))

    valid = sum(p.status == "valid" for p in problems)
    batch_cost = sum(p.metadata.cost_usd for p in problems)
    print(
        f"\nDone in {time.monotonic() - start:.0f}s: {valid} valid, {len(problems) - valid} graveyard. "
        f"Batch cost ${batch_cost:.3f}. All-time spend ${total_spend():.3f} "
        f"(this run added ${total_spend() - spend_before:.3f})."
    )


if __name__ == "__main__":
    main()
