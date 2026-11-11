#!/usr/bin/env python3
"""Validate comment attribution and ownership of annotation changes.

Compare with base-branch metadata rather than trusting fields modified by the PR.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import quote
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parent.parent
JOB_ID = re.compile(r"^[A-Za-z0-9_-]{5,80}$")


def git(*args: str) -> str:
    p = subprocess.run(["git", *args], cwd=ROOT, check=True,
                       capture_output=True, text=True)
    return p.stdout


def read_at_commit(ref: str, path: str) -> dict | None:
    process = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=ROOT,
                             capture_output=True, text=True)
    return json.loads(process.stdout) if process.returncode == 0 else None


def original_author(jobid: str, base: str, base_files: list[str], base_manifest: dict,
                    added_files: list[str]) -> str | None:
    matches = [path for path in base_files if Path(path).stem == jobid]
    if len(matches) > 1:
        raise ValueError(f"{jobid}: job ID is ambiguous in the base repository")
    if matches:
        payload = read_at_commit(base, matches[0]) or {}
        submission = payload.get("submission")
        if isinstance(submission, dict) and submission.get("github_username"):
            return submission["github_username"]
    else:
        # Allow simultaneous submission and annotations by the same PR author.
        fresh = [path for path in added_files if Path(path).stem == jobid]
        if len(fresh) == 1:
            payload = json.loads((ROOT / fresh[0]).read_text(encoding="utf-8"))
            submission = payload.get("submission")
            if isinstance(submission, dict):
                return submission.get("github_username")
        if fresh:
            raise ValueError(f"{jobid}: expected exactly one newly added result")
    original = base_manifest.get(jobid, {})
    return original.get("github_username") if isinstance(original, dict) else None


def repository_maintainer(login: str) -> bool:
    """Recognise collaborators with WRITE, MAINTAIN or ADMIN permissions.

    Uses GitHub's metadata-read API, not a user-controlled annotation field.
    Fail closed if the token or permission lookup is unavailable.
    """
    token = os.environ.get("GITHUB_TOKEN", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        return False
    url = f"https://api.github.com/repos/{repository}/collaborators/{quote(login)}/permission"
    request = Request(url, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "hammerdb-results-pr-validation",
    })
    try:
        with urlopen(request, timeout=10) as response:
            permission = json.load(response).get("permission", "")
        return permission in {"write", "maintain", "admin"}
    except (HTTPError, URLError, ValueError, TimeoutError, OSError):
        return False


def annotation_change_errors(path: str, current: dict, previous: dict | None,
                             original: str, author: str, is_maintainer: bool) -> list[str]:
    """Anyone may append attributed comments. Original author/maintainer may edit metadata."""
    errors: list[str] = []
    if not isinstance(current, dict):
        return [f"{path}: annotation must be a JSON object"]
    if current.get("jobid") != Path(path).stem:
        errors.append(f"{path}: job ID does not match filename")
    if not original:
        return errors + [f"{path}: original GitHub submitter not recorded in base repository"]
    if str(current.get("github_username", "")).casefold() != original.casefold():
        errors.append(f"{path}: original submitter must remain @{original}")
    previous = previous or {}
    prior_comments = previous.get("comments", [])
    comments = current.get("comments", [])
    if not isinstance(comments, list) or not isinstance(prior_comments, list):
        return errors + [f"{path}: comments must be an array"]
    if comments[:len(prior_comments)] != prior_comments:
        errors.append(f"{path}: earlier comments cannot be edited or removed")
    new_comments = comments[len(prior_comments):]
    for c in new_comments:
        username = c.get("github_username") if isinstance(c, dict) else None
        text = c.get("text") if isinstance(c, dict) else None
        if (not isinstance(username, str) or username.casefold() != author.casefold()
            or not isinstance(text, str) or not text.strip() or len(text) > 4000):
            errors.append(f"{path}: every new comment needs the authenticated PR author's login and text")
            break
    owner = original.casefold() == author.casefold()
    if not (owner or is_maintainer):
        if current.get("company") != previous.get("company", {}):
            errors.append(f"{path}: only the original submitter or a maintainer may change company details")
        if current.get("workload") != previous.get("workload"):
            errors.append(f"{path}: only the original submitter or a maintainer may change the workload classification")
    return errors


def main() -> int:
    author = os.environ.get("EXPECTED_PR_AUTHOR", "").strip()
    base = os.environ.get("BASE_SHA", "").strip()
    if not author or not base:
        print("Missing PR author or base SHA; annotation validation cannot run.")
        return 1
    try:
        changes = git("diff", "--name-status", base, "HEAD", "--",
                      "submissions/annotations").splitlines()
        if not changes:
            print("No annotation changes in this pull request.")
            return 0
        base_files = [p for p in git("ls-tree", "-r", "--name-only", base,
                                    "results").splitlines() if p.endswith(".json")]
        added_files = git("diff", "--name-only", "--diff-filter=A", base,
                          "HEAD", "--", "results").splitlines()
        manifest = read_at_commit(base, "submissions/legacy-attribution.json") or {}
        errors = []
        checked = 0
        maintainer = None
        for change in changes:
            pieces = change.split("\t")
            change_kind, path = pieces[0], pieces[-1]
            if change_kind not in ("A", "M"):
                errors.append(f"{path}: annotations cannot be deleted or renamed")
                continue
            if not (path.startswith("submissions/annotations/") and path.endswith(".json")):
                errors.append(f"{path}: unexpected annotation path")
                continue
            jobid = Path(path).stem
            if not JOB_ID.fullmatch(jobid):
                errors.append(f"{path}: invalid job ID")
                continue
            try:
                annotation = json.loads((ROOT / path).read_text(encoding="utf-8"))
                original = original_author(jobid, base, base_files, manifest, added_files)
                previous = read_at_commit(base, path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"{path}: {exc}")
                continue
            changes_metadata = isinstance(annotation, dict) and (
                annotation.get("company") != (previous or {}).get("company", {})
                or annotation.get("workload") != (previous or {}).get("workload")
            )
            if (original and original.casefold() != author.casefold()
                    and changes_metadata and maintainer is None):
                maintainer = repository_maintainer(author)
            errors.extend(annotation_change_errors(
                path, annotation, previous, original or "", author, bool(maintainer),
            ))
            checked += 1
        if errors:
            print("Annotation validation failed:\n" + "\n".join(errors))
            return 1
        print(f"Verified {checked} annotation change(s) and comment attribution for @{author}.")
        return 0
    except (subprocess.CalledProcessError, OSError, json.JSONDecodeError) as exc:
        print(f"Failed to validate annotation PR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
