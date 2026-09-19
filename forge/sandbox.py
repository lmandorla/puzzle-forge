"""Run LLM-written Python in a separate process with a timeout, a memory cap and no network.

This is a soft boundary suited to a single-user local tool: the guards are applied inside
the child interpreter, not by the OS.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import psutil

from forge.answers import parse_number
from forge.schema import ExecutionResult

MAX_OUTPUT_CHARS = 20_000
ANSWER_RE = re.compile(r"^\s*ANSWER:\s*(.+?)\s*$", re.MULTILINE)

# Runs in the child before the script: disables network access and process spawning,
# then executes script.py so tracebacks keep the script's own line numbers.
RUNNER = r'''
import os, socket, subprocess, sys

def _blocked(*args, **kwargs):
    raise PermissionError("disabled in sandbox")

socket.socket.connect = _blocked
socket.socket.connect_ex = _blocked
socket.create_connection = _blocked
subprocess.Popen.__init__ = _blocked
os.system = _blocked
os.popen = _blocked
for _name in ("startfile", "execv", "execve", "spawnv", "spawnve"):
    if hasattr(os, _name):
        setattr(os, _name, _blocked)

sys.argv = ["script.py"]
with open("script.py", encoding="utf-8") as _f:
    _code = compile(_f.read(), "script.py", "exec")
exec(_code, {"__name__": "__main__", "__file__": "script.py"})
'''


def _kill_tree(proc: psutil.Process) -> None:
    try:
        for child in proc.children(recursive=True):
            child.kill()
        proc.kill()
    except psutil.NoSuchProcess:
        pass


def _tree_rss_mb(proc: psutil.Process) -> float:
    total = proc.memory_info().rss
    for child in proc.children(recursive=True):
        try:
            total += child.memory_info().rss
        except psutil.NoSuchProcess:
            pass
    return total / 1e6


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS // 2] + "\n...[truncated]...\n" + text[-MAX_OUTPUT_CHARS // 2:]


def extract_answer(stdout: str) -> tuple[float | None, str | None]:
    """Return (answer, error). The last ANSWER: line wins."""
    matches = ANSWER_RE.findall(stdout)
    if not matches:
        return None, "no ANSWER: line in output"
    value = parse_number(matches[-1])
    if value is None:
        return None, f"could not parse ANSWER value {matches[-1]!r}"
    return value, None


def run_python(script: str, timeout_s: float = 30, memory_mb: float = 512) -> ExecutionResult:
    workdir = Path(tempfile.mkdtemp(prefix="forge_sandbox_"))
    try:
        return _run(script, workdir, timeout_s, memory_mb)
    except Exception as e:  # the sandbox must never crash the pipeline
        return ExecutionResult(success=False, error_kind="crash", error=f"sandbox failure: {e!r}")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _run(script: str, workdir: Path, timeout_s: float, memory_mb: float) -> ExecutionResult:
    (workdir / "script.py").write_text(script, encoding="utf-8")
    (workdir / "_runner.py").write_text(RUNNER, encoding="utf-8")
    env = {"SYSTEMROOT": os.environ.get("SYSTEMROOT", ""), "TEMP": str(workdir), "TMP": str(workdir)}
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    start = time.monotonic()
    popen = subprocess.Popen(
        [sys.executable, "-I", "-X", "utf8", "_runner.py"],
        cwd=workdir, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", creationflags=flags,
    )
    proc = psutil.Process(popen.pid)
    state = {"peak": 0.0, "over": False}
    done = threading.Event()

    def watchdog():
        while not done.is_set():
            try:
                rss = _tree_rss_mb(proc)
            except psutil.NoSuchProcess:
                return
            state["peak"] = max(state["peak"], rss)
            if rss > memory_mb:
                state["over"] = True
                _kill_tree(proc)
                return
            done.wait(0.1)

    watcher = threading.Thread(target=watchdog, daemon=True)
    watcher.start()
    timed_out = False
    try:
        stdout, stderr = popen.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc)
        stdout, stderr = popen.communicate()
    finally:
        done.set()
        watcher.join(timeout=2)

    result = ExecutionResult(
        success=False,
        stdout=_truncate(stdout or ""),
        stderr=_truncate(stderr or ""),
        return_code=popen.returncode,
        timed_out=timed_out,
        memory_exceeded=state["over"],
        runtime_s=round(time.monotonic() - start, 3),
        peak_memory_mb=round(state["peak"], 1),
    )
    if state["over"]:
        result.error_kind, result.error = "memory", f"exceeded memory limit of {memory_mb} MB"
    elif timed_out:
        result.error_kind, result.error = "timeout", f"exceeded time limit of {timeout_s} s"
    elif popen.returncode != 0:
        last = (stderr or "").strip().splitlines()
        result.error_kind = "crash"
        result.error = f"exit code {popen.returncode}: {last[-1] if last else 'no stderr'}"
    else:
        result.answer, error = extract_answer(stdout or "")
        if error:
            result.error_kind, result.error = "no_answer", error
        else:
            result.success = True
    return result
