# TPC-Council: tested HammerDB submission workflow

This code is proposed from the `sm-shaw/hammerdb-results` fork for
`TPC-Council/hammerdb-results`. It is a **code-only change**. It is based on
TPC-Council `main` at merge commit `7d91933f113ac4b098590046ef4f7f862a3e6592`
and **does not add, edit, remove, or replace any `results/` JSON files**.
In particular, the MariaDB result from TPC-Council PR #18,
`6AB85F34CAB703E263535343`, remains present. The unchanged
`tools/build_leaderboard.py` dynamically publishes all results from the
current TPC-Council repository after a maintainer merges the code PR.

## What this code brings to TPC-Council

- **I'll create my own PR:** preserve the TPC-Council Copy enriched JSON →
  Continue to GitHub process. No App installation or Worker is necessary.
- **Do it for me:** once approved and enabled, the same public,
  HammerDB Ltd-owned `hammerdb-results-submit` GitHub App and the existing
  Cloudflare **account** can open PRs against TPC-Council, with user OAuth
  verification. This does **not** mean transferring the repository or giving
  `sm-shaw` / HammerDB Ltd personal Write access.
- **Reviewed-result transfer:** accept one validated JSON draft from **any
  HTTP(S) website, hostname, IP address or port** (not just localhost).
  A sender does not need to be registered or allowlisted. No draft is
  submitted automatically: a human checks the form, clicks Submit,
  authorises GitHub, and the resulting PR awaits maintainer review.

**Single-PR rollout:** PR #19 includes the planned endpoint
`https://hammerdb-results-tpc-submit.hammerdb.workers.dev` for the **separate**
TPC-Council Worker. The form first checks `/health`; **until that Worker is
configured and running, automatic submission stays disabled and the existing
manual PR route remains usable**. When the TPC Worker becomes ready, the same
merged code enables automatic submission **without a second PR**. The Worker URL
is a deployment target, **not a claim that it has been deployed**. Never point
the TPC form at the existing **HammerDB Ltd-only** Worker.

## TPC-Council administrator: approve the existing App request and PR #19

1. Review the branch as a normal fork PR. The diff must include **no changes
   to `results/`, `submissions/`, `site/leaderboard.json`,
   `tools/build_leaderboard.py`, leaderboard pages or source repository
   context**. All TPC community results remain.
2. If GitHub asks, choose **Approve workflows to run** for the fork PR, then
   check validation is green. Review and merge only when satisfied.
3. Approve the **already-submitted installation request** for the existing
   HammerDB Ltd-owned public GitHub App `hammerdb-results-submit` on **only**
   `TPC-Council/hammerdb-results` with repository Contents **read/write** and
   Pull requests **read/write** (Metadata read is automatic).
4. The Actions repository variable
   `SUBMISSION_APP_BOT_LOGIN=hammerdb-results-submit[bot]` has **already
   been configured** by the contributor; the Council may verify it. The exact
   approved App bot may then author `submission/` branches in the SAME
   TPC-Council repo without weakening human PR attribution checks.
5. Review/merge **the one PR #19**. No follow-up activation PR is required.
   If the separate Cloudflare Worker has not yet been deployed, automatic
   submission remains disabled but manual submission continues to work.
6. No TPC-Council organisation ownership change, repository transfer, new
   GitHub App, Cloudflare account, or personal Write access is required.

## HammerDB Ltd: configure the TPC Worker in the existing Cloudflare account

1. HammerDB Ltd operates a **separate TPC-only Cloudflare Worker instance in
   our existing Cloudflare account** with a **separate KV namespace**. Do not
   reconfigure or redeploy the working HammerDB Ltd Worker. Use the included
   `service/worker.mjs` and `service/wrangler.toml` template with:
   `GITHUB_TARGET_OWNER=TPC-Council`,
   `GITHUB_TARGET_REPO=hammerdb-results`, and
   `ALLOWED_ORIGIN=https://tpc-council.github.io`.
   Replace the placeholder TPC KV namespace ID; set `GITHUB_APP_CLIENT_ID`,
   `GITHUB_APP_CLIENT_SECRET`, and `GITHUB_APP_PRIVATE_KEY` as **private
   Worker secrets**, not repository/Pages files. We reuse the *approved App*
   credentials; no new App is created.
2. Add the new TPC Worker `https://hammerdb-results-tpc-submit.hammerdb.workers.dev/oauth/callback` as an
   **additional** OAuth redirect URI on the existing GitHub App without
   removing the working HammerDB Ltd callback. Confirm that the separate
   TPC Worker `/health` returns `configured:true`.
3. Test a complete real authorisation using a **new, valid** benchmark JSON,
   verifying that the PR is created against **TPC-Council**, comes from
   `hammerdb-results-submit[bot]`, and passes CI. Do not merge a synthetic
   benchmark result. Do not send submissions to HammerDB Ltd.
4. **No second PR.** The public endpoint is already part of PR #19; when the
   independent TPC Worker is live and its `/health` response reports
   `configured: true`, **Do it for me** becomes selectable. The manual route
   remains available. A successful `/health` response checks configured
   credentials, not GitHub App installation; verify App authorisation with a
   real test PR before announcing the automatic route as operational.

## Safeguards and compatibility

- The browser cannot choose a different repository: the Worker requires an
  exact matching target and the verified GitHub OAuth user.
- A pending draft lives in the separate private KV for up to 15 minutes.
  The Worker restricts browser POST origins to the exact configured TPC site.
- A user-facing handoff permits any HTTP(S) sender address/port while
  verifying a one-use nonce, binding the originating window **and its origin**
  for the whole handshake, checking the SHA-256 checksum and enforcing a
  two-minute timeout. No handoff sends a PR by itself; user review and GitHub
  authorisation are required. A checksum verifies transfer integrity, not
  independent benchmark authenticity (maintainer PR review still applies).
- This applies to the **incoming browser-to-form handoff**. The separate TPC
  Worker still accepts PR-creation requests only **from the official TPC
  submission form origin**; contributors may access that form from anywhere.
- Neither route merges automatically; both create reviewable PRs.
- GitHub App access tokens are treated as opaque strings. The forthcoming
  stateless/longer token format should not require a token-length assumption,
  but we will verify in the live test.
- `node --test tests/test_submit_form.cjs service/worker.test.mjs` is included
  in both TPC CI and TPC Pages build. Existing Python tests remain unchanged.

**Do not merge a test result or change the HammerDB Ltd production Worker to
make this rollout work.**
