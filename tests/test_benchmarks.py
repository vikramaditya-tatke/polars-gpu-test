import json
import os
from pathlib import Path
import sys

import psutil
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from benchmarks import adapters, reference, runner, worker
from benchmarks.report import comparisons, generate_report, summarize
from benchmarks.spec import ENGINES, WORKLOADS

ROOT = Path(__file__).resolve().parents[1]
PYTHONS = {name: ROOT / f".venv-bench-{name}/bin/python" for name in ("legacy", "modern")}
ENVIRONMENTS_READY = all(p.exists() for p in PYTHONS.values())


@pytest.fixture
def benchmark_shards(tmp_path):
    records = [
        ("US", "polars", "url/a"), ("US", "polars", "url/a"),
        ("GB", "pandas", "url/b"), ("GB", "pandas", "url/b"),
        (None, "polars", "url/a"), ("", "polars", ""),
        ("US", None, None), (None, None, None), ("GB", None, "url/null"),
        ("DE", "quote's", "url/c"), ("JP", "日本語", "url/日本語"), ("GB", "", "url/empty"),
    ]
    schema = pa.schema([(n, pa.string()) for n in ("COUNTRY_CODE", "PROJECT", "URL")])
    source = tmp_path / "input"
    source.mkdir()
    for index, rows in enumerate((records[:6], records[6:])):
        table = pa.Table.from_pylist([dict(zip(schema.names, row)) for row in rows], schema=schema)
        pq.write_table(table, source / f"{index}.parquet")
    return source


@pytest.mark.skipif(not ENVIRONMENTS_READY, reason="Install both hash-locked benchmark environments")
def test_all_configurations_and_checked_warmups(benchmark_shards, tmp_path):
    output = tmp_path / "run"
    manifest = runner.run_benchmarks(str(benchmark_shards / "*.parquet"), output,
                                     PYTHONS["legacy"], PYTHONS["modern"],
                                     repeats=1, warmups=1, threads=2)
    assert manifest["status"] == "passed"
    assert manifest["input_rows"] == 12
    assert manifest["reference"]["workloads"]["original"] == {"groups": 10, "matching_rows": 12}
    assert manifest["gpu"]["status"] == "pending" and not manifest["gpu"]["verified"]
    trials = json.loads((output / "trials.json").read_text())
    assert len(trials) == 80
    assert all(t["status"] == "passed" for t in trials)
    pids = [t["query_worker"]["pid"] for t in trials]
    assert len(set(pids)) == 80
    for trial in trials:
        info = trial["query_worker"]
        family = ENGINES[trial["engine"]].family
        assert family in info["imported_engines"]
        assert set(info["imported_engines"]) <= {family, "pandas"}  # chDB imports pandas itself.
        assert info["affinity"] == manifest["protocol"]["affinity"]
        assert info["peak_rss_mib"] >= info["baseline_rss_mib"]
        if "ingestion_worker" in trial:
            assert trial["ingestion_worker"]["pid"] != info["pid"]
            assert trial["one_shot_s"] == pytest.approx(trial["ingest_s"] + trial["open_s"] + trial["query_s"])
    original = {p.name: p.read_bytes() for p in output.iterdir() if p.name.startswith("summary") or p.name == "charts.html"}
    generate_report(output)
    assert all((output / name).read_bytes() == data for name, data in original.items())
    assert all(s["eligible"] for s in json.loads((output / "summary.json").read_text()))
    assert not (output / "scratch").exists()
    evidence = tmp_path / "evidence"
    runner.export_evidence(output, evidence)
    assert runner.sha256(evidence / "dimension.parquet") == manifest["reference_sha256"]["dimension.parquet"]


@pytest.mark.skipif(not ENVIRONMENTS_READY, reason="Install both hash-locked benchmark environments")
@pytest.mark.parametrize("engine", ENGINES)
def test_empty_selection_and_unmatched_join(benchmark_shards, tmp_path, engine):
    files = [str(p) for p in sorted(benchmark_shards.glob("*.parquet"))]
    # No GB rows: preserve a typed empty result in every adapter.
    for path in files:
        table = pq.read_table(path)
        table = table.set_column(0, "COUNTRY_CODE", pa.array(["US"] * len(table)))
        pq.write_table(table, path)
    dimension = tmp_path / "dimension.parquet"
    pq.write_table(pa.table({"PROJECT": ["polars"], "PROJECT_BUCKET": pa.array([3], type=pa.uint8())}), dimension)
    for workload in ("selective", "join"):
        directory = tmp_path / workload
        directory.mkdir()
        task = {"engine": engine, "cpus": sorted(os.sched_getaffinity(0))[:2], "files": files,
                "dimension": str(dimension), "workload": workload, "result": str(directory / "result.arrow")}
        python = PYTHONS[ENGINES[engine].environment]
        if ENGINES[engine].storage == "persistent":
            store = directory / "store"
            store.mkdir()
            task["store"] = str(store)
            runner.phase(python, task | {"role": "ingest"}, directory, directory / "ingest.log", 60)
        runner.phase(python, task | {"role": "query"}, directory, directory / "query.log", 60)
        table = reference.read_table(task["result"]).cast(reference.schema_for(workload))
        assert table.num_rows == (0 if workload == "selective" else 1)
        if workload == "join":
            assert table.to_pylist() == [{"COUNTRY_CODE": "US", "PROJECT_BUCKET": 3, "DOWNLOADS": 4}]


