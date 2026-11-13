from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_leaderboard  # noqa: E402
from result_validation import canonical_result_path, validate_artifacts  # noqa: E402


def sample_result(*, jobid="SUBMIT123") -> dict:
    return {
        "schema": "hammerdb-job-report-v1",
        "disclaimer": {"audited": False},
        "job": {
            "jobid": jobid, "hdb_version": "v6.0",
            "database": "MariaDB", "database_display": "MariaDB",
            "benchmark": "TPROC-C", "timestamp": "2026-11-10 12:34:56",
            "release": "12.3.3",
        },
        "benchmark_config": {
            "warehouses": 1000, "virtual_users": 48,
            "rampup_minutes": 2, "duration_minutes": 5,
        },
        "result": {"nopm": 800000, "tpm": 1700000},
        "system": {"cpumodel": "Example CPU", "memory": "128 GB"},
    }


class SubmissionMetadataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.results = self.root / "results"
        self.results.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, payload):
        rel = canonical_result_path(payload["job"])
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def check(self):
        return validate_artifacts(self.root, self.results).errors

    def test_legacy_unannotated_artifacts_remain_valid(self):
        self.save(sample_result())
        self.assertEqual([], self.check())

    def test_valid_io_focused_submission(self):
        artifact = sample_result()
        artifact["submission"] = {
            "github_username": "benchmark-user",
            "description": "A storage-heavy MariaDB benchmark.",
            "company": {
                "name": "ExampleDB",
                "logo_url": "https://example.org/logo.png",
                "description": "Database engineering",
            },
            "workload": {
                "classification": "io-intensive",
                "use_all_warehouses": True,
                "durability": "full",
                "details": "Use All Warehouses enabled; durability and transaction logging enabled.",
            },
        }
        self.save(artifact)
        self.assertEqual([], self.check())

    def test_bad_io_focused_claim_is_rejected(self):
        artifact = sample_result()
        artifact["submission"] = {
            "github_username": "some-user",
            "workload": {
                "classification": "io-intensive",
                "use_all_warehouses": False,
                "durability": "relaxed",
                "details": "Claimed I/O heavy but UAW and durability are not enabled.",
            },
        }
        self.save(artifact)
        self.assertIn("I/O-focused classification requires UAW enabled and full durability", "\n".join(self.check()))

    def test_cpu_focused_submission_requires_evidence(self):
        artifact = sample_result()
        artifact["submission"] = {
            "github_username": "some-user",
            "workload": {
                "classification": "cpu-intensive",
                "use_all_warehouses": False,
                "durability": "relaxed",
                "details": "Storage waits reduced using asynchronous commit with UAW disabled.",
            },
        }
        self.save(artifact)
        self.assertEqual([], self.check())
        artifact["submission"]["workload"]["details"] = ""
        self.save(artifact)
        self.assertIn("configuration evidence", "\n".join(self.check()))

    def test_artifact_uaw_conflict_is_rejected(self):
        artifact = sample_result()
        artifact["benchmark_config"]["use_all_warehouses"] = True
        artifact["submission"] = {
            "github_username": "some-user",
            "workload": {
                "classification": "cpu-intensive",
                "use_all_warehouses": False,
                "durability": "full",
                "details": "CPU-focused configuration with verified explicit UAW value.",
            },
        }
        self.save(artifact)
        self.assertIn("declared UAW conflicts", "\n".join(self.check()))

    def test_untrusted_logo_url_and_invalid_account_are_rejected(self):
        artifact = sample_result()
        artifact["submission"] = {
            "github_username": "bad user !",
            "company": {"name": "Example", "logo_url": "javascript:alert(1)"},
        }
        self.save(artifact)
        messages = "\n".join(self.check())
        self.assertIn("valid GitHub username", messages)
        self.assertIn("public HTTPS URL", messages)

    def test_builder_preserves_legacy_attribution_and_does_not_guess_profile(self):
        self.save(sample_result())
        att = self.root / "submissions"
        att.mkdir()
        (att / "legacy-attribution.json").write_text(
            json.dumps({"SUBMIT123": {"github_username": "original-pr-user",
                                      "pr_url": "https://github.com/example/repo/pull/123"}}),
            encoding="utf-8",
        )
        previous = {name: getattr(build_leaderboard, name) for name in
                    ("REPO_ROOT", "RESULTS_ROOT", "SITE_ROOT", "LEADERBOARD_JSON", "INDEX_HTML")}
        try:
            build_leaderboard.REPO_ROOT = self.root
            build_leaderboard.RESULTS_ROOT = self.results
            build_leaderboard.SITE_ROOT = self.root / "site"
            build_leaderboard.LEADERBOARD_JSON = self.root / "site" / "leaderboard.json"
            build_leaderboard.INDEX_HTML = self.root / "site" / "index.html"
            self.assertEqual(0, build_leaderboard.main())
            row = json.loads(build_leaderboard.LEADERBOARD_JSON.read_text())["rows"][0]
            self.assertEqual("original-pr-user", row["submitted_by"])
            self.assertEqual("original-pr", row["attribution_source"])
            self.assertEqual("unclassified", row["workload_class"])
        finally:
            for name, value in previous.items():
                setattr(build_leaderboard, name, value)


    def test_annotations_merge_without_changing_benchmark_artifact(self):
        artifact = sample_result()
        self.save(artifact)
        result_path = self.root / canonical_result_path(artifact["job"])
        original_bytes = result_path.read_bytes()
        attribution = self.root / "submissions"
        (attribution / "annotations").mkdir(parents=True)
        (attribution / "legacy-attribution.json").write_text(
            json.dumps({"SUBMIT123": {
                "github_username": "original-pr-user",
                "pr_url": "https://github.com/TPC-Council/hammerdb-results/pull/99",
                "pr_description": "Settings described in the original PR",
            }}), encoding="utf-8")
        (attribution / "annotations" / "SUBMIT123.json").write_text(json.dumps({
            "jobid": "SUBMIT123",
            "github_username": "original-pr-user",
            "company": {
                "name": "ExampleDB",
                "logo_url": "https://example.org/logo.png",
                "description": "Database research",
            },
            "comments": ["Used synchronous database durability", "Follow-up testing on larger instance"],
        }), encoding="utf-8")
        old_root, old_results = build_leaderboard.REPO_ROOT, build_leaderboard.RESULTS_ROOT
        try:
            build_leaderboard.REPO_ROOT = self.root
            build_leaderboard.RESULTS_ROOT = self.results
            rows = build_leaderboard._load_rows()
            self.assertEqual(1, len(rows))
            self.assertEqual("ExampleDB", rows[0]["company_name"])
            self.assertEqual("https://example.org/logo.png", rows[0]["company_logo_url"])
            self.assertEqual("Settings described in the original PR", rows[0]["original_pr_description"])
            self.assertEqual(2, len(rows[0]["submitter_comments"]))
            self.assertEqual(True, rows[0]["annotation_exists"])
            self.assertEqual(original_bytes, result_path.read_bytes())
        finally:
            build_leaderboard.REPO_ROOT, build_leaderboard.RESULTS_ROOT = old_root, old_results

    def test_annotations_reject_original_submitter_impersonation(self):
        artifact = sample_result()
        self.save(artifact)
        directory = self.root / "submissions" / "annotations"
        directory.mkdir(parents=True)
        (self.root / "submissions" / "legacy-attribution.json").write_text(
            json.dumps({"SUBMIT123": {"github_username": "original-pr-user"}}),
            encoding="utf-8")
        (directory / "SUBMIT123.json").write_text(json.dumps({
            "jobid": "SUBMIT123", "github_username": "different-github-user",
            "comments": ["These are not the original author's comments"],
        }), encoding="utf-8")
        original_root, original_results = build_leaderboard.REPO_ROOT, build_leaderboard.RESULTS_ROOT
        try:
            build_leaderboard.REPO_ROOT = self.root
            build_leaderboard.RESULTS_ROOT = self.results
            with self.assertRaisesRegex(ValueError, "Invalid annotation owner"):
                build_leaderboard._load_rows()
        finally:
            build_leaderboard.REPO_ROOT, build_leaderboard.RESULTS_ROOT = original_root, original_results

    def test_annotations_reject_orphan_jobids(self):
        self.save(sample_result())
        directory = self.root / "submissions" / "annotations"
        directory.mkdir(parents=True)
        (directory / "UNKNOWN999.json").write_text(json.dumps({
            "jobid": "UNKNOWN999", "github_username": "tester123",
            "comments": ["Notes on an unpublished result"],
        }), encoding="utf-8")
        original_root, original_results = build_leaderboard.REPO_ROOT, build_leaderboard.RESULTS_ROOT
        try:
            build_leaderboard.REPO_ROOT = self.root
            build_leaderboard.RESULTS_ROOT = self.results
            with self.assertRaisesRegex(ValueError, "Annotations reference unpublished jobs"):
                build_leaderboard._load_rows()
        finally:
            build_leaderboard.REPO_ROOT, build_leaderboard.RESULTS_ROOT = original_root, original_results



    def test_public_comment_has_authenticated_attribution_and_preserves_metadata(self):
        from check_annotation_author import annotation_change_errors
        path = "submissions/annotations/SUBMIT123.json"
        current = {
            "jobid": "SUBMIT123", "github_username": "original-pr-user",
            "company": {},
            "comments": [{"github_username": "independent-reviewer", "text": "I tested the same database."}],
        }
        self.assertEqual([], annotation_change_errors(
            path, current, None, "original-pr-user", "independent-reviewer", False
        ))
        current["comments"][0]["github_username"] = "another-person"
        self.assertIn("authenticated PR author's login", " ".join(annotation_change_errors(
            path, current, None, "original-pr-user", "independent-reviewer", False
        )))

    def test_ordinary_user_cannot_change_company_or_classification(self):
        from check_annotation_author import annotation_change_errors
        path = "submissions/annotations/SUBMIT123.json"
        payload = {
            "jobid": "SUBMIT123",
            "github_username": "original-pr-user",
            "company": {"name": "Example Co"},
            "workload": {
                "classification": "io-intensive",
                "use_all_warehouses": True, "durability": "full",
                "details": "Full synchronous durability and UAW explicitly enabled.",
            },
            "comments": [{"github_username": "guest-user", "text": "A useful observation"}],
        }
        errors = " ".join(annotation_change_errors(
            path, payload, None, "original-pr-user", "guest-user", False
        ))
        self.assertIn("only the original submitter or a maintainer", errors)
        self.assertIn("company details", errors)
        self.assertIn("workload classification", errors)

    def test_maintainer_can_update_company_and_cpu_io_profile(self):
        from check_annotation_author import annotation_change_errors
        path = "submissions/annotations/SUBMIT123.json"
        original_note = {
            "jobid": "SUBMIT123", "github_username": "original-pr-user",
            "company": {"name": "Company A"},
            "comments": [{"github_username": "original-pr-user", "text": "Original comment"}],
        }
        updated = {
            **original_note,
            "company": {"name": "Company A", "description": "Company description"},
            "workload": {
                "classification": "cpu-intensive",
                "use_all_warehouses": False, "durability": "relaxed",
                "details": "UAW disabled and asynchronous transactions for CPU-oriented run.",
            },
            "comments": original_note["comments"] + [
                {"github_username": "repo-maintainer", "text": "Verified performance settings"}
            ],
        }
        self.assertEqual([], annotation_change_errors(
            path, updated, original_note, "original-pr-user", "repo-maintainer", True
        ))
        updated["comments"][0] = {"github_username": "repo-maintainer", "text": "Edited old comment"}
        self.assertIn("earlier comments cannot be edited", " ".join(annotation_change_errors(
            path, updated, original_note, "original-pr-user", "repo-maintainer", True
        )))

    def test_annotation_cpu_io_badge_from_separate_json(self):
        artifact = sample_result()
        self.save(artifact)
        at = self.root / "submissions"
        (at / "annotations").mkdir(parents=True)
        (at / "legacy-attribution.json").write_text(
            json.dumps({"SUBMIT123": {"github_username": "original-pr-user"}}),
            encoding="utf-8",
        )
        (at / "annotations" / "SUBMIT123.json").write_text(json.dumps({
            "jobid": "SUBMIT123",
            "github_username": "original-pr-user",
            "comments": [{"github_username": "review-user", "text": "Follow-up observations"}],
            "workload": {
                "classification": "io-intensive",
                "use_all_warehouses": True,
                "durability": "full",
                "details": "Synchronous durability configured with all warehouses enabled.",
            },
        }), encoding="utf-8")
        original_root, original_results = build_leaderboard.REPO_ROOT, build_leaderboard.RESULTS_ROOT
        try:
            build_leaderboard.REPO_ROOT = self.root
            build_leaderboard.RESULTS_ROOT = self.results
            row = build_leaderboard._load_rows()[0]
            self.assertEqual("io-intensive", row["workload_class"])
            self.assertEqual(True, row["workload_uaw"])
            self.assertEqual("full", row["workload_durability"])
            self.assertEqual("review-user", row["submitter_comments"][0]["github_username"])
        finally:
            build_leaderboard.REPO_ROOT, build_leaderboard.RESULTS_ROOT = original_root, original_results



if __name__ == "__main__":
    unittest.main()
