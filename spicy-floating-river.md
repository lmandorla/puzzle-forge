# Puzzle Forge: a pipeline that writes and checks math puzzles

## Context
This is a new, empty project for Fable Build Day. The goal is a local tool that invents "Fiddler on the Proof"-style math puzzles. Each puzzle has a single numeric answer, a difficulty (easy/medium/hard) and a category. Before any puzzle is shown, independent agents check it. A puzzle is **valid** only when two things hold:
- Fable's step-by-step solution and an executed simulation script agree on the answer.
- The adversarial agent finds no second reasonable reading of the problem.

Every other puzzle goes to a **graveyard**, along with the reason it was rejected. Valid puzzles are then rewritten in a fun voice, illustrated with an SVG and given a ladder of hints. A local web UI lets the user:
- start generation runs
- browse the valid puzzles and the graveyard
- solve a puzzle by revealing hints one at a time, submitting an answer after a confirmation prompt, and then seeing the answer key and Fable's solution

Decisions already made with the user:
- **Stack:** Python and FastAPI, with a front-end in plain HTML/CSS/JS
- **Storage:** flat JSON files
- **Code execution:** a subprocess with limits
- **Illustrations:** SVG only for v1
- **Hints and answers:** 3–4 hints per puzzle; the answer is a number with an optional tolerance
- **Categories:** a starter list that can be edited as config

## Important API constraint (check in M0)
According to the `claude-api` skill, **`temperature` is not accepted by `claude-opus-5`, `claude-sonnet-5` or `claude-fable-5-1`**. Sending it returns a 400 error. The proposer's "high temperature" therefore has to come from other sources:
- a random **inspiration seed** in each call (theme, setting, a structural twist)
- `effort: high`
- a prompt that says to avoid well-known puzzles
- the titles of recent puzzles from the index, passed in so the proposer doesn't repeat itself

Before writing any agent code, check model IDs and request parameters against the `claude-api` skill and `client.models.list()`. This includes the exact Haiku ID and whether Fable supports a refusal fallback. Don't guess any of these.

## Project location and layout
New folder: `Fable Build Day/puzzle-forge/`. Run `git init` there. The folder is inside Google Drive, so the virtualenv goes **outside Drive**, or at least in `.gitignore`, so Drive doesn't sync thousands of files. `ANTHROPIC_API_KEY` goes in `.env`, which is also gitignored.

```
puzzle-forge/
  config/
    categories.yaml     # categories + easy/medium/hard rubric per category
    models.yaml         # per-stage model id + effort
    pipeline.yaml       # concurrency, retries, sandbox timeout/memory, answer tolerance default
  forge/                # Python package
    schema.py           # Pydantic Problem model (single source of truth for the JSON format)
    config.py           # loads the YAML
    storage.py          # save/load/list, atomic writes, index.json rebuild
    llm.py              # shared AsyncAnthropic client, call_structured(stage, prompt, OutputModel), timing
    prompts/*.md        # one prompt template per stage
    agents/             # proposer, reasoning_verifier, code_verifier, adversarial,
                        # rewriter, illustrator, hints; each a single async function
    sandbox.py          # run_python(script, timeout_s, memory_mb) -> ExecutionResult
    validity.py         # decide(reasoning_ans, code_ans, tolerance, adversarial) -> (status, rejection)
    pipeline.py         # run_problem(), run_batch()
    api.py              # FastAPI app: REST routes + serves web/ as static files
  generate.py           # CLI: python generate.py --count 10 [--category geometry] [--difficulty hard] [--concurrency 3]
  web/                  # index.html, style.css, app.js (+ small view modules)
  data/valid/<id>.json, data/graveyard/<id>.json, data/index.json
  tests/                # test_storage, test_sandbox, test_validity (no live API)
```