def test_independent_reference_and_strict_verification(benchmark_shards, tmp_path):
    directory = tmp_path / "oracle"
    result = reference.prepare(sorted(benchmark_shards.glob("*.parquet")), WORKLOADS, directory)
    assert result["workloads"]["selective"]["matching_rows"] == 4
    assert result["workloads"]["join"]["matching_rows"] == 9
    expected = directory / "original.arrow"
    table = reference.read_table(expected)
    # A reordered result, dropped row or incorrect count is not accepted.
    for index, wrong in enumerate((table.take(pa.array(list(reversed(range(len(table)))))),
                                   table.slice(1), table.set_column(2, "DOWNLOADS", pa.array([99] * len(table), type=pa.uint64())))):
        path = tmp_path / f"wrong-{index}.arrow"
        reference.write_table(wrong, path)
        with pytest.raises(AssertionError, match="differs"):
            reference.verify(path, expected, "original")
    assert reference.verify(expected, expected, "original")["matching_rows"] == 12


@pytest.mark.parametrize("projects,buckets", [(["x", "x"], [1, 2]), ([None], [1]), (["x"], [16]), (["x"], [None])])
def test_dimension_contract(projects, buckets):
    with pytest.raises(ValueError):
        reference.validate_dimension(pa.table({"PROJECT": pa.array(projects, type=pa.string()),
                                               "PROJECT_BUCKET": pa.array(buckets, type=pa.uint8())}))


def test_preflight_rejects_wrong_versions_before_loading_data(tmp_path):
    with pytest.raises(ValueError, match="polars==2.0.0"):
        runner.preflight({"modern": sys.executable}, sorted(os.sched_getaffinity(0))[:1], tmp_path, 60)


def test_timing_and_peak_memory_captured_before_export(monkeypatch, tmp_path):
    events = []
    class FakeAdapter:
        module = type("Module", (), {"__version__": "test"})
        def open(self, store): events.append("open")
        def close(self): events.append("close")
        def query(self, *args):
            events.append("query")
            return pa.table({"x": [1]})
        def settings(self):
            events.append("settings")
            return {}
    monkeypatch.setattr(worker, "configure", lambda cpus: None)
    monkeypatch.setattr(adapters, "Adapter", lambda *args: FakeAdapter())
    ticks = iter([0, 1, 10, 12])
    monkeypatch.setattr(worker.time, "perf_counter", lambda: next(ticks))
    monkeypatch.setattr(worker, "peak_mib", lambda: events.append("peak") or 100)
    monkeypatch.setattr(reference, "write_table", lambda *args: events.append("export"))
    metrics = worker.execute({"role": "query", "engine": "pandas", "cpus": [0],
                              "files": [], "dimension": "", "workload": "original", "result": ""})
    assert metrics["open_s"] == 1 and metrics["query_s"] == 2
    assert events == ["peak", "open", "query", "peak", "settings", "export", "close"]


def test_timeout_kills_process_group_and_missing_metrics_fails(tmp_path):
    shim = tmp_path / "worker-shim"
    pidfile = tmp_path / "child-pid"
    shim.write_text(f"#!{sys.executable}\nimport subprocess,time\nfrom pathlib import Path\n"
                    f"child=subprocess.Popen([{sys.executable!r},'-c','import time; time.sleep(60)'])\n"
                    f"Path({str(pidfile)!r}).write_text(str(child.pid))\ntime.sleep(60)\n")
    shim.chmod(0o755)
    with pytest.raises(runner.PhaseFailure, match="timed out"):
        runner.phase(shim, {"role": "query"}, tmp_path / "phase", tmp_path / "log", 1)
    child = psutil.Process(int(pidfile.read_text())) if psutil.pid_exists(int(pidfile.read_text())) else None
    assert child is None or child.status() == psutil.STATUS_ZOMBIE
    shim.write_text(f"#!{sys.executable}\n")
    with pytest.raises(runner.PhaseFailure, match="without metrics"):
        runner.phase(shim, {"role": "query"}, tmp_path / "empty", tmp_path / "empty.log", 5)


