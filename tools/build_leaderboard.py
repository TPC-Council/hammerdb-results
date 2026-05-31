#!/usr/bin/env python3
from __future__ import annotations
import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_ROOT = REPO_ROOT / "results"
SITE_ROOT = REPO_ROOT / "site"
LEADERBOARD_JSON = SITE_ROOT / "leaderboard.json"
INDEX_HTML = SITE_ROOT / "index.html"

def _fmt_num(v: object) -> str:
    if v is None:
        return "—"
    if isinstance(v, (int, float)):
        if isinstance(v, float) and not v.is_integer():
            return f"{v:,.2f}"
        return f"{int(v):,}"
    return str(v)

def _short_os(v: object) -> str:
    s = str(v or "").replace("LTS", "").strip()
    parts = s.split()
    return " ".join(parts[:2]) if parts else "—"

def _load_rows() -> list[dict]:
    rows = []
    for fp in sorted(RESULTS_ROOT.rglob("*.json")):
        rel = fp.relative_to(REPO_ROOT).as_posix()
        p = json.loads(fp.read_text(encoding="utf-8"))
        job, cfg, res, sys = p.get("job", {}), p.get("benchmark_config", {}), p.get("result", {}), p.get("system", {})
        rows.append({
            "jobid": job.get("jobid"), "benchmark": job.get("benchmark"), "database": job.get("database"),
            "database_display": job.get("database_display"), "release": job.get("release"), "timestamp": job.get("timestamp"),
            "hdb_version": job.get("hdb_version"), "nopm": res.get("nopm"), "tpm": res.get("tpm"),
            "geomean_seconds": res.get("geomean_seconds"), "total_query_time_seconds": res.get("total_query_time_seconds"),
            "warehouses": cfg.get("warehouses"), "virtual_users": cfg.get("virtual_users"), "rampup_minutes": cfg.get("rampup_minutes"),
            "duration_minutes": cfg.get("duration_minutes"), "cpu_model": sys.get("cpumodel"), "cpu_count": sys.get("cpucount"),
            "memory": sys.get("memory"), "os_name": sys.get("os_name"), "source_path": rel,
        })
    def _sort_key(row: dict) -> tuple:
        benchmark = row.get("benchmark")
        if benchmark == "TPROC-H":
            value = row.get("geomean_seconds")
            missing = value is None
            return (benchmark or "", missing, float(value) if isinstance(value, (int, float)) else float("inf"), row.get("jobid") or "")
        value = row.get("nopm")
        missing = value is None
        return (benchmark or "", missing, -(value or 0), row.get("jobid") or "")

    rows.sort(key=_sort_key)

    ranks_by_benchmark: dict[str, int] = {}
    for r in rows:
        benchmark = r.get("benchmark") or "Unknown"
        ranks_by_benchmark[benchmark] = ranks_by_benchmark.get(benchmark, 0) + 1
        r["rank"] = ranks_by_benchmark[benchmark]
    return rows


def _write_json(rows: list[dict]) -> None:
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "title": "HammerDB Result Artifacts Prototype Data",
        "disclaimer": ["Community-submitted HammerDB results", "Unaudited", "Not official TPC benchmark results"],
        "rows": rows,
    }
    LEADERBOARD_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def _row_html(row: dict) -> str:
    report = f"report.html?artifact={quote(row.get('source_path',''), safe='')}"
    db = row.get("database_display") or row.get("database") or "Unknown"
    benchmark = row.get("benchmark") or "—"
    if benchmark == "TPROC-C":
        result_html = f"<div class='main-metric'>{escape(_fmt_num(row.get('nopm')))} <span>NOPM</span></div><div class='sub-metric'>TPM {escape(_fmt_num(row.get('tpm')))}</div>"
    elif benchmark == "TPROC-H":
        result_html = f"<div class='main-metric'>{escape(_fmt_num(row.get('geomean_seconds')))} <span>Geomean sec</span></div><div class='sub-metric'>Total Query Time {escape(_fmt_num(row.get('total_query_time_seconds')))}</div>"
    else:
        result_html = "<div class='main-metric'>— <span>Result</span></div><div class='sub-metric'>No primary metric</div>"
    chips = [("Warehouses", row.get("warehouses")), ("VUs", row.get("virtual_users")), ("Rampup", row.get("rampup_minutes")), ("Duration", row.get("duration_minutes"))]
    cfg = "".join(f"<span class='chip'>{k}: {escape(_fmt_num(v))}</span>" for k, v in chips if v is not None)
    compact_sys = " · ".join([x for x in [row.get("cpu_count") and f"CPU {row.get('cpu_count')}", row.get("memory"), _short_os(row.get("os_name"))] if x and x != "—"])
    return f"""<article class='lb-row'>
<div class='left'><div class='rank'>#{escape(str(row.get('rank','—')))}</div><div><strong>{escape(str(db))}</strong><div class='muted'>Release {escape(str(row.get('release') or '—'))} · {escape(str(benchmark))}</div></div></div>
<div class='mid'><div class='result'>{result_html}</div><div class='config'>{cfg}</div></div>
<div class='right'><div class='system'>{escape(compact_sys or 'System unavailable')}</div><div class='date'>{escape(str(row.get('timestamp') or '—'))}</div><a class='btn' href='{escape(report)}'>View report</a></div>
</article>"""


