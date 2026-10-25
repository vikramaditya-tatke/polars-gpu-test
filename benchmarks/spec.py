"""Declarative workload and engine identities; safe to import before affinity setup."""

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class Engine:
    family: str
    version: str
    environment: str
    storage: str = "parquet"
    mode: str = "default"


ENGINES = {
    "polars-1.8-default": Engine("polars", "1.8.2", "legacy"),
    "polars-2.0-default": Engine("polars", "2.0.0", "modern"),
    "polars-2.0-in-memory": Engine("polars", "2.0.0", "modern", mode="in-memory"),
    "duckdb-1.5-parquet": Engine("duckdb", "1.5.6", "legacy"),
    "duckdb-1.5-persistent": Engine("duckdb", "1.5.6", "legacy", "persistent"),
    "duckdb-2.0-parquet": Engine("duckdb", "2.0.0", "modern"),
    "duckdb-2.0-persistent": Engine("duckdb", "2.0.0", "modern", "persistent"),
    "chdb-parquet": Engine("chdb", "3.7.2", "modern"),
    "chdb-mergetree": Engine("chdb", "3.7.2", "modern", "persistent"),
    "pandas": Engine("pandas", "2.2.2", "modern"),
}
COMMON_VERSIONS = {
    "pandas": "2.2.2", "chdb": "3.7.2", "pyarrow": "16.1.0",
    "numpy": "1.26.4", "psutil": "7.2.2",
}


@dataclass(frozen=True)
class Workload:
    columns: tuple[str, ...]
    keys: tuple[str, ...]
    description: str


WORKLOADS = {
    "original": Workload(("COUNTRY_CODE", "PROJECT"), ("COUNTRY_CODE", "PROJECT"),
                         "Count events by country and project"),
    "selective": Workload(("COUNTRY_CODE", "PROJECT"), ("PROJECT",),
                          "Filter country = GB; count events by project"),
    "high-cardinality": Workload(("COUNTRY_CODE", "URL"), ("COUNTRY_CODE", "URL"),
                                 "Count events by country and URL"),
    "join": Workload(("COUNTRY_CODE", "PROJECT"), ("COUNTRY_CODE", "PROJECT_BUCKET"),
                     "Inner join unique project dimension; count by country and bucket"),
}


def definitions():
    return {"engines": {k: asdict(v) for k, v in ENGINES.items()},
            "workloads": {k: asdict(v) for k, v in WORKLOADS.items()},
            "dimension": "Distinct non-null PROJECT; SHA256(UTF8(PROJECT))[0] % 16",
            "sort": "DOWNLOADS DESC, grouping keys ASC NULLS LAST"}
