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
- **Reviewed-result transfer:** accept one validated JSON draft from specifically
  allowed local assistant/browser origins. No draft is submitted automatically:
  a human checks the form, clicks Submit, authorises GitHub, and the resulting
  PR awaits maintainer review. Externally hosted assistant sites require their
  exact HTTPS origins to be approved and added separately.

**Rollout safety:** `site/submission-service-config.js` deliberately contains
`endpoint: ""`. The manual option remains the default and usable on the
published TPC-Council site; the automatic option is disabled until there is an
approved, independently tested TPC-targeted service. Never point the TPC site
at the existing **HammerDB Ltd-only** Worker.

## TPC-Council administrator: before approving the code PR

1. Review the branch as a normal fork PR. The diff must include **no changes
   to `results/`, `submissions/`, `site/leaderboard.json`,
   `tools/build_leaderboard.py`, leaderboard pages or source repository
   context**. All TPC community results remain.
2. If GitHub asks, choose **Approve workflows to run** for the fork PR, then
   check validation is green. Review and merge only when satisfied.
3. Agree in principle to allow the existing HammerDB Ltd-owned public
   GitHub App `hammerdb-results-submit` on **only**
   `TPC-Council/hammerdb-results` with repository Contents **read/write** and
   Pull requests **read/write** (Metadata read is automatic). **App installation
   is not required for the initial code PR to merge** because auto submission
   stays disabled.
4. No TPC-Council organisation ownership change, repository transfer, new
   GitHub App, Cloudflare account, or personal Write access is required.

## TPC-Council administrator: after merging, before enabling automatic PRs

1. A TPC-Council organisation owner / authorised GitHub App manager installs
   or approves **the existing App** for **only the `hammerdb-results`
   repository**. The App stays owned by HammerDB Ltd, retaining the branded
   HammerDB icon.
2. A TPC repository administrator sets GitHub Actions **repository variable**
   `SUBMISSION_APP_BOT_LOGIN=hammerdb-results-submit[bot]`, checking the
   actual App bot login. This enables validation to recognise ONLY the exact
   approved App bot authoring `submission/` branches in the SAME
   TPC-Council repository. Existing human PR attribution remains enforced.
3. HammerDB Ltd operates a **separate TPC-only Cloudflare Worker instance in
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
4. Add the new TPC Worker `https://<tpc-worker-host>/oauth/callback` as an
   **additional** OAuth redirect URI on the existing GitHub App without
   removing the working HammerDB Ltd callback. Confirm that the separate
   TPC Worker `/health` returns `configured:true`.
5. Test a complete real authorisation using a **new, valid** benchmark JSON,
   verifying that the PR is created against **TPC-Council**, comes from
   `hammerdb-results-submit[bot]`, and passes CI. Do not merge a synthetic
   benchmark result. Do not send submissions to HammerDB Ltd.
6. After the test, submit a **small second PR** changing only the public
   `endpoint` in `site/submission-service-config.js` to the tested TPC
   Worker URL. TPC-Council reviews/merges that activation PR. Then
   **Do it for me** becomes selectable. The manual route remains available.

## Safeguards and compatibility

- The browser cannot choose a different repository: the Worker requires an
  exact matching target and the verified GitHub OAuth user.
- A pending draft lives in the separate private KV for up to 15 minutes.
  The Worker restricts browser POST origins to the exact configured TPC site.
- A user-facing handoff uses an allowlisted origin, one-use nonce, exact
  `postMessage` source, a SHA-256 checksum and a two-minute timeout.
- Neither route merges automatically; both create reviewable PRs.
- GitHub App access tokens are treated as opaque strings. The forthcoming
  stateless/longer token format should not require a token-length assumption,
  but we will verify in the live test.
- `node --test tests/test_submit_form.cjs service/worker.test.mjs` is included
  in both TPC CI and TPC Pages build. Existing Python tests remain unchanged.

**Do not merge a test result or change the HammerDB Ltd production Worker to
make this rollout work.**
