#!/usr/bin/env python3
"""Shared validation helpers for HammerDB result artifacts."""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

EXPECTED_SCHEMA = "hammerdb-job-report-v1"
VALID_BENCHMARKS = {"TPROC-C", "TPROC-H"}
DUPLICATE_UPLOAD_RE = re.compile(r"\s*\(\d+\)$")


@dataclass(frozen=True)
class ValidationResult:
    errors: list[str]
    json_file_count: int

    @property
    def ok(self) -> bool:
        return not self.errors


def as_slug(value: str) -> str:
    """Convert values like 'SQL Server' into filesystem-safe lowercase slugs."""
    slug = value.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def parse_timestamp(raw: str) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _display(value: Any) -> str:
    if value is None:
        return "<missing>"
    return str(value)


def _canonical_database(job: dict[str, Any]) -> Any:
    return job.get("database_display") or job.get("database")


def canonical_result_path(job: dict[str, Any]) -> Path | None:
    """Derive results/<benchmark>/<database>/<year>/<month>/<jobid>.json from JSON job fields."""
    benchmark = job.get("benchmark")
    database = _canonical_database(job)
    timestamp_raw = job.get("timestamp")
    jobid = job.get("jobid")

    if not all(isinstance(v, str) and v for v in (benchmark, database, timestamp_raw, jobid)):
        return None

    parsed = parse_timestamp(timestamp_raw)
    if parsed is None:
        return None

    return (
        Path("results")
        / as_slug(benchmark)
        / as_slug(database)
        / parsed.strftime("%Y")
        / parsed.strftime("%m")
        / f"{jobid}.json"
    )


def _path_mismatch_error(rel_path: Path, job: dict[str, Any], expected: Path) -> str:
    benchmark = job.get("benchmark")
    database = _canonical_database(job)
    timestamp = job.get("timestamp")
    jobid = job.get("jobid")
    return (
        f"{rel_path.as_posix()}: artifact path does not match canonical path derived from JSON; "
        f"actual path: {rel_path.as_posix()}; "
        f"benchmark found in JSON: {_display(benchmark)}; "
        f"database found in JSON: {_display(database)}; "
        f"timestamp found in JSON: {_display(timestamp)}; "
        f"jobid found in JSON: {_display(jobid)}; "
        f"expected canonical path: {expected.as_posix()}"
    )


def _duplicate_upload_error(rel_path: Path, expected: Path) -> str | None:
    if DUPLICATE_UPLOAD_RE.search(rel_path.stem):
        return (
            f"{rel_path.as_posix()}: filename looks like a duplicate browser/GitHub upload; "
            f"delete this duplicate artifact or rename it to the canonical path {expected.as_posix()}"
        )
    return None


def _iter_json_files(results_root: Path) -> Iterable[Path]:
    return sorted(results_root.rglob("*.json"))



GH_USERNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
VALID_WORKLOADS = {"unclassified", "cpu-intensive", "io-intensive"}
VALID_DURABILITY = {"unknown", "full", "relaxed"}


def _validate_submission_metadata(payload: dict, rel_path: Path) -> list[str]:
    """Optional, additive fields: do not reject unannotated historical artifacts."""
    errors: list[str] = []
    label = rel_path.as_posix()
    if "submission" not in payload:
        return errors

    submission = payload["submission"]
    if not isinstance(submission, dict):
        return [f"{label}: field 'submission' must be an object"]

    username = submission.get("github_username")
    if (not isinstance(username, str) or not GH_USERNAME_RE.fullmatch(username)
            or "--" in username):
        errors.append(f"{label}: field 'submission.github_username' must be a valid GitHub username")

    value = submission.get("description", "")
    if not isinstance(value, str) or len(value) > 2000:
        errors.append(f"{label}: field 'submission.description' must be a string of at most 2000 characters")

    company = submission.get("company", {})
    if not isinstance(company, dict):
        errors.append(f"{label}: field 'submission.company' must be an object")
        company = {}
    for field, limit in (("name", 120), ("logo_url", 500), ("description", 350)):
        value = company.get(field, "")
        if not isinstance(value, str) or len(value) > limit:
            errors.append(f"{label}: field 'submission.company.{field}' must be a string of at most {limit} characters")

    logo = company.get("logo_url", "")
    if isinstance(logo, str) and logo:
        try:
            parsed = urlparse(logo)
            valid_logo = parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password
        except ValueError:
            valid_logo = False
        if not valid_logo:
            errors.append(f"{label}: field 'submission.company.logo_url' must be a public HTTPS URL")
        if not company.get("name"):
            errors.append(f"{label}: field 'submission.company.name' is required when providing a logo")

    workload = submission.get("workload")
    if workload is None:
        return errors
    if not isinstance(workload, dict):
        return errors + [f"{label}: field 'submission.workload' must be an object"]

    classification = workload.get("classification", "unclassified")
    uaw = workload.get("use_all_warehouses")
    durability = workload.get("durability", "unknown")
    details = workload.get("details", "")
    if not isinstance(classification, str) or classification not in VALID_WORKLOADS:
        errors.append(f"{label}: invalid submission workload classification")
    if uaw is not None and type(uaw) is not bool:
        errors.append(f"{label}: submission workload use_all_warehouses must be true, false or null")
    if not isinstance(durability, str) or durability not in VALID_DURABILITY:
        errors.append(f"{label}: invalid submission workload durability")
    if not isinstance(details, str) or len(details) > 1200:
        errors.append(f"{label}: submission workload details must be a string of at most 1200 characters")
        details = ""

    job = payload.get("job")
    job = job if isinstance(job, dict) else {}
    cfg = payload.get("benchmark_config") or {}
    if classification != "unclassified":
        if job.get("benchmark") != "TPROC-C":
            errors.append(f"{label}: CPU/I/O classifications are supported only for TPROC-C")
        if len(details.strip()) < 20:
            errors.append(f"{label}: classified TPROC-C workload requires configuration evidence (20+ characters)")
        if classification == "io-intensive" and (uaw is not True or durability != "full"):
            errors.append(f"{label}: I/O-focused classification requires UAW enabled and full durability")
        if classification == "cpu-intensive" and (uaw is not False or durability not in ("full", "relaxed")):
            errors.append(f"{label}: CPU-focused classification requires UAW disabled and declared durability")

    for field in ("use_all_warehouses", "all_warehouses", "uaw"):
        if not isinstance(cfg, dict) or field not in cfg:
            continue
        recorded = cfg.get(field)
        if type(recorded) is bool and type(uaw) is bool and recorded != uaw:
            errors.append(f"{label}: declared UAW conflicts with benchmark_config.{field}")
    return errors


