/* Client-rendered leaderboard: plain JS and no external charting dependencies. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const state = { rows: [] };
  const GH_USER = /^[a-z\d](?:[a-z\d-]{0,37}[a-z\d])?$/i;

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (ch) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
  }
  function fmt(value, digits) {
    const n = typeof value === "number" ? value : Number(value);
    return value == null || value === "" || !Number.isFinite(n)
      ? "—" : n.toLocaleString(undefined, { maximumFractionDigits: digits == null ? 0 : digits });
  }
  function safeHttps(url) {
    try {
      const parsed = new URL(String(url || ""));
      return parsed.protocol === "https:" && !parsed.username && !parsed.password
        ? parsed.href : null;
    } catch (error) { return null; }
  }
  const colourMedia = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  function themeChoice() {
    try { return localStorage.getItem("hammerdb-results-theme") || "system"; } catch (e) { return "system"; }
  }
  function showTheme(choice) {
    const selected = ["system","dark","light"].includes(choice) ? choice : "system";
    const resolved = selected === "system" ? (colourMedia?.matches ? "dark" : "light") : selected;
    document.documentElement.dataset.theme = resolved;
    $("theme-select").value = selected;
  }
  showTheme(themeChoice());
  $("theme-select").addEventListener("change", (event) => {
    const choice = event.target.value;
    try { if (choice === "system") localStorage.removeItem("hammerdb-results-theme");
          else localStorage.setItem("hammerdb-results-theme",choice); } catch (e) {}
    showTheme(choice);
  });
  colourMedia?.addEventListener?.("change", () => {
    if (themeChoice() === "system") showTheme("system");
  });

  // Report artifacts are small immutable JSON files. Warm the browser cache as
  // results approach the viewport so opening a report need not wait on a new GET.
  const loadedReports = new Set();
  let reportObserver;
  function prefetchReport(link) {
    if (navigator.connection?.saveData) return;
    const path = new URL(link.href).searchParams.get("artifact");
    if (!path || !/^results\/[a-z0-9/_-]+\.json$/i.test(path) || loadedReports.has(path)) return;
    loadedReports.add(path);
    fetch(new URL(path,new URL("./",location.href)), {cache:"force-cache"})
      .then((response) => response.ok ? response.json() : null)
      .then((artifact) => {
        if (!artifact || !artifact.job) return;
        try { sessionStorage.setItem("hammerdb-report-v1:"+path,
              JSON.stringify({at:Date.now(),body:artifact})); } catch (e) {}
      })
      .catch(() => loadedReports.delete(path));
  }
  function observeReportLinks() {
    reportObserver?.disconnect();
    const links = [...document.querySelectorAll("a.report-link")];
    for (const link of links) {
      link.addEventListener("pointerenter",() => prefetchReport(link),{once:true});
      link.addEventListener("focus",() => prefetchReport(link),{once:true});
    }
    if (!navigator.connection?.saveData && "IntersectionObserver" in window) {
      reportObserver = new IntersectionObserver((entries) => {
        for(const entry of entries)if(entry.isIntersecting) {
          prefetchReport(entry.target);
          reportObserver.unobserve(entry.target);
        }
      },{rootMargin:"500px 0px"});
      links.forEach((link) => reportObserver.observe(link));
    }
  }
  function badge(row) {
    if (row.benchmark !== "TPROC-C") return "";
    const type = row.workload_class || "unclassified";
    const labels = { "cpu-intensive": "◈ CPU-INTENSIVE", "io-intensive": "◈ I/O-INTENSIVE", unclassified: "◇ NOT CLASSIFIED" };
    const css = type === "cpu-intensive" ? "cpu" : type === "io-intensive" ? "io" : "unknown";
    const help = type === "unclassified"
      ? "Configuration evidence not supplied. No classification inferred from performance metrics."
      : "Self-declared TPROC-C configuration, not a proven hardware bottleneck.";
    return '<span class="profile-badge ' + css + '" title="' + esc(help) + '">' + esc(labels[type] || labels.unclassified) + "</span>";
  }

  function logo(row) {
    const url = safeHttps(row.company_logo_url);
    return url ? '<img class="company-logo" loading="lazy" decoding="async" referrerpolicy="no-referrer" src="' + esc(url) + '" alt="' + esc(row.company_name || "Company") + ' logo">' : "";
  }

  function identity(row) {
    const username = String(row.submitted_by || "");
    let content;
    if (GH_USER.test(username)) {
      content = '<a href="https://github.com/' + encodeURIComponent(username) + '" target="_blank" rel="noopener noreferrer">@' + esc(username) + "</a>";
    } else {
      content = '<span class="origin">GitHub submitter not recorded</span>';
    }
    const origin = row.attribution_source === "original-pr" ? "From original accepted pull request" :
      row.attribution_source === "submission" ? "Declared in submitted artifact" : "Older artifact";
    const companyText = row.company_name || row.company_description || row.company_logo_url;
    return '<div class="attribution">' +
      '<div class="github-avatar" aria-hidden="true">GH</div>' +
      '<div class="attribution-text"><div>Submitted by ' + content + '</div><div class="origin">' + esc(origin) + "</div></div></div>" +
      (companyText ? '<div class="company-block">' + logo(row) + '<div><div class="company-name">' + esc(row.company_name || "Company information") +
        '</div>' + (row.company_description ? '<div class="company-description">' + esc(row.company_description) + "</div>" : "") + "</div></div>" : "");
  }

  function evidence(row) {
    if (row.benchmark !== "TPROC-C") return "";
    if (row.workload_class === "unclassified" && row.workload_uaw == null && (row.workload_durability === "unknown" || !row.workload_durability) && !row.workload_details) return "";
    const uaw = row.workload_uaw === true ? "Enabled" : row.workload_uaw === false ? "Disabled" : "Not recorded";
    const durability = row.workload_durability === "full" ? "Full / synchronous" :
      row.workload_durability === "relaxed" ? "Relaxed" : "Not recorded";
    return '<details class="configuration-evidence"><summary>' + (row.workload_class === "unclassified" ? "View recorded configuration" : "Why is this labelled " + esc(row.workload_class === "io-intensive" ? "I/O-intensive" : "CPU-intensive")) +
      '?</summary><p><strong>Submitter-declared configuration.</strong> UAW: ' + esc(uaw) +
      " · Durability: " + esc(durability) + "\n" + esc(row.workload_details || "") +
      '\nThis describes the test configuration, not a diagnosis of the hardware bottleneck.</p></details>';
  }

  function card(row, rank, topNopm) {
    const isC = row.benchmark === "TPROC-C";
    const val = isC ? row.nopm : row.geomean_seconds;
    const unit = isC ? "NOPM" : "s geomean";
    const secondary = isC ? "TPM " + fmt(row.tpm) : "Total query time " + fmt(row.total_query_time_seconds, 2) + "s";
    const ratio = isC && topNopm > 0 ? Math.min(100, Math.max(0, Number(row.nopm || 0) / topNopm * 100)) : 0;
    const bar = isC ? '<div class="perf-track" role="img" aria-label="' + fmt(ratio, 1) +
      '% of the best reported TPROC-C NOPM in the same workload category"><div class="perf-fill" style="width:' + ratio.toFixed(1) + '%"></div></div>' : "";
    const chips = [
      ["Warehouses", row.warehouses],
      ["Virtual users", row.virtual_users],
      ["Ramp-up", row.rampup_minutes == null ? null : String(row.rampup_minutes) + "m"],
      ["Duration", row.duration_minutes == null ? null : String(row.duration_minutes) + "m"],
      ["Scale factor", row.scale_factor],
    ].filter((pair) => pair[1] != null).map((pair) =>
      '<span class="chip">' + esc(pair[0]) + ": " + esc(pair[1]) + "</span>").join("");
    const file = String(row.source_path || "");
    const link = /^results\/[a-z\d/-]+\.json$/i.test(file) ?
      "report.html?artifact=" + encodeURIComponent(file) : "report.html";
    const sourceLink = safeHttps(row.submission_pr_url);
    return '<article class="result-card" aria-label="' + esc((row.database_display || row.database || "Database") + " result") + '">' +
      badge(row) +
      '<div class="card-top"><div class="rank-pill">#' + esc(rank) + '</div><div><h4 class="db-title">' + esc(row.database_display || row.database || "Unknown database") +
      '</h4><div class="db-subtitle">Release ' + esc(row.release || "not recorded") +
      " · " + esc(row.hdb_version || "HammerDB") + " · " + esc(row.timestamp || "Date unavailable") + "</div></div></div>" +
      '<div class="card-core"><div class="metric-main"><strong>' + fmt(val, isC ? 0 : 4) +
      '</strong><span class="metric-unit">' + esc(unit) + '</span><div class="metric-secondary">' + esc(secondary) +
      '</div>' + bar + '</div><div class="metric-context"><div class="context-label">SYSTEM</div><div class="context-value" title="' +
      esc(row.cpu_model || "") + '">' + esc(row.cpu_count ? row.cpu_count + " logical CPUs" : "CPU not recorded") +
      '</div><div class="context-small">' + esc(row.cpu_model || "CPU model not recorded") +
      '</div><div class="context-small">' + esc(row.memory || "Memory not recorded") + "</div></div>" +
      '<div class="configuration">' + chips + "</div></div>" +
      (row.result_description ? '<p class="card-description">' + esc(row.result_description) + "</p>" : "") +
      '<div class="card-bottom">' + identity(row) +
      '<div class="card-actions"><a class="provenance-link" href="annotate.html?jobid=' + encodeURIComponent(row.jobid || "") + '">Comments' + (isC ? " / CPU-I/O" : "") + '</a>' + (sourceLink && row.attribution_source === "original-pr" ?
        '<a class="provenance-link" href="' + esc(sourceLink) + '" target="_blank" rel="noopener noreferrer">Original PR</a>' : "") +
      '<a class="report-link" href="' + esc(link) + '">View full report ↗</a></div></div>' + evidence(row) + "</article>";
  }

  function order(rows) {
    const sort = $("sort-filter").value;
    if (sort === "recent") {
      return rows.slice().sort((a, b) => String(b.timestamp || "").localeCompare(String(a.timestamp || "")));
    }
    return rows.slice().sort((a, b) => {
      if (a.benchmark === "TPROC-H") return Number(a.geomean_seconds ?? Infinity) - Number(b.geomean_seconds ?? Infinity);
      return Number(b.nopm || 0) - Number(a.nopm || 0);
    });
  }

  function render() {
    const query = $("search-input").value.trim().toLowerCase();
    const benchmark = $("benchmark-filter").value;
    const workload = $("workload-filter").value;
    const visible = state.rows.filter((r) => {
      if (benchmark !== "all" && r.benchmark !== benchmark) return false;
      if (workload !== "all" && r.workload_class !== workload) return false;
      if (!query) return true;
      return [r.database, r.database_display, r.release, r.cpu_model, r.submitted_by, r.company_name,
              r.company_description, r.result_description, r.jobid].some((x) => String(x || "").toLowerCase().includes(query));
    });
    $("filter-count").textContent = visible.length + " of " + state.rows.length + " results";
    const c = order(visible.filter((r) => r.benchmark === "TPROC-C"));
    const h = order(visible.filter((r) => r.benchmark === "TPROC-H"));
    const topByProfile = {};
    state.rows.filter((r) => r.benchmark === "TPROC-C").forEach((r) => {
      const profile = r.workload_class || "unclassified";
      topByProfile[profile] = Math.max(topByProfile[profile] || 0, Number(r.nopm || 0));
    });
    $("section-tproc-c").hidden = !c.length;
    $("section-tproc-h").hidden = !h.length;
    $("no-results").hidden = !!visible.length;
    $("count-c").textContent = "(" + c.length + ")";
    $("count-h").textContent = "(" + h.length + ")";
    $("results-c").innerHTML = c.map((r, i) => card(r, i + 1, topByProfile[r.workload_class || "unclassified"] || 0)).join("");
    const hGroups = [];
    const byScale = new Map();
    h.forEach((r) => {
      const scale = r.scale_factor ?? "Unspecified";
      if (!byScale.has(scale)) byScale.set(scale, []);
      byScale.get(scale).push(r);
    });
    Array.from(byScale.entries()).sort((a, b) => Number(a[0] || 0) - Number(b[0] || 0)).forEach(([scale, group]) => {
      hGroups.push('<h4 class="sf-heading">Scale factor ' + esc(scale) + "</h4>" +
        group.map((r, i) => card(r, i + 1, 0)).join(""));
    });
    $("results-h").innerHTML = hGroups.join("");
    observeReportLinks();
  }

  ["search-input", "benchmark-filter", "workload-filter", "sort-filter"].forEach((id) => {
    $(id).addEventListener(id === "search-input" ? "input" : "change", render);
  });

  fetch("leaderboard.json", { cache: "no-store" }).then((response) => {
    if (!response.ok) throw Error("HTTP " + response.status);
    return response.json();
  }).then((data) => {
    if (!data || !Array.isArray(data.rows)) throw Error("Invalid leaderboard data");
    state.rows = data.rows;
    try { sessionStorage.setItem("hammerdb-leaderboard-v1",JSON.stringify({at:Date.now(),rows:data.rows})); } catch (e) {}
    const dbCount = new Set(state.rows.map((r) => r.database_display || r.database)).size;
    const ghCount = new Set(state.rows.map((r) => r.submitted_by).filter((r) => r && GH_USER.test(r))).size;
    $("stat-results").textContent = fmt(state.rows.length);
    $("stat-dbs").textContent = fmt(dbCount);
    $("stat-submitters").textContent = fmt(ghCount);
    $("stat-top-nopm").textContent = fmt(Math.max(0, ...state.rows.filter((r) => r.benchmark === "TPROC-C").map((r) => Number(r.nopm || 0))));
    $("load-status").hidden = true;
    render();
  }).catch((error) => {
    $("load-status").textContent = "Unable to load leaderboard data (" + error.message + "). Check site/leaderboard.json.";
    $("filter-count").textContent = "Data unavailable";
  });
})();
