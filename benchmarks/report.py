"""Deterministic summaries and standalone SVG/HTML charts from saved trials."""

from collections import defaultdict
import csv
import html
import itertools
import json
from pathlib import Path
import statistics

from .spec import ENGINES

METRICS = ("query_s", "open_s", "ingest_s", "one_shot_s", "peak_rss_mib", "ingest_peak_rss_mib")


def distribution(values):
    ordered = sorted(values)
    def quantile(q):
        index = (len(ordered) - 1) * q
        low = int(index)
        return ordered[low] + (ordered[min(low + 1, len(ordered) - 1)] - ordered[low]) * (index - low)
    return {"median": statistics.median(ordered), "q1": quantile(.25), "q3": quantile(.75),
            "min": ordered[0], "max": ordered[-1]}


def summarize(trials, repeats, warmups):
    grouped = defaultdict(list)
    for trial in trials:
        grouped[trial["workload"], trial["engine"]].append(trial)
    summaries = []
    for (workload, engine), records in sorted(grouped.items()):
        passed = [r for r in records if r["kind"] == "measured" and r["status"] == "passed"]
        failures = sum(r["status"] != "passed" for r in records)
        warm = [r for r in records if r["kind"] == "warmup"]
        eligible = (not failures and len(passed) == repeats and len(warm) == warmups
                    and {r["repeat"] for r in passed} == set(range(1, repeats + 1))
                    and {r["repeat"] for r in warm} == set(range(1, warmups + 1)))
        result = {"workload": workload, "engine": engine, "storage": ENGINES[engine].storage,
                  "n": len(passed), "failures": failures, "eligible": eligible}
        for metric in METRICS:
            values = [r[metric] for r in passed if metric in r]
            if values:
                result[metric] = distribution(values)
        summaries.append(result)
    return summaries


def comparisons(summaries):
    result = []
    for left, right in itertools.combinations(summaries, 2):
        if (not left["eligible"] or not right["eligible"] or left["workload"] != right["workload"]
                or left["storage"] != right["storage"]):
            continue
        a, b = left["query_s"], right["query_s"]
        faster = left["engine"] if a["max"] < b["min"] else (
            right["engine"] if b["max"] < a["min"] else None)
        result.append({"workload": left["workload"], "left": left["engine"], "right": right["engine"],
                       "conclusion": "observed ranges disjoint" if faster else "inconclusive: ranges overlap",
                       "faster": faster})
    return result


def write_csv(rows, path):
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with Path(path).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v
                             for k, v in row.items()})


def render_chart(rows, metric, title):
    rows = [r for r in rows if r["eligible"] and metric in r]
    if not rows:
        return "<p>No eligible measurements.</p>"
    maximum = max(r[metric]["max"] for r in rows) * 1.05 or 1
    width, label, plot = 980, 265, 640
    x = lambda value: label + value / maximum * plot
    parts = [f'<svg viewBox="0 0 {width} {60 + 30 * len(rows)}" role="img" '
             f'aria-label="{html.escape(title)}"><title>{html.escape(title)}</title>']
    for fraction in (0, .25, .5, .75, 1):
        at = x(maximum * fraction)
        parts.append(f'<line x1="{at}" x2="{at}" y1="22" y2="{35 + 30 * len(rows)}" stroke="#ddd"/>'
                     f'<text x="{at}" y="15" text-anchor="middle">{maximum * fraction:.2f}</text>')
    for i, row in enumerate(rows):
        y = 40 + i * 30
        stats = row[metric]
        parts.append(f'<text x="5" y="{y + 4}">{html.escape(row["engine"])}</text>'
                     f'<line x1="{x(stats["min"])}" x2="{x(stats["max"])}" y1="{y}" y2="{y}" stroke="#304a6e"/>'
                     f'<rect x="{x(stats["q1"])}" y="{y-6}" width="{max(1, x(stats["q3"])-x(stats["q1"]))}" height="12" fill="#a4bfdc"/>'
                     f'<circle cx="{x(stats["median"])}" cy="{y}" r="4" fill="#18395f"/>'
                     f'<text x="{label+plot+12}" y="{y+4}">{stats["median"]:.3f}</text>')
    parts.append("</svg>")
    return "".join(parts)