def _benchmark_summary_html(benchmark: str, rows: list[dict]) -> str:
    db_count = len({(r.get("database_display") or r.get("database") or "Unknown") for r in rows})
    if benchmark == "TPROC-H":
        primary_label = "Best geomean"
        primary_value = min((r.get("geomean_seconds") for r in rows if isinstance(r.get("geomean_seconds"), (int, float))), default=None)
    else:
        primary_label = "Top NOPM"
        primary_value = max((r.get("nopm") for r in rows if isinstance(r.get("nopm"), (int, float))), default=None)

    return f"""<section class='stats benchmark-stats'><article class='stat'><div class='k'>Results</div><div class='v'>{len(rows)}</div></article><article class='stat'><div class='k'>Databases</div><div class='v'>{db_count}</div></article><article class='stat'><div class='k'>{escape(primary_label)}</div><div class='v'>{escape(_fmt_num(primary_value))}</div></article></section>"""


def _section_html(title: str, rows: list[dict], empty_message: str) -> str:
    visible = rows[:100]
    summary = _benchmark_summary_html(title, rows)
    if visible:
        body = "".join(_row_html(r) for r in visible)
    else:
        body = f"<article class='empty-row'>{escape(empty_message)}</article>"
    return f"""<section class='section-head'><h2>{escape(title)}</h2></section>{summary}<section class='lb'>{body}</section>"""

def _write_html(rows: list[dict]) -> None:
    tproc_c_rows = sorted(
        [r for r in rows if r.get("benchmark") == "TPROC-C"],
        key=lambda r: (r.get("nopm") is None, -(r.get("nopm") or 0), r.get("jobid") or ""),
    )
    tproc_h_rows = sorted(
        [r for r in rows if r.get("benchmark") == "TPROC-H"],
        key=lambda r: (r.get("geomean_seconds") is None, r.get("geomean_seconds") if isinstance(r.get("geomean_seconds"), (int, float)) else float("inf"), r.get("jobid") or ""),
    )

    for i, r in enumerate(tproc_c_rows, 1):
        r["rank"] = i
    for i, r in enumerate(tproc_h_rows, 1):
        r["rank"] = i

    top_c_html = _section_html("TPROC-C", tproc_c_rows, "No TPROC-C results yet.")
    top_h_html = _section_html("TPROC-H", tproc_h_rows, "No TPROC-H results yet.")
    html = f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>HammerDB Result Artifacts</title>
