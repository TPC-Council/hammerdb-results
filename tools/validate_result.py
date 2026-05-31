#!/usr/bin/env python3
"""Validate HammerDB result artifacts under results/."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_ROOT = REPO_ROOT / "results"
EXPECTED_SCHEMA = "hammerdb-job-report-v1"
VALID_BENCHMARKS = {"TPROC-C", "TPROC-H"}


def _as_slug(value: str) -> str:
    """Convert values like 'MariaDB' into filesystem-safe lowercase slugs."""
    slug = value.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _parse_timestamp(raw: str) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def main() -> int:
    errors: list[str] = []
    jobid_to_path: dict[str, Path] = {}

    json_files = sorted(RESULTS_ROOT.rglob("*.json"))
    if not json_files:
        print("ERROR: No JSON files found under results/")
        return 1

    for file_path in json_files:
        rel_path = file_path.relative_to(REPO_ROOT)
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{rel_path}: invalid JSON ({exc})")
            continue

        if payload.get("schema") != EXPECTED_SCHEMA:
            errors.append(f"{rel_path}: field 'schema' must equal '{EXPECTED_SCHEMA}'")

        disclaimer = payload.get("disclaimer")
        if not isinstance(disclaimer, dict):
            errors.append(f"{rel_path}: field 'disclaimer' must exist and be an object")
        elif disclaimer.get("audited") is not False:
            errors.append(f"{rel_path}: field 'disclaimer.audited' must be false")

        job = payload.get("job")
        if not isinstance(job, dict):
            errors.append(f"{rel_path}: field 'job' must exist and be an object")
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
                errors.append(f"{rel_path}: field 'job.{field}' is required and must be non-empty")

        benchmark = job.get("benchmark")
        if benchmark not in VALID_BENCHMARKS:
            errors.append(f"{rel_path}: field 'job.benchmark' must be one of {sorted(VALID_BENCHMARKS)}")

        if "benchmark_config" not in payload or not isinstance(payload.get("benchmark_config"), dict):
            errors.append(f"{rel_path}: field 'benchmark_config' must exist and be an object")

        result = payload.get("result")
        if not isinstance(result, dict):
            errors.append(f"{rel_path}: field 'result' must exist and be an object")

        jobid = job.get("jobid")
        if isinstance(jobid, str) and jobid:
            if jobid in jobid_to_path:
                errors.append(
                    f"{rel_path}: duplicate job.jobid '{jobid}' also seen in {jobid_to_path[jobid].relative_to(REPO_ROOT)}"
                )
            else:
                jobid_to_path[jobid] = file_path

        if benchmark == "TPROC-C":
            if not isinstance(result, dict):
                pass
            else:
                if not _is_number(result.get("nopm")):
                    errors.append(f"{rel_path}: field 'result.nopm' must exist and be numeric for TPROC-C")
                if not _is_number(result.get("tpm")):
                    errors.append(f"{rel_path}: field 'result.tpm' must exist and be numeric for TPROC-C")

            benchmark_config = payload.get("benchmark_config")
            if isinstance(benchmark_config, dict):
                for field in ("warehouses", "virtual_users", "rampup_minutes", "duration_minutes"):
                    if field not in benchmark_config:
                        errors.append(
                            f"{rel_path}: field 'benchmark_config.{field}' must exist for TPROC-C"
                        )
            timestamp_raw = job.get("timestamp")
            parsed = _parse_timestamp(timestamp_raw) if isinstance(timestamp_raw, str) else None
            if not parsed:
                errors.append(
                    f"{rel_path}: field 'job.timestamp' must be parseable as YYYY-MM-DD HH:MM:SS (or ISO T variant)"
                )
            elif isinstance(jobid, str) and jobid and isinstance(job.get("database_display"), str):
                expected = Path("results") / benchmark.lower() / _as_slug(job["database_display"]) / parsed.strftime("%Y") / parsed.strftime("%m") / f"{jobid}.json"
                if rel_path.as_posix() != expected.as_posix():
                    errors.append(
                        f"{rel_path}: path mismatch; expected '{expected.as_posix()}' from job fields"
                    )

    if errors:
        print("Validation failed:")
        for err in errors:
            print(f" - {err}")
        return 1

    print(f"Validation succeeded for {len(json_files)} JSON file(s) under results/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
