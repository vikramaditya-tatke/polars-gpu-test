# Benchmark results

Run status: **passed**. GPU: **pending**.

Warm local files. Seconds include complete Arrow materialization. Peak RSS includes initialization.

| Workload | Engine | n | Eligible | Query median [min–max] s | Peak RSS median / max MiB | Ingest median s | One-shot median s |
|---|---|---:|---|---:|---:|---:|---:|
| high-cardinality | chdb-mergetree | 5 | True | 4.644 [3.614–6.723] | 1774.8 / 1801.3 | 5.766 | 10.557 |
| high-cardinality | chdb-parquet | 5 | True | 6.346 [4.373–7.441] | 5510.9 / 5642.0 | — | 6.389 |
| high-cardinality | duckdb-1.5-parquet | 5 | True | 2.641 [2.377–4.581] | 1931.8 / 1975.3 | — | 2.653 |
| high-cardinality | duckdb-1.5-persistent | 5 | True | 3.352 [2.002–3.523] | 3039.4 / 3046.3 | 12.597 | 15.962 |
| high-cardinality | duckdb-2.0-parquet | 5 | True | 2.767 [2.426–4.199] | 2728.8 / 2779.0 | — | 2.835 |
| high-cardinality | duckdb-2.0-persistent | 5 | True | 2.793 [1.850–3.105] | 2336.2 / 2352.5 | 9.733 | 12.605 |
| high-cardinality | pandas | 5 | True | 25.918 [19.616–26.955] | 2271.4 / 2300.2 | — | 25.918 |
| high-cardinality | polars-1.8-default | 5 | True | 11.465 [10.397–17.166] | 16265.7 / 16624.0 | — | 11.465 |
| high-cardinality | polars-2.0-default | 5 | True | 4.055 [2.606–4.490] | 4839.2 / 4868.3 | — | 4.055 |
| high-cardinality | polars-2.0-in-memory | 5 | True | 3.647 [3.439–6.768] | 10710.6 / 10781.8 | — | 3.647 |
| join | chdb-mergetree | 5 | True | 1.094 [0.866–1.618] | 735.9 / 748.5 | 0.942 | 2.068 |
| join | chdb-parquet | 5 | True | 1.671 [0.999–1.759] | 1260.3 / 1404.2 | — | 1.696 |
| join | duckdb-1.5-parquet | 5 | True | 0.336 [0.298–0.541] | 192.3 / 193.1 | — | 0.346 |
| join | duckdb-1.5-persistent | 5 | True | 0.416 [0.337–0.563] | 250.5 / 251.2 | 3.187 | 3.615 |
| join | duckdb-2.0-parquet | 5 | True | 0.349 [0.243–0.394] | 279.8 / 283.2 | — | 0.382 |
| join | duckdb-2.0-persistent | 5 | True | 0.270 [0.192–0.398] | 249.8 / 250.2 | 2.006 | 2.342 |
| join | pandas | 5 | True | 15.909 [12.053–18.128] | 2321.1 / 2323.7 | — | 15.909 |
| join | polars-1.8-default | 5 | True | 2.716 [2.054–2.818] | 2962.9 / 3007.9 | — | 2.716 |
| join | polars-2.0-default | 5 | True | 0.936 [0.824–1.411] | 1021.4 / 1045.9 | — | 0.936 |
| join | polars-2.0-in-memory | 5 | True | 1.619 [1.396–2.218] | 2921.7 / 2965.1 | — | 1.619 |
| original | chdb-mergetree | 5 | True | 1.552 [1.097–1.845] | 728.5 / 735.6 | 1.044 | 2.775 |
| original | chdb-parquet | 5 | True | 1.534 [1.266–2.033] | 1414.0 / 1424.0 | — | 1.558 |
| original | duckdb-1.5-parquet | 5 | True | 0.558 [0.444–0.836] | 477.6 / 479.2 | — | 0.574 |
| original | duckdb-1.5-persistent | 5 | True | 0.707 [0.485–0.914] | 499.2 / 501.1 | 3.125 | 3.881 |
| original | duckdb-2.0-parquet | 5 | True | 0.543 [0.489–0.735] | 507.8 / 539.3 | — | 0.600 |
| original | duckdb-2.0-persistent | 5 | True | 0.595 [0.340–0.893] | 493.3 / 496.3 | 1.980 | 2.613 |
| original | pandas | 5 | True | 8.828 [8.264–10.737] | 1611.4 / 1612.6 | — | 8.828 |
| original | polars-1.8-default | 5 | True | 3.629 [2.553–4.074] | 3743.7 / 3772.4 | — | 3.629 |
| original | polars-2.0-default | 5 | True | 0.706 [0.560–1.049] | 1237.5 / 1271.8 | — | 0.706 |
| original | polars-2.0-in-memory | 5 | True | 2.440 [1.330–2.711] | 4362.7 / 4551.7 | — | 2.440 |
| selective | chdb-mergetree | 5 | True | 0.421 [0.355–0.537] | 487.8 / 489.3 | 0.845 | 1.315 |
| selective | chdb-parquet | 5 | True | 0.986 [0.855–1.404] | 2086.0 / 2104.1 | — | 1.013 |
| selective | duckdb-1.5-parquet | 5 | True | 0.079 [0.063–0.092] | 189.4 / 190.6 | — | 0.091 |
| selective | duckdb-1.5-persistent | 5 | True | 0.081 [0.066–0.097] | 242.6 / 243.6 | 3.197 | 3.291 |
| selective | duckdb-2.0-parquet | 5 | True | 0.083 [0.061–0.113] | 263.0 / 268.6 | — | 0.120 |
| selective | duckdb-2.0-persistent | 5 | True | 0.052 [0.050–0.073] | 234.6 / 235.3 | 1.864 | 1.939 |
| selective | pandas | 5 | True | 4.919 [4.284–6.604] | 1119.6 / 1152.5 | — | 4.919 |
| selective | polars-1.8-default | 5 | True | 0.199 [0.176–0.330] | 525.4 / 533.6 | — | 0.199 |
| selective | polars-2.0-default | 5 | True | 0.076 [0.045–0.115] | 193.3 / 197.5 | — | 0.076 |
| selective | polars-2.0-in-memory | 5 | True | 0.066 [0.052–0.151] | 210.1 / 211.6 | — | 0.066 |
