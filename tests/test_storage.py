import json

from forge.schema import Answer, Hint, Problem, Rejection, Statement
from forge.storage import ProblemStore


def make_problem(**overrides) -> Problem:
    fields = dict(
        title="Socks in the Dark",
        category="combinatorics",
        difficulty="easy",
        status="valid",
        statement=Statement(original="How many ways...", final="Your drawer..."),
        answer=Answer(value=42, format="integer"),
        hints=[Hint(level=1, text="Count without restrictions first.")],
    )
    fields.update(overrides)
    return Problem(**fields)


def graveyard_problem(**overrides) -> Problem:
    return make_problem(
        status="graveyard",
        answer=None,
        rejection=Rejection(stage="validity", reason="verifier_disagreement", detail="42 != 41",
                            reasoning_answer=42, code_answer=41),
        **overrides,
    )


def test_round_trip(tmp_path):
    store = ProblemStore(tmp_path)
    p = make_problem()
    store.save(p)
    assert store.load(p.id) == p
    assert (tmp_path / "valid" / f"{p.id}.json").exists()


def test_load_missing_returns_none(tmp_path):
    assert ProblemStore(tmp_path).load("prob_nope") is None


def test_list_filters(tmp_path):
    store = ProblemStore(tmp_path)
    a = make_problem(category="geometry", difficulty="hard")
    b = make_problem(category="combinatorics", difficulty="easy")
    c = graveyard_problem(category="geometry")
    for p in (a, b, c):
        store.save(p)

    assert {r["id"] for r in store.list(status="valid")} == {a.id, b.id}
    assert {r["id"] for r in store.list(category="geometry")} == {a.id, c.id}
    assert [r["id"] for r in store.list(status="valid", difficulty="hard")] == [a.id]
    assert [r["id"] for r in store.list(reason="verifier_disagreement")] == [c.id]


def test_status_change_moves_file(tmp_path):
    store = ProblemStore(tmp_path)
    p = make_problem()
    store.save(p)
    moved = p.model_copy(update={"status": "graveyard"})
    store.save(moved)
    assert not (tmp_path / "valid" / f"{p.id}.json").exists()
    assert (tmp_path / "graveyard" / f"{p.id}.json").exists()
    assert store.list(status="valid") == []


def test_reindex_rebuilds_from_files(tmp_path):
    store = ProblemStore(tmp_path)
    p, q = make_problem(), graveyard_problem()
    store.save(p)
    store.save(q)
    (tmp_path / "index.json").unlink()

    fresh = ProblemStore(tmp_path)
    assert {r["id"] for r in fresh.list()} == {p.id, q.id}


def test_corrupt_index_is_rebuilt(tmp_path):
    store = ProblemStore(tmp_path)
    p = make_problem()
    store.save(p)
    (tmp_path / "index.json").write_text("{not json", encoding="utf-8")
    assert [r["id"] for r in ProblemStore(tmp_path).list()] == [p.id]


def test_no_tmp_files_left(tmp_path):
    store = ProblemStore(tmp_path)
    for _ in range(3):
        store.save(make_problem())
    assert list(tmp_path.rglob("*.tmp")) == []
    json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
