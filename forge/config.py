import os
from functools import lru_cache
from pathlib import Path

import anthropic
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"

# The project .env must win over any key set elsewhere on the machine so all
# calls bill to the Build Day organization; a stray OAuth token is dropped for the same reason.
load_dotenv(ROOT / ".env", override=True)
os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)


def _load(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache
def models() -> dict:
    return _load("models.yaml")


@lru_cache
def pipeline() -> dict:
    return _load("pipeline.yaml")


@lru_cache
def categories() -> dict:
    return _load("categories.yaml")


def api_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY") or None


def make_client(async_: bool = False, **kwargs):
    """Single place that builds API clients, so every call bills the same key and workspace."""
    headers = {}
    # Organization-level keys (not scoped to a workspace) must name the workspace to bill.
    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    if workspace:
        headers["anthropic-workspace-id"] = workspace
    cls = anthropic.AsyncAnthropic if async_ else anthropic.Anthropic
    return cls(api_key=api_key(), default_headers=headers or None, **kwargs)
