#!/usr/bin/env python3
"""Ensure new result artifacts are attributed to the authenticated GitHub PR author."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def is_service_pr(expected: str, app_bot: str, head_ref: str,
                  head_repo: str, target_repo: str) -> bool:
    """Trust the service identity only for its exact bot on a same-repo branch."""
    return bool(
        app_bot and expected.casefold() == app_bot.casefold()
        and head_ref.startswith("submission/")
        and head_repo.casefold() == target_repo.casefold()
        and target_repo
    )


def main() -> int:
    expected = os.environ.get("EXPECTED_PR_AUTHOR", "").strip()
    base = os.environ.get("BASE_SHA", "").strip()
    if not expected or not base:
        print("PR attribution check requires EXPECTED_PR_AUTHOR and BASE_SHA.")
        return 1

    try:
        diff = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=A", base, "HEAD", "--", "results"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"Failed to retrieve PR changes: {exc.stderr}")
        return 1

    manifest_path = ROOT / "submissions" / "legacy-attribution.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    errors = []
    found = 0
    # GitHub App submits PRs on behalf of an OAuth-authenticated contributor.
    # Only the exact configured app bot, using a same-repo submission branch,
    # can rely on the user identity that the server verified with GitHub.
    app_bot = os.environ.get("SUBMISSION_APP_BOT_LOGIN", "").strip()
    head_ref = os.environ.get("PR_HEAD_REF", "").strip()
    head_repo = os.environ.get("PR_HEAD_REPO", "").strip()
    target_repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    service_pr = is_service_pr(expected, app_bot, head_ref, head_repo, target_repo)
    for rel in diff.stdout.splitlines():
        if not rel.startswith("results/") or not rel.endswith(".json"):
            continue
        found += 1
        payload = json.loads((ROOT / rel).read_text(encoding="utf-8"))
        submission = payload.get("submission") or {}
        username = submission.get("github_username")
        if isinstance(username, str) and username:
            if not service_pr and username.casefold() != expected.casefold():
                errors.append(f"{rel}: submitted by {username!r}; PR author is @{expected}. "
                              "Use the authenticated GitHub account submitting this pull request.")
            if service_pr:
                print(f"{rel}: identity @{username} was verified by the configured GitHub App.")
        else:
            # Already accepted upstream imports may have original PR attribution.
            # TPC-Council remains strictly read-only.
            jobid = (payload.get("job") or {}).get("jobid")
            original = manifest.get(jobid, {})
            url = original.get("pr_url", "") if isinstance(original, dict) else ""
            original_user = original.get("github_username") if isinstance(original, dict) else None
            if not original_user or not url.startswith("https://github.com/TPC-Council/hammerdb-results/pull/"):
                errors.append(f"{rel}: missing submission.github_username. "
                              "New results require the authenticated PR author's username. "
                              "Imports of accepted upstream results require their original PR provenance.")
    if errors:
        print("GitHub submitter check failed:\n" + "\n".join(errors))
        return 1
    print(f"Verified submitter identity for {found} new result artifact(s); "
          f"PR author @{expected}; GitHub App submission: {service_pr}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
