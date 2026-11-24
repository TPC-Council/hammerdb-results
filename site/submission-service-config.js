/* TPC-Council automatic submission endpoint.
 * Deployed as an independent TPC-only Worker in the EXISTING HammerDB Ltd
 * Cloudflare account; do not repurpose the working HammerDB Ltd Worker.
 *
 * IMPORTANT: This URL is the planned destination, not yet a verified live
 * service. Deploy the TPC Worker, configure its GitHub App credentials and
 * callback, and test it BEFORE TPC-Council merges the activation in PR #19.
 * No GitHub App secrets or tokens belong in this public website file.
 */
window.HammerDBSubmissionAPI = Object.freeze({
  endpoint: "https://hammerdb-results-tpc-submit.hammerdb.workers.dev"
});

// Any HTTP(S) website and port may initiate a reviewed-result handoff.
// The receiver still checks the one-use nonce, sender window/origin, checksum
// and form validation. No handoff can submit a PR without user approval.