def validate_artifacts(repo_root: Path, results_root: Path) -> ValidationResult:
    """Validate all JSON artifacts under results_root without inferring fields from paths."""
    errors: list[str] = []
    jobid_to_path: dict[str, Path] = {}

    json_files = list(_iter_json_files(results_root))
    for file_path in json_files:
        rel_path = file_path.relative_to(repo_root)
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{rel_path.as_posix()}: invalid JSON ({exc})")
            continue

        if not isinstance(payload, dict):
            errors.append(f"{rel_path.as_posix()}: artifact JSON root must be an object")
            continue

        if payload.get("schema") != EXPECTED_SCHEMA:
            errors.append(f"{rel_path.as_posix()}: field 'schema' must equal '{EXPECTED_SCHEMA}'")

        disclaimer = payload.get("disclaimer")
        if not isinstance(disclaimer, dict):
            errors.append(f"{rel_path.as_posix()}: field 'disclaimer' must exist and be an object")
        elif disclaimer.get("audited") is not False:
            errors.append(f"{rel_path.as_posix()}: field 'disclaimer.audited' must be false")

        errors.extend(_validate_submission_metadata(payload, rel_path))

        job = payload.get("job")
        if not isinstance(job, dict):
            errors.append(f"{rel_path.as_posix()}: field 'job' must exist and be an object")
            continue

        required_job_fields = [
            "jobid",
            "hdb_version",
            "database",
            "database_display",
            "benchmark",
            "timestamp",
        ]
        for field in required_job_fields:
            if not job.get(field):
                errors.append(f"{rel_path.as_posix()}: field 'job.{field}' is required and must be non-empty")

        benchmark = job.get("benchmark")
        if benchmark not in VALID_BENCHMARKS:
            errors.append(f"{rel_path.as_posix()}: field 'job.benchmark' must be one of {sorted(VALID_BENCHMARKS)}")

        timestamp_raw = job.get("timestamp")
        parsed_timestamp = parse_timestamp(timestamp_raw) if isinstance(timestamp_raw, str) else None
        if not parsed_timestamp:
            errors.append(
                f"{rel_path.as_posix()}: field 'job.timestamp' must be parseable as YYYY-MM-DD HH:MM:SS (or ISO T variant)"
            )

        expected = canonical_result_path(job)
        if expected is not None and rel_path.as_posix() != expected.as_posix():
            duplicate_upload = _duplicate_upload_error(rel_path, expected)
            if duplicate_upload:
                errors.append(duplicate_upload)
            errors.append(_path_mismatch_error(rel_path, job, expected))

        benchmark_config = payload.get("benchmark_config")
        if not isinstance(benchmark_config, dict):
            errors.append(f"{rel_path.as_posix()}: field 'benchmark_config' must exist and be an object")

        result = payload.get("result")
        if not isinstance(result, dict):
            errors.append(f"{rel_path.as_posix()}: field 'result' must exist and be an object")

        jobid = job.get("jobid")
        if isinstance(jobid, str) and jobid:
            if jobid in jobid_to_path:
                errors.append(
                    f"{rel_path.as_posix()}: duplicate job.jobid '{jobid}' also seen in {jobid_to_path[jobid].relative_to(repo_root).as_posix()}"
                )
            else:
                jobid_to_path[jobid] = file_path

        if benchmark == "TPROC-C":
            if isinstance(result, dict):
                if not is_number(result.get("nopm")):
                    errors.append(f"{rel_path.as_posix()}: field 'result.nopm' must exist and be numeric for TPROC-C")
                if not is_number(result.get("tpm")):
                    errors.append(f"{rel_path.as_posix()}: field 'result.tpm' must exist and be numeric for TPROC-C")

            if isinstance(benchmark_config, dict):
                for field in ("warehouses", "virtual_users", "rampup_minutes", "duration_minutes"):
                    if field not in benchmark_config:
                        errors.append(
                            f"{rel_path.as_posix()}: field 'benchmark_config.{field}' must exist for TPROC-C"
                        )

    return ValidationResult(errors=errors, json_file_count=len(json_files))


def format_validation_failure(errors: list[str]) -> str:
    return "Validation failed:\n" + "\n".join(f" - {err}" for err in errors)
