"""Command line entry point: ``dfthpc parse | scan | summary | watch``."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from . import __version__
from .scan import ScanError, qe_scan, vasp_scan
from .summary import parse_any, plot, summarize_scan, write_csv
from .watch import format_history, history


def _fmt(value, spec: str) -> str:
    return format(value, spec) if isinstance(value, (int, float)) and not isinstance(value, bool) else str(value if value is not None else "-")


def cmd_parse(args: argparse.Namespace) -> int:
    results = []
    for path in args.paths:
        try:
            result = parse_any(path)
        except (OSError, ValueError) as exc:
            print("ERROR %s: %s" % (path, exc), file=sys.stderr)
            return 1
        result["path"] = str(path)
        results.append(result)
    print(json.dumps(results if len(results) > 1 else results[0], indent=2, default=list))
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    try:
        if args.code == "vasp":
            entries = vasp_scan(args.template, args.out, args.parameter, args.values)
        else:
            entries = qe_scan(args.template, args.out, args.parameter, args.values, keep_dual=not args.no_keep_dual)
    except (OSError, ScanError) as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 1
    print("Created %d directories in %s" % (len(entries), args.out))
    print("Submit with: sbatch --array=0-%d slurm/scan_array.sbatch %s" % (len(entries) - 1, args.out))
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    summary = summarize_scan(args.scan_dir, tolerance_mev=args.tol)
    rows = summary["rows"]
    print("%-18s %-10s %16s %14s %6s %9s" % ("dir", "value", "E/atom [eV]", "dE [meV/at]", "scf", "time [s]"))
    for r in rows:
        print(
            "%-18s %-10s %16s %14s %6s %9s"
            % (
                r["dir"], r["value"],
                _fmt(r.get("energy_per_atom_ev"), ".6f"),
                _fmt(r.get("delta_mev_per_atom"), ".3f"),
                _fmt(r.get("scf_converged"), ""),
                _fmt(r.get("elapsed_s"), ".0f"),
            )
            + ("" if r.get("status") == "ok" else "   (%s)" % r.get("status"))
        )
    if summary["converged_at"] is not None:
        print("Converged within %g meV/atom from %s on (relative to the last row)." % (args.tol, summary["converged_at"]))
    else:
        print("No setting stays within %g meV/atom of the last row." % args.tol)
    if args.csv:
        write_csv(rows, args.csv)
    if args.plot:
        try:
            plot(summary, args.plot)
        except ImportError:
            print("ERROR: --plot needs matplotlib (pip install .[plot])", file=sys.stderr)
            return 1
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    import time

    while True:
        try:
            hist = history(args.path)
        except (OSError, ValueError) as exc:
            print("ERROR: %s" % exc, file=sys.stderr)
            return 1
        print(format_history(hist, last=args.last))
        if not args.follow:
            return 0
        print("-- %s, refreshing every %ds (Ctrl+C to stop)" % (time.strftime("%H:%M:%S"), args.interval))
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dfthpc", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("parse", help="print key results of OUTCAR / pw.x output files as JSON")
    p.add_argument("paths", nargs="+", help="OUTCAR, pw.x output, or a directory with one")
    p.set_defaults(func=cmd_parse)

    p = sub.add_parser("scan", help="create a cutoff or k-point convergence scan")
    p.add_argument("code", choices=["vasp", "qe"])
    p.add_argument("template", help="VASP: directory with INCAR/POSCAR/KPOINTS[/POTCAR]; QE: pw.x input file")
    p.add_argument("out", help="new directory for the scan")
    p.add_argument("parameter", help="VASP: ENCUT or KPOINTS; QE: ecutwfc or kpoints")
    p.add_argument("values", nargs="+", help="e.g. 400 450 500, or 6x6x1 9x9x1 12x12x1")
    p.add_argument("--no-keep-dual", action="store_true", help="QE: do not scale ecutrho with ecutwfc")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("summary", help="tabulate a finished scan")
    p.add_argument("scan_dir")
    p.add_argument("--tol", type=float, default=1.0, help="tolerance in meV/atom (default 1)")
    p.add_argument("--csv", help="also write the table to this CSV file")
    p.add_argument("--plot", help="also save a PNG plot (needs matplotlib)")
    p.set_defaults(func=cmd_summary)
    p = sub.add_parser("watch", help="show the SCF history of a VASP or pw.x run")
    p.add_argument("path", help="VASP run directory (OSZICAR), pw.x output, or a directory with one")
    p.add_argument("--last", type=int, default=20, help="show the last N ionic steps (default 20)")
    p.add_argument("--follow", "-f", action="store_true", help="refresh until interrupted")
    p.add_argument("--interval", type=int, default=30, help="seconds between refreshes with --follow")
    p.set_defaults(func=cmd_watch)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
