import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from threading import RLock


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_jsonl(path):
    with Path(path).open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSON on line {number}") from exc


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tokens(text):
    return re.findall(r"[a-z0-9_+#.-]{2,}", text.lower())


@dataclass(frozen=True)
class Task:
    task_id: str
    query: str
    family_id: str | None = None


class Corpus:
    def __init__(self, path, agent_id):
        self.path = Path(path)
        self.agent_id = agent_id
        self._offsets = {}
        self._postings = {}
        self._lengths = {}
        self._lock = RLock()
        self._loaded = False

    def _load(self):
        with self._lock:
            if not self._loaded:
                self._build()
                self._loaded = True

    def _build(self):
        if self._loaded:
            return
        with self.path.open("rb") as stream:
            while True:
                offset = stream.tell()
                line = stream.readline()
                if not line:
                    break
                record = json.loads(line)
                ref = record["evidence_id"]
                if record["agent_id"] != self.agent_id or ref in self._offsets:
                    raise ValueError(
                        "Invalid corpus ownership or duplicate evidence ID"
                    )
                self._offsets[ref] = offset
                frequencies = Counter(
                    tokens(
                        record.get("question", record["title"]) + " " + record["text"]
                    )
                )
                self._lengths[ref] = sum(frequencies.values())
                for term, count in frequencies.items():
                    self._postings.setdefault(term, []).append((ref, count))

    def fetch(self, evidence_id):
        self._load()
        if evidence_id not in self._offsets:
            raise KeyError("Evidence is not available to this member")
        with self.path.open("rb") as stream:
            stream.seek(self._offsets[evidence_id])
            return json.loads(stream.readline())

    def _scores(self, query):
        self._load()
        terms = set(tokens(query))
        scores = {}
        n = len(self._offsets)
        average = sum(self._lengths.values()) / n if n else 1
        for term in sorted(terms):
            postings = self._postings.get(term, ())
            weight = math.log(1 + (n - len(postings) + 0.5) / (len(postings) + 0.5))
            for ref, frequency in postings:
                normalizer = 0.9 * (1 - 0.4 + 0.4 * self._lengths[ref] / (average or 1))
                scores[ref] = scores.get(ref, 0) + weight * frequency * 1.9 / (
                    frequency + normalizer
                )
        return scores

    def rank(self, query, evidence_ids):
        scores = self._scores(query)
        ranks = {}
        for evidence in evidence_ids:
            if evidence not in self._offsets:
                raise KeyError("Evidence is not available to this member")
            value = scores.get(evidence, 0)
            ranks[evidence] = 1 + sum(
                score > value or (score == value and ref < evidence)
                for ref in self._offsets
                for score in [scores.get(ref, 0)]
            )
        return ranks

    def search(self, query, limit=8):
        if not 1 <= limit <= 8:
            raise ValueError("Search limit must be between 1 and 8")
        scores = self._scores(query)
        ranked = sorted(self._offsets, key=lambda ref: (-scores.get(ref, 0), ref))[
            :limit
        ]
        return [self.fetch(ref) for ref in ranked]


class Dataset:
    def __init__(self, root):
        self.root = Path(root)
        self.manifest = read_json(self.root / "manifest.json")
        if self.manifest.get("schema_version") != "1.0":
            raise ValueError("Unsupported runtime schema")
        self._profiles = read_json(self.root / "profiles.json")
        self._tasks = {}
        for row in read_jsonl(self.root / "tasks.jsonl"):
            if not {"task_id", "query"} <= set(row) or set(row) - {
                "task_id",
                "query",
                "family_id",
            }:
                raise ValueError("Public tasks allow task_id, query and family_id only")
            if row["task_id"] in self._tasks:
                raise ValueError("Duplicate task ID")
            self._tasks[row["task_id"]] = Task(**row)
        ids = [p["agent_id"] for p in self._profiles]
        if len(ids) != len(set(ids)) or any(
            re.fullmatch(r"[a-z0-9_.-]+", x) is None for x in ids
        ):
            raise ValueError("Invalid agent identifiers")
        self._corpora = {
            agent: Corpus(self.root / "corpora" / (agent + ".jsonl"), agent)
            for agent in ids
        }

    def __len__(self):
        return len(self._tasks)

    def __iter__(self):
        return iter(self._tasks.values())

    def task(self, task_id):
        return self._tasks[task_id]

    def profiles(self):
        return json.loads(json.dumps(self._profiles))

    def corpus(self, agent_id):
        return self._corpora[agent_id]

    def verify(self):
        for name, expected in self.manifest.get("files", {}).items():
            path = (self.root / name).resolve()
            if not path.is_relative_to(self.root.resolve()) or sha256(path) != expected:
                raise ValueError(f"Integrity check failed: {name}")
        if (
            len(self) != self.manifest["query_count"]
            or len(self._profiles) != self.manifest["agent_count"]
        ):
            raise ValueError("Runtime counts disagree with manifest")
        return {
            "queries": len(self),
            "agents": len(self._profiles),
            "version": self.manifest["version"],
        }
