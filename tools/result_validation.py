#!/usr/bin/env python3
"""Shared validation helpers for HammerDB result artifacts."""

from __future__ import annotations

import json
import re
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
