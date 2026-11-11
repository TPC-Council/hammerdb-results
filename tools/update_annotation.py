#!/usr/bin/env python3
"""Create or update separate, reviewable benchmark annotations.

Accepts either command-line options or a JSON request (--input FILE/-).
Writes only to submissions/annotations/<jobid>.json. Does not change results/.
Pull-request validation determines who may change company/workload metadata.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
JOB_ID = re.compile(r"^[A-Za-z0-9_-]{5,80}$")
ACCOUNT = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?(?:\[bot\])?$")
PROFILES = {"unclassified", "cpu-intensive", "io-intensive"}
DURABILITY = {"unknown", "full", "relaxed"}


def account_valid(login: object) -> bool:
    return (isinstance(login, str) and bool(ACCOUNT.fullmatch(login))
            and "--" not in login and len(login) <= 45)


def _published_result(root: Path, jobid: str) -> dict:
    matches = sorted((root / "results").rglob(jobid + ".json"))
    if len(matches) != 1:
        raise ValueError(
            f"Expected one published result for {jobid}; found {len(matches)}. "
            "Only existing, unambiguous results can be annotated."
        )
    artifact = json.loads(matches[0].read_text(encoding="utf-8"))
    if (artifact.get("job") or {}).get("jobid") != jobid:
        raise ValueError("Artifact job ID does not match its filename")
    return artifact


def _original_account(root: Path, artifact: dict, jobid: str) -> str:
    submission = artifact.get("submission") or {}
    if not isinstance(submission, dict):
        raise ValueError("Invalid submission metadata")
    username = submission.get("github_username")
    if not username:
        path = root / "submissions" / "legacy-attribution.json"
        legacy = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        item = legacy.get(jobid, {})
        username = item.get("github_username") if isinstance(item, dict) else None
    if not account_valid(username):
        raise ValueError(f"No verified original GitHub submitter is recorded for {jobid}")
    return username


def _company_check(company: dict) -> None:
    if not isinstance(company, dict):
        raise ValueError("company must be an object")
    for name, limit in (("name", 120), ("description", 350), ("logo_url", 500)):
        value = company.get(name, "")
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError(f"company.{name} must be a string with at most {limit} characters")
    logo = company.get("logo_url", "")
    if logo:
        try:
            parsed = urlsplit(logo)
            valid = (parsed.scheme == "https" and bool(parsed.hostname)
                     and not parsed.username and not parsed.password)
        except ValueError:
            valid = False
        if not valid or not company.get("name"):
            raise ValueError("A company logo requires a company name and a public HTTPS URL")


def _workload_check(workload: dict, artifact: dict) -> None:
    if (artifact.get("job") or {}).get("benchmark") != "TPROC-C":
        raise ValueError("Workload classifications are only supported for TPROC-C")
    if not isinstance(workload, dict):
        raise ValueError("workload must be an object")
    classification = workload.get("classification", "unclassified")
    uaw = workload.get("use_all_warehouses")
    durability = workload.get("durability", "unknown")
    details = workload.get("details", "")
    if classification not in PROFILES:
        raise ValueError("Invalid workload classification")
    if uaw is not None and type(uaw) is not bool:
        raise ValueError("use_all_warehouses must be true, false or null")
    if durability not in DURABILITY:
        raise ValueError("Invalid workload durability")
    if not isinstance(details, str) or len(details) > 1200:
        raise ValueError("Workload details must be a string with at most 1200 characters")
    if classification != "unclassified":
        if len(details.strip()) < 20:
            raise ValueError("Classified workloads require 20+ characters of configuration evidence")
        if classification == "io-intensive" and (uaw is not True or durability != "full"):
            raise ValueError("I/O-intensive requires UAW enabled and full durability")
        if classification == "cpu-intensive" and (uaw is not False or durability not in ("full", "relaxed")):
            raise ValueError("CPU-intensive requires UAW disabled and declared durability")
    config = artifact.get("benchmark_config") or {}
    if isinstance(config, dict) and type(uaw) is bool:
        for key in ("use_all_warehouses", "all_warehouses", "uaw"):
            if type(config.get(key)) is bool and config[key] != uaw:
                raise ValueError(f"Declared UAW contradicts benchmark_config.{key}")


def make_annotation(root: Path, request: dict) -> tuple[Path, dict, bool]:
    """Prepare one additive annotation without writing to disk."""
    if not isinstance(request, dict):
        raise ValueError("Request must be a JSON object")
    allowed = {"jobid", "author", "comment", "company", "workload"}
    if set(request) - allowed:
        raise ValueError("Unknown request keys: " + ", ".join(sorted(set(request) - allowed)))
    jobid = request.get("jobid")
    author = request.get("author")
    if not isinstance(jobid, str) or not JOB_ID.fullmatch(jobid):
        raise ValueError("jobid is required and must be a valid published job ID")
    if not account_valid(author):
        raise ValueError("author must be the GitHub login that will open the pull request")
    artifact = _published_result(root, jobid)
    original = _original_account(root, artifact, jobid)
    path = root / "submissions" / "annotations" / (jobid + ".json")
    existing = path.exists()
    previous = json.loads(path.read_text(encoding="utf-8")) if existing else {}
    if not isinstance(previous, dict):
        raise ValueError("Existing annotation must be an object")
    if existing and (previous.get("jobid") != jobid or
                     str(previous.get("github_username", "")).casefold() != original.casefold()):
        raise ValueError("Existing annotation provenance does not match the original result")
    output = copy.deepcopy(previous) if existing else {"jobid": jobid, "github_username": original}
    changed = False

    if "comment" in request:
        comment = request["comment"]
        if not isinstance(comment, str) or not comment.strip() or len(comment) > 4000:
            raise ValueError("comment must be nonempty text of at most 4000 characters")
        comments = output.setdefault("comments", [])
        if not isinstance(comments, list) or len(comments) >= 30:
            raise ValueError("Maximum 30 comments per result")
        comments.append({"github_username": author, "text": comment.strip()})
        changed = True

    if "company" in request:
        patch = request["company"]
        if not isinstance(patch, dict) or not patch or set(patch) - {"name", "description", "logo_url"}:
            raise ValueError("company must contain recognised fields")
        company = copy.deepcopy(output.get("company") or {})
        for key, value in patch.items():
            company[key] = value
        _company_check(company)
        if company != output.get("company", {}):
            output["company"] = company
            changed = True

    if "workload" in request:
        patch = request["workload"]
        if not isinstance(patch, dict) or not patch or set(patch) - {
            "classification", "use_all_warehouses", "durability", "details"
        }:
            raise ValueError("workload must contain recognised fields")
        workload = copy.deepcopy(output.get("workload") or {})
        workload.update(patch)
        _workload_check(workload, artifact)
        if workload != output.get("workload"):
            output["workload"] = workload
            changed = True

    if not changed:
        raise ValueError("No new comment or changed company/workload fields")
    if "company" in output:
        _company_check(output["company"])
    if "workload" in output:
        _workload_check(output["workload"], artifact)
    if not any([output.get("comments"), output.get("company", {}).get("name"),
                output.get("company", {}).get("description"), output.get("workload")]):
        raise ValueError("Annotation needs a comment, company information, or workload settings")
    return path, output, existing


def _request_from_args(args: argparse.Namespace) -> dict:
    if args.input is not None:
        if any(x is not None for x in (
            args.jobid, args.author, args.comment, args.company_name,
            args.company_description, args.company_logo_url, args.classification,
            args.uaw, args.durability, args.details
        )):
            raise ValueError("--input cannot be combined with individual fields")
        with sys.stdin if args.input == "-" else open(args.input, encoding="utf-8") as handle:
            return json.load(handle)
    req = {"jobid": args.jobid, "author": args.author}
    if args.comment is not None:
        req["comment"] = args.comment
    company = {}
    for name, value in (
        ("name", args.company_name), ("description", args.company_description),
        ("logo_url", args.company_logo_url)
    ):
        if value is not None:
            company[name] = value
    if company:
        req["company"] = company
    workload = {}
    for key, value in (
        ("classification", args.classification),
        ("use_all_warehouses", {"enabled": True, "disabled": False, "unknown": None}.get(args.uaw)
         if args.uaw is not None else None),
        ("durability", args.durability),
        ("details", args.details),
    ):
        if value is not None or (key == "use_all_warehouses" and args.uaw == "unknown"):
            workload[key] = value
    if workload:
        req["workload"] = workload
    return req


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare comments and metadata for a result PR")
    parser.add_argument("--input", metavar="FILE", help="JSON request file; - reads stdin")
    parser.add_argument("--jobid")
    parser.add_argument("--author", help="GitHub login that opens the PR")
    parser.add_argument("--comment")
    parser.add_argument("--company-name")
    parser.add_argument("--company-description")
    parser.add_argument("--company-logo-url")
    parser.add_argument("--classification", choices=sorted(PROFILES))
    parser.add_argument("--uaw", choices=("enabled", "disabled", "unknown"))
    parser.add_argument("--durability", choices=sorted(DURABILITY))
    parser.add_argument("--details", help="Evidence supporting the workload selection")
    parser.add_argument("--dry-run", action="store_true", help="Preview JSON without writing")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        request = _request_from_args(args)
        path, output, existed = make_annotation(args.repo_root, request)
        if not args.dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            text = json.dumps(output, indent=2, ensure_ascii=False) + "\n"
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=".annotation-", suffix=".tmp", delete=False
            ) as tmp:
                tmp.write(text)
                temp_path = Path(tmp.name)
            try:
                os.replace(temp_path, path)
            finally:
                temp_path.unlink(missing_ok=True)
        response = {
            "path": path.relative_to(args.repo_root).as_posix(),
            "action": "preview" if args.dry_run else ("updated" if existed else "created"),
            "jobid": request["jobid"],
            "comment_count": len(output.get("comments", [])),
            "requires_pull_request": True,
        }
        if args.dry_run:
            response["annotation"] = output
        print(json.dumps(response, ensure_ascii=False))
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
