#!/usr/bin/env python3
"""Build the public leaderboard data from immutable HammerDB result artifacts.

The HTML is a static client-side view: its styling and interactions live in
site/index.html, site/leaderboard.css and site/leaderboard.js.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit
from datetime import datetime, timezone
from pathlib import Path

from result_validation import format_validation_failure, validate_artifacts

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_ROOT = REPO_ROOT / "results"
SITE_ROOT = REPO_ROOT / "site"
LEADERBOARD_JSON = SITE_ROOT / "leaderboard.json"
INDEX_HTML = SITE_ROOT / "index.html"
SUPPORTED_TPROC_H_SCALE_FACTORS = (1, 10, 30, 100, 300, 1000, 3000, 10000, 30000, 100000)


def _legacy_attribution() -> dict:
    path = REPO_ROOT / "submissions" / "legacy-attribution.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))



ANNOTATIONS_DIR = REPO_ROOT / "submissions" / "annotations"
GH_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
COMMENT_AUTHOR = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?(?:\[bot\])?$")
JOB_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{5,80}$")


def _annotations() -> dict[str, dict]:
    """Optional, separately reviewed submitter notes; never alter result artifacts."""
    out: dict[str, dict] = {}
    directory = REPO_ROOT / "submissions" / "annotations"
    if not directory.exists():
        return out
    for file in sorted(directory.glob("*.json")):
        note = json.loads(file.read_text(encoding="utf-8"))
        if not isinstance(note, dict):
            raise ValueError(f"{file}: annotation must be an object")
        jobid = note.get("jobid")
        username = note.get("github_username")
        if not isinstance(jobid, str) or not JOB_IDENTIFIER.fullmatch(jobid) or file.stem != jobid:
            raise ValueError(f"{file}: jobid does not match filename")
        if not isinstance(username, str) or not GH_LOGIN.fullmatch(username) or "--" in username:
            raise ValueError(f"{file}: invalid github_username")
        company = note.get("company", {})
        if not isinstance(company, dict):
            raise ValueError(f"{file}: company must be an object")
        for key, limit in (("name", 120), ("description", 350), ("logo_url", 500)):
            value = company.get(key, "")
            if not isinstance(value, str) or len(value) > limit:
                raise ValueError(f"{file}: invalid company.{key}")
        logo = company.get("logo_url", "")
        if logo:
            try:
                url = urlsplit(logo)
                allowed = url.scheme == "https" and bool(url.hostname) and not url.username and not url.password
            except ValueError:
                allowed = False
            if not allowed or not company.get("name"):
                raise ValueError(f"{file}: logo requires company name and a public HTTPS URL")
        comments = note.get("comments", [])
        if not isinstance(comments, list) or len(comments) > 30:
            raise ValueError(f"{file}: comments must be an array (maximum 30 entries)")
        for comment in comments:
            if isinstance(comment, str):  # Pre-existing original-submitters' notes
                valid = bool(comment.strip()) and len(comment) <= 4000
            elif isinstance(comment, dict):
                author = comment.get("github_username")
                text = comment.get("text")
                valid = (
                    isinstance(author, str) and bool(COMMENT_AUTHOR.fullmatch(author)) and "--" not in author
                    and isinstance(text, str) and bool(text.strip()) and len(text) <= 4000
                )
            else:
                valid = False
            if not valid:
                raise ValueError(f"{file}: invalid or unattributed comment")
        workload = note.get("workload")
        if workload is not None:
            if not isinstance(workload, dict):
                raise ValueError(f"{file}: workload must be an object")
            classification = workload.get("classification", "unclassified")
            uaw = workload.get("use_all_warehouses")
            durability = workload.get("durability", "unknown")
            details = workload.get("details", "")
            if classification not in ("unclassified", "cpu-intensive", "io-intensive"):
                raise ValueError(f"{file}: invalid workload classification")
            if uaw is not None and type(uaw) is not bool:
                raise ValueError(f"{file}: UAW must be boolean or null")
            if durability not in ("unknown", "full", "relaxed") or not isinstance(details, str) or len(details) > 1200:
                raise ValueError(f"{file}: invalid workload durability or details")
            if classification in ("cpu-intensive", "io-intensive") and len(details.strip()) < 20:
                raise ValueError(f"{file}: classified workloads require 20+ characters of configuration evidence")
            if classification == "cpu-intensive" and (uaw is not False or durability not in ("full", "relaxed")):
                raise ValueError(f"{file}: CPU-intensive requires UAW disabled and declared durability")
            if classification == "io-intensive" and (uaw is not True or durability != "full"):
                raise ValueError(f"{file}: I/O-intensive requires UAW enabled and full durability")
        if not any([company.get("name"), company.get("description"), comments, workload]):
            raise ValueError(f"{file}: add company information, a comment or workload settings")
        out[jobid] = note
    return out


def _submission_fields(payload: dict, legacy: dict, annotations: dict | None = None) -> dict:
    """Keep submission declarations distinct from measurements in the artifact.

    Performance telemetry cannot establish whether a run was configured to
    stress CPU or storage. The declaration is only displayed if UAW and
    durability evidence is supplied and consistent.
    """
    job = payload.get("job") or {}
    submission = payload.get("submission")
    submission = submission if isinstance(submission, dict) else {}
    company = submission.get("company")
    company = company if isinstance(company, dict) else {}
    workload = submission.get("workload")
    workload = workload if isinstance(workload, dict) else {}
    legacy_info = legacy.get(job.get("jobid"), {})
    if not isinstance(legacy_info, dict):
        legacy_info = {}
    annotation = (annotations or {}).get(job.get("jobid"), {})
    if annotation:
        expected = submission.get("github_username") or legacy_info.get("github_username")
        if not expected or expected.casefold() != annotation["github_username"].casefold():
            raise ValueError(f"Invalid annotation owner for job {job.get('jobid')!r}")
    extra_company = annotation.get("company", {}) if annotation else {}

    submitter = submission.get("github_username") or legacy_info.get("github_username")
    attribution = ("submission" if submission.get("github_username") else
                   "original-pr" if legacy_info.get("github_username") else "unknown")
    # A separately reviewed annotation overrides the declaration without
    # changing the immutable original result JSON.
    annotation_workload = annotation.get("workload") if annotation else None
    effective = annotation_workload if isinstance(annotation_workload, dict) else workload
    kind = effective.get("classification", "unclassified")
    uaw = effective.get("use_all_warehouses")
    durability = effective.get("durability", "unknown")
    details = str(effective.get("details") or "").strip()
    benchmark = job.get("benchmark")

    if benchmark != "TPROC-C":
        kind = "unclassified"
    elif kind == "io-intensive":
        if uaw is not True or durability != "full" or not details:
            kind = "unclassified"
    elif kind == "cpu-intensive":
        if uaw is not False or durability not in ("full", "relaxed") or not details:
            kind = "unclassified"
    else:
        kind = "unclassified"

    return {
        "submitted_by": submitter,
        "attribution_source": attribution,
        "submission_pr_url": legacy_info.get("pr_url"),
        "original_pr_description": legacy_info.get("pr_description"),
        "submitter_comments": annotation.get("comments", []) if annotation else [],
        "annotation_exists": bool(annotation),
        "annotation_company": annotation.get("company", {}) if annotation else {},
        "annotation_workload": annotation_workload if isinstance(annotation_workload, dict) else None,
        "company_name": extra_company.get("name") or company.get("name"),
        "company_logo_url": extra_company.get("logo_url") or company.get("logo_url"),
        "company_description": extra_company.get("description") or company.get("description"),
        "result_description": submission.get("description"),
        "workload_class": kind,
        "workload_uaw": uaw if type(uaw) is bool else None,
        "workload_durability": durability,
        "workload_details": details or None,
        "workload_attribution": ("author-or-maintainer-declared" if annotation_workload is not None else "submitter-declared")
                                if kind != "unclassified" else "not supplied",
    }


def _load_rows() -> list[dict]:
    legacy = _legacy_attribution()
    annotations = _annotations()
    rows: list[dict] = []
    for fp in sorted(RESULTS_ROOT.rglob("*.json")):
        rel = fp.relative_to(REPO_ROOT).as_posix()
        payload = json.loads(fp.read_text(encoding="utf-8"))
        job = payload.get("job") or {}
        cfg = payload.get("benchmark_config") or {}
        res = payload.get("result") or {}
        system = payload.get("system") or {}
        row = {
            "jobid": job.get("jobid"),
            "benchmark": job.get("benchmark"),
            "database": job.get("database"),
            "database_display": job.get("database_display"),
            "release": job.get("release"),
            "timestamp": job.get("timestamp"),
            "hdb_version": job.get("hdb_version"),
            "nopm": res.get("nopm"),
            "tpm": res.get("tpm"),
            "geomean_seconds": res.get("geomean_seconds"),
            "total_query_time_seconds": res.get("total_query_time_seconds"),
            "warehouses": cfg.get("warehouses"),
            "virtual_users": cfg.get("virtual_users"),
            "rampup_minutes": cfg.get("rampup_minutes"),
            "duration_minutes": cfg.get("duration_minutes"),
            "scale_factor": cfg.get("scale_factor"),
            "cpu_model": system.get("cpumodel"),
            "cpu_count": system.get("cpucount"),
            "memory": system.get("memory"),
            "os_name": system.get("os_name"),
            "source_path": rel,
        }
        row.update(_submission_fields(payload, legacy, annotations))
        rows.append(row)

    # Reject annotations contradicting values explicitly recorded in the artifact.
    for row in rows:
        annotation = annotations.get(row["jobid"])
        if not annotation or not isinstance(annotation.get("workload"), dict):
            continue
        if row["benchmark"] != "TPROC-C":
            raise ValueError(f"{row['jobid']}: workload classification is only supported for TPROC-C")
        original = json.loads((REPO_ROOT / row["source_path"]).read_text(encoding="utf-8"))
        config = original.get("benchmark_config") or {}
        declared = annotation["workload"].get("use_all_warehouses")
        for key in ("use_all_warehouses", "all_warehouses", "uaw"):
            if type(config.get(key)) is bool and type(declared) is bool and config[key] != declared:
                raise ValueError(f"{row['jobid']}: workload UAW contradicts artifact benchmark_config.{key}")

    unknown = set(annotations) - {row["jobid"] for row in rows}
    if unknown:
        raise ValueError("Annotations reference unpublished jobs: " + ", ".join(sorted(unknown)))

    def sort_key(row: dict):
        if row["benchmark"] == "TPROC-H":
            metric = row.get("geomean_seconds")
            return ("TPROC-H", metric is None, metric if isinstance(metric, (int, float)) else float("inf"), row.get("jobid") or "")
        metric = row.get("nopm")
        return (row.get("benchmark") or "", metric is None, -(metric or 0), row.get("jobid") or "")

    rows.sort(key=sort_key)
    rank_by_benchmark: dict[str, int] = {}
    for row in rows:
        benchmark = row.get("benchmark") or "Unknown"
        rank_by_benchmark[benchmark] = rank_by_benchmark.get(benchmark, 0) + 1
        row["rank"] = rank_by_benchmark[benchmark]
    return rows


def _write_json(rows: list[dict]) -> None:
    SITE_ROOT.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "title": "HammerDB Community Benchmark Leaderboard",
        "disclaimer": [
            "Community-submitted HammerDB results",
            "Unaudited; not official TPC benchmark results",
            "CPU- and I/O-focused badges describe submitter-declared configurations, not proven hardware bottlenecks",
        ],
        "rows": rows,
    }
    LEADERBOARD_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    validation = validate_artifacts(REPO_ROOT, RESULTS_ROOT)
    if not validation.ok:
        print(format_validation_failure(validation.errors))
        return 1
    _write_json(_load_rows())
    if not INDEX_HTML.exists():
        # Tests with a temporary repository may intentionally omit the website.
        print("Warning: site/index.html not found; static web interface is not present.")
    print(f"Generated {LEADERBOARD_JSON.relative_to(REPO_ROOT)} with {validation.json_file_count} result(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
