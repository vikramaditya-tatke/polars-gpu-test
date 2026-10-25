"""Engine adapters. Heavy imports happen only inside the selected worker."""

import importlib
from pathlib import Path

from .spec import ENGINES, WORKLOADS


class Adapter:
    def __init__(self, engine_id, threads):
        self.spec = ENGINES[engine_id]
        self.module = importlib.import_module(self.spec.family)
        if self.module.__version__ != self.spec.version:
            raise RuntimeError(f"Runtime version mismatch: {self.module.__version__} != {self.spec.version}")
        import pyarrow as pa
        self.pa = pa
        self.threads = threads
        self.connection = None

    def open(self, store=None):
        family = self.spec.family
        if family == "duckdb":
            self.connection = self.module.connect(str(Path(store) / "duckdb.db") if store else ":memory:")
            self.connection.execute(f"SET threads = {self.threads}")
        elif family == "chdb":
            from chdb.session import Session
            self.connection = Session(str(Path(store) / "chdb") if store else None)
            self.connection.query(f"SET max_threads = {self.threads}; SET max_insert_threads = {self.threads}")

    def close(self):
        if self.connection is not None:
            self.connection.close()

    def settings(self):
        if self.spec.family == "duckdb":
            names = ["threads", "memory_limit", "max_temp_directory_size", "temp_directory"]
            return {name: self.connection.execute(f"SELECT current_setting('{name}')").fetchone()[0]
                    for name in names}
        if self.spec.family == "chdb":
            table = self.connection.query(
                "SELECT name, value FROM system.settings WHERE name IN "
                "('max_threads', 'max_insert_threads', 'max_memory_usage', 'join_algorithm', "
                "'max_bytes_before_external_group_by', 'max_bytes_before_external_sort')", "ArrowTable")
            return dict(zip(table["name"].to_pylist(), table["value"].to_pylist()))
        if self.spec.family == "polars":
            return {"thread_pool_size": self.module.thread_pool_size(),
                    "engine": "in-memory" if self.spec.mode == "in-memory" else (
                        "streaming (2.0 default)" if self.spec.version == "2.0.0" else "cpu (1.8 default)"),
                    "memory_policy": "engine defaults"}
        return {"groupby": "pandas single-threaded", "arrow_threads": self.threads}

    def literal(self, value):
        value = str(value)
        if self.spec.family == "chdb":
            return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
        return "'" + value.replace("'", "''") + "'"

    def source(self, files, columns):
        if self.spec.family == "duckdb":
            return "read_parquet([" + ",".join(self.literal(f) for f in files) + "])"
        projection = ", ".join(f'"{c}"' for c in columns)
        return "(" + " UNION ALL ".join(
            f"SELECT {projection} FROM file({self.literal(f)}, Parquet)" for f in files) + ")"

    def ingest(self, files, dimension, workload):
        spec = WORKLOADS[workload]
        sources = [("events", files, spec.columns)]
        if workload == "join":
            sources.append(("dimension", [dimension], ("PROJECT", "PROJECT_BUCKET")))
        for name, paths, columns in sources:
            projection = ", ".join(f'"{c}"' for c in columns)
            storage = " ENGINE=MergeTree ORDER BY ()" if self.spec.family == "chdb" else ""
            sql = f"CREATE TABLE {name}{storage} AS SELECT {projection} FROM {self.source(paths, columns)}"
            if self.spec.family == "chdb":
                self.connection.query(sql)
            else:
                self.connection.execute(sql)

    def query(self, files, dimension, workload):
        spec = WORKLOADS[workload]
        if self.spec.family == "polars":
            pl = self.module
            frame = pl.scan_parquet(files).select(list(spec.columns))
            if workload == "selective":
                frame = frame.filter(pl.col("COUNTRY_CODE") == "GB")
            elif workload == "join":
                frame = frame.join(pl.scan_parquet(dimension), on="PROJECT", how="inner")
            frame = frame.group_by(list(spec.keys)).agg(pl.len().cast(pl.UInt64).alias("DOWNLOADS"))
            frame = frame.sort(["DOWNLOADS", *spec.keys],
                               descending=[True] + [False] * len(spec.keys), nulls_last=True)
            # Do not override the version default unless this is the explicit control.
            kwargs = {"engine": "in-memory"} if self.spec.mode == "in-memory" else {}
            return frame.collect(**kwargs).to_arrow()
        if self.spec.family == "pandas":
            pd = self.module
            frame = pd.concat([pd.read_parquet(f, columns=list(spec.columns)) for f in files],
                              ignore_index=True)
            if workload == "selective":
                frame = frame[frame["COUNTRY_CODE"] == "GB"]
            elif workload == "join":
                # The unique non-null dimension prevents pandas' null=null join behavior.
                frame = frame.merge(pd.read_parquet(dimension), on="PROJECT", how="inner",
                                    validate="many_to_one")
            result = frame.groupby(list(spec.keys), dropna=False, sort=False).size().reset_index(name="DOWNLOADS")
            result = result.sort_values(["DOWNLOADS", *spec.keys],
                                        ascending=[False] + [True] * len(spec.keys), na_position="last")
            return self.pa.Table.from_pandas(result, preserve_index=False)

        source = "events" if self.spec.storage == "persistent" else self.source(files, spec.columns)
        dimension_source = "dimension" if self.spec.storage == "persistent" else self.source(
            [dimension], ("PROJECT", "PROJECT_BUCKET"))
        expressions = [f'{"d" if key == "PROJECT_BUCKET" else "f"}."{key}"' for key in spec.keys]
        projection = ", ".join(f'{expr} AS "{key}"' for expr, key in zip(expressions, spec.keys))
        join = ""
        if workload == "join":
            kind = "ALL INNER" if self.spec.family == "chdb" else "INNER"
            join = f' {kind} JOIN {dimension_source} AS d ON f."PROJECT" = d."PROJECT"'
        where = " WHERE f.\"COUNTRY_CODE\" = 'GB'" if workload == "selective" else ""
        ordering = ', '.join(f'"{key}" ASC NULLS LAST' for key in spec.keys)
        sql = (f'SELECT {projection}, COUNT(*) AS "DOWNLOADS" FROM {source} AS f{join}{where} '
               f'GROUP BY {", ".join(expressions)} ORDER BY "DOWNLOADS" DESC, {ordering}')
        if self.spec.family == "duckdb":
            connection = self.connection.execute(sql)
            # DuckDB 2.0 removed fetch_arrow_table in favor of to_arrow_table.
            return (connection.to_arrow_table() if self.spec.version == "2.0.0"
                    else connection.fetch_arrow_table())
        return self.connection.query(sql, "ArrowTable")
