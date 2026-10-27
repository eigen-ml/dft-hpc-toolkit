"""Command line entry point: ``dfthpc parse | scan | summary | watch | check | status | potcar | vacuum | supercell``."""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .chain import (
    REQUIREMENTS, convergence_problems, format_status, ionic_ok, read_status, scf_ok, status_row, write_merged, write_status,
)
from .poscar import PoscarError, expand_magmom, read_poscar, supercell, vacuum, write_poscar
from .potcar import assemble_potcar
from .scan import ScanError, parse_mesh, qe_scan, vasp_scan
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


def _flag(value) -> str:
    return "n/a" if value is None else ("yes" if value else "no")


def _structure_file(directory: Path) -> Optional[Path]:
    for name in ("CONTCAR", "POSCAR"):
        if (directory / name).is_file() and (directory / name).stat().st_size:
            return directory / name
    return None


def cmd_check(args: argparse.Namespace) -> int:
    path = Path(args.path)
    directory = path if path.is_dir() else path.parent
    result, problems, notes = None, [], []
    try:
        result = parse_any(path)
    except (OSError, ValueError) as exc:
        problems.append("cannot read the output: %s" % exc)
    if result is not None:
        problems += convergence_problems(result, args.require)
        if result.get("nelm_hits") and "scf-all" not in args.require:
            notes.append("%d SCF loop(s) ended without reaching EDIFF" % result["nelm_hits"])
    if args.exit_code:
        problems.append("the program exited with code %d" % args.exit_code)
    if args.min_vacuum is not None:
        structure_file = _structure_file(directory)
        if structure_file is None:
            problems.append("no CONTCAR or POSCAR for the vacuum check")
        else:
            try:
                gap = vacuum(read_poscar(structure_file))["vacuum"]
            except (OSError, ValueError) as exc:
                problems.append("cannot read %s: %s" % (structure_file.name, exc))
            else:
                if gap < args.min_vacuum:
                    problems.append("vacuum in %s is %.2f A, below %g A" % (structure_file.name, gap, args.min_vacuum))
                else:
                    notes.append("vacuum in %s: %.2f A" % (structure_file.name, gap))
    if (directory / "STOPCAR").is_file():
        notes.append("STOPCAR present: the run was told to stop before the time limit")

    summary = ""
    if result is not None:
        energy = result.get("energy_sigma0") if result["code"] == "vasp" else result.get("energy_ev")
        summary = "  (scf %s, ionic %s, E = %s eV, mag = %s)" % (
            _flag(scf_ok(result)), _flag(ionic_ok(result)), _fmt(energy, ".6f"), _fmt(result.get("magnetization"), ".3f"),
        )
    print("%s: %s%s" % (path, "FAILED" if problems else "OK", summary))
    for problem in problems:
        print("  - " + problem)
    for note in notes:
        print("  note: " + note)
    sites = (result or {}).get("magnetization_sites")
    if sites:
        shown = " ".join("%.2f" % m for m in sites[:32])
        print("  site moments: " + shown + (" ... (%d sites)" % len(sites) if len(sites) > 32 else ""))
    if args.record:
        row = status_row(
            result, problems, args.step or directory.resolve().name, directory,
            jobid=args.jobid, exit_code=args.exit_code, elapsed_s=args.elapsed, cores=args.cores,
        )
        write_status(row, args.record)
    if not problems:
        return 0
    return 2 if result is None else 1


def cmd_status(args: argparse.Namespace) -> int:
    rows = read_status(args.root)
    if not rows:
        print("ERROR: no status/*.csv files below %s" % args.root, file=sys.stderr)
        return 1
    print(format_status(rows, args.root))
    if args.csv:
        write_merged(rows, args.csv)
    return 0


def cmd_potcar(args: argparse.Namespace) -> int:
    try:
        structure = read_poscar(args.poscar)
        if not structure["species"]:
            raise PoscarError("%s has no species names on line 6 (VASP 4 format); add them" % args.poscar)
        text, info = assemble_potcar(structure["species"], args.root, dict(args.use))
    except (OSError, ValueError) as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 1
    out = Path(args.output) if args.output else Path(args.poscar).parent / "POTCAR"
    out.write_text(text)
    for item in info:
        print("%-6s %-30s ENMAX = %8.3f eV   %s" % (item["species"], item["titel"], item["enmax"], item["path"]))
    enmax = max(item["enmax"] for item in info)
    print("Wrote %s (%s). Largest ENMAX %.3f eV; 1.3 x ENMAX = %.0f eV, the usual minimum ENCUT for ISIF=3."
          % (out, " ".join(structure["species"]), enmax, 1.3 * enmax))
    return 0


