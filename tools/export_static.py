"""Build a read-only copy of the web app (no server, no Generate) and optionally publish it to GitHub Pages.

    python tools/export_static.py                  # build into dist/
    python tools/export_static.py --publish        # build, commit to the gh-pages branch and push
    python tools/export_static.py --publish --cname mathpuzzle.example.com

Answers ship with the page (lightly encoded so they aren't readable at a glance), since the site
grades them in the browser.
"""

import argparse
import base64
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forge.api import answer_reveal, config_payload, public_view  # noqa: E402
from forge.schema import utcnow  # noqa: E402
from forge.storage import ProblemStore  # noqa: E402

DIST = ROOT / "dist"
WEB = ROOT / "web"


def seal(payload: dict) -> str:
    return base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")


def build_data(store: ProblemStore) -> dict:
    valid, graveyard = [], []
    for row in store.list():
        p = store.load(row["id"])
        if p.status == "valid":
            valid.append({"summary": p.summary(), "public": public_view(p), "sealed": seal(answer_reveal(p))})
        else:
            graveyard.append({"summary": p.summary(), "record": p.model_dump(mode="json")})
    return {"generated_at": utcnow().isoformat(), "config": config_payload(), "valid": valid, "graveyard": graveyard}


def build(cname: str | None) -> dict:
    DIST.mkdir(exist_ok=True)
    for entry in DIST.iterdir():  # keep the worktree's .git link, replace everything else
        if entry.name == ".git":
            continue
        shutil.rmtree(entry) if entry.is_dir() else entry.unlink()

    html = (WEB / "index.html").read_text(encoding="utf-8")
    marker = '<meta charset="utf-8">'
    assert marker in html, "index.html layout changed; update export_static.py"
    html = html.replace(marker, marker + '\n  <meta name="pf-static-data" content="puzzles.json">', 1)
    (DIST / "index.html").write_text(html, encoding="utf-8")
    for name in ("app.js", "style.css"):
        shutil.copy2(WEB / name, DIST / name)

    data = build_data(ProblemStore())
    (DIST / "puzzles.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (DIST / ".nojekyll").write_text("", encoding="utf-8")
    if cname:
        (DIST / "CNAME").write_text(cname.strip() + "\n", encoding="utf-8")
    return data


def git(*args: str, cwd: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True)


def ensure_worktree() -> None:
    """Check out the gh-pages branch at dist/ so publishing is an ordinary commit and push."""
    if (DIST / ".git").exists():
        return
    # Empty rather than delete dist/: Google Drive can hold a lock on the folder itself,
    # and git accepts an existing empty directory for a worktree.
    DIST.mkdir(exist_ok=True)
    for entry in DIST.iterdir():
        shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
    if git("rev-parse", "--verify", "--quiet", "gh-pages", check=False).returncode == 0:
        git("worktree", "add", str(DIST), "gh-pages")
    elif git("ls-remote", "--exit-code", "--heads", "origin", "gh-pages", check=False).returncode == 0:
        git("fetch", "origin", "gh-pages")
        git("worktree", "add", "-b", "gh-pages", str(DIST), "origin/gh-pages")
    else:
        git("worktree", "add", "--orphan", "-b", "gh-pages", str(DIST))


def publish(author: list[str]) -> None:
    git("add", "-A", cwd=DIST)
    if git("diff", "--cached", "--quiet", cwd=DIST, check=False).returncode == 0:
        print("Nothing changed since the last publish.")
        return
    git(*author, "commit", "-m", f"Publish puzzles ({utcnow():%Y-%m-%d %H:%M} UTC)", cwd=DIST)
    result = git("push", "-u", "origin", "gh-pages", cwd=DIST, check=False)
    if result.returncode != 0:
        raise SystemExit(f"Push failed:\n{result.stderr}")
    print("Pushed to the gh-pages branch.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--publish", action="store_true", help="commit to gh-pages and push")
    parser.add_argument("--cname", help="custom domain to serve the site from")
    parser.add_argument("--author", help='commit author, e.g. "Jane Doe <jane@example.com>" (default: git config)')
    args = parser.parse_args()

    author = []
    if args.author:
        name, _, email = args.author.partition("<")
        author = ["-c", f"user.name={name.strip()}", "-c", f"user.email={email.rstrip('>').strip()}"]

    if args.publish:
        ensure_worktree()
    data = build(args.cname)
    print(f"Built dist/ with {len(data['valid'])} puzzle(s) and {len(data['graveyard'])} in the graveyard.")
    if args.publish:
        publish(author)


if __name__ == "__main__":
    main()
