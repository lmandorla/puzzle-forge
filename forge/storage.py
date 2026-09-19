import json
import os
import threading
import time
from pathlib import Path

from pydantic import ValidationError

from forge.config import DATA_DIR
from forge.schema import Problem

STATUSES = ("valid", "graveyard")


def atomic_write(path: Path, text: str, attempts: int = 5) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    # Google Drive sync can briefly lock files, so retry the swap.
    for i in range(attempts):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == attempts - 1:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.2 * (i + 1))


class ProblemStore:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = Path(data_dir)
        self.index_path = self.data_dir / "index.json"
        self._lock = threading.Lock()
        self._index_mtime: float | None = None
        for status in STATUSES:
            (self.data_dir / status).mkdir(parents=True, exist_ok=True)
        self._index = self._read_index()

    def _path(self, status: str, problem_id: str) -> Path:
        return self.data_dir / status / f"{problem_id}.json"

    def _mtime(self) -> float | None:
        try:
            return self.index_path.stat().st_mtime
        except FileNotFoundError:
            return None

    def _read_index(self) -> dict[str, dict]:
        try:
            index = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return self.reindex()
        self._index_mtime = self._mtime()
        return index

    def _refresh(self) -> None:
        # The CLI and the web server may both write puzzles; pick up the other process's changes.
        if self._mtime() != self._index_mtime:
            self._index = self._read_index()

    def _write_index(self) -> None:
        atomic_write(self.index_path, json.dumps(self._index, indent=1, sort_keys=True))
        self._index_mtime = self._mtime()

    def reindex(self) -> dict[str, dict]:
        """Rebuild the index cache from the problem files, which are the source of truth."""
        index = {}
        for status in STATUSES:
            for path in (self.data_dir / status).glob("*.json"):
                try:
                    problem = Problem.model_validate_json(path.read_text(encoding="utf-8"))
                except (ValidationError, OSError):
                    continue
                index[problem.id] = problem.summary()
        self._index = index
        with self._lock:
            self._write_index()
        return index

    def save(self, problem: Problem) -> None:
        with self._lock:
            self._refresh()
            atomic_write(self._path(problem.status, problem.id), problem.model_dump_json(indent=2))
            for other in STATUSES:
                if other != problem.status:
                    self._path(other, problem.id).unlink(missing_ok=True)
            self._index[problem.id] = problem.summary()
            self._write_index()

    def load(self, problem_id: str) -> Problem | None:
        for status in STATUSES:
            path = self._path(status, problem_id)
            if path.exists():
                return Problem.model_validate_json(path.read_text(encoding="utf-8"))
        return None

    def list(self, status=None, category=None, difficulty=None, reason=None) -> list[dict]:
        self._refresh()
        filters = {"status": status, "category": category, "difficulty": difficulty, "reason": reason}
        rows = [
            row for row in self._index.values()
            if all(v is None or row.get(k) == v for k, v in filters.items())
        ]
        return sorted(rows, key=lambda r: r["created_at"], reverse=True)
