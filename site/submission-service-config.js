/* TPC-Council production rollout gate: manual PR submission continues to work.
 * The automatic route is disabled until the Council approves installation of
 * the existing HammerDB Ltd GitHub App and the separately deployed TPC-only
 * Cloudflare Worker has passed a real end-to-end test.
 * Add ONLY that new public Worker URL in a follow-up reviewed change.
 * Never point the TPC form at the working HammerDB Ltd test Worker.
 */
window.HammerDBSubmissionAPI = Object.freeze({
  endpoint: ""
});

// Any HTTP(S) website and port may initiate a reviewed-result handoff.
// The receiver still checks the one-use nonce, sender window/origin, checksum
// and form validation. No handoff can submit a PR without user approval.
