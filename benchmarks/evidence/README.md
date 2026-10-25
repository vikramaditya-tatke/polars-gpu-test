# Benchmark evidence

`2026-10-23-legacy-correctness.json` preserves the original full-dataset verifier's report from revision `031d66c344c475a0588dceed4722e11db458131e`: 30,385,077 events and 463,523 country/project groups matched across all six CPU stages. GPU verification was false.

Its one-repeat timings used a shared process, and persistent timings included ingestion. They establish functional correctness, not a fair performance ranking. Keep them separate from the new isolated CPU comparison.

`2026-10-25/` contains the complete isolated comparison from source revision `18460f74d5a15db3081e6ce6b84ad57a2ae55c22`: all 40 warmups and 200 measured repetitions passed. The independent references cover all 19 shards and four workloads. GPU results remain pending. `checksums.json` covers every exported artifact, including the published project dimension. The oracle references were reused from a prior completed reference-generation phase only after validating the input, generator and artifact hashes; the 240 timing trials ran afresh.

New passing benchmark runs are exported here with `python -m benchmarks report --output-dir results/RUN --evidence-dir benchmarks/evidence/RUN`. Each export contains the manifest, raw trials, regenerated summaries/charts, project dimension and artifact checksums. Large oracle result tables and temporary stores remain under ignored `results/`.