def test_failed_and_incomplete_groups_are_ineligible():
    base = {"engine": "pandas", "workload": "original", "kind": "measured", "status": "passed",
            "query_s": 2, "open_s": 0, "one_shot_s": 2, "peak_rss_mib": 100, "repeat": 1}
    records = [base, base | {"repeat": 2, "status": "failed", "query_s": 1000}]
    summary = summarize(records, 2, 0)[0]
    assert summary["query_s"]["median"] == 2
    assert not summary["eligible"] and summary["failures"] == 1
    assert not summarize([base], 2, 0)[0]["eligible"]
    assert comparisons([summary]) == []
    other = summary | {"eligible": True, "engine": "polars-2.0-default", "query_s": {"min": 1, "max": 3}}
    same = summary | {"eligible": True}
    assert comparisons([same, other])[0]["faster"] is None


def test_invalid_arguments_and_input_schema(tmp_path):
    with pytest.raises(ValueError, match="positive"):
        runner.run_benchmarks("missing", tmp_path / "bad", sys.executable, sys.executable, repeats=0)
    with pytest.raises(FileNotFoundError):
        runner.input_manifest(str(tmp_path / "*.parquet"))
    pq.write_table(pa.table({"PROJECT": ["x"]}), tmp_path / "bad.parquet")
    with pytest.raises(ValueError, match="required string column"):
        runner.input_manifest(str(tmp_path / "*.parquet"))


def test_global_failure_and_missing_trials_never_produce_eligible_charts(tmp_path):
    runner.save_json(tmp_path / "manifest.json", {"status": "failed", "protocol": {"repeats": 1, "warmups": 0},
                                                "engines": ["pandas"], "workloads": ["original", "join"]})
    runner.save_json(tmp_path / "trials.json", [{"engine": "pandas", "workload": "original", "kind": "measured",
                                               "repeat": 1, "status": "passed", "query_s": 1, "open_s": 0,
                                               "one_shot_s": 1, "peak_rss_mib": 100}])
    summaries = generate_report(tmp_path)
    assert len(summaries) == 2 and not any(s["eligible"] for s in summaries)
    assert json.loads((tmp_path / "comparisons.json").read_text()) == []
    assert "No eligible measurements" in (tmp_path / "charts.html").read_text()


def test_console_disconnect_does_not_fail_run(monkeypatch):
    class Disconnected:
        def write(self, value): raise BrokenPipeError()
        def flush(self): pass
    monkeypatch.setattr(sys, "stdout", Disconnected())
    runner.progress("saved trial")
    assert sys.stdout.name == os.devnull
    sys.stdout.close()


def test_reused_reference_checks_data_code_and_every_artifact(benchmark_shards, tmp_path):
    from benchmarks.spec import definitions
    source = tmp_path / "source"
    files = sorted(benchmark_shards.glob("*.parquet"))
    metadata = reference.prepare(files, ["original"], source / "reference")
    inputs = runner.input_manifest(str(benchmark_shards / "*.parquet"))
    manifest = {"inputs": inputs, "definitions": definitions(), "reference": metadata,
                "code_sha256": {f"benchmarks/{name}": runner.sha256(ROOT / "benchmarks" / name)
                                for name in ["reference.py", "spec.py"]},
                "reference_sha256": {p.name: runner.sha256(p) for p in (source / "reference").iterdir()}}
    runner.save_json(source / "manifest.json", manifest)
    assert runner.reuse_reference(source, inputs, ["original"], tmp_path / "copy") == metadata
    with pytest.raises(ValueError, match="inputs differ"):
        runner.reuse_reference(source, [], ["original"], tmp_path / "other")
    manifest["code_sha256"]["benchmarks/reference.py"] = "different"
    runner.save_json(source / "manifest.json", manifest)
    with pytest.raises(ValueError, match="generator changed"):
        runner.reuse_reference(source, inputs, ["original"], tmp_path / "changed")
    manifest["code_sha256"]["benchmarks/reference.py"] = runner.sha256(ROOT / "benchmarks/reference.py")
    runner.save_json(source / "manifest.json", manifest)
    (source / "reference/original.arrow").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum mismatch"):
        runner.reuse_reference(source, inputs, ["original"], tmp_path / "corrupt")
