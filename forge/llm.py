"""Shared structured-output call used by every agent: config lookup, fallback, cost, spend ledger."""

import asyncio
import json
import re
import time
from pathlib import Path
from typing import TypeVar

import anthropic
from anthropic.lib._parse._transform import transform_schema  # same schema transform as output_format
from pydantic import BaseModel, ValidationError

from forge import config
from forge.schema import CallInfo, utcnow

PROMPTS_DIR = Path(__file__).parent / "prompts"
SPEND_LOG = config.DATA_DIR / "spend.jsonl"
T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """kind: 'refusal' | 'max_tokens' | 'malformed' | 'api'. `call` carries the cost already spent."""

    def __init__(self, kind: str, message: str, call: CallInfo | None = None):
        super().__init__(message)
        self.kind = kind
        self.call = call


_DOUBLE_ESCAPED_UNICODE = re.compile(r"\\\\u([0-9a-fA-F]{4})")


def fix_double_escapes(raw_json: str) -> str:
    r"""Models sometimes emit "\\u2264" (literal backslash-u) in JSON where "\u2264" (≤) was meant."""
    return _DOUBLE_ESCAPED_UNICODE.sub(r"\\u\1", raw_json)


def load_prompt(name: str, **values) -> str:
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


_client_state: dict = {"loop": None, "client": None}


def _client() -> anthropic.AsyncAnthropic:
    # An async client is bound to the event loop it was first used on.
    loop = asyncio.get_running_loop()
    if _client_state["loop"] is not loop:
        timeout = config.pipeline()["api"]["request_timeout_s"]
        _client_state.update(loop=loop, client=config.make_client(async_=True, timeout=timeout, max_retries=3))
    return _client_state["client"]


def cost_usd(model: str, usage) -> float:
    price_in, price_out = config.models()["pricing"].get(model, (0.0, 0.0))
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    return (
        usage.input_tokens * price_in
        + cache_write * price_in * 1.25
        + cache_read * price_in * 0.1
        + usage.output_tokens * price_out
    ) / 1e6


def _log_spend(stage: str, requested: str, call: CallInfo, stop_reason: str | None) -> None:
    SPEND_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": utcnow().isoformat(), "stage": stage, "requested_model": requested, "model": call.model,
        "input_tokens": call.input_tokens, "output_tokens": call.output_tokens,
        "cost_usd": round(call.cost_usd, 6), "duration_s": call.duration_s, "stop_reason": stop_reason,
    }
    with open(SPEND_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def total_spend() -> float:
    try:
        lines = SPEND_LOG.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return 0.0
    return sum(json.loads(line)["cost_usd"] for line in lines if line.strip())


def _merge(total: CallInfo, call: CallInfo) -> None:
    total.model = call.model
    total.input_tokens += call.input_tokens
    total.output_tokens += call.output_tokens
    total.cost_usd += call.cost_usd
    total.duration_s = round(total.duration_s + call.duration_s, 2)


async def _call_once(stage: str, cfg: dict, system: str, user: str, output: type[T]) -> tuple[T, CallInfo]:
    output_config = {"format": {"type": "json_schema", "schema": transform_schema(output.model_json_schema())}}
    if cfg.get("effort"):
        output_config["effort"] = cfg["effort"]
    kwargs = dict(
        model=cfg["model"], max_tokens=cfg["max_tokens"], system=system,
        messages=[{"role": "user", "content": user}], output_config=output_config,
    )
    fallback = config.models()["refusal_fallback"]
    if fallback["enabled"] and cfg["model"] in fallback["models"]:
        kwargs.update(betas=[fallback["beta"]], fallbacks=fallback["mode"])

    start = time.monotonic()
    try:
        async with _client().beta.messages.stream(**kwargs) as stream:
            msg = await stream.get_final_message()
    except anthropic.APIStatusError as e:
        raise LLMError("api", f"HTTP {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise LLMError("api", f"connection error: {e}") from e

    call = CallInfo(
        model=msg.model, input_tokens=msg.usage.input_tokens, output_tokens=msg.usage.output_tokens,
        cost_usd=cost_usd(msg.model, msg.usage), duration_s=round(time.monotonic() - start, 2),
    )
    _log_spend(stage, cfg["model"], call, msg.stop_reason)
    if msg.stop_reason == "refusal":
        category = getattr(msg.stop_details, "category", None) if msg.stop_details else None
        raise LLMError("refusal", f"model declined (category: {category})", call)
    if msg.stop_reason == "max_tokens":
        raise LLMError("max_tokens", f"output hit max_tokens={cfg['max_tokens']}", call)
    text = "".join(block.text for block in msg.content if block.type == "text")
    try:
        return output.model_validate_json(fix_double_escapes(text)), call
    except ValidationError as e:
        raise LLMError("malformed", f"output did not match schema: {str(e)[:400]}", call) from e


async def call_structured(stage: str, system: str, user: str, output: type[T]) -> tuple[T, CallInfo]:
    """Call the model configured for `stage`; returns the parsed output and the cumulative call cost.

    Malformed output is retried; refusals, truncation and API errors are raised immediately.
    """
    cfg = config.models()["stages"][stage]
    retries = config.pipeline()["retries"]["malformed_output"]
    total = CallInfo(model=cfg["model"])
    for attempt in range(retries + 1):
        try:
            parsed, call = await _call_once(stage, cfg, system, user, output)
        except LLMError as e:
            if e.call:
                _merge(total, e.call)
            e.call = total
            if e.kind != "malformed" or attempt == retries:
                raise
            continue
        _merge(total, call)
        return parsed, total
    raise AssertionError("unreachable")
