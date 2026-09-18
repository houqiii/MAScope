import argparse
import json
import os
from pathlib import Path

from .dataset import Dataset
from .download import download, fetch_sources
from .evaluation import Evaluator, JudgeValidationError, aggregate
from .model import OpenAICompatible
from .runner import load_agent, run
from .report import summarize_directories


def parser():
    root = argparse.ArgumentParser(prog="mascope")
    commands = root.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("download")
    fetch.add_argument("--base-url", default=os.getenv("MASCOPE_DATA_URL"))
    fetch.add_argument("--dest", default="data")
    fetch.add_argument(
        "--component", choices=["runtime", "evaluator", "all"], default="all"
    )
    sources = commands.add_parser("fetch-sources")
    sources.add_argument("--manifest", required=True)
    sources.add_argument("--dest", required=True)
    sources.add_argument("--site")
    summary = commands.add_parser("summarize")
    summary.add_argument("--evaluations", nargs="+", required=True)
    summary.add_argument("--out", required=True)
    for name in ["verify", "list", "run", "evaluate"]:
        command = commands.add_parser(name)
        command.add_argument("--runtime", required=True)
        if name in {"run", "evaluate"}:
            command.add_argument("--task-ids", nargs="+")
            command.add_argument("--out", required=True)
            command.add_argument("--base-url")
        if name == "run":
            command.add_argument("--agent", required=True)
            command.add_argument("--model", required=True)
            command.add_argument("--token-budget", type=int, default=2000000)
            command.add_argument("--call-budget", type=int, default=256)
            command.add_argument("--resume", action="store_true")
        if name == "evaluate":
            command.add_argument("--annotations", required=True)
            command.add_argument("--runs", required=True)
            command.add_argument("--judge-model", required=True)
    return root


def main():
    arguments = parser().parse_args()
    if arguments.command == "summarize":
        report = summarize_directories(arguments.evaluations)
        output = Path(arguments.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
        return
    if arguments.command == "download":
        if not arguments.base_url:
            raise SystemExit(
                "Provide --base-url or set MASCOPE_DATA_URL to the data release directory"
            )
        names = (
            ["runtime", "evaluator"]
            if arguments.component == "all"
            else [arguments.component]
        )
        for name in names:
            print(download(arguments.base_url, arguments.dest, name))
        return
    if arguments.command == "fetch-sources":
        print(fetch_sources(arguments.manifest, arguments.dest, arguments.site))
        return
    dataset = Dataset(arguments.runtime)
    if arguments.command == "verify":
        print(json.dumps(dataset.verify(), indent=2))
    elif arguments.command == "list":
        for task in dataset:
            print(
                json.dumps(
                    {"task_id": task.task_id, "query": task.query}, ensure_ascii=False
                )
            )
    elif arguments.command == "run":
        for record in run(
            dataset,
            load_agent(arguments.agent),
            OpenAICompatible(arguments.model, arguments.base_url),
            arguments.out,
            arguments.task_ids,
            arguments.token_budget,
            arguments.call_budget,
            arguments.resume,
        ):
            print(
                json.dumps(
                    {
                        "task_id": record["task_id"],
                        "status": record["status"],
                        "usage": record["usage"],
                    }
                )
            )
    elif arguments.command == "evaluate":
        evaluator = Evaluator(
            arguments.annotations,
            OpenAICompatible(arguments.judge_model, arguments.base_url),
        )
        tasks = (
            [dataset.task(x) for x in arguments.task_ids]
            if arguments.task_ids
            else list(dataset)
        )
        if len({t.task_id for t in tasks}) != len(tasks):
            raise ValueError("Duplicate task selection")
        missing = [
            t.task_id
            for t in tasks
            if not (Path(arguments.runs) / (t.task_id + ".json")).is_file()
        ]
        if missing:
            raise SystemExit(
                f"Missing {len(missing)} runs; select the intended task IDs explicitly"
            )
        output = Path(arguments.out)
        output.mkdir(parents=True, exist_ok=True)
        rows = []
        for task in tasks:
            record = json.loads(
                (Path(arguments.runs) / (task.task_id + ".json")).read_text()
            )
            try:
                row = evaluator.evaluate(task, record)
            except JudgeValidationError as exc:
                failure = {
                    "task_id": task.task_id,
                    "error": str(exc),
                    "judge_attempts": exc.attempts,
                    "judge_usage": exc.usage,
                }
                (output / (task.task_id + ".failed.json")).write_text(
                    json.dumps(failure, ensure_ascii=False, indent=2)
                )
                raise
            rows.append(row)
            (output / (task.task_id + ".json")).write_text(
                json.dumps(row, ensure_ascii=False, indent=2)
            )
            (output / (task.task_id + ".failed.json")).unlink(missing_ok=True)
        summary = aggregate(rows)
        summary["dataset_version"] = dataset.manifest["version"]
        summary["task_ids"] = [task.task_id for task in tasks]
        (output / "summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary, indent=2))
