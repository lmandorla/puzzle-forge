"""Checks that need no API calls: schemas, prompts, pricing, SVG safety, tolerances."""

from types import SimpleNamespace

import pytest
from anthropic.lib._parse._transform import transform_schema

from forge import config
from forge.agents.adversarial import AdversarialOutput
from forge.agents.code_verifier import CodeOutput
from forge.agents.hints import HintsOutput
from forge.agents.illustrator import IllustrationOutput, svg_problem
from forge.agents.proposer import ProposerOutput, category_info
from forge.agents.reasoning_verifier import ReasoningOutput
from forge.agents.rewriter import RewriteOutput
from forge.answers import answers_agree, tolerance_for
from forge.llm import cost_usd, load_prompt
from forge.seeds import random_seed

OUTPUTS = [ProposerOutput, ReasoningOutput, CodeOutput, AdversarialOutput, RewriteOutput, IllustrationOutput, HintsOutput]


@pytest.mark.parametrize("model", OUTPUTS, ids=lambda m: m.__name__)
def test_output_schema_transforms(model):
    schema = transform_schema(model.model_json_schema())
    assert schema["type"] == "object"
    assert schema.get("additionalProperties") is False


def test_every_stage_has_a_prompt_and_config():
    stages = config.models()["stages"]
    prompt_names = {"proposer": "proposer", "reasoning_verifier": "reasoning_verifier",
                    "code_verifier": "code_verifier", "adversarial_verifier": "adversarial_verifier",
                    "rewriter": "rewriter", "illustrator": "illustrator", "hints": "hints"}
    assert set(stages) == set(prompt_names)
    for stage, prompt in prompt_names.items():
        assert load_prompt(prompt).strip()
        assert stages[stage]["model"] in config.models()["pricing"]


def test_categories_have_all_difficulties():
    for cat in config.categories()["categories"]:
        assert set(category_info(cat["id"])["difficulty"]) == {"easy", "medium", "hard"}


def test_seed_format():
    assert random_seed().startswith("setting: ")


def test_cost_uses_served_model_prices():
    usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=1_000_000,
                            cache_creation_input_tokens=0, cache_read_input_tokens=0)
    assert cost_usd("claude-fable-5-1", usage) == pytest.approx(60.0)
    assert cost_usd("claude-sonnet-5", usage) == pytest.approx(12.0)


GOOD_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 480 320"><rect width="480" height="320" fill="#fbf8f1"/><use href="#a"/></svg>'


@pytest.mark.parametrize("svg,ok", [
    (GOOD_SVG, True),
    ('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', False),
    ('<svg xmlns="http://www.w3.org/2000/svg"><rect onclick="x()"/></svg>', False),
    ('<svg xmlns="http://www.w3.org/2000/svg"><image href="http://evil/x.png"/></svg>', False),
    ('<svg xmlns="http://www.w3.org/2000/svg"><a href="javascript:x()"><rect/></a></svg>', False),
    ('<div>not svg</div>', False),
    ('<svg><rect></svg>', False),
    ('<!DOCTYPE svg [<!ENTITY x "y">]><svg xmlns="http://www.w3.org/2000/svg"/>', False),
])
def test_svg_safety(svg, ok):
    assert (svg_problem(svg) is None) == ok


def test_double_escaped_unicode_is_repaired():
    import json
    from forge.llm import fix_double_escapes
    raw = json.dumps({"s": "1 \\u2264 d, \\frac{1}{2}, \\underbrace{x}"})
    assert json.loads(fix_double_escapes(raw))["s"] == "1 ≤ d, \\frac{1}{2}, \\underbrace{x}"


def test_tolerances():
    assert tolerance_for("integer", None) == 0.0
    assert tolerance_for("decimal", 3) == pytest.approx(0.0005)
    assert answers_agree(60, 60.0000000001, 0.0)
    assert not answers_agree(60, 61, 0.0)
    assert answers_agree(0.7854, 0.785398, tolerance_for("decimal", 4))
    assert not answers_agree(0.7849, 0.785398, tolerance_for("decimal", 4))
    assert answers_agree(0.1 + 0.2, 0.3, 0.0)
