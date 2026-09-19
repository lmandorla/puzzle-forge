import argparse
import asyncio

from pydantic import BaseModel

from forge import config
from forge.llm import LLMError, call_structured, load_prompt
from forge.sandbox import run_python
from forge.schema import CallInfo, CodeAttempt, CodeRecord


class CodeOutput(BaseModel):
    approach: str
    script: str


async def write_script(statement: str, previous: CodeAttempt | None = None) -> tuple[CodeOutput, CallInfo]:
    user = f"Puzzle:\n\n{statement}"
    if previous:
        run = previous.execution
        user += (
            f"\n\nYour previous program failed: {run.error}\n"
            f"Last part of its stderr:\n{run.stderr[-2000:]}\n"
            f"Last part of its stdout:\n{run.stdout[-1000:]}\n"
            f"Previous program:\n```python\n{previous.script}\n```\n"
            "Fix the problem and return a complete corrected program."
        )
    return await call_structured("code_verifier", load_prompt("code_verifier"), user, CodeOutput)


async def verify(statement: str) -> CodeRecord:
    """Write a program, run it in the sandbox, and give the agent one chance to fix a failure.

    If an API call fails, the LLMError carries the attempts so far as `e.partial`.
    """
    sandbox = config.pipeline()["sandbox"]
    retries = config.pipeline()["retries"]["code_fix"]
    record = CodeRecord()
    previous = None
    for _ in range(retries + 1):
        try:
            output, call = await write_script(statement, previous)
        except LLMError as e:
            e.partial = record
            raise
        result = await asyncio.to_thread(run_python, output.script, sandbox["timeout_s"], sandbox["memory_mb"])
        previous = CodeAttempt(call=call, approach=output.approach, script=output.script, execution=result)
        record.attempts.append(previous)
        if result.success:
            record.answer = result.answer
            break
    return record


if __name__ == "__main__":
    from forge.agents._cli import BANANA

    parser = argparse.ArgumentParser()
    parser.add_argument("--statement", default=BANANA)
    args = parser.parse_args()
    record = asyncio.run(verify(args.statement))
    for i, attempt in enumerate(record.attempts, 1):
        run = attempt.execution
        print(f"== attempt {i}: {attempt.approach}")
        print(attempt.script)
        print(f"-- sandbox: success={run.success} answer={run.answer} error={run.error} runtime={run.runtime_s}s")
        print(f"-- served by {attempt.call.model}: ${attempt.call.cost_usd:.4f}, {attempt.call.duration_s}s")
    print(f"FINAL ANSWER: {record.answer}")
