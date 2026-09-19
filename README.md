# Puzzle Forge

Generates "Fiddler on the Proof"-style math puzzles, each with one numeric answer, and only publishes the ones that independent checks agree on.

For each puzzle:
1. **Proposer** (Opus 5) invents a puzzle for a category and difficulty, inspired by a random seed.
2. **Verification**, three checks in parallel that see only the puzzle statement:
   - **Reasoning verifier** (Fable 5.1) solves it step by step.
   - **Code verifier** (Fable 5.1) writes a Python program that computes the answer, run in a sandbox (time and memory limits, no network), with one chance to fix a failing program.
   - **Adversarial verifier** (Fable 5.1) looks for wording that allows a different answer.
3. The puzzle is **valid** if Fable's answer and the program's answer agree and nothing ambiguous was found. Otherwise it goes to the **graveyard** with the reason.
4. Valid puzzles get a **fun rewrite**, an **SVG illustration** and a **ladder of 3–4 hints** (Sonnet 5).

## Setup

```powershell
python -m venv $env:USERPROFILE\.venvs\puzzle-forge
& $env:USERPROFILE\.venvs\puzzle-forge\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env    # then paste your API key into .env
& $env:USERPROFILE\.venvs\puzzle-forge\Scripts\python.exe -m forge.check_api
```

The virtualenv lives outside Google Drive so Drive doesn't sync thousands of files. The key in `.env` takes priority over any other `ANTHROPIC_API_KEY` on the machine. If the key isn't tied to a workspace, also set `ANTHROPIC_WORKSPACE_ID`.

## Use

In the commands below, `python` means the project virtualenv's interpreter (`%USERPROFILE%\.venvs\puzzle-forge\Scripts\python.exe`).

| What | Command |
|---|---|
| Web app (generate, solve, graveyard) | `python -m forge.api` then open http://127.0.0.1:8765 |
| Generate from the command line | `python generate.py --count 3 [--category geometry] [--difficulty hard] [--concurrency 3]` |
| Run one agent on its own | `python -m forge.agents.proposer --category probability --difficulty easy` (also `reasoning_verifier`, `code_verifier`, `adversarial`, `rewriter`, `illustrator`, `hints`) |
| Publish the read-only site to GitHub Pages | `python tools/export_static.py --publish [--cname your.domain.com]` |
| Tests (no API calls) | `python -m pytest` |
| Browser check (server must be running) | `python tools/ui_check.py basic` (free); `python tools/ui_check.py generate` (runs a real 2-puzzle batch) |

Costs: roughly $0.15–$1 per puzzle, mostly the Fable verifiers. Every API call is logged to `data/spend.jsonl`, and each puzzle records its own cost. The web app shows the running total.

## Configuration

- `config/models.yaml`: the model, effort and max tokens for each stage; the refusal fallback; prices used for cost logging.
- `config/categories.yaml`: categories and what easy, medium and hard mean for each.
- `config/pipeline.yaml`: batch limits, retries, sandbox limits.
- `forge/prompts/*.md`: the prompt for each agent.

## Layout

- `forge/`: pipeline code (`pipeline.py`, `validity.py`, `sandbox.py`, `llm.py`, `storage.py`, `schema.py`, `api.py`, `agents/`).
- `web/`: the front-end (plain HTML, CSS and JS, served by the API).
- `data/`: gitignored. Contains `valid/` and `graveyard/` (one JSON file per puzzle), `index.json` (a rebuildable cache) and `spend.jsonl`.
