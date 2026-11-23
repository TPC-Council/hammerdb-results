"""New GitHub App PR trust must never weaken human-authored PR attribution."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from check_pr_submitter import is_service_pr


class SubmissionAuthorTests(unittest.TestCase):
    def test_exact_app_bot_on_same_repo_branch_is_eligible(self):
        self.assertTrue(is_service_pr(
            "hammerdb-results-submit[bot]", "hammerdb-results-submit[bot]", "submission/job-1234",
            "TPC-Council/hammerdb-results", "TPC-Council/hammerdb-results"))

    def test_human_pr_cannot_bypass_attribution(self):
        self.assertFalse(is_service_pr(
            "ls250", "hammerdb-results-submit[bot]", "submission/job-1234",
            "TPC-Council/hammerdb-results", "TPC-Council/hammerdb-results"))

    def test_app_pr_from_user_fork_cannot_bypass(self):
        self.assertFalse(is_service_pr(
            "hammerdb-results-submit[bot]", "hammerdb-results-submit[bot]", "submission/job-1234",
            "ls250/hammerdb-results", "TPC-Council/hammerdb-results"))

    def test_wrong_branch_cannot_bypass(self):
        self.assertFalse(is_service_pr(
            "hammerdb-results-submit[bot]", "hammerdb-results-submit[bot]", "feature/change",
            "TPC-Council/hammerdb-results", "TPC-Council/hammerdb-results"))

    def test_missing_config_disables_app_override(self):
        self.assertFalse(is_service_pr(
            "hammerdb-results-submit[bot]", "", "submission/job-1234",
            "TPC-Council/hammerdb-results", "TPC-Council/hammerdb-results"))


if __name__ == "__main__":
    unittest.main()
