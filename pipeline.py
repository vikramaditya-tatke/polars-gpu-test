"""Run the notebook's seven aggregation stages and check their complete results."""

import argparse
from collections import Counter
import ctypes
from datetime import datetime, timezone
import glob
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time

import altair as alt
import chdb
from chdb.session import Session
import duckdb
import pandas as pd
import polars as pl
from polars.testing import assert_frame_equal
import psutil
import pyarrow.parquet as pq

KEYS = ["COUNTRY_CODE", "PROJECT"]


def canonical(frame):
    """SQL counts use different integer widths; row order of ties is unspecified."""
    return frame.select(
        pl.col(KEYS).cast(pl.String), pl.col("DOWNLOADS").cast(pl.UInt64)
    ).sort(["DOWNLOADS", *KEYS], descending=[True, False, False], nulls_last=True)


def reference_counts(files):
    """Independent streaming Python oracle, including null grouping keys."""
    counts = Counter()
    for file in files:
        for batch in pq.ParquetFile(file).iter_batches(columns=KEYS):
            counts.update(zip(*(column.to_pylist() for column in batch.columns)))
    records = [(country, project, count) for (country, project), count in counts.items()]
    return canonical(pl.DataFrame(records, schema={
        "COUNTRY_CODE": pl.String, "PROJECT": pl.String, "DOWNLOADS": pl.UInt64
    }, orient="row"))


def gpu_unavailable_reason():
    """Check the CUDA driver and hardware before accepting a GPU benchmark."""
    try:
        cuda = ctypes.CDLL("libcuda.so.1")
        status = cuda.cuInit(0)
        if status:
            return f"CUDA driver initialization failed (code {status})"
        device = ctypes.c_int()
        if cuda.cuDeviceGet(ctypes.byref(device), 0):
            return "No CUDA device is available"
        major, minor = ctypes.c_int(), ctypes.c_int()
        status = cuda.cuDeviceComputeCapability(ctypes.byref(major), ctypes.byref(minor), device)
        if status:
            return f"Cannot determine CUDA compute capability (code {status})"
        if major.value < 7:
            return (f"GPU compute capability {major.value}.{minor.value} is unsupported; "
                    "the Polars GPU engine requires Volta or newer (7.0+)")
    except OSError as error:
        return f"CUDA driver unavailable: {error}"
    if importlib.util.find_spec("cudf_polars") is None:
        return "GPU backend missing; install the project's gpu extra on compatible hardware"
    return None


def measured(function):
    """Sample process RSS; this does not measure GPU VRAM or isolated engine memory."""
    process = psutil.Process()
    baseline = process.memory_info().rss
    samples = [baseline]
    stopped = threading.Event()

    def sample():
        while not stopped.wait(0.01):
            samples.append(process.memory_info().rss)

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    start = time.perf_counter()
    try:
        frame = function()
        elapsed = time.perf_counter() - start
    finally:
        samples.append(process.memory_info().rss)
        stopped.set()
        sampler.join()
    return frame, elapsed, max(samples) / 2**20, (max(samples) - baseline) / 2**20


def chart_results(measurements, output):
    data = pd.DataFrame(measurements)
    passed = (data[data["Status"] == "passed"]
              .groupby("Technology", as_index=False).mean(numeric_only=True))
    charts = []
    for field, title in [("Time per loop (s)", "Execution time (seconds)"),
                         ("Peak Memory (MiB)", "Sampled process peak RSS (MiB)")]:
        charts.append(alt.Chart(passed).mark_bar().encode(
            x=alt.X("Technology:N", sort="-y", title=None),
            y=alt.Y(f"{field}:Q", title=title),
            color="Technology:N", tooltip=["Technology:N", alt.Tooltip(f"{field}:Q")]
        ).properties(width=650, height=250))
    chart = alt.vconcat(*charts)
    chart.save(str(output))
    return chart


