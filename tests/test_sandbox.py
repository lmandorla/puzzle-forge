import pytest

from forge.answers import parse_number
from forge.sandbox import run_python


@pytest.mark.parametrize("text,expected", [
    ("42", 42.0), (" -3.5 ", -3.5), ("3/4", 0.75), ("1e-3", 0.001), ("1,000", 1000.0), ("60.", 60.0),
    ("abc", None), ("", None), ("1/0", None), ("inf", None), ("nan", None),
])
def test_parse_number(text, expected):
    assert parse_number(text) == expected


def test_answer_parsed():
    r = run_python('print("working...")\nprint("ANSWER: 4")')
    assert r.success and r.answer == 4.0 and r.error_kind is None


def test_fraction_answer():
    r = run_python('print("ANSWER: 3/4")')
    assert r.success and r.answer == 0.75


def test_last_answer_line_wins():
    r = run_python('print("ANSWER: 1")\nprint("ANSWER: 2")')
    assert r.answer == 2.0


def test_numpy_and_sympy_available():
    r = run_python(
        "import numpy as np, sympy as sp\n"
        "print(f'ANSWER: {int(np.sum([1, 2, 3])) + int(sp.binomial(6, 2))}')"
    )
    assert r.success, r.stderr
    assert r.answer == 21.0


def test_missing_answer_line():
    r = run_python('print("the answer is 5")')
    assert not r.success and r.error_kind == "no_answer"


def test_unparseable_answer():
    r = run_python('print("ANSWER: lots")')
    assert not r.success and r.error_kind == "no_answer"


def test_crash_reports_stderr():
    r = run_python('x = 1\nraise ValueError("boom")')
    assert not r.success and r.error_kind == "crash"
    assert "ValueError: boom" in r.stderr
    assert 'File "script.py", line 2' in r.stderr


def test_timeout():
    r = run_python("import time\ntime.sleep(30)\nprint('ANSWER: 1')", timeout_s=2)
    assert not r.success and r.timed_out and r.error_kind == "timeout"
    assert r.runtime_s < 10


def test_memory_limit():
    script = "chunks = []\nwhile True:\n    chunks.append(b'x' * 10_000_000)\n"
    r = run_python(script, timeout_s=30, memory_mb=256)
    assert not r.success and r.memory_exceeded and r.error_kind == "memory"
    assert r.peak_memory_mb > 256


def test_network_blocked():
    r = run_python('import socket\nsocket.create_connection(("example.com", 80), timeout=3)\nprint("ANSWER: 1")')
    assert not r.success and "disabled in sandbox" in r.stderr


def test_subprocess_blocked():
    r = run_python('import subprocess\nsubprocess.run(["cmd", "/c", "echo hi"])\nprint("ANSWER: 1")')
    assert not r.success and "disabled in sandbox" in r.stderr


def test_unicode_output():
    r = run_python('print("π ≈ 3.14159")\nprint("ANSWER: 3.14159")')
    assert r.success and "π" in r.stdout
