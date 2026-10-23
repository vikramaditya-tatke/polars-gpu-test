# Polars GPU pipeline verification

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
