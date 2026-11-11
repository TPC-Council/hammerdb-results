/* Resolve the repository hosting the deployed leaderboard.
 * The publishing workflow supplies the repository context, including on custom domains.
 * This script only constructs links; it does not write to GitHub.
 */
(function () {
  "use strict";
  const host = location.hostname.toLowerCase();
  let owner = "";
  let repo = "hammerdb-results";
  let branch = "";
  const context = window.HammerDBResultsDeploy;
  if (context && /^(HammerDBLtd|TPC-Council)$/i.test(context.owner) &&
      context.repo === "hammerdb-results" && /^main$/.test(context.branch)) {
    owner = context.owner;
    branch = context.branch;
  } else if (host === "tpc-council.github.io") {
    owner = "TPC-Council";
  } else if (host === "hammerdbltd.github.io") {
    owner = "HammerDBLtd";
  } else if (host === "raw.githack.com" || host === "rawcdn.githack.com") {
    const match = location.pathname.match(/^\/(HammerDBLtd|TPC-Council)\/hammerdb-results\//i);
    if (match) owner = match[1];
  } else if (host === "github.com") {
    const match = location.pathname.match(/^\/(HammerDBLtd|TPC-Council)\/hammerdb-results\//i);
    if (match) owner = match[1];
  }
  if (!owner) owner = "TPC-Council"; // preview fallback when no deployment context is available
  owner = owner.toLowerCase() === "tpc-council" ? "TPC-Council" : "HammerDBLtd";
  if (!branch) branch = "main";
  const url = "https://github.com/" + owner + "/" + repo;
  window.HammerDBResultsRepo = Object.freeze({owner, repo, branch, url, fullName:owner+"/"+repo});

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-repository-link]").forEach(function (link) {
      link.href = url;
    });
    document.querySelectorAll("[data-repository-name]").forEach(function (node) {
      node.textContent = owner + "/" + repo;
    });
  });
})();
