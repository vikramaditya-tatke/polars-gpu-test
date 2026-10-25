"""Run from the repository root: python -m benchmarks --help."""

import argparse
import sys

from .spec import ENGINES, WORKLOADS


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run checked trials in fresh subprocesses")
    run.add_argument("--input", default="dataset/*.parquet")
    run.add_argument("--output-dir", required=True, help="New output directory (never overwritten)")
    run.add_argument("--legacy-python", default=".venv-bench-legacy/bin/python")
    run.add_argument("--modern-python", default=".venv-bench-modern/bin/python")
    run.add_argument("--engines", nargs="+", choices=ENGINES)
    run.add_argument("--workloads", nargs="+", choices=WORKLOADS)
    run.add_argument("--repeats", type=int, default=5)
    run.add_argument("--warmups", type=int, default=1)
    run.add_argument("--threads", type=int)
    run.add_argument("--seed", type=int, default=42)
    run.add_argument("--timeout", type=float, default=300)
    run.add_argument("--reference-run", help="Reuse byte-verified references from a prior run with identical data and oracle code")
    report = commands.add_parser("report", help="Regenerate summaries/charts without rerunning engines")
    report.add_argument("--output-dir", required=True)
    report.add_argument("--evidence-dir", help="Copy a passing run and its dimension into a new evidence directory")
    args = vars(parser.parse_args(argv))
    command = args.pop("command")
    try:
        if command == "run":
            from .runner import run_benchmarks
            args["input_pattern"] = args.pop("input")
            return 0 if run_benchmarks(**args)["status"] == "passed" else 1
        from .report import generate_report
        generate_report(args["output_dir"])
        if args["evidence_dir"]:
            from .runner import export_evidence
            export_evidence(args["output_dir"], args["evidence_dir"])
        return 0
    except (Exception, KeyboardInterrupt) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
