# Choosing a local analytics engine with reproducible evidence

Compare Polars, DuckDB, chDB and pandas on identical PyPI-event workloads, with complete correctness checks, fresh processes, repeated timings and kernel peak-memory measurements. The new CPU harness lives in `benchmarks/`; the original notebook and GPU verifier remain available below.

[Polars 2.0 shipped on 6 October 2026](https://pola.rs/posts/release-polars-2/) and [DuckDB 2.0 shipped on 21 October 2026](https://duckdb.org/2026/10/21/announcing-duckdb-200). This comparison includes older versions so an upgrade can be evaluated alongside an engine choice. **GPU performance remains pending.**

## Reproduce the CPU comparison

Run these commands from the repository root. The two environments use the same Python patch version and hash-locked dependencies. They do not replace the original `.venv` or its legacy GPU dependencies.

```sh
uv venv --python 3.12.12 .venv-bench-legacy
uv venv --python 3.12.12 .venv-bench-modern
uv pip sync --python .venv-bench-legacy/bin/python --require-hashes benchmarks/requirements/legacy.txt
uv pip sync --python .venv-bench-modern/bin/python --require-hashes benchmarks/requirements/modern.txt

# Download all 19 shards using the existing verifier environment.
.venv/bin/python download_dataset.py --output-dir dataset

.venv-bench-modern/bin/python -m benchmarks run \
  --input 'dataset/*.parquet' --output-dir results/my-comparison
.venv-bench-modern/bin/python -m benchmarks report --output-dir results/my-comparison
```

Output directories must be new, preventing accidental mixing of different runs. `report` regenerates summaries and standalone HTML/SVG charts without executing any engine. To publish a completely passing run and its project dimension:

```sh
.venv-bench-modern/bin/python -m benchmarks report \
  --output-dir results/my-comparison --evidence-dir benchmarks/evidence/my-comparison
```

Options include `--legacy-python`, `--modern-python`, `--engines`, `--workloads`, `--repeats` (5), `--warmups` (1), `--threads` (available logical CPUs), `--seed` (42), and `--timeout` (300 seconds per subprocess phase). Use `python -m benchmarks run --help` for engine IDs and workload names. Linux is required for affinity and kernel peak RSS. Input files must contain string columns `COUNTRY_CODE`, `PROJECT` and `URL`.

If an interrupted run completed reference generation, `--reference-run results/prior-run` reuses its oracle tables only after checking identical input hashes, workload definitions, generator code and every reference-artifact checksum. Timing trials always run afresh. A disconnected console does not stop measurement collection; redirecting stdout to a log is also supported.

The ten configurations are Polars 1.8.2 default, Polars 2.0.0 default, Polars 2.0.0 in-memory, DuckDB 1.5.6 and 2.0.0 each reading Parquet and persistent tables, chDB 3.7.2 reading Parquet and MergeTree, and pandas 2.2.2. All environments hold pandas, chDB, PyArrow 16.1.0 and NumPy 1.26.4 constant. Full transitive versions and wheel hashes are locked in `benchmarks/requirements/`.

## What is measured

| Workload | Operation | What it helps assess |
| --- | --- | --- |
| `original` | Count downloads by country/project | Original correctness case; full scan and aggregation |
| `selective` | Filter country `GB`, then count by project | Selective file scanning and filtering before aggregation |
| `high-cardinality` | Count by country/URL | Larger grouping state and result materialization |
| `join` | Inner join a unique project dimension, count by country/bucket | Small-dimension enrichment followed by aggregation |

The complete dataset contains **30,385,077 rows**, **463,523 country/project groups**, and approximately **1.13 million country/URL groups**. `GB` selects approximately 1.5% of events. The dimension is derived outside measurements from distinct non-null projects: `SHA256(UTF8(PROJECT))[0] % 16`. It is a deterministic synthetic lookup, not a real project category. Its Parquet file and checksum accompany published evidence.

Every implementation reads the same files and required columns, returns every group, and sorts by download count descending followed by grouping keys ascending with nulls last. Counts use all rows; null and empty keys remain distinct. Null project keys do not match the non-null join dimension. Every warmup and measured result is compared in full against an independent streaming Python `Counter` oracle, including its order. Only physical string and integer widths are normalized.

Each trial runs in a fresh interpreter with the same CPU affinity and thread budget. Native engines may use that budget; pandas groupby remains single-threaded. Warmups and measured rounds run serially in reproducibly shuffled order. Relevant file bytes are pre-read before each phase: these are **warm local-file results**, without a guarantee of cache residency under memory pressure or any claim about cold storage.

Query time includes construction, reads, execution, deterministic sorting and complete Arrow materialization. Engine imports, reference generation, verification, output serialization and reporting are outside that timer. The Arrow conversion cost is included for every engine. Connection opening is recorded separately. Persistent modes bulk-load a fresh store for each trial, close it, then reopen it in a separate query process. Ingestion includes checkpoint/close; `one_shot_s` adds ingestion, reopen and query. Direct-file `one_shot_s` adds open and query.

Peak memory is Linux `ru_maxrss`, captured through materialization before export and verification. It includes initialization of that worker; baseline RSS and initialization high-water mark are recorded separately. It excludes the controller, oracle, verifier, OS file cache and GPU VRAM. Persistent ingestion has its own process peak; **peaks are not added together**. Engine memory policies use their defaults, with effective settings recorded.

Polars 2.0's lazy default is streaming; the explicit in-memory control helps distinguish that execution-mode change from other version changes. The legacy default uses its older CPU engine. See the [Polars 2.0 migration guide](https://docs.pola.rs/releases/upgrade/2/). Upgrade results compare shipped behavior, not a single isolated optimizer change.

MergeTree uses an explicitly untuned `ORDER BY ()` baseline, with no added index, partition or speculative datatype optimization. Per `schema-pk-plan-before-creation`, this physical layout is declared before table creation; selective results do not measure a filter-aligned ClickHouse index. Per `schema-types-avoid-nullable`, nullable keys are retained because they carry meaning. Per `query-join-choose-algorithm`, the small unique dimension is on the right. Bulk ingestion follows `insert-batch-size` guidance. These choices constrain what can be concluded about tuned ClickHouse deployments.

## Read the evidence

`manifest.json` records inputs and SHA-256 hashes, schemas, exact dependencies, Python versions, code and lock hashes, Git revision, hardware, settings and protocol. `trials.json`/`trials.csv` retain every warmup, repetition and failure. Query and ingestion workers have distinct PIDs. Timeouts kill the process group; crashes and incorrect results remain failures.

`summary.json`, `summary.csv`, `summary.md` and `charts.html` are regenerated from raw trials. Timings show median, interquartile range and observed range; memory shows median and maximum. A configuration is eligible only after every requested trial and warmup passes. Failed measurements are excluded from successful distributions, and failed/incomplete configurations are excluded from comparison charts. `comparisons.json` compares configurations within the same workload and storage mode; overlapping timing ranges are labeled **inconclusive**. Disjoint ranges describe these observations, not a statistical significance test.

### Engine-selection guidance

All ten configurations passed fixture correctness coverage for all four workloads, including checked warmups, null/empty/Unicode keys, empty selections and unmatched joins. The nine original verifier and notebook regression tests also passed. The full-dataset references independently reproduce 30,385,077 events, 463,523 country/project groups, 13,566 filtered project groups, 1,133,980 country/URL groups, and 3,009 country/bucket groups after the join.

**New performance rankings are pending the complete measured sweep.** An initial full-dataset run was interrupted after six passing warmups and zero measured samples; those warmups establish no performance ranking. Use the historical run below as correctness evidence only: it used a shared process and mixed ingestion with querying.

The [historical correctness report](benchmarks/evidence/2026-10-23-legacy-correctness.json) is retained in the repository so the original counts and verification status can be inspected without the ignored local outputs.

Use the measurements to choose for the actual workload and memory budget, alongside the interface your project needs. Polars exposes composable dataframe expressions; DuckDB supports SQL directly over files and persistent tables; chDB embeds ClickHouse query behavior; pandas integrates with existing pandas workflows. These are capability considerations, supported by the [Polars](https://docs.pola.rs/), [DuckDB](https://duckdb.org/docs/2.0/), [chDB](https://clickhouse.com/docs/chdb) and [pandas](https://pandas.pydata.org/docs/) documentation, rather than performance conclusions from this dataset.

Compare direct-file engines together. For persistent stores, compare both query time and ingestion-inclusive one-shot time. For repeated queries, estimate total cost as `ingestion + N × (open + query)` using the recorded phases; this is an estimate for repeated equivalent queries, not a measured long-lived database workload. It does not establish behavior on remote storage, data exceeding RAM, arbitrary joins, or tuned server deployments.

## Original notebook and GPU verification

Download public PyPI events, aggregate downloads by `COUNTRY_CODE` and `PROJECT`, and compare all seven notebook stages: chDB file queries and MergeTree, DuckDB in-memory and persistent, Polars CPU/GPU, and pandas.

Each complete result is checked against independent, streaming Python `Counter` counts. Null keys are retained and ties are normalized before comparison. Persistent stores are rebuilt in temporary directories and reopened before querying.

## Setup

Use Python 3.11 or 3.12. The notebook's RAPIDS 24.8.3 wheel is no longer published on NVIDIA's index. The nearest published release, 24.10.1, requires Polars >=1.8,<1.9; the project therefore pins Polars 1.8.2 and RAPIDS 24.10.1.

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e . pytest nbclient nbformat ipykernel
```

Alternatively, use `poetry install` and prefix the following Python commands with `poetry run`.

GPU execution requires Linux/WSL2, an NVIDIA Volta or newer GPU (compute capability 7.0+), and a compatible CUDA 12 runtime/driver. On supported hardware:

```sh
uv pip install --python .venv/bin/python --extra-index-url https://pypi.nvidia.com -e '.[gpu]'
# Or: poetry install -E gpu
```

The GTX 1050 Ti is Pascal (6.1) and cannot run this GPU backend. See the [Polars GPU documentation](https://docs.pola.rs/user-guide/gpu-support/) and use the [RAPIDS legacy installation guidance](https://docs.rapids.ai/install/) for the pinned stack.

## Run against real data

```sh
# One public shard, about 142 MiB. Omit --limit to download all 19 shards.
.venv/bin/python download_dataset.py --limit 1 --output-dir dataset
.venv/bin/python pipeline.py --input 'dataset/*.parquet' --gpu auto
```

- `--gpu auto` explicitly skips an unavailable GPU; all CPU stages must pass.
- `--gpu required` exits nonzero unless actual GPU execution and every CPU stage pass.
- `--gpu off` explicitly disables the GPU stage.
- `--repeats 3` repeats every engine, checking every result.
- `--output-dir results/run-name` chooses the artifact directory.

GPU execution uses `pl.GPUEngine(raise_on_fail=True)` to prevent silent CPU fallback. An execution error on an available GPU is a failure, even in `auto` mode. The pipeline reads the original uppercase Parquet key columns; file and schema errors propagate from the readers.

Downloads use bounded concurrency, propagate HTTP errors, clean up partial files, and atomically replace completed transfers. The downloader keeps its original current-directory default; the examples explicitly select `dataset/`. Parquet parsing remains the responsibility of the pipeline. A failed replacement preserves an existing destination. Use `--url URL` (repeatable), `--output-dir PATH`, and `--concurrency N` for custom sources.

## Notebook

Open `polars-gpu-test.ipynb` using this virtual environment's kernel and run all cells. It calls the same verifier and generates charts from current measurements. If the default dataset directory is empty, it downloads one shard automatically.

Optional environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `PYPI_DATASET` | `dataset/*.parquet` | File or glob with the original uppercase key columns |
| `PYPI_RESULTS_DIR` | `results/notebook` | Output directory |
| `PYPI_GPU` | `auto` | `auto`, `required`, or `off` |
| `PYPI_REPEATS` | `1` | Runs per engine |

## Outputs and verification

`results/verification.json` records versions, inputs, exact row/group counts, per-engine results, and GPU skip/failure reasons. It returns overall `passed` only when all required stages pass; always check `gpu_verified` separately when using `auto`.

`downloads.parquet` contains the independent reference aggregation, `measurements.csv` contains measured stage results, and `resource_usage.html` contains the resource charts. The HTML loads Vega libraries from a CDN when opened.

Timings support functional verification, not definitive performance comparisons. Persistent timings include ingestion and reopening; the DuckDB index from the old notebook was omitted because the query scans all rows. Memory is sampled process RSS, includes earlier stages' retained allocations, and excludes GPU VRAM. Data ingestion projects the two grouping keys consistently across engines.

For chDB, `ORDER BY ()` remains appropriate to this full-scan comparison: there are no filter predicates or joins. Per `schema-pk-plan-before-creation`, the ordering decision follows that query pattern. Per `schema-types-avoid-nullable`, null keys are retained because unknown and empty keys are semantically distinct; no speculative type or index optimization is applied. File ingestion is one bulk operation, consistent with `insert-batch-size`.

```sh
.venv/bin/python -m pytest -q
```

Tests exercise multiple Parquet shards, duplicate and tied counts, null/empty/Unicode keys, all six CPU stages, persistence after reopening, chart averages, missing inputs, strict GPU configuration, required-GPU failures, and downloader path contracts and HTTP/error atomicity using a local HTTP server. The GPU configuration test simulates execution and does not establish hardware support; only a successful real `--gpu required` run does.

## Verified run (23 October 2026)

The complete notebook executed in a fresh Python 3.12 kernel against all 19 default shards (2,648,789,261 bytes). All six CPU stages matched the independent reference: **30,385,077 rows and 463,523 groups**. Runtime versions: Polars 1.8.2, DuckDB 1.5.6, chDB 3.7.2, pandas 2.2.2, PyArrow 16.1.0. The integration suite passed **9 tests** and the installed dependencies passed `uv pip check`.

The host GTX 1050 Ti reports compute capability 6.1, so GPU execution remains unverified. A real `--gpu required` run returned exit code 1 and recorded that incompatibility. Dependency resolution for the GPU extra succeeded; the GPU packages were not installed on this unsupported device.

Local evidence is saved under `results/full-dataset/` and `results/gpu-required/`; the executed notebook is `results/executed-polars-gpu-test.ipynb`. Generated data and results are ignored by Git.
