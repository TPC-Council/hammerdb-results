"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const html = fs.readFileSync(path.join(__dirname, "../site/annotate.html"), "utf8");
const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)];
assert.ok(scripts.length >= 2, "The annotation page must contain its controller script");
const controller = scripts[scripts.length - 1][1];

class Element {
  constructor(id) {
    this.id = id;
    this.value = "";
    this.textContent = "";
    this.hidden = false;
    this.open = false;
    this.checked = false;
    this.href = "";
    this.className = "";
    this.style = {};
    this.attrs = {};
    this.children = [];
    this.events = new Map();
  }
  addEventListener(type, callback) {
    if (!this.events.has(type)) this.events.set(type, []);
    this.events.get(type).push(callback);
  }
  setAttribute(name, value) { this.attrs[name] = value; }
  removeAttribute(name) { delete this.attrs[name]; }
  append(child) { this.children.push(child); }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...children) { this.children = children; }
  focus() { this.focused = true; }
  select() { this.selected = true; }
  scrollIntoView() { this.scrolled = true; }
  remove() { this.removed = true; }
}
const rowBase = {
  jobid: "6A484A99945303E263335303",
  submitted_by: "original-user",
  benchmark: "TPROC-C",
  database_display: "MariaDB",
  submitter_comments: [],
  annotation_company: {},
  annotation_workload: null,
  annotation_exists: false,
  workload_class: "unclassified",
  workload_uaw: null,
  workload_durability: "unknown",
  workload_details: "",
};

async function mount({ row: changes = {}, clipboard = "working", popupBlocked = false, legacyCopy = true } = {}) {
  const row = { ...rowBase, ...changes };
  const elements = new Map();
  const get = id => {
    if (!elements.has(id)) elements.set(id, new Element(id));
    return elements.get(id);
  };
  const radios = ["unclassified", "cpu-intensive", "io-intensive"].map(value => {
    const item = new Element(value);
    item.value = value;
    item.checked = value === "unclassified";
    return item;
  });
  const body = new Element("body");
  const clipboardWrites = [];
  const openedTabs = [];
  const document = {
    body,
    documentElement: { dataset: {} },
    getElementById: get,
    createElement: tag => new Element(tag),
    createTextNode: text => String(text),
    querySelector(selector) {
      if (selector === ".annotate-preview") return get("annotate-preview");
      if (selector === 'input[name="classification"]:checked')
        return radios.find(r => r.checked) || null;
      if (selector.startsWith('input[name="classification"][value="')) {
        const match = selector.match(/value="([^"]+)"/);
        return radios.find(r => r.value === match?.[1]) || null;
      }
      throw new Error("Unexpected selector: " + selector);
    },
    querySelectorAll(selector) {
      if (selector === 'input[name="classification"]') return radios;
      throw new Error("Unexpected selector list: " + selector);
    },
    execCommand(action) {
      if (action !== "copy" || !legacyCopy) return false;
      const textarea = body.children[body.children.length - 1];
      clipboardWrites.push(textarea.value);
      return true;
    },
  };
  const url = "https://github.com/HammerDBLtd/hammerdb-results";
  const window = {
    HammerDBResultsRepo: {
      owner: "HammerDBLtd", repo: "hammerdb-results", branch: "main",
      fullName: "HammerDBLtd/hammerdb-results", url
    },
    matchMedia() { return { matches: false, addEventListener() {} }; },
    open(initial, target) {
      if (popupBlocked) return null;
      const tab = {
        initial, target, closed: false, navigated: null, opener: window,
        close() { this.closed = true; },
        location: { replace(next) { tab.navigated = next; } }
      };
      openedTabs.push(tab);
      return tab;
    },
  };
  const navigator = {};
  if (clipboard !== "unavailable") {
    navigator.clipboard = {
      async writeText(text) {
        if (clipboard === "denied") throw new Error("Clipboard denied");
        clipboardWrites.push(text);
      }
    };
  }
  const localStorage = {
    getItem() { return null; },
    setItem() {},
    removeItem() {},
  };
  const location = { search: "?jobid=" + row.jobid };
  get("form-container").hidden = true;
  get("action-status").hidden = true;
  get("workload-section").hidden = true;
  get("github-editor-link").href = "";
  vm.runInNewContext(controller, {
    document, window, location, localStorage, navigator,
    URL, URLSearchParams, encodeURIComponent, fetch: async () => ({
      ok: true, json: async () => ({ rows: [row] })
    })
  }, { filename: "site/annotate.html" });
  await new Promise(setImmediate);
  async function click(id) {
    for (const fn of get(id).events.get("click") || []) fn();
    await new Promise(setImmediate);
  }
  return { get, row, radios, click, clipboardWrites, openedTabs };
}
function payload(page) {
  assert.equal(page.clipboardWrites.length, 1);
  return JSON.parse(page.clipboardWrites[0]);
}

