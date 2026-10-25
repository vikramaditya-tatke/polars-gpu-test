# Choosing a local analytics engine with reproducible evidence

Compare Polars, DuckDB, chDB and pandas on identical PyPI-event workloads, with complete correctness checks, fresh processes, repeated timings and kernel peak-memory measurements. The new CPU harness lives in `benchmarks/`; the original notebook and GPU verifier remain available below.

[Polars 2.0 shipped on 6 October 2026](https://pola.rs/posts/release-polars-2/) and [DuckDB 2.0 shipped on 21 October 2026](https://duckdb.org/2026/10/21/announcing-duckdb-200). This comparison includes older versions so an upgrade can be evaluated alongside an engine choice. **GPU performance remains pending.**

## Measured results and engine choices

The complete **25 October 2026** run passed **240 full-result checks**: one warmup and five measured repetitions for each of ten configurations across four workloads. Every original aggregation matched **30,385,077 events and 463,523 groups**. The host was an Intel Core i7-8750H (6 physical cores / 12 logical CPUs), with 30.5 GiB visible RAM, Ubuntu 26.10 and Python 3.12.12. All workers shared the same 12-CPU affinity budget.

[Full results and ranges](benchmarks/evidence/2026-10-25/summary.md) · [Standalone charts](benchmarks/evidence/2026-10-25/charts.html) · [Raw trials](benchmarks/evidence/2026-10-25/trials.csv) · [Manifest and input hashes](benchmarks/evidence/2026-10-25/manifest.json)

Each cell below is **median query seconds / maximum query-worker peak RSS in MiB**, over five measured repetitions. Query time includes sorted Arrow materialization; startup/imports and correctness checks are excluded. These are warm local-file results for these implementations.

| Workload | Polars 2.0 default | Polars 2.0 in-memory | DuckDB 2.0 Parquet | chDB 3.7.2 Parquet | pandas 2.2.2 |
| --- | ---: | ---: | ---: | ---: | ---: |
| original | 0.706 / 1272 | 2.440 / 4552 | 0.543 / 539 | 1.534 / 1424 | 8.828 / 1613 |
| selective | 0.076 / 198 | 0.066 / 212 | 0.083 / 269 | 0.986 / 2104 | 4.919 / 1152 |
| high-cardinality | 4.055 / 4868 | 3.647 / 10782 | 2.767 / 2779 | 6.346 / 5642 | 25.918 / 2300 |
| join | 0.936 / 1046 | 1.619 / 2965 | 0.349 / 283 | 1.671 / 1404 | 15.909 / 2324 |

A lower median alone does not establish a speed winner. DuckDB 2.0 and default Polars 2.0 have overlapping timing ranges for `original` (0.489–0.735 vs 0.560–1.049 seconds), `selective` and `high-cardinality`; those speed comparisons are **inconclusive**. For `join`, the ranges are disjoint: DuckDB 2.0 took 0.243–0.394 seconds versus Polars 2.0's 0.824–1.411. These are observations from five samples, not a statistical significance test. [Pairwise comparisons](benchmarks/evidence/2026-10-25/comparisons.json) retain the same rule for every comparable pair.

| Engine | Choose it when | Evidence and tradeoff on this dataset |
| --- | --- | --- |
| Polars 2.0 | You want composable Python dataframe transformations and lazy file queries. | The streaming default reduced `original` to 0.706 s and 1,272 MiB maximum RSS, versus 2.440 s and 4,552 MiB for its in-memory control. The high-cardinality mode timings overlap, while the default uses substantially less memory: 4,868 vs 10,782 MiB maximum. |
| DuckDB 2.0 | SQL over files or an embedded database fits your application. | Its join was faster than Polars in these observations and peaked at 283 MiB. On the original and higher-cardinality aggregations, speed overlaps with default Polars; DuckDB used lower peak RSS. The selective case instead has lower peak RSS in default Polars. |
| chDB 3.7.2 | Reusing ClickHouse SQL and functions matters to your workflow. | The untuned file baseline has a performance/memory cost relative to DuckDB in these cases. MergeTree can reduce query memory and selective-query time, with separate ingestion costs shown below. This does not characterize a tuned ClickHouse server. |
| pandas 2.2.2 | Existing pandas behavior and integration justify the measured runtime cost. | All four dataframe baselines were slower than default Polars and DuckDB here. Memory is workload-dependent: its high-cardinality peak of 2,300 MiB was lower than default Polars' 4,868 MiB. Arrow reader predicates and dtype tuning are outside this baseline. |

The interface considerations above are supported by the [Polars lazy API](https://docs.pola.rs/user-guide/lazy/using/), [DuckDB Parquet support](https://duckdb.org/docs/2.0/data/parquet/overview), [chDB overview](https://clickhouse.com/docs/chdb) and [pandas documentation](https://pandas.pydata.org/docs/). The numerical recommendations come from the linked local evidence.

### What the older versions establish

Default Polars 1.8.2 took a median 3.629 s / maximum 3,772 MiB on `original`, and 11.465 s / 16,624 MiB on `high-cardinality`. Polars 2.0's defaults reduced both runtime and peak RSS in those cases, with disjoint observed timing ranges. This comparison includes the change to streaming; it does not isolate a single optimizer improvement. Keep the legacy stack when dependency compatibility requires it, including this repository's pinned legacy GPU verifier.

DuckDB 1.5.6 and 2.0 have overlapping direct-file timing ranges in **all four workloads**, so these data do not establish a direct-file speedup from that upgrade. DuckDB 1.5.6 also used less query-worker peak RSS in each direct-file case. Evaluate the new release's features and your dependency requirements alongside these measurements.

### When persistent storage pays

Ingestion-inclusive one-shot medians exceeded direct Parquet medians for every engine/workload pair. The table separates ingestion from querying; **one-shot includes ingestion, reopen and query**. Each column is summarized independently, so its medians need not add exactly.

| Workload | DuckDB 2.0: ingest / query / one-shot s | chDB MergeTree: ingest / query / one-shot s |
| --- | ---: | ---: |
| original | 1.980 / 0.595 / 2.613 | 1.044 / 1.552 / 2.775 |
| selective | 1.864 / 0.052 / 1.939 | 0.845 / 0.421 / 1.315 |
| high-cardinality | 9.733 / 2.793 / 12.605 | 5.766 / 4.644 / 10.557 |
| join | 2.006 / 0.270 / 2.342 | 0.942 / 1.094 / 2.068 |

For example, MergeTree's selective-query range was 0.355–0.537 s, versus 0.855–1.404 s from Parquet, but its ingestion median was 0.845 s. Its one-shot median was 1.315 s, versus 1.013 s for direct files. Budget both phases' memory as well: higher-cardinality MergeTree peaked at **7,559 MiB while ingesting** and **1,801 MiB while querying**.

For repeated equivalent queries, estimate `ingestion + N × (open + query)` from the recorded phases and compare it with direct-file cost. This is a phase-based estimate with fresh connections, not a measured long-lived database workload. Cold storage, remote files, data exceeding RAM, arbitrary joins, tuned layouts and newer pandas releases require their own measurements. **GPU results remain pending supported-hardware verification.**

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

These results describe the checked implementations rather than each library's performance ceiling. The pandas baseline projects columns with `read_parquet`, then filters and groups with dataframe operations; it does not pass Arrow reader predicates or tune categorical/Arrow-backed dtypes. Its join uses `validate="many_to_one"`. Phase-based one-shot costs exclude interpreter startup and imports, so they are not full CLI wall-clock times.

Peak memory is Linux `ru_maxrss`, captured through materialization before export and verification. It includes initialization of that worker; baseline RSS and initialization high-water mark are recorded separately. It excludes the controller, oracle, verifier, OS file cache and GPU VRAM. Persistent ingestion has its own process peak; **peaks are not added together**. Engine memory policies use their defaults, with effective settings recorded.

Polars 2.0's lazy default is streaming; the explicit in-memory control helps distinguish that execution-mode change from other version changes. The legacy default uses its older CPU engine. See the [Polars 2.0 migration guide](https://docs.pola.rs/releases/upgrade/2/). Upgrade results compare shipped behavior, not a single isolated optimizer change.

MergeTree uses an explicitly untuned `ORDER BY ()` baseline, with no added index, partition or speculative datatype optimization. Per `schema-pk-plan-before-creation`, this physical layout is declared before table creation; selective results do not measure a filter-aligned ClickHouse index. Per `schema-types-avoid-nullable`, nullable keys are retained because they carry meaning. Per `query-join-choose-algorithm`, the small unique dimension is on the right. Bulk ingestion follows `insert-batch-size` guidance. These choices constrain what can be concluded about tuned ClickHouse deployments.

## Read the evidence

`manifest.json` records inputs and SHA-256 hashes, schemas, exact dependencies, Python versions, code and lock hashes, Git revision, hardware, settings and protocol. `trials.json`/`trials.csv` retain every warmup, repetition and failure. Query and ingestion workers have distinct PIDs. Timeouts kill the process group; crashes and incorrect results remain failures.

`summary.json`, `summary.csv`, `summary.md` and `charts.html` are regenerated from raw trials. Timings show median, interquartile range and observed range; memory shows median and maximum. A configuration is eligible only after every requested trial and warmup passes. Failed measurements are excluded from successful distributions, and failed/incomplete configurations are excluded from comparison charts. `comparisons.json` compares configurations within the same workload and storage mode; overlapping timing ranges are labeled **inconclusive**. Disjoint ranges describe these observations, not a statistical significance test.

The [historical correctness report](benchmarks/evidence/2026-10-23-legacy-correctness.json) preserves the original six-stage verification separately. Its shared-process, one-repeat timings establish no fair performance ranking.

With the original development environment and both benchmark environments installed, run `.venv/bin/python -m pytest -q`. The complete suite passed **33 tests**, including all ten configurations, checked warmups, null/empty/Unicode keys, empty selections, unmatched joins, version checks, process isolation, timing boundaries, timeout cleanup, reference-cache validation and the original notebook/downloader regressions. Benchmark integration cases are skipped when their dedicated environments are absent.

## Original notebook and GPU verification

Download public PyPI events, aggregate downloads by `COUNTRY_CODE` and `PROJECT`, and compare all seven notebook stages: chDB file queries and MergeTree, DuckDB in-memory and persistent, Polars CPU/GPU, and pandas.

Each complete result is checked against independent, streaming Python `Counter` counts. Null keys are retained and ties are normalized before comparison. Persistent stores are rebuilt in temporary directories and reopened before querying.

### Setup

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

### Run against real data

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

### Notebook

Open `polars-gpu-test.ipynb` using this virtual environment's kernel and run all cells. It calls the same verifier and generates charts from current measurements. If the default dataset directory is empty, it downloads one shard automatically.

Optional environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `PYPI_DATASET` | `dataset/*.parquet` | File or glob with the original uppercase key columns |
| `PYPI_RESULTS_DIR` | `results/notebook` | Output directory |
| `PYPI_GPU` | `auto` | `auto`, `required`, or `off` |
| `PYPI_REPEATS` | `1` | Runs per engine |

### Outputs and verification

`results/verification.json` records versions, inputs, exact row/group counts, per-engine results, and GPU skip/failure reasons. It returns overall `passed` only when all required stages pass; always check `gpu_verified` separately when using `auto`.

`downloads.parquet` contains the independent reference aggregation, `measurements.csv` contains measured stage results, and `resource_usage.html` contains the resource charts. The HTML loads Vega libraries from a CDN when opened.

Timings support functional verification, not definitive performance comparisons. Persistent timings include ingestion and reopening; the DuckDB index from the old notebook was omitted because the query scans all rows. Memory is sampled process RSS, includes earlier stages' retained allocations, and excludes GPU VRAM. Data ingestion projects the two grouping keys consistently across engines.

For chDB, `ORDER BY ()` remains appropriate to this full-scan comparison: there are no filter predicates or joins. Per `schema-pk-plan-before-creation`, the ordering decision follows that query pattern. Per `schema-types-avoid-nullable`, null keys are retained because unknown and empty keys are semantically distinct; no speculative type or index optimization is applied. File ingestion is one bulk operation, consistent with `insert-batch-size`.

```sh
.venv/bin/python -m pytest -q
```

Tests exercise multiple Parquet shards, duplicate and tied counts, null/empty/Unicode keys, all six CPU stages, persistence after reopening, chart averages, missing inputs, strict GPU configuration, required-GPU failures, and downloader path contracts and HTTP/error atomicity using a local HTTP server. The GPU configuration test simulates execution and does not establish hardware support; only a successful real `--gpu required` run does.

### Verified run (23 October 2026)

The complete notebook executed in a fresh Python 3.12 kernel against all 19 default shards (2,648,789,261 bytes). All six CPU stages matched the independent reference: **30,385,077 rows and 463,523 groups**. Runtime versions: Polars 1.8.2, DuckDB 1.5.6, chDB 3.7.2, pandas 2.2.2, PyArrow 16.1.0. The integration suite passed **9 tests** and the installed dependencies passed `uv pip check`.

The host GTX 1050 Ti reports compute capability 6.1, so GPU execution remains unverified. A real `--gpu required` run returned exit code 1 and recorded that incompatibility. Dependency resolution for the GPU extra succeeded; the GPU packages were not installed on this unsupported device.

Local evidence is saved under `results/full-dataset/` and `results/gpu-required/`; the executed notebook is `results/executed-polars-gpu-test.ipynb`. Generated data and results are ignored by Git.