def cmd_vacuum(args: argparse.Namespace) -> int:
    try:
        report = vacuum(read_poscar(args.poscar))
    except (OSError, ValueError) as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2
    print("%s: cell height %.2f A, layer thickness %.2f A, vacuum %.2f A"
          % (args.poscar, report["height"], report["thickness"], report["vacuum"]))
    if report["vacuum"] < args.min:
        print("FAILED: vacuum is below %g A" % args.min)
        return 1
    return 0


def cmd_supercell(args: argparse.Namespace) -> int:
    try:
        dim = parse_mesh(args.dim)
        unit = read_poscar(args.poscar)
        cell = supercell(unit, dim)
        if args.incar:
            incar = Path(args.incar).read_text()
            new_incar, message = expand_magmom(incar, sum(unit["counts"]), dim[0] * dim[1] * dim[2])
    except (OSError, ValueError) as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 1
    write_poscar(cell, args.output)
    print("Wrote %s: %s supercell of %s, %d atoms (phonopy SPOSCAR order)"
          % (args.output, "x".join(str(n) for n in dim), args.poscar, sum(cell["counts"])))
    if args.incar:
        if new_incar != incar:
            Path(args.incar).write_text(new_incar)
        print("%s: %s" % (args.incar, message))
    return 0


def _requirements(text: str) -> List[str]:
    items = [item.strip().lower() for item in text.split(",") if item.strip()]
    unknown = [item for item in items if item not in REQUIREMENTS]
    if unknown:
        raise argparse.ArgumentTypeError(
            "unknown requirement %s (choose from %s)" % (", ".join(unknown), ", ".join(REQUIREMENTS))
        )
    return items


def _species_entry(text: str):
    if text.count("=") != 1 or not all(text.split("=")):
        raise argparse.ArgumentTypeError("expected SPECIES=ENTRY such as Cr=Cr_pv, got %r" % text)
    return tuple(text.split("="))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dfthpc", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")
    sub.required = True  # not a keyword argument before Python 3.7

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

    p = sub.add_parser("check", help="exit with a non-zero code unless a run converged (end of a chained job)")
    p.add_argument("path", help="OUTCAR, pw.x output, or a run directory")
    p.add_argument("--require", type=_requirements, default=["scf", "ionic"],
                   help="comma-separated, from scf, ionic, scf-all (default scf,ionic). "
                        "ionic passes for runs without a relaxation (NSW=0, IBRION=7/8)")
    p.add_argument("--min-vacuum", type=float, metavar="A",
                   help="also fail if the vacuum of CONTCAR (or POSCAR) in the directory is below A angstrom")
    p.add_argument("--exit-code", type=int, help="exit code of the DFT program; non-zero fails the check")
    p.add_argument("--record", metavar="CSV", help="write the result as one row to this CSV (one file per job)")
    p.add_argument("--step", help="step name for --record (default: the directory name)")
    p.add_argument("--jobid", default=os.environ.get("SLURM_JOB_ID", ""), help="job ID for --record (default $SLURM_JOB_ID)")
    p.add_argument("--elapsed", type=float, help="wall time in s for --record (default: from the output)")
    p.add_argument("--cores", type=int, help="cores for --record (default: from the output)")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("status", help="table of the status/*.csv rows written by chained jobs")
    p.add_argument("root", help="directory searched for status/ folders")
    p.add_argument("--csv", help="also write all rows to this CSV file")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("potcar", help="join POTCARs in the species order of a POSCAR")
    p.add_argument("poscar")
    p.add_argument("--root", required=True, help="library with one <species>/POTCAR per entry, e.g. pseudoPOT/PP_GGA")
    p.add_argument("--use", type=_species_entry, action="append", default=[], metavar="SPECIES=ENTRY",
                   help="take another library entry for a species, e.g. --use Cr=Cr_pv (repeatable)")
    p.add_argument("-o", "--output", help="output file (default: POTCAR next to the POSCAR)")
    p.set_defaults(func=cmd_potcar)

    p = sub.add_parser("vacuum", help="layer thickness and vacuum of a 2D cell; fails below --min")
    p.add_argument("poscar", help="POSCAR or CONTCAR")
    p.add_argument("--min", type=float, default=20.0, help="minimum vacuum in angstrom (default 20)")
    p.set_defaults(func=cmd_vacuum)

    p = sub.add_parser("supercell", help="supercell in phonopy order (for DFPT phonons), optionally expanding MAGMOM")
    p.add_argument("poscar", help="unit cell, e.g. the CONTCAR of the last relaxation")
    p.add_argument("dim", help="supercell size, e.g. 4x4x1")
    p.add_argument("-o", "--output", default="SPOSCAR", help="output file (default SPOSCAR)")
    p.add_argument("--incar", help="INCAR whose MAGMOM (one value per unit-cell atom) is expanded in place")
    p.set_defaults(func=cmd_supercell)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
