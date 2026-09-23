import gzip
import hashlib
import importlib.resources
import json
import os
import shutil
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path


def release_manifest():
    return json.loads(
        importlib.resources.files("mascope").joinpath("release.json").read_text()
    )


def unpack(archive, destination, prefix):
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        root = Path(temporary)
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
            names = [m.name for m in members]
            if (
                len(names) != len(set(names))
                or sum(m.size for m in members) > 4 * 1024**3
            ):
                raise ValueError("Invalid archive size or duplicate entries")
            for member in members:
                target = (root / member.name).resolve()
                if (
                    not target.is_relative_to(root.resolve())
                    or Path(member.name).parts[0] != prefix
                    or not (member.isfile() or member.isdir())
                ):
                    raise ValueError("Unsafe archive member")
            for member in members:
                target = root / member.name
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with (
                        bundle.extractfile(member) as source,
                        target.open("wb") as output,
                    ):
                        shutil.copyfileobj(source, output)
        if not (root / prefix / "manifest.json").is_file():
            raise ValueError("Archive has no manifest")
        (root / prefix).rename(destination)


def download(base_url=None, destination="data", component="runtime"):
    manifest = release_manifest()
    item = manifest["components"][component]
    parsed = urllib.parse.urlparse(base_url or "")
    rewritten_release = (
        parsed.hostname == "anonymous.4open.science"
        and parsed.path.startswith("/r/")
        and "/releases/" in parsed.path
    )
    if base_url and not rewritten_release:
        if parsed.scheme not in {"https", "http", "file"}:
            raise ValueError("Use an HTTP(S) or file URL")
        url = base_url.rstrip("/") + "/" + item["filename"]
    else:
        url = item["url"]
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/octet-stream",
            "User-Agent": "MAScope-data-downloader",
        },
    )
    with tempfile.TemporaryDirectory() as temporary:
        archive = Path(temporary) / item["filename"]
        digest = hashlib.sha256()
        size = 0
        with (
            urllib.request.urlopen(request, timeout=60) as response,
            archive.open("wb") as output,
        ):
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > item["size"]:
                    raise ValueError("Download exceeds expected size")
                digest.update(chunk)
                output.write(chunk)
        if size != item["size"] or digest.hexdigest() != item["sha256"]:
            raise ValueError("Download checksum mismatch")
        unpack(archive, Path(destination) / component, component)
    return str(Path(destination) / component)


def _api(path, params):
    params = {**params, "pagesize": 100, "filter": "withbody"}
    if os.getenv("STACKEXCHANGE_API_KEY"):
        params["key"] = os.environ["STACKEXCHANGE_API_KEY"]
    url = (
        "https://api.stackexchange.com/2.3/"
        + path
        + "?"
        + urllib.parse.urlencode(params)
    )
    with urllib.request.urlopen(url, timeout=60) as response:
        body = response.read()
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    result = json.loads(body)
    if "error_id" in result:
        raise RuntimeError(f"Source API returned error {result['error_id']}")
    if result.get("backoff"):
        time.sleep(result["backoff"])
    return result


def fetch_sources(manifest_path, destination, site=None):
    plan = json.loads(Path(manifest_path).read_text())
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for entry in plan["sites"]:
        if site is not None and entry["agent_id"] != site:
            continue
        path = destination / (entry["agent_id"] + ".jsonl")
        existing = set()
        if path.exists():
            with path.open() as stream:
                existing = {
                    json.loads(line)["evidence_id"] for line in stream if line.strip()
                }
        pending = [r for r in entry["records"] if r["evidence_id"] not in existing]
        for start in range(0, len(pending), 100):
            batch = pending[start : start + 100]
            ids = ";".join(str(r["answer_id"]) for r in batch)
            result = _api("answers/" + ids, {"site": entry["api_site_id"]})
            answers = {r["answer_id"]: r for r in result["items"]}
            with path.open("a", encoding="utf-8") as output:
                for record in batch:
                    answer = answers.get(record["answer_id"])
                    if answer is None:
                        continue
                    row = {
                        **record,
                        "agent_id": entry["agent_id"],
                        "text": answer["body"],
                        "content_format": "html",
                        "attribution": answer.get("owner", {}),
                        "content_license": answer.get("content_license"),
                        "creation_date": answer.get("creation_date"),
                        "last_edit_date": answer.get("last_edit_date"),
                    }
                    output.write(json.dumps(row, ensure_ascii=False) + "\n")
            missing = [r["evidence_id"] for r in batch if r["answer_id"] not in answers]
            if missing:
                raise RuntimeError(
                    f"{len(missing)} source answers are unavailable; saved all available answers"
                )
            if result.get("quota_remaining", 1) == 0 and start + 100 < len(pending):
                raise RuntimeError("Source API quota exhausted; rerun to resume")
            time.sleep(0.2)
    return str(destination)
