"""Browser check of the web UI against a running server (python -m forge.api).

    python tools/ui_check.py basic      # free: browse, hints, confirm dialog, answers, graveyard, mobile, dark
    python tools/ui_check.py generate   # spends credits: runs a 2-puzzle batch through the Generate page
"""

import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from forge.answers import display_answer  # noqa: E402
from forge.config import DATA_DIR  # noqa: E402
from forge.storage import ProblemStore  # noqa: E402

BASE = "http://127.0.0.1:8765"
SHOTS = DATA_DIR / "previews"
SHOTS.mkdir(parents=True, exist_ok=True)


def check(condition, message):
    print(("PASS " if condition else "FAIL ") + message)
    if not condition:
        check.failures += 1


check.failures = 0


def new_page(browser, errors, **context_args):
    page = browser.new_context(**context_args).new_page()
    page.on("console", lambda m: m.type == "error" and not m.text.startswith("Failed to load resource")
            and errors.append(m.text))
    page.on("pageerror", lambda e: errors.append(str(e)))
    # The unknown-puzzle check expects a 404; any other failed request is a real error.
    page.on("response", lambda r: r.status >= 400 and "does-not-exist" not in r.url
            and errors.append(f"HTTP {r.status} {r.url}"))
    return page


def basic(browser):
    errors = []
    page = new_page(browser, errors, viewport={"width": 1280, "height": 900})
    page.goto(BASE)
    rows = page.locator(".rows .row")
    expect(rows.first).to_be_visible()
    check(rows.count() >= 1, f"puzzle list shows {rows.count()} puzzle(s)")
    page.screenshot(path=SHOTS / "ui_list.png", full_page=True)

    page.select_option("select >> nth=0", "combinatorics")
    page.wait_for_timeout(400)
    cats = page.locator(".rows .row-meta").all_inner_texts()
    check(cats and all("Combinatorics" in c for c in cats), "category filter narrows the list")
    page.select_option("select >> nth=0", "")

    rows.first.click()
    expect(page.locator("article h1")).to_be_visible()
    problem_id = page.url.rsplit("/", 1)[-1]
    problem = ProblemStore().load(problem_id)
    check(page.locator(".statement").inner_text().strip() != "", "statement is rendered")
    if problem.illustration and problem.illustration.svg:
        loaded = page.eval_on_selector(".illustration img", "img => img.complete && img.naturalWidth > 0")
        check(loaded, "SVG illustration loads as an image")

    page.get_by_role("button", name="Show the original, precise wording").click()
    check(page.locator(".precise").is_visible(), "precise wording toggles open")

    n_hints = len(problem.hints)
    for i in range(n_hints):
        page.get_by_role("button", name=f"Reveal hint {i + 1} of {n_hints}").click()
        check(page.locator(".rung.revealed").count() == i + 1, f"hint {i + 1} revealed, later hints still hidden")
    check(page.get_by_role("button", name="Reveal hint").count() == 0, "no reveal button left after the last hint")
    page.screenshot(path=SHOTS / "ui_hints.png", full_page=True)

    page.fill("#answer", "1")
    page.get_by_role("button", name="Check answer").click()
    dialog = page.locator("dialog#confirm")
    check(dialog.is_visible(), "confirmation dialog appears before submitting")
    page.get_by_role("button", name="Keep thinking").click()
    check(not dialog.is_visible() and page.locator(".verdict").count() == 0, "'Keep thinking' cancels without submitting")

    wrong = "1" if problem.answer.value != 1 else "2"
    page.fill("#answer", wrong)
    page.get_by_role("button", name="Check answer").click()
    page.get_by_role("button", name="Submit answer").click()
    expect(page.locator(".verdict")).to_be_visible()
    check(page.locator(".verdict.wrong").count() == 1, f"wrong answer {wrong} is marked 'Not quite'")
    key = display_answer(problem.answer.value, problem.answer.format, problem.answer.decimal_places)
    check(key in page.locator(".key").inner_text(), f"answer key {key} is shown after submitting")
    check(page.locator(".solution").inner_text().strip() != "", "Fable's solution is shown")
    check(page.locator(".solution .katex").count() > 0 or "$" not in problem.reasoning_verifier.reasoning,
          "math in the solution is typeset by KaTeX")
    page.screenshot(path=SHOTS / "ui_wrong.png", full_page=True)

    page.get_by_role("button", name="Reset this puzzle and try again").click()
    expect(page.locator("#answer")).to_be_visible()
    page.fill("#answer", key)
    page.get_by_role("button", name="Check answer").click()
    page.get_by_role("button", name="Submit answer").click()
    expect(page.locator(".verdict.correct")).to_be_visible()
    check(True, f"correct answer {key} is marked 'Correct!'")

    page.goto(f"{BASE}/#/puzzles")
    expect(page.locator(".row-side.correct").first).to_be_visible()
    check(True, "the list marks the puzzle as solved")

    page.goto(f"{BASE}/#/puzzle/{problem_id}")
    expect(page.locator(".verdict.correct")).to_be_visible()
    check(True, "revisiting the puzzle restores the result")

    page.goto(f"{BASE}/#/graveyard")
    expect(page.locator("h1")).to_have_text("Graveyard")
    graves = page.locator(".rows .row").count()
    check(graves > 0 or page.locator(".empty").is_visible(), f"graveyard renders ({graves} buried)")
    if graves:
        page.locator(".rows .row").first.click()
        expect(page.locator(".rejection")).to_be_visible()
        check(True, "graveyard detail shows the rejection reason")
        page.screenshot(path=SHOTS / "ui_grave_detail.png", full_page=True)
    page.goto(f"{BASE}/#/graveyard")
    page.screenshot(path=SHOTS / "ui_graveyard.png", full_page=True)

    page.goto(f"{BASE}/#/generate")
    expect(page.get_by_role("button", name="Generate 3 puzzles")).to_be_visible()
    page.fill("#count", "2")
    check(page.get_by_role("button", name="Generate 2 puzzles").is_visible(), "generate button label follows the count")
    page.screenshot(path=SHOTS / "ui_generate.png", full_page=True)

    page.goto(f"{BASE}/#/puzzle/does-not-exist")
    expect(page.locator(".notice")).to_be_visible()
    check("Unknown puzzle" in page.locator(".notice").inner_text(), "unknown puzzle shows a clear error")

    mobile = new_page(browser, errors, viewport={"width": 390, "height": 844}, is_mobile=True)
    mobile.goto(f"{BASE}/#/puzzle/{problem_id}")
    expect(mobile.locator("article h1")).to_be_visible()
    overflow = mobile.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
    check(not overflow, "no horizontal scrolling at phone width")
    mobile.screenshot(path=SHOTS / "ui_mobile.png", full_page=True)

    dark = new_page(browser, errors, viewport={"width": 1280, "height": 900}, color_scheme="dark")
    dark.goto(f"{BASE}/#/puzzle/{problem_id}")
    expect(dark.locator("article h1")).to_be_visible()
    dark.screenshot(path=SHOTS / "ui_dark.png", full_page=True)

    check(not errors, f"no console errors ({errors[:3]})")


def generate(browser):
    errors = []
    page = new_page(browser, errors, viewport={"width": 1280, "height": 900})
    page.goto(f"{BASE}/#/generate")
    page.locator("label.chip", has_text="Hard").click()
    page.fill("#count", "2")
    page.get_by_role("button", name="Generate 2 puzzles").click()
    expect(page.locator(".batch").first).to_be_visible()
    page.wait_for_timeout(8000)
    page.screenshot(path=SHOTS / "ui_generate_running.png", full_page=True)
    check(page.locator(".track i.now").count() > 0, "progress track shows a stage in progress")
    expect(page.locator(".batch-head").first).to_contain_text("Finished", timeout=15 * 60 * 1000)
    page.screenshot(path=SHOTS / "ui_generate_done.png", full_page=True)
    outcomes = page.locator(".batch").first.locator(".outcome-valid, .outcome-grave")
    check(outcomes.count() == 2, "both puzzles report an outcome with a link")
    print("batch:", page.locator(".batch-head").first.inner_text())
    check(not errors, f"no console errors ({errors[:3]})")


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "basic"
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        {"basic": basic, "generate": generate}[phase](browser)
        browser.close()
    print(f"\n{check.failures} failure(s)")
    sys.exit(1 if check.failures else 0)
