"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const leaderboard = fs.readFileSync(path.join(__dirname, "../site/leaderboard.js"), "utf8");

async function render(description) {
  const nodes = new Map();
  function get(id) {
    if (!nodes.has(id)) {
      const listeners = new Map();
      const defaults = {"theme-select": "system", "benchmark-filter": "all",
        "workload-filter": "all", "sort-filter": "performance"};
      nodes.set(id, {value: defaults[id] || "", innerHTML: "", textContent: "",
        hidden: false, listeners,
        addEventListener(name, fn) {listeners.set(name, fn);}});
    }
    return nodes.get(id);
  }
  const document = {
    documentElement: {dataset: {}},
    getElementById: get,
    querySelectorAll: () => []
  };
  const row = {benchmark: "TPROC-C", jobid: "EXAMPLE", database: "mariadb",
    database_display: "MariaDB", nopm: 2653370, tpm: 6162972,
    cpu_count: 192, cpu_model: "AMD EPYC", memory: "1487 GB",
    workload_class: "cpu-intensive", workload_uaw: false,
    workload_durability: "relaxed", result_description: description,
    submitted_by: "example-user", source_path: "results/tproc-c/mariadb/2026/09/EXAMPLE.json"};
  const context = {window: {}, document, navigator: {},
    localStorage: {getItem: () => null, removeItem() {}, setItem() {}},
    sessionStorage: {setItem() {}}, URL, location: {href: "https://tpc-council.github.io/hammerdb-results/"},
    fetch: async () => ({ok: true, json: async () => ({rows: [row]})})};
  vm.runInNewContext(leaderboard, context, {filename: "site/leaderboard.js"});
  await new Promise(setImmediate);
  await new Promise(setImmediate);
  return {html: get("results-c").innerHTML, get};
}

test("long result commentary is collapsed in Test details and preserves score and attribution", async () => {
  const {html} = await render(["Hardware: 192 CPUs", "Workload: 768 warehouses", "Tuning: <script>alert(1)</script>"].join(String.fromCharCode(10)));
  assert.ok(html.includes('<details class="run-details"><summary>Test details</summary>'));
  assert.doesNotMatch(html, /<details class="run-details"[^>]*open/);
  assert.match(html, /<p class="card-description">Hardware: 192 CPUs/);
  assert.match(html, /Workload: 768 warehouses/);
  assert.ok(html.includes("&lt;script&gt;alert(1)&lt;/script&gt;"));
  assert.doesNotMatch(html, /<script>alert/);
  assert.match(html, /2,653,370/);
  assert.match(html, /Submitted by/);
  assert.match(html, /View full report/);
});

test("results without commentary have no empty details dropdown", async () => {
  const {html} = await render("");
  assert.doesNotMatch(html, /class="run-details"/);
  assert.match(html, /class="card-bottom"/);
});

test("collapsed commentary remains searchable", async () => {
  const {get} = await render("An unusual storage layout called marker99");
  get("search-input").value = "marker99";
  get("search-input").listeners.get("input")();
  assert.match(get("results-c").innerHTML, /Test details/);
  assert.match(get("filter-count").textContent, /1 of 1 results/);
});
