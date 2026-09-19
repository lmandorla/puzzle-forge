"""Confirm the project's API key works for every configured model. Never prints the key."""

import sys

import anthropic

from forge import config


def main() -> int:
    key = config.api_key()
    if not key:
        print("No ANTHROPIC_API_KEY in puzzle-forge/.env - copy .env.example to .env and paste the Build Day key.")
        return 1

    client = config.make_client()
    models_cfg = config.models()
    fallback = models_cfg["refusal_fallback"]
    pricing = models_cfg["pricing"]

    try:
        available = {m.id for m in client.models.list()}
    except anthropic.AuthenticationError:
        print("Authentication failed: the key in .env was rejected.")
        return 1
    except anthropic.BadRequestError as e:
        print(f"Request rejected: {e.message}")
        if "workspace" in str(e.message):
            print("Fix: use a key created inside a workspace, or add ANTHROPIC_WORKSPACE_ID=wrkspc_... to .env.")
        return 1
    print(f"Key accepted. {len(available)} models visible to this organization.")

    wanted = sorted({s["model"] for s in models_cfg["stages"].values()})
    failures = 0
    total_cost = 0.0
    for model in wanted:
        if model not in available:
            print(f"  [MISSING] {model} is not available to this key")
            failures += 1
            continue

        kwargs = dict(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": "Reply with the single word: ok"}],
        )
        if not model.startswith("claude-haiku"):
            kwargs["output_config"] = {"effort": "low"}
        use_fallback = fallback["enabled"] and model in fallback["models"]

        try:
            if use_fallback:
                resp = client.beta.messages.create(
                    betas=[fallback["beta"]], extra_body={"fallbacks": fallback["mode"]}, **kwargs
                )
            else:
                resp = client.messages.create(**kwargs)
        except anthropic.APIStatusError as e:
            print(f"  [FAIL] {model}: HTTP {e.status_code} {e.message}")
            failures += 1
            continue
        except anthropic.APIConnectionError:
            print(f"  [FAIL] {model}: network error")
            failures += 1
            continue

        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        # Price by the model that actually answered: a refusal fallback bills at its own rate.
        in_price, out_price = pricing.get(resp.model, (0.0, 0.0))
        cost = (resp.usage.input_tokens * in_price + resp.usage.output_tokens * out_price) / 1e6
        total_cost += cost
        note = " (refusal fallback enabled)" if use_fallback else ""
        if resp.model != model:
            note += f" [served by {resp.model}]"
        print(
            f"  [OK] {model}{note}: stop={resp.stop_reason}, reply={text[:20]!r}, "
            f"tokens in/out={resp.usage.input_tokens}/{resp.usage.output_tokens}, ~${cost:.4f}"
        )

    print(f"Total cost of this check: ~${total_cost:.4f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