<style>:root{{--bg:#f4f7ff;--page:#f4f7ff;--panel:#fff;--line:#ddd8cf;--line-strong:#cfc7bb;--muted:#64748b;--blue:#2563eb;--text:#0f172a}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);font-family:Inter,Segoe UI,Arial,sans-serif;color:var(--text)}}
.wrap{{max-width:1220px;margin:0 auto;padding:0 24px 32px}}.hero{{background:var(--bg);color:var(--text);padding:22px 0 0;margin-bottom:0}}
.hero-card{{background:#fff;border:1px solid var(--line);border-radius:18px;padding:18px 20px;box-shadow:0 1px 2px rgba(60,50,40,.06)}}
    .brandbar{{display:flex;align-items:flex-start;justify-content:space-between;gap:24px;margin-bottom:12px}}.brand-left{{display:flex;align-items:flex-end;gap:18px}}.brand-hammerdb{{height:62px;width:auto;display:block}}.brand-tpc{{height:62px;width:auto;display:block;margin-top:0}}
.hero h1{{margin:0;font-size:2.2rem;line-height:1.08;letter-spacing:-.03em}}.hero p{{max-width:780px;color:#334155;margin:0}}.badges{{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 0}}.badge{{padding:6px 12px;border-radius:999px;background:#fff;border:1px solid var(--line-strong);color:#334155;font-weight:700;font-size:.84rem}}
.warn{{margin-top:16px;padding:12px 14px;border-radius:12px;background:#fff;border:1px solid var(--line);color:#334155;font-weight:600;margin-bottom:0}}
.top-grid{{display:grid;grid-template-columns:1.4fr 1fr;gap:16px;margin:14px 0 16px}}.card{{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:18px 20px;box-shadow:0 1px 2px rgba(60,50,40,.06)}}
.btn{{display:inline-block;background:#111827;color:#fff;text-decoration:none;padding:9px 12px;border-radius:10px;font-weight:800}}.star{{color:#facc15;margin-right:4px}}.stats{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:0 0 10px}}
.stat{{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:14px 16px;box-shadow:0 1px 2px rgba(60,50,40,.05)}}.stat .k{{color:var(--muted);font-size:.84rem}}.stat .v{{margin-top:6px;font-size:1.5rem;font-weight:850;letter-spacing:-.02em}}
.section-head{{margin:22px 0 10px}}.section-head h2{{margin:0;font-size:1.35rem;letter-spacing:-.02em}}.lb{{display:flex;flex-direction:column;gap:10px}}.empty-row{{background:var(--panel);border:1px dashed var(--line-strong);border-radius:16px;padding:18px 20px;color:var(--muted)}}.lb-row{{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:14px;display:grid;grid-template-columns:1.15fr 1.4fr .95fr;gap:12px;align-items:center;box-shadow:0 1px 2px rgba(60,50,40,.05)}}
.lb-row:hover{{border-color:var(--line-strong);box-shadow:0 8px 20px rgba(60,50,40,.08)}}.left{{display:flex;gap:10px;align-items:center}}.rank{{font-weight:850;color:#1d4ed8;min-width:38px}}.left strong{{font-size:1.03rem}}.muted{{color:var(--muted);font-size:.84rem}}
.main-metric{{font-size:1.18rem;font-weight:850;letter-spacing:-.015em}}.main-metric span{{font-size:.72rem;color:var(--muted);text-transform:uppercase}}.sub-metric{{color:var(--muted);font-size:.86rem;margin-top:2px}}
.config{{display:flex;flex-wrap:wrap;gap:6px;margin-top:7px}}.chip{{background:#fff;border:1px solid #ddd8cf;color:#334155;border-radius:999px;padding:2px 8px;font-size:.76rem;font-weight:700}}
.right{{text-align:right}}.system{{font-size:.88rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.date{{color:var(--muted);font-size:.82rem;margin:4px 0 7px}}.right .btn{{background:var(--blue)}}
@media(max-width:980px){{.top-grid,.stats{{grid-template-columns:1fr}}.lb-row{{grid-template-columns:1fr}}.right{{text-align:left}}.system{{white-space:normal}}}}@media(max-width:700px){{.brandbar{{align-items:center}}.brand-hammerdb{{height:48px}}.brand-tpc{{height:48px}}.brand-left{{gap:12px}}.hero h1{{font-size:1.8rem}}.hero{{padding:14px 0 0}}}}</style></head><body>
<header class='hero'><div class='wrap'><div class='hero-card'><div class='brandbar'><div class='brand-left'><img class='brand-hammerdb' src='assets/images/hammerDB-H-logo-FINAL.png' alt='HammerDB'><h1>HammerDB Result Artifacts</h1></div><img class='brand-tpc' src='assets/images/tpclogo.png' alt='TPC'></div><div class='warn'>User-submitted, unaudited HammerDB result artifacts reviewed through GitHub.</div></div></div></header>
<main class='wrap'><section class='top-grid'><article class='card'><h2 style='margin:0 0 8px'>Star HammerDB on GitHub</h2><p>Help others discover HammerDB by starring the project.</p><a class='btn' href='https://github.com/TPC-Council/HammerDB'><span class='star'>★</span> Star HammerDB</a></article><article class='card'><h3 style='margin:0 0 8px'>Submission guidance</h3><p style='margin:0;color:var(--muted)'>To submit a result, open the benchmark report in HammerDB and use Share with TPC-OSS.</p></article></section>
{top_c_html}{top_h_html}</main></body></html>"""
    INDEX_HTML.write_text(html, encoding='utf-8')

def main() -> int:
    SITE_ROOT.mkdir(parents=True, exist_ok=True)
    rows = _load_rows(); _write_json(rows); _write_html(rows)
    print(f"Generated {LEADERBOARD_JSON.relative_to(REPO_ROOT)} and {INDEX_HTML.relative_to(REPO_ROOT)} with {len(rows)} row(s).")
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
