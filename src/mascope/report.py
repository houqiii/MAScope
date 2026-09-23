import statistics
from pathlib import Path

from .dataset import read_json
from .evaluation import aggregate

METRICS = (
    "success",
    "evidence_coverage",
    "expert_recall",
    "expert_precision",
    "task_orchestration",
    "information_transfer",
    "local_solve",
    "result_integration",
    "dependency_survival",
    "mean_calls",
    "mean_tokens",
)


def summarize_runs(runs):
    runs = [list(rows) for rows in runs]
    if not runs or any(not rows for rows in runs):
        raise ValueError("Expected nonempty evaluation runs")
    summaries = [aggregate(rows) for rows in runs]
    identities = []
    versions = set()
    for rows in runs:
        identity = {}
        for row in rows:
            if not row.get("dataset_version"):
                raise ValueError("Evaluation records must include dataset_version")
            versions.add(row["dataset_version"])
            identity[row["task_id"]] = (
                row["family_id"],
                row["instance_id"],
                row["cell"],
                row["required_experts"],
                row.get("scorer_version", "legacy"),
                row.get("reference_sha256"),
            )
        identities.append(identity)
    if len(versions) != 1 or any(x != identities[0] for x in identities[1:]):
        raise ValueError("Repeated runs must use the same version and task references")

    def combine(items):
        result = {}
        for metric in METRICS:
            values = [item[metric] for item in items]
            known = [v for v in values if v is not None]
            complete = len(known) == len(values)
            result[metric] = {
                "mean": statistics.mean(known) if complete else None,
                "std": statistics.stdev(known) if complete and len(known) > 1 else None,
                "values": values,
            }
        return result

    result = {
        "dataset_version": next(iter(versions)),
        "scorer_version": runs[0][0].get("scorer_version", "legacy"),
        "runs": len(runs),
        "queries_per_run": len(runs[0]),
        "metrics": combine(summaries),
    }
    for group in ("by_cell", "by_structure", "by_scale"):
        result[group] = {
            name: combine([item[group][name] for item in summaries])
            for name in summaries[0][group]
        }
    return result


def summarize_directories(directories):
    paths = [Path(directory).resolve() for directory in directories]
    if len(paths) != len(set(paths)):
        raise ValueError("Duplicate evaluation directory")
    runs = []
    for path in paths:
        if not path.is_dir():
            raise ValueError("Evaluation directory does not exist")
        if list(path.glob("*.failed.json")):
            raise ValueError("Resolve failed judgments before summarizing")
        manifest = read_json(path / "summary.json")
        ids = manifest.get("task_ids", [])
        if not ids or len(ids) != len(set(ids)) or len(ids) != manifest.get("n"):
            raise ValueError("Evaluation summary must identify its complete task set")
        rows = []
        for task_id in ids:
            filename = path / (task_id + ".json")
            if filename.resolve().parent != path:
                raise ValueError("Invalid task identifier in evaluation summary")
            row = read_json(filename)
            if row["task_id"] != task_id or row.get("dataset_version") != manifest.get(
                "dataset_version"
            ):
                raise ValueError("Evaluation record disagrees with summary")
            rows.append(row)
        runs.append(rows)
    return summarize_runs(runs)
