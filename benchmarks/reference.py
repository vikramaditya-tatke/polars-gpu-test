"""Python Counter oracle. No benchmark engine is imported here."""

from collections import Counter
import hashlib
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.ipc as ipc
import pyarrow.parquet as pq

from .spec import WORKLOADS


def schema_for(workload):
    return pa.schema([(key, pa.uint8() if key == "PROJECT_BUCKET" else pa.string())
                      for key in WORKLOADS[workload].keys] + [("DOWNLOADS", pa.uint64())])


def write_table(table, path):
    with pa.OSFile(str(path), "wb") as sink:
        with ipc.new_file(sink, table.schema) as writer:
            writer.write_table(table)


def read_table(path):
    with pa.memory_map(str(path), "r") as source:
        return ipc.open_file(source).read_all()


def rows(files, columns):
    for path in files:
        for batch in pq.ParquetFile(path).iter_batches(columns=list(columns)):
            yield from zip(*(column.to_pylist() for column in batch.columns))


def validate_dimension(table):
    table = table.select(["PROJECT", "PROJECT_BUCKET"]).cast(
        pa.schema([("PROJECT", pa.string()), ("PROJECT_BUCKET", pa.uint8())]))
    projects, buckets = (column.to_pylist() for column in table.columns)
    if any(p is None for p in projects) or len(set(projects)) != len(projects):
        raise ValueError("Dimension PROJECT keys must be unique and non-null")
    if any(b is None or not 0 <= b < 16 for b in buckets):
        raise ValueError("Dimension buckets must be integers in [0, 15]")
    return dict(zip(projects, buckets))


def prepare(files, workloads, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    projects = sorted({project for (project,) in rows(files, ["PROJECT"]) if project is not None})
    dimension = pa.table({"PROJECT": pa.array(projects, type=pa.string()),
                          "PROJECT_BUCKET": pa.array([
                              hashlib.sha256(p.encode("utf-8")).digest()[0] % 16
                              for p in projects], type=pa.uint8())})
    pq.write_table(dimension, directory / "dimension.parquet")
    lookup = validate_dimension(dimension)
    descriptions = {}
    for name in workloads:
        spec = WORKLOADS[name]
        counts = Counter()
        for values in rows(files, spec.columns):
            if name == "selective":
                if values[0] != "GB":
                    continue
                key = (values[1],)
            elif name == "join":
                country, project = values
                if project is None or project not in lookup:
                    continue
                key = (country, lookup[project])
            else:
                key = values
            counts[key] += 1
        # Explicit Python ordering gives an oracle independent of engine sorting.
        ordered = sorted(counts.items(), key=lambda pair: (
            -pair[1], *((v is None, v if v is not None else "") for v in pair[0])))
        columns = list(zip(*[(*key, count) for key, count in ordered])) if ordered else [
            [] for _ in schema_for(name)]
        table = pa.Table.from_arrays([pa.array(c, type=f.type)
                                      for c, f in zip(columns, schema_for(name))],
                                     schema=schema_for(name))
        write_table(table, directory / f"{name}.arrow")
        descriptions[name] = {"groups": len(counts), "matching_rows": sum(counts.values())}
    return {"workloads": descriptions, "dimension_rows": len(projects)}


def verify(actual_path, expected_path, workload):
    actual = read_table(actual_path)
    expected = read_table(expected_path)
    if actual.column_names != schema_for(workload).names:
        raise AssertionError(f"Unexpected output columns: {actual.column_names}")
    # Normalize physical integer/string widths, preserving nulls and order.
    actual = actual.cast(schema_for(workload))
    if not actual.equals(expected):
        raise AssertionError(f"Complete ordered result differs: {actual.num_rows} vs "
                             f"{expected.num_rows} reference rows")
    return {"groups": actual.num_rows,
            "matching_rows": pc.sum(actual["DOWNLOADS"]).as_py() or 0}
