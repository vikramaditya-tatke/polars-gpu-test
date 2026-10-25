"""Serial subprocess orchestration, preflight and input provenance."""

from datetime import datetime, timezone
import glob
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import shutil
import signal
import subprocess
import sys
import tempfile

from .spec import COMMON_VERSIONS, ENGINES, WORKLOADS, definitions

ROOT = Path(__file__).resolve().parents[1]


class PhaseFailure(RuntimeError):
    pass


def save_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def warm_files(files):
    # Read bytes outside worker timing. This requests warm OS caching; it does not
    # promise residency under memory pressure and never evicts global caches.
    for path in files:
        with Path(path).open("rb") as stream:
            while stream.read(8 * 1024 * 1024):
                pass


def progress(message):
    """A disconnected terminal must not invalidate completed benchmark work."""
    try:
        print(message, flush=True)
    except BrokenPipeError:
        sys.stdout = open(os.devnull, "w")


def reuse_reference(source_dir, inputs, workloads, destination):
    """Reuse only complete, byte-verified oracle artifacts from identical code/data."""
    source = Path(source_dir).resolve()
    manifest = json.loads((source / "manifest.json").read_text())
    if manifest.get("inputs") != inputs:
        raise ValueError("Reference inputs differ from this run")
    if manifest.get("definitions") != json.loads(json.dumps(definitions())):
        raise ValueError("Reference workload definitions differ")
    for name in ("reference.py", "spec.py"):
        path = ROOT / "benchmarks" / name
        if manifest.get("code_sha256", {}).get(f"benchmarks/{name}") != sha256(path):
            raise ValueError(f"Reference generator changed: {name}")
    reference = manifest.get("reference", {})
    if not set(workloads) <= set(reference.get("workloads", {})):
        raise ValueError("Reference workload artifacts are incomplete")
    destination.mkdir(parents=True)
    for name in ["dimension.parquet", *(f"{workload}.arrow" for workload in workloads)]:
        artifact = source / "reference" / name
        if sha256(artifact) != manifest.get("reference_sha256", {}).get(name):
            raise ValueError(f"Reference checksum mismatch: {name}")
        shutil.copy2(artifact, destination / name)
    return {"dimension_rows": reference["dimension_rows"],
            "workloads": {name: reference["workloads"][name] for name in workloads}}


def phase(python, task, directory, log, timeout):
    directory, log = Path(directory), Path(log)
    directory.mkdir(parents=True, exist_ok=True)
    log.parent.mkdir(parents=True, exist_ok=True)
    metrics = directory / f"{task['role']}-metrics.json"
    spec = directory / f"{task['role']}-task.json"
    save_json(spec, task | {"metrics": str(metrics.resolve())})
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONHASHSEED"] = "0"
    with log.open("w") as output:
        process = subprocess.Popen([str(python), "-m", "benchmarks.worker", str(spec.resolve())],
                                   cwd=directory, env=env, stdout=output, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            returncode = process.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            if sys.exc_info()[0] is KeyboardInterrupt:
                raise
            raise PhaseFailure(f"{task['role']} timed out after {timeout}s; process group killed") from None
    if returncode:
        tail = log.read_text(errors="replace")[-6000:]
        raise PhaseFailure(f"{task['role']} exited {returncode}: {tail}")
    if not metrics.is_file():
        raise PhaseFailure(f"{task['role']} exited without metrics")
    return json.loads(metrics.read_text())


def preflight(interpreters, cpus, output, timeout):
    environments = {}
    for name, python in interpreters.items():
        result = phase(python, {"role": "probe", "cpus": cpus}, output / "scratch" / name,
                       output / "logs" / f"preflight-{name}.log", timeout)
        if not result["python"].startswith("3.12."):
            raise ValueError(f"{name}: Python 3.12 required; found {result['python']}")
        expected = COMMON_VERSIONS | ({"polars": "1.8.2", "duckdb": "1.5.6"} if name == "legacy"
                                      else {"polars": "2.0.0", "duckdb": "2.0.0"})
        for package, version in expected.items():
            actual = result["dependencies"].get(package)
            if actual != version:
                raise ValueError(f"{name}: {package}=={version} required, found {actual}")
        environments[name] = result
    if len({v["python"] for v in environments.values()}) > 1:
        raise ValueError("Benchmark environments must use the same Python patch version")
    return environments


def input_manifest(pattern):
    import pyarrow as pa
    import pyarrow.parquet as pq
    files = sorted({str(Path(f).resolve()) for f in glob.glob(str(pattern))})
    if not files:
        raise FileNotFoundError(f"No Parquet files match {pattern!r}")
    result = []
    for file in files:
        parquet = pq.ParquetFile(file)
        for key in ("COUNTRY_CODE", "PROJECT", "URL"):
            if key not in parquet.schema_arrow.names or not (
                pa.types.is_string(parquet.schema_arrow.field(key).type)
                or pa.types.is_large_string(parquet.schema_arrow.field(key).type)):
                raise ValueError(f"{file}: required string column {key}")
        result.append({"path": file, "bytes": Path(file).stat().st_size,
                       "rows": parquet.metadata.num_rows, "sha256": sha256(file),
                       "schema": str(parquet.schema_arrow)})
    return result


def hardware():
    import psutil
    cpu = next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")), platform.processor())
    result = {"platform": platform.platform(), "distribution": platform.freedesktop_os_release(),
              "cpu": cpu, "logical_cpus": os.cpu_count(), "physical_cores": psutil.cpu_count(logical=False),
              "available_affinity": sorted(os.sched_getaffinity(0)),
              "memory": dict(psutil.virtual_memory()._asdict()), "load_average": os.getloadavg(),
              "disk_free_bytes": shutil.disk_usage(ROOT).free}
    try:
        result["gpu_inventory"] = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,compute_cap,driver_version,memory.total", "--format=csv,noheader"],
            text=True, timeout=10).strip()
    except (OSError, subprocess.SubprocessError) as error:
        result["gpu_inventory"] = str(error)
    return result