def generate_report(output_dir):
    output = Path(output_dir)
    manifest = json.loads((output / "manifest.json").read_text())
    trials = json.loads((output / "trials.json").read_text())
    summaries = summarize(trials, manifest["protocol"]["repeats"], manifest["protocol"]["warmups"])
    covered = {(r["workload"], r["engine"]) for r in summaries}
    for workload in manifest["workloads"]:
        for engine in manifest["engines"]:
            if (workload, engine) not in covered:
                summaries.append({"workload": workload, "engine": engine,
                                  "storage": ENGINES[engine].storage, "n": 0,
                                  "failures": 0, "eligible": False})
    summaries.sort(key=lambda r: (r["workload"], r["engine"]))
    if manifest["status"] != "passed":
        for row in summaries:
            row["eligible"] = False
    (output / "summary.json").write_text(json.dumps(summaries, indent=2) + "\n")
    (output / "comparisons.json").write_text(json.dumps(comparisons(summaries), indent=2) + "\n")
    write_csv(trials, output / "trials.csv")
    flat = [{k: v for k, v in row.items() if not isinstance(v, dict)} | {
        f"{metric}_{stat}": value for metric, values in row.items() if isinstance(values, dict)
        for stat, value in values.items()} for row in summaries]
    write_csv(flat, output / "summary.csv")
    markdown = ["# Benchmark results", "", f"Run status: **{manifest['status']}**. GPU: **pending**.", "",
                "Warm local files. Seconds include complete Arrow materialization. Peak RSS includes initialization.",
                "", "| Workload | Engine | n | Eligible | Query median [min–max] s | Peak RSS median / max MiB | Ingest median s | One-shot median s |",
                "|---|---|---:|---|---:|---:|---:|---:|"]
    for row in summaries:
        if "query_s" not in row:
            markdown.append(f"| {row['workload']} | {row['engine']} | 0 | False | no valid samples | — | — | — |")
            continue
        time = row["query_s"]
        memory = row["peak_rss_mib"]
        ingest = f"{row['ingest_s']['median']:.3f}" if "ingest_s" in row else "—"
        markdown.append(f"| {row['workload']} | {row['engine']} | {row['n']} | {row['eligible']} | "
                        f"{time['median']:.3f} [{time['min']:.3f}–{time['max']:.3f}] | "
                        f"{memory['median']:.1f} / {memory['max']:.1f} | {ingest} | {row['one_shot_s']['median']:.3f} |")
    (output / "summary.md").write_text("\n".join(markdown) + "\n")
    parts = ["<!doctype html><html lang='en'><meta charset='utf-8'><title>Engine comparison</title>",
             "<style>body{font:16px system-ui;margin:32px auto;max-width:1100px;color:#16283b}"
             "svg{width:100%;font:12px system-ui}section{margin:36px 0}pre{white-space:pre-wrap}</style>",
             "<h1>Engine comparison: warm local files</h1>",
             f"<p>Run: {html.escape(manifest['status'])}. GPU pending. "
             "Only complete, correct configurations appear. Fresh process for every trial.</p>",
             "<p>Lines: observed range; boxes: interquartile range; dots: median. "
             "Overlapping timing ranges are inconclusive. RSS includes engine initialization, excludes verification and GPU VRAM.</p>"]
    for workload in manifest["workloads"]:
        for storage in ("parquet", "persistent"):
            rows = [r for r in summaries if r["workload"] == workload and r["storage"] == storage]
            if not rows:
                continue
            parts.append(f"<section><h2>{html.escape(workload)} — {storage}</h2>")
            for metric, title in [("query_s", "Query seconds"), ("peak_rss_mib", "Query-worker peak RSS (MiB)"),
                                  ("ingest_s", "Ingestion seconds"), ("ingest_peak_rss_mib", "Ingestion-worker peak RSS (MiB)"),
                                  ("one_shot_s", "One-shot seconds (ingest + reopen + query)")]:
                if any(metric in r for r in rows):
                    parts.append(f"<h3>{title}</h3>" + render_chart(rows, metric, title))
            parts.append("</section>")
    parts.append("</html>")
    (output / "charts.html").write_text("\n".join(parts) + "\n")
    return summaries
