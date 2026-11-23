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

// Only approved senders may transfer a reviewed result; this does not submit it.
// Existing tested local/SSH-forwarded assistant origins. Any externally hosted
// assistant must have its exact HTTPS origin separately approved and added.
window.HammerDBSubmissionHandoff = Object.freeze({
  allowedOrigins: Object.freeze([
    "http://localhost:18093", "http://127.0.0.1:18093",
    "http://localhost:18094", "http://127.0.0.1:18094",
    "http://localhost:18194", "http://127.0.0.1:18194"
  ])
});
