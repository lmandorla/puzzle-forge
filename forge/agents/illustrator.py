import argparse
import asyncio
import xml.etree.ElementTree as ET

from pydantic import BaseModel

from forge.llm import call_structured, load_prompt
from forge.schema import Illustration

FORBIDDEN_TAGS = {"script", "foreignobject", "iframe", "object", "embed", "image"}


class IllustrationOutput(BaseModel):
    skip: bool
    skip_reason: str | None
    svg: str | None


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def svg_problem(svg: str) -> str | None:
    """Return why an SVG is unsafe or invalid, or None if it is fine to store."""
    if "<!DOCTYPE" in svg or "<!ENTITY" in svg:
        return "contains a DOCTYPE or entity declaration"
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as e:
        return f"not valid XML ({e})"
    if _local(root.tag) != "svg":
        return "root element is not <svg>"
    for element in root.iter():
        if _local(element.tag).lower() in FORBIDDEN_TAGS:
            return f"forbidden element <{_local(element.tag)}>"
        for key, value in element.attrib.items():
            name = _local(key).lower()
            if name.startswith("on"):
                return f"event handler attribute {name}"
            if name == "href" and not value.startswith("#"):
                return "external link"
    return None


async def illustrate(statement: str) -> Illustration:
    output, call = await call_structured(
        "illustrator", load_prompt("illustrator"), f"Puzzle:\n\n{statement}", IllustrationOutput
    )
    if output.skip or not output.svg:
        return Illustration(call=call, skipped=True, skip_reason=output.skip_reason or "no illustration returned")
    problem = svg_problem(output.svg)
    if problem:
        return Illustration(call=call, skipped=True, skip_reason=f"invalid SVG: {problem}")
    return Illustration(call=call, svg=output.svg.strip())


if __name__ == "__main__":
    from forge import config
    from forge.agents._cli import BANANA, show

    parser = argparse.ArgumentParser()
    parser.add_argument("--statement", default=BANANA)
    args = parser.parse_args()
    result = asyncio.run(illustrate(args.statement))
    show("illustrator", result.model_dump(exclude={"svg", "call"}), result.call)
    if result.svg:
        out = config.DATA_DIR / "previews" / "illustration_test.svg"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(result.svg, encoding="utf-8")
        print(f"SVG saved to {out}")