def run_pipeline(input_pattern="dataset/*.parquet", output_dir="results", gpu="auto", repeats=1):
    files = sorted(str(Path(file).resolve()) for file in glob.glob(str(input_pattern)))
    if not files:
        raise FileNotFoundError(f"No Parquet files match {input_pattern!r}; run download_dataset.py first")
    expected = reference_counts(files)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    measurements, failures = [], []
    projection = ", ".join(KEYS)
    sql = 'SELECT COUNTRY_CODE, PROJECT, COUNT(*) AS DOWNLOADS FROM {source} GROUP BY COUNTRY_CODE, PROJECT ORDER BY DOWNLOADS DESC'
    query = (pl.scan_parquet(files).group_by(KEYS).agg(pl.len().alias("DOWNLOADS"))
             .sort("DOWNLOADS", descending=True))

    def check(name, function):
        for repeat in range(repeats):
            try:
                frame, elapsed, peak, increment = measured(function)
                assert_frame_equal(canonical(frame), expected)
                measurements.append({"Technology": name, "Repeat": repeat + 1, "Status": "passed",
                                     "Time per loop (s)": elapsed, "Peak Memory (MiB)": peak,
                                     "Increment (MiB)": increment})
                print(f"PASS {name}: {expected.height:,} groups, {elapsed:.3f}s", flush=True)
            except Exception as error:
                reason = f"{type(error).__name__}: {error}"
                failures.append(f"{name}: {reason}")
                measurements.append({"Technology": name, "Repeat": repeat + 1,
                                     "Status": "failed", "Reason": reason})
                print(f"FAIL {name}: {reason}", flush=True)
                break

    # A fresh store avoids stale CREATE TABLE IF NOT EXISTS data on reruns.
    with tempfile.TemporaryDirectory(prefix="polars-stores-") as store:
        check("Polars CPU", lambda: query.collect(engine="cpu"))
        reason = "GPU explicitly disabled" if gpu == "off" else gpu_unavailable_reason()
        if reason:
            status = "failed" if gpu == "required" else "skipped"
            measurements.append({"Technology": "Polars GPU", "Status": status, "Reason": reason})
            if status == "failed":
                failures.append(f"Polars GPU: {reason}")
            print(f"{status.upper()} Polars GPU: {reason}", flush=True)
        else:
            check("Polars GPU", lambda: query.collect(engine=pl.GPUEngine(raise_on_fail=True)))

        def duck_memory():
            with duckdb.connect() as connection:
                return connection.execute(sql.format(source="read_parquet(?)"), [files]).pl()
        check("DuckDB In-Memory", duck_memory)

        def duck_disk():
            database = str(Path(store) / "duckdb.db")
            with duckdb.connect(database) as connection:
                connection.execute(f"CREATE OR REPLACE TABLE pypi AS SELECT {projection} FROM read_parquet(?)", [files])
            # Reopen to verify persistence; ingestion is included in this stage's timing.
            with duckdb.connect(database) as connection:
                return connection.execute(sql.format(source="pypi")).pl()
        check("DuckDB Persistent", duck_disk)

        # Explicit filenames keep the input set identical in every engine.
        def literal(value):
            return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
        sources = " UNION ALL ".join(
            f"SELECT {projection} FROM file({literal(file)}, Parquet)" for file in files)
        ch_source = f"({sources})"
        check("chDB In-Memory", lambda: pl.from_pandas(chdb.query(
            sql.format(source=ch_source), "Dataframe")))

        def ch_disk():
            path = str(Path(store) / "chdb")
            session = Session(path=path)
            try:
                session.query("DROP TABLE IF EXISTS pypi")
                # Full-table aggregation: no filter-driven index or partition is needed.
                # Nullable keys preserve unknown values as distinct groups.
                session.query(f"CREATE TABLE pypi ENGINE=MergeTree ORDER BY () "
                              f"AS SELECT * FROM {ch_source}")
            finally:
                session.close()
            session = Session(path=path)
            try:
                return pl.from_pandas(session.query(sql.format(source="pypi"), "Dataframe"))
            finally:
                session.close()
        check("chDB MergeTree", ch_disk)

        def pandas_query():
            frame = pd.concat([pd.read_parquet(file, columns=KEYS) for file in files], ignore_index=True)
            # pandas otherwise discards every row with a null grouping key.
            result = frame.groupby(KEYS, dropna=False).size().reset_index(name="DOWNLOADS")
            return pl.from_pandas(result)
        check("Pandas", pandas_query)

    expected.write_parquet(output / "downloads.parquet")
    pd.DataFrame(measurements).to_csv(output / "measurements.csv", index=False)
    chart_results(measurements, output / "resource_usage.html")
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "failed" if failures else "passed",
        "gpu_verified": any(row["Technology"] == "Polars GPU" and row["Status"] == "passed" for row in measurements),
        "files": files, "input_rows": int(expected["DOWNLOADS"].sum()), "groups": expected.height,
        "repeats": repeats, "measurements": measurements, "failures": failures,
        "versions": {name: importlib.metadata.version(name) for name in
                     ["polars", "duckdb", "chdb", "pandas", "pyarrow"]},
        "measurement_notes": "Process RSS includes earlier stages and excludes GPU VRAM. Persistent timings include ingestion and reopen. Functional checks, not an isolated performance benchmark."
    }
    (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="dataset/*.parquet", help="Parquet file or quoted glob")
    parser.add_argument("--output-dir", default="results")
    parser.add_argument("--gpu", choices=["auto", "required", "off"], default="auto")
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()
    report = run_pipeline(args.input, args.output_dir, args.gpu, args.repeats)
    raise SystemExit(1 if report["failures"] else 0)
