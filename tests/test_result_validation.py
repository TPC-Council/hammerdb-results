from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import build_leaderboard  # noqa: E402
from result_validation import canonical_result_path, validate_artifacts  # noqa: E402


def artifact(
    *,
    jobid: str = "ABC123",
    benchmark: str = "TPROC-C",
    database: str = "PostgreSQL",
    database_display: str = "PostgreSQL",
    timestamp: str = "2026-06-04 12:34:56",
) -> dict:
    payload = {
        "schema": "hammerdb-job-report-v1",
        "disclaimer": {"audited": False},
        "job": {
            "jobid": jobid,
            "hdb_version": "5.0",
            "database": database,
            "database_display": database_display,
            "benchmark": benchmark,
            "timestamp": timestamp,
            "release": "test",
        },
        "benchmark_config": {
            "warehouses": 1,
            "virtual_users": 1,
            "rampup_minutes": 1,
            "duration_minutes": 1,
        },
        "result": {"nopm": 100, "tpm": 200},
        "system": {},
    }
    if benchmark == "TPROC-H":
        payload["result"] = {"geomean_seconds": 1.5, "total_query_time_seconds": 10}
    return payload


class ResultValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.repo_root = Path(self.tmp.name)
        self.results_root = self.repo_root / "results"
        self.results_root.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_artifact(self, rel_path: Path | str, payload: dict) -> Path:
        path = self.repo_root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def canonical_rel(self, payload: dict) -> Path:
        expected = canonical_result_path(payload["job"])
        self.assertIsNotNone(expected)
        return expected

    def validate(self) -> list[str]:
        return validate_artifacts(self.repo_root, self.results_root).errors

    def assertValidationFailsWith(self, text: str) -> None:
        errors = self.validate()
        self.assertTrue(errors, "validation unexpectedly passed")
        self.assertIn(text, "\n".join(errors))

    def test_valid_artifact_at_correct_path_passes(self) -> None:
        payload = artifact(jobid="VALID1")
        self.write_artifact(self.canonical_rel(payload), payload)
        self.assertEqual(self.validate(), [])

    def test_postgresql_artifact_under_mariadb_path_fails(self) -> None:
        payload = artifact(jobid="PGUNDERMDB", database="PostgreSQL", database_display="PostgreSQL")
        self.write_artifact("results/tproc-c/mariadb/2026/06/PGUNDERMDB.json", payload)
        self.assertValidationFailsWith("expected canonical path: results/tproc-c/postgresql/2026/06/PGUNDERMDB.json")

    def test_mariadb_artifact_under_postgresql_path_fails(self) -> None:
        payload = artifact(jobid="MDBUNDERPG", database="MariaDB", database_display="MariaDB")
        self.write_artifact("results/tproc-c/postgresql/2026/06/MDBUNDERPG.json", payload)
        self.assertValidationFailsWith("database found in JSON: MariaDB")
        self.assertValidationFailsWith("expected canonical path: results/tproc-c/mariadb/2026/06/MDBUNDERPG.json")

    def test_tproc_h_artifact_under_tproc_c_path_fails(self) -> None:
        payload = artifact(jobid="HUNDERC", benchmark="TPROC-H")
        self.write_artifact("results/tproc-c/postgresql/2026/06/HUNDERC.json", payload)
        self.assertValidationFailsWith("benchmark found in JSON: TPROC-H")
        self.assertValidationFailsWith("expected canonical path: results/tproc-h/postgresql/2026/06/HUNDERC.json")

    def test_wrong_year_month_path_fails(self) -> None:
        payload = artifact(jobid="WRONGDATE", timestamp="2026-06-04 12:34:56")
        self.write_artifact("results/tproc-c/postgresql/2026/05/WRONGDATE.json", payload)
        self.assertValidationFailsWith("timestamp found in JSON: 2026-06-04 12:34:56")
        self.assertValidationFailsWith("expected canonical path: results/tproc-c/postgresql/2026/06/WRONGDATE.json")

    def test_filename_with_parenthesized_duplicate_suffix_fails(self) -> None:
        payload = artifact(jobid="DUPUPLOAD")
        self.write_artifact("results/tproc-c/postgresql/2026/06/DUPUPLOAD(1).json", payload)
        self.assertValidationFailsWith("filename looks like a duplicate browser/GitHub upload")
        self.assertValidationFailsWith("rename it to the canonical path results/tproc-c/postgresql/2026/06/DUPUPLOAD.json")

    def test_duplicate_jobid_fails(self) -> None:
        first = artifact(jobid="DUPJOB", database="PostgreSQL", database_display="PostgreSQL")
        second = copy.deepcopy(first)
        second["job"]["database"] = "MariaDB"
        second["job"]["database_display"] = "MariaDB"
        self.write_artifact(self.canonical_rel(first), first)
        self.write_artifact(self.canonical_rel(second), second)
        self.assertValidationFailsWith("duplicate job.jobid 'DUPJOB'")

    def test_invalid_artifact_prevents_build_outputs(self) -> None:
        payload = artifact(jobid="BUILDBLOCK", database="PostgreSQL", database_display="PostgreSQL")
        self.write_artifact("results/tproc-c/mariadb/2026/06/BUILDBLOCK.json", payload)

        old_globals = {
            "REPO_ROOT": build_leaderboard.REPO_ROOT,
            "RESULTS_ROOT": build_leaderboard.RESULTS_ROOT,
            "SITE_ROOT": build_leaderboard.SITE_ROOT,
            "LEADERBOARD_JSON": build_leaderboard.LEADERBOARD_JSON,
            "INDEX_HTML": build_leaderboard.INDEX_HTML,
        }
        try:
            build_leaderboard.REPO_ROOT = self.repo_root
            build_leaderboard.RESULTS_ROOT = self.results_root
            build_leaderboard.SITE_ROOT = self.repo_root / "site"
            build_leaderboard.LEADERBOARD_JSON = build_leaderboard.SITE_ROOT / "leaderboard.json"
            build_leaderboard.INDEX_HTML = build_leaderboard.SITE_ROOT / "index.html"

            self.assertEqual(build_leaderboard.main(), 1)
            self.assertFalse(build_leaderboard.LEADERBOARD_JSON.exists())
            self.assertFalse(build_leaderboard.INDEX_HTML.exists())
        finally:
            for name, value in old_globals.items():
                setattr(build_leaderboard, name, value)


if __name__ == "__main__":
    unittest.main()