test("comment-only needs only a GitHub login and text, without workload or company changes", async () => {
  const page = await mount({ row: { workload_uaw: undefined } });
  assert.equal(page.get("form-container").hidden, false);
  page.get("comment-author").value = "guest-user";
  page.get("new-comment").value = "I verified the MariaDB configuration.";
  await page.click("copy-json");
  const json = payload(page);
  assert.equal(json.github_username, "original-user");
  assert.deepEqual(json.comments, [{ github_username: "guest-user", text: "I verified the MariaDB configuration." }]);
  assert.deepEqual(json.company, {});
  assert.equal(Object.hasOwn(json, "workload"), false);
  assert.equal(page.get("action-status").hidden, false);
  assert.match(page.get("action-status").textContent, /JSON copied/);
});

test("new comments preserve previous comments and original company and workload metadata", async () => {
  const previous = { github_username: "original-user", text: "Original observation" };
  const workload = { classification: "cpu-intensive", use_all_warehouses: false, durability: "relaxed", details: "Original CPU settings verified in the report." };
  const company = { name: "Example DB", description: "Original description", logo_url: "https://example.org/logo.png" };
  const page = await mount({ row: {
    annotation_exists: true, submitter_comments: [previous], annotation_workload: workload,
    annotation_company: company, company_name: company.name,
    company_description: company.description, company_logo_url: company.logo_url,
    workload_class: workload.classification, workload_uaw: false,
    workload_durability: workload.durability, workload_details: workload.details,
  } });
  page.get("comment-author").value = "another-user";
  page.get("new-comment").value = "A later observation";
  await page.click("copy-json");
  const json = payload(page);
  assert.deepEqual(json.company, company);
  assert.deepEqual(json.workload, workload);
  assert.deepEqual(json.comments, [previous, { github_username: "another-user", text: "A later observation" }]);
});

test("missing GitHub login reports error beside the buttons, not at the top", async () => {
  const page = await mount();
  const topMessage = page.get("annotate-status").textContent;
  page.get("new-comment").value = "Comment without a login";
  await page.click("send-github");
  assert.equal(page.get("action-status").hidden, false);
  assert.match(page.get("action-status").textContent, /GitHub username/);
  assert.equal(page.get("comment-author").attrs["aria-invalid"], "true");
  assert.equal(page.get("action-status").scrolled, true);
  assert.equal(page.get("annotate-status").textContent, topMessage);
  assert.equal(page.openedTabs.length, 0);
});

test("nothing entered gets an actionable local error", async () => {
  const page = await mount();
  await page.click("copy-json");
  assert.match(page.get("action-status").textContent, /Enter a comment above/);
  assert.equal(page.get("new-comment").attrs["aria-invalid"], "true");
  assert.equal(page.clipboardWrites.length, 0);
});

test("open GitHub copies first, then navigates to a new annotation file", async () => {
  const page = await mount();
  page.get("comment-author").value = "guest-user";
  page.get("new-comment").value = "Tested the result";
  await page.click("send-github");
  assert.equal(page.clipboardWrites.length, 1);
  assert.equal(page.openedTabs.length, 1);
  assert.equal(page.openedTabs[0].initial, "about:blank");
  assert.match(page.openedTabs[0].navigated, /\/new\/main\?filename=submissions%2Fannotations%2F/);
  assert.match(page.get("action-status").textContent, /Paste it into the GitHub editor/);
});

test("existing annotation uses the GitHub edit URL", async () => {
  const page = await mount({ row: { annotation_exists: true, submitter_comments: [{github_username:"original-user", text:"First note"}] } });
  assert.match(page.get("github-editor-link").href, /\/edit\/main\/submissions\/annotations\/6A484A99945303E263335303\.json$/);
});

test("clipboard API failure uses the old copy fallback", async () => {
  const page = await mount({ clipboard: "denied" });
  page.get("comment-author").value = "guest-user";
  page.get("new-comment").value = "Copy with fallback";
  await page.click("copy-json");
  assert.equal(payload(page).comments[0].text, "Copy with fallback");
  assert.match(page.get("action-status").textContent, /JSON copied/);
});

test("when copying is blocked, show the prepared JSON next to the error", async () => {
  const page = await mount({ clipboard: "denied", legacyCopy: false });
  page.get("comment-author").value = "guest-user";
  page.get("new-comment").value = "Copy by hand";
  await page.click("send-github");
  assert.equal(page.clipboardWrites.length, 0);
  assert.equal(page.openedTabs[0].closed, true);
  assert.equal(page.get("annotate-preview").open, true);
  assert.match(page.get("action-status").textContent, /copy is unavailable/);
  assert.match(page.get("annotation-preview").textContent, /Copy by hand/);
});

test("editing CPU/I/O classification still requires evidence, but an ordinary comment does not", async () => {
  const page = await mount();
  page.radios[0].checked = false;
  page.radios[2].checked = true;
  page.get("comment-author").value = "guest-user";
  page.get("new-comment").value = "A comment";
  await page.click("copy-json");
  assert.match(page.get("action-status").textContent, /configuration details/);
  assert.equal(page.get("workload-details").attrs["aria-invalid"], "true");
  assert.equal(page.clipboardWrites.length, 0);
});