## Using the Build Day API credits
- Charges go to whichever Console organization the API key belongs to. The key must be created **in the organization or workspace that received the Build Day credits** (Console → the org holding the credits → API Keys → Create).
- The key goes only in `puzzle-forge/.env`, which the user fills in themselves. Claude never reads or prints it. There is also a committed `.env.example` with `ANTHROPIC_API_KEY=` left blank.
- `forge/config.py` loads `.env` with `override=True`. Any older `ANTHROPIC_API_KEY` set elsewhere on the machine is then ignored inside this project, so charges can't go to a different account by mistake.
- The M0 check makes one tiny call with the project key and reports only whether it succeeded, plus the model IDs available. The user then confirms in the Console (Usage/Billing for that org) that the call appeared there.
- The key lives in `puzzle-forge/.env` (user's choice; Drive will sync it).
- **No spending cap** (user's choice). Every call's tokens and cost are logged, priced by `response.model` so fallback calls are costed correctly, into `metadata.stage_costs_usd` / `metadata.cost_usd`. The CLI prints running totals. `max_problems_per_batch` (20) and per-stage `max_tokens` still apply. Testing starts with `--count 1`.

## Models by stage (defaults live in `config/models.yaml`)
| Stage | Model | Output |
|---|---|---|
| Proposer | `claude-opus-5` (Fable can be swapped in) | structured: title, statement, category, difficulty, believed answer, reasoning |
| Reasoning verifier | `claude-fable-5-1` | structured: step-by-step reasoning, numeric answer |
| Code verifier (writes the script) | `claude-fable-5-1` | structured: Python script that ends by printing `ANSWER: <number>` |
| Adversarial verifier | `claude-fable-5-1` | structured: `blocking` (bool), concerns, alternate interpretation, alternate answer |
| Rewriter, Illustrator, Hints | `claude-sonnet-5` (Haiku can be swapped in) | text / `{skip, skip_reason, svg}` / list of 3–4 hints |

Independence rule: the two verifiers and the adversarial agent get **only the original problem statement**. They never see the proposer's answer or reasoning. The code enforces this by passing them the statement string, not the proposer's output object.

## How one problem moves through the pipeline (`pipeline.run_problem`)
1. **Propose.** If the output is malformed, retry once. If it fails again, send it to the graveyard as `proposer_malformed_output`.
2. **Verify.** Three checks run at the same time with `asyncio.gather`:
   - the reasoning verifier
   - the adversarial verifier
   - the code verifier: it writes a script, then the sandbox runs it. If the script crashes, times out, runs out of memory or prints no `ANSWER` line, the error is sent back to the agent for **one** fix attempt. If that also fails, the reason is `code_execution_error`, `code_timeout` or `code_output_unparseable`. A timeout also covers puzzles that are too heavy to compute.
3. **Decide validity** (`validity.decide`):
   - Code answer and reasoning answer differ by more than the tolerance: `verifier_disagreement`, with both values saved.
   - The adversarial agent sets `blocking`: `adversarial_ambiguity`.
   - Otherwise the puzzle is **valid**, and the answer key is the code verifier's value. The proposer's own answer is saved as information only.
4. **Rewrite.** The rewriter turns the original statement into the fun final version and must keep every quantity and constraint.
5. **Illustrate and write hints**, in parallel. The illustrator may skip when a picture adds nothing. The hints build on the verified reasoning and never state the answer.
6. **Save.** The file is written to `data/valid/` or `data/graveyard/` (write to `.tmp`, then `os.replace`) and the index is updated.

`run_batch(count, concurrency, filters, progress_cb)`:
- An `asyncio.Semaphore` caps how many problems run at once.
- Category and difficulty are spread evenly across the batch unless filters are given.
- Each problem is wrapped in try/except, so an unexpected error becomes a graveyard record (`pipeline_error`) and never kills the batch.
- Every problem ends up saved on disk.

## JSON format (`forge/schema.py`, Pydantic, `schema_version: 1`)
```json
{
  "id": "prob_20260919_a3f9c2", "schema_version": 1, "title": "The Carnival Ring Toss",
  "category": "probability", "difficulty": "medium",
  "status": "valid",                       // "valid" | "graveyard"
  "rejection": null,                       // {stage, reason, detail, reasoning_answer?, code_answer?}
  "statement": { "original": "...", "final": "..." },
  "answer": { "value": 0.4375, "tolerance": 1e-6, "is_integer": false },
  "proposer":            { "model", "seed", "reasoning", "believed_answer", "timestamp" },
  "reasoning_verifier":  { "model", "reasoning", "answer", "timestamp" },
  "code_verifier":       { "model", "script", "attempts",
                           "execution": { "stdout", "stderr", "return_code", "timed_out",
                                          "memory_exceeded", "runtime_s" },
                           "answer", "timestamp" },
  "adversarial":         { "model", "blocking", "concerns", "alternate_interpretation",
                           "alternate_answer", "timestamp" },
  "hints": [ { "level": 1, "text": "..." } ],        // 3-4, null for graveyard
  "illustration": { "svg": "<svg ...>", "skipped": false, "skip_reason": null, "model" },
  "metadata": { "created_at", "finalized_at", "pipeline_version", "stage_durations_s": {} }
}
```
Rejection reasons: `proposer_malformed_output`, `code_execution_error`, `code_timeout`, `code_output_unparseable`, `verifier_disagreement`, `adversarial_ambiguity`, `pipeline_error`. Graveyard records keep everything produced up to the point of failure. `data/index.json` holds a summary row per problem (id, title, category, difficulty, status, reason, created_at). It is a cache that is rebuilt at startup from the problem files.

## Starter categories (`config/categories.yaml`)
Combinatorics, Probability, Geometry, Number Theory, Game Theory, Graph Theory, Algebra & Optimization, Logic & Recreational (weighings, knights/knaves-style puzzles that still have a numeric answer). Each category defines easy, medium and hard in the same three-tier shape:
- **easy:** one standard technique, small numbers
- **medium:** two combined techniques, casework, or a clever reframing
- **hard:** needs a non-obvious insight, a recursion or invariant, or brute force is impractical by hand

The proposer prompt includes the general tier definition plus the rubric line for its category.

## Sandbox (`forge/sandbox.py`, Windows-compatible)
- The script is written to a fresh temp directory. A short preamble turns off `socket` connections and blocks `subprocess`/`os.system`. This is a soft guard, which is fine for a single-user local tool.
- The script runs with `subprocess.Popen([sys.executable, "-I", script], cwd=tmp, env=minimal)` and a wall-clock timeout (default 30 s).
- Memory is capped by a watchdog thread that checks the process's resident memory (`psutil`) every 100 ms and kills it above the limit (default 512 MB). Windows has no `setrlimit`.
- The answer is taken from the last `ANSWER: <number>` line. Allowed libraries: standard library, plus `numpy`, `sympy` and `fractions`.
- A failure always comes back as an `ExecutionResult` and never raises an exception.

## REST API (`forge/api.py`)
```
POST /api/generate {count, categories?, difficulties?, concurrency?} -> {batch_id}
GET  /api/generate/{batch_id}   -> {requested, done_count, valid, graveyard, events[], finished}
GET  /api/problems?status=valid|graveyard&category=&difficulty=&reason=  -> summaries from index
GET  /api/problems/{id}         -> valid: public view (final + original statement, svg, hints) without
                                   the answer or reasoning; graveyard: full record
POST /api/problems/{id}/answer {value} -> {correct, answer, tolerance, fable_reasoning, fable_answer,
                                          code_script, code_output}
GET  /api/categories, GET /api/stats
```
Batches run as background `asyncio` tasks inside the FastAPI process, and batch progress is kept in memory. The CLI calls the same `run_batch`. The answer and the solution are left out of `GET /api/problems/{id}` for valid puzzles, so they only appear after submission.

## Front-end (`web/`, no build step, served by FastAPI)
Three tabs:
- **Generate:** choose a count, filters and concurrency. The page then checks the batch status every 2 s and shows a progress bar and a live list of valid/graveyard results.
- **Problems:** a filterable card grid of valid puzzles, showing title, category and difficulty badges.
- **Graveyard:** filterable by reason. Each card shows why the puzzle failed, and opening it shows the full record: both answers, the adversarial agent's concerns, and the script with its output.

Problem page:
- the fun statement, plus a "show precise statement" toggle for the original wording (in case the rewrite reads loosely)
- the SVG illustration
- hint buttons that reveal the hints one at a time
- an answer box: Submit → `confirm()` dialog → POST → correct or incorrect, with the answer key and Fable's full reasoning (math shown with KaTeX from a CDN)

## Build order (verify each step before moving on)
| # | Milestone | Verification |
|---|---|---|
| M0 | Scaffold, config YAMLs, `.env.example`, deps (`anthropic`, `python-dotenv`, `fastapi`, `uvicorn`, `pydantic`, `pyyaml`, `psutil`, `numpy`, `sympy`, `pytest`); check model IDs and params against the `claude-api` skill. **Pause here** while the user pastes the Build Day key into `.env` | `python -m forge.check_api` lists models and makes one tiny call per configured model, printing success or failure only (never the key); the user sees the calls in the Build Day org's Console usage |
| M1 | `schema.py` + `storage.py` | `pytest tests/test_storage.py`: save/load round trip, index rebuild, filters |
| M2 | `sandbox.py` | `pytest tests/test_sandbox.py`: prints ANSWER→parsed, sleep→timeout, huge list→memory kill, socket→blocked, syntax error→clean failure |
| M3 | `validity.py` | `pytest tests/test_validity.py`: tolerance edges, disagreement, blocking adversarial |
| M4 | Agents one at a time, each runnable alone (`python -m forge.agents.proposer ...`) | Check the JSON output by eye; open the SVG in a browser; run the verifiers on a known puzzle (e.g. an answer already known to be 42) |
| M5 | `pipeline.py` + `generate.py` | `python generate.py --count 1` → one file in `data/`. Then `--count 6 --concurrency 3` → 6 files, index updated, total time well under 6× a single run |
| M6 | `api.py` | `uvicorn forge.api:app`; call every endpoint with curl; confirm a valid problem's GET response has no answer |
| M7 | Front-end | In the browser: start a batch and watch progress; open a puzzle and reveal hints one by one; submit (confirm dialog appears) and see the result and Fable's reasoning; filter the graveyard by reason (use the `webapp-testing` skill for a Playwright check) |
| M8 | README, error display in the UI, stats | Set everything up from scratch by following only the README |

## Implementation notes (check each against the `claude-api` skill in M0)
- **Haiku ID:** `claude-haiku-4-5`, without the `-20251001` suffix.
- **Refusal fallback:** Fable and Opus calls may need a server-side refusal-fallback beta. Confirm the exact form in the skill, check that it works with structured outputs, and tell the user when it's enabled.
- **Fable is slow and expensive:** calls can take minutes, and pricing is about $10/$50 per million tokens (input/output), which uses up the credits quickly. Set a long request timeout (about 900 s), keep concurrency around 3, and default to `--count 3` during development.
- **Failures after validation don't reject a puzzle:** if the rewriter fails, the original statement is used. If the illustrator fails, the illustration is marked skipped. If hint generation fails, the puzzle is saved with no hints. None of these send a valid puzzle to the graveyard.
- **Answer parsing:** accept `p/q` fractions from both the script output and the user's answer (via `fractions.Fraction`). A non-numeric submission returns 400.
- **Google Drive file locks:** Drive sync can briefly lock files, so `os.replace` retries a few times on `PermissionError`. Paths contain spaces ("My Drive"), so always quote them.

## Out of scope for v1
Raster image generation, user accounts and saved attempt history, hosted deployment, Docker sandboxing, manually moving puzzles between the graveyard and the valid set.
