"""Private subprocess entrypoint. JSON files isolate engine imports and IPC costs."""

import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import sys
import time


def configure(cpus):
    os.sched_setaffinity(0, cpus)
    threads = len(cpus)
    for name in ("POLARS_MAX_THREADS", "OMP_NUM_THREADS", "ARROW_NUM_THREADS"):
        os.environ[name] = str(threads)
    for name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[name] = "1"
    # An inherited affinity override must not change the version default.
    os.environ.pop("POLARS_ENGINE_AFFINITY", None)
    import pyarrow as pa
    pa.set_cpu_count(threads)
    pa.set_io_thread_count(threads)


def peak_mib():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def execute(task):
    configure(task["cpus"])
    role = task["role"]
    if role == "prepare":
        from .reference import prepare
        return prepare(task["files"], task["workloads"], task["directory"])
    if role == "verify":
        from .reference import verify
        return verify(task["actual"], task["expected"], task["workload"])
    if role == "probe":
        return {"python": platform.python_version(), "executable": sys.executable,
                "dependencies": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}}

    from .adapters import Adapter
    import psutil
    adapter = Adapter(task["engine"], len(task["cpus"]))
    metrics = {"pid": os.getpid(), "affinity": sorted(os.sched_getaffinity(0)),
               "runtime_version": adapter.module.__version__,
               "baseline_rss_mib": psutil.Process().memory_info().rss / 2**20,
               "initialization_peak_rss_mib": peak_mib()}
    try:
        start = time.perf_counter()
        adapter.open(task.get("store"))
        metrics["open_s"] = time.perf_counter() - start
        if role == "ingest":
            start = time.perf_counter()
            adapter.ingest(task["files"], task["dimension"], task["workload"])
            adapter.close()  # Include checkpoint/flush/close in ingestion.
            metrics["ingest_s"] = metrics.pop("open_s") + time.perf_counter() - start
            metrics["peak_rss_mib"] = peak_mib()
        else:
            start = time.perf_counter()
            table = adapter.query(task["files"], task["dimension"], task["workload"])
            metrics["query_s"] = time.perf_counter() - start
            # Capture before settings inspection, export, and independent verification.
            metrics["peak_rss_mib"] = peak_mib()
            metrics["groups"] = table.num_rows
            metrics["settings"] = adapter.settings()
            from .reference import write_table
            write_table(table, task["result"])
    finally:
        adapter.close()
    metrics["imported_engines"] = [m for m in ("polars", "duckdb", "chdb", "pandas") if m in sys.modules]
    return metrics


if __name__ == "__main__":
    task = json.loads(Path(sys.argv[1]).read_text())
    result = execute(task)
    Path(task["metrics"]).write_text(json.dumps(result, indent=2) + "\n")
