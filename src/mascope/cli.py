import argparse
import json
import os
from pathlib import Path

from .dataset import Dataset
from .deterministic import DeterministicEvaluator
from .download import download, fetch_sources
from .evaluation import aggregate
from .model import OpenAICompatible
from .report import summarize_directories
from .runner import load_agent, run


def parser():
    root = argparse.ArgumentParser(prog="mascope")
    commands = root.add_subparsers(dest="command", required=True)
    construct = commands.add_parser("certify-family")
    construct.add_argument("--runtime", required=True)
    construct.add_argument("--candidate", required=True)
    construct.add_argument("--validation", required=True)
    construct.add_argument("--out", required=True)
    fetch = commands.add_parser("download")
    fetch.add_argument("--base-url", default=os.getenv("MASCOPE_DATA_URL"))
    fetch.add_argument("--dest", default="data")
    fetch.add_argument(
        "--component", choices=["runtime", "evaluator", "all"], default="all"
    )
    validate = commands.add_parser("verify-references")
    validate.add_argument("--annotations", required=True)
    validate.add_argument("--runtime")
    validate.add_argument("--release", action="store_true")
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
        if name == "verify":
            command.add_argument("--paper")
            command.add_argument("--annotations")
            command.add_argument("--out", default="run_manifest.json")
        if name in {"run", "evaluate"}:
            command.add_argument("--task-ids", nargs="+")
            command.add_argument("--out", required=True)

        if name == "run":
            command.add_argument("--base-url")
            command.add_argument("--agent", required=True)
            command.add_argument("--model", required=True)
            command.add_argument("--token-budget", type=int, default=2000000)
            command.add_argument("--call-budget", type=int, default=256)
            command.add_argument("--resume", action="store_true")
            command.add_argument("--seed", type=int)
        if name == "evaluate":
            command.add_argument("--annotations", required=True)
            command.add_argument("--runs", required=True)
            command.add_argument(
                "--scorer",
                choices=["deterministic", "semantic"],
                default="deterministic",
            )
            command.add_argument("--judge-model")
            command.add_argument("--identifier-free", action="store_true")
    return root


def main():
    arguments = parser().parse_args()
    if arguments.command == "certify-family":
        from .pipeline import assess_family, freeze_family

        dataset = Dataset(arguments.runtime)
        candidate = json.loads(Path(arguments.candidate).read_text())
        validation = json.loads(Path(arguments.validation).read_text())
        corpora = {
            p["agent_id"]: dataset.corpus(p["agent_id"]) for p in dataset.profiles()
        }
        assessment = assess_family(candidate, corpora, dataset.profiles(), validation)
        output = Path(arguments.out)
        output.mkdir(parents=True, exist_ok=True)
        (output / "assessment.json").write_text(json.dumps(assessment, indent=2))
        if assessment["disposition"] != "freeze":
            print(assessment["disposition"])
            raise SystemExit(1)
        (output / "references.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in freeze_family(candidate, assessment))
        )
        print("freeze")
        return
    if arguments.command == "verify-references":
        evaluator = DeterministicEvaluator(arguments.annotations)
        if arguments.release:
            if not arguments.runtime or evaluator.manifest.get("scope") == "subset":
                raise ValueError(
                    "Full-release validation requires a runtime and complete references"
                )
            from .reference import validate_release

            validate_release(
                list(evaluator.references.values()), Dataset(arguments.runtime)
            )
        print(
            json.dumps(
                {**evaluator.inventory, "version": evaluator.manifest["version"]},
                indent=2,
            )
        )
        return
    if arguments.command == "summarize":
        report = summarize_directories(arguments.evaluations)
        output = Path(arguments.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
        return
    if arguments.command == "download":
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
        if arguments.paper:
            from .verification import verify_paper

            if not arguments.annotations:
                raise ValueError("--paper requires --annotations")
            report = verify_paper(
                arguments.runtime, arguments.annotations, arguments.paper, arguments.out
            )
            for check in report["checks"]:
                print(f"{check['status']} {check['check']}")
            print(
                json.dumps(
                    {
                        "passed": report["passed"],
                        "failed": report["failed"],
                        "local_solvability": report["local_solvability_coverage"],
                    },
                    indent=2,
                )
            )
            if report["failed"]:
                raise SystemExit(1)
        else:
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
            OpenAICompatible(arguments.model, arguments.base_url, seed=arguments.seed),
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
        if arguments.scorer == "semantic":
            from .legacy_semantic import Evaluator

            if not arguments.judge_model or arguments.identifier_free:
                raise ValueError(
                    "Legacy semantic scoring needs --judge-model and does not support identifier-free scoring"
                )
            evaluator = Evaluator(
                arguments.annotations, OpenAICompatible(arguments.judge_model)
            )
        else:
            if arguments.judge_model:
                raise ValueError("The deterministic scorer does not use a judge model")
            evaluator = DeterministicEvaluator(
                arguments.annotations, identifier_free=arguments.identifier_free
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
        strict_rows = []
        strict_evaluator = (
            DeterministicEvaluator(arguments.annotations)
            if arguments.identifier_free
            else None
        )
        for task in tasks:
            record = json.loads(
                (Path(arguments.runs) / (task.task_id + ".json")).read_text()
            )
            try:
                row = evaluator.evaluate(task, record)
            except ValueError as exc:
                (output / (task.task_id + ".failed.json")).write_text(
                    json.dumps({"task_id": task.task_id, "error": str(exc)}, indent=2)
                )
                raise
            if strict_evaluator is not None:
                strict_rows.append(strict_evaluator.evaluate(task, record))
            rows.append(row)
            (output / (task.task_id + ".json")).write_text(
                json.dumps(row, ensure_ascii=False, indent=2)
            )
            (output / (task.task_id + ".failed.json")).unlink(missing_ok=True)
        summary = aggregate(rows)
        if strict_rows:
            strict = aggregate(strict_rows)
            summary["identifier_comparison"] = {
                "strict_success": strict["success"],
                "identifier_free_success": summary["success"],
                "success_gain_points": summary["success"] - strict["success"],
                "strict_dependency_drop": strict["dependency_success_drop"],
                "identifier_free_dependency_drop": summary["dependency_success_drop"],
            }
        summary["dataset_version"] = dataset.manifest["version"]
        summary["scorer_version"] = rows[0]["scorer_version"]
        summary["task_ids"] = [task.task_id for task in tasks]
        (output / "summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary, indent=2))