def run_benchmarks(input_pattern, output_dir, legacy_python, modern_python, engines=None,
                   workloads=None, repeats=5, warmups=1, threads=None, seed=42, timeout=300,
                   reference_run=None):
    if sys.platform != "linux":
        raise ValueError("Linux required for affinity and kernel peak RSS measurements")
    if repeats < 1 or warmups < 0 or timeout <= 0:
        raise ValueError("repeats/timeout must be positive; warmups must be nonnegative")
    available = sorted(os.sched_getaffinity(0))
    threads = threads if threads is not None else len(available)
    if not 1 <= threads <= len(available):
        raise ValueError(f"threads must be in [1, {len(available)}]")
    cpus = available[:threads]
    engines, workloads = list(engines or ENGINES), list(workloads or WORKLOADS)
    if len(set(engines)) != len(engines) or len(set(workloads)) != len(workloads):
        raise ValueError("Engine/workload selections cannot contain duplicates")
    for name in engines:
        if name not in ENGINES:
            raise ValueError(f"Unknown engine: {name}")
    for name in workloads:
        if name not in WORKLOADS:
            raise ValueError(f"Unknown workload: {name}")
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    interpreters = {name: str(Path(python).absolute()) for name, python in
                    (("legacy", legacy_python), ("modern", modern_python))}
    interpreters = {name: python for name, python in interpreters.items()
                    if name in {ENGINES[e].environment for e in engines}}
    git = lambda *args: subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()
    manifest = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
                "status": "running", "git_revision": git("rev-parse", "HEAD"),
                "git_dirty": bool(git("status", "--porcelain")), "hardware": hardware(),
                "code_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in sorted((ROOT / "benchmarks").glob("*.py"))},
                "locks_sha256": {p.name: sha256(p) for p in sorted((ROOT / "benchmarks/requirements").glob("*.txt"))},
                "engines": engines, "workloads": workloads, "definitions": definitions(),
                "gpu": {"status": "pending", "verified": False,
                        "reason": "No supported-hardware strict GPU run is part of this CPU comparison"},
                "protocol": {"repeats": repeats, "warmups": warmups, "seed": seed, "threads": threads,
                             "affinity": cpus, "timeout_s": timeout,
                             "cache": "warm local files; relevant files pre-read before every phase",
                             "timing": "query construction through sorted Arrow materialization; excludes imports, export, verification",
                             "memory": "Linux ru_maxrss KiB / 1024; per worker through materialization, includes initialization; excludes verifier and VRAM",
                             "persistence": "fresh store per trial; ingestion incl. close; separate worker reopens before query"}}
    trials = []
    save_json(output / "manifest.json", manifest)
    save_json(output / "trials.json", trials)
    try:
        manifest["environments"] = preflight(interpreters, cpus, output, timeout)
        manifest["inputs"] = input_manifest(input_pattern)
        manifest["input_rows"] = sum(f["rows"] for f in manifest["inputs"])
        files = [f["path"] for f in manifest["inputs"]]
        reference_dir = output / "reference"
        controller = str(Path(sys.executable).absolute())
        if reference_run:
            reference = reuse_reference(reference_run, manifest["inputs"], workloads, reference_dir)
            manifest["reference_reused_from"] = str(Path(reference_run).resolve())
        else:
            reference = phase(controller, {"role": "prepare", "files": files, "workloads": workloads,
                                          "directory": str(reference_dir), "cpus": cpus}, output / "scratch/reference",
                              output / "logs/reference.log", timeout)
        dimension = str(reference_dir / "dimension.parquet")
        manifest["reference"] = reference
        manifest["reference_sha256"] = {p.name: sha256(p) for p in sorted(reference_dir.iterdir())}
        if "original" in reference["workloads"] and reference["workloads"]["original"]["matching_rows"] != manifest["input_rows"]:
            raise AssertionError("Oracle row count differs from Parquet metadata")
        save_json(output / "manifest.json", manifest)
        rng = random.Random(seed)
        for kind, rounds in (("warmup", warmups), ("measured", repeats)):
            for repeat in range(1, rounds + 1):
                combinations = [(engine, workload) for engine in engines for workload in workloads]
                rng.shuffle(combinations)
                for engine, workload in combinations:
                    trial_id = f"{kind}-{repeat}-{engine}-{workload}"
                    record = {"id": trial_id, "engine": engine, "workload": workload,
                              "kind": kind, "repeat": repeat, "status": "failed"}
                    spec = ENGINES[engine]
                    python = interpreters[spec.environment]
                    with tempfile.TemporaryDirectory(prefix=trial_id + "-", dir=output / "scratch") as scratch:
                        scratch = Path(scratch)
                        store = scratch / "store"
                        store.mkdir()
                        task = {"engine": engine, "workload": workload, "files": files,
                                "dimension": dimension, "cpus": cpus, "result": str(scratch / "result.arrow")}
                        if spec.storage == "persistent":
                            task["store"] = str(store)
                        try:
                            if spec.storage == "persistent":
                                warm_files(files + ([dimension] if workload == "join" else []))
                                ingestion = phase(python, task | {"role": "ingest"}, scratch,
                                                  output / "logs" / f"{trial_id}-ingest.log", timeout)
                                record.update(ingest_s=ingestion["ingest_s"],
                                              ingest_peak_rss_mib=ingestion["peak_rss_mib"], ingestion_worker=ingestion)
                                warm_files(sorted(p for p in store.rglob("*") if p.is_file()))
                            else:
                                warm_files(files + ([dimension] if workload == "join" else []))
                            measured = phase(python, task | {"role": "query"}, scratch,
                                             output / "logs" / f"{trial_id}-query.log", timeout)
                            record.update({key: measured[key] for key in
                                           ("open_s", "query_s", "peak_rss_mib", "baseline_rss_mib")})
                            record["query_worker"] = measured
                            record["one_shot_s"] = record.get("ingest_s", 0) + measured["open_s"] + measured["query_s"]
                            checked = phase(controller, {"role": "verify", "cpus": cpus, "workload": workload,
                                                         "actual": task["result"],
                                                         "expected": str(reference_dir / f"{workload}.arrow")}, scratch,
                                            output / "logs" / f"{trial_id}-verify.log", timeout)
                            record.update(status="passed", correctness=checked)
                        except (PhaseFailure, OSError, ValueError) as error:
                            record["error"] = f"{type(error).__name__}: {error}"
                    trials.append(record)
                    save_json(output / "trials.json", trials)
                    progress(f"{record['status'].upper()} {trial_id}" + (
                        f" {record['query_s']:.3f}s {record['peak_rss_mib']:.1f}MiB" if record['status'] == 'passed'
                        else f" {record['error'][-300:]}"))
        # Reject a run whose data changed while it was being measured.
        for entry in manifest["inputs"]:
            if sha256(entry["path"]) != entry["sha256"]:
                raise ValueError(f"Input changed during benchmark: {entry['path']}")
        manifest["status"] = "passed" if all(t["status"] == "passed" for t in trials) else "failed"
    except (Exception, KeyboardInterrupt) as error:
        manifest["status"] = "interrupted" if isinstance(error, KeyboardInterrupt) else "failed"
        manifest["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
        save_json(output / "manifest.json", manifest)
        shutil.rmtree(output / "scratch", ignore_errors=True)
        from .report import generate_report
        generate_report(output)
    return manifest


def export_evidence(output_dir, evidence_dir):
    output, evidence = Path(output_dir), Path(evidence_dir)
    manifest = json.loads((output / "manifest.json").read_text())
    if manifest["status"] != "passed":
        raise ValueError("Only a completely passing run can be published as evidence")
    evidence.mkdir(parents=True, exist_ok=False)
    for name in ("manifest.json", "trials.json", "trials.csv", "summary.json", "summary.csv",
                 "summary.md", "comparisons.json", "charts.html"):
        shutil.copy2(output / name, evidence / name)
    shutil.copy2(output / "reference/dimension.parquet", evidence / "dimension.parquet")
    save_json(evidence / "checksums.json", {p.name: sha256(p) for p in sorted(evidence.iterdir())})
