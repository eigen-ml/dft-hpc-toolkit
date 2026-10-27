"""Pass/fail checks and status files for jobs that start each other (``dfthpc check`` / ``status``).

A job of a chain ends with ``dfthpc check``; a non-zero exit fails the job, so
the next job (submitted with ``--dependency=afterok``) never starts. Each job
writes its own one-row CSV, ``status/<jobid>.csv``, instead of appending to a
shared file: file locks are not reliable on the parallel file system of the
cluster (Weka on TRUBA). ``dfthpc status`` joins them.
"""

import csv
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

REQUIREMENTS = ("scf", "ionic", "scf-all")
STATUS_COLUMNS = [
    "time", "jobid", "step", "dir", "exit_code", "scf", "ionic", "energy_ev",
    "magnetization", "elapsed_s", "cores", "core_hours", "site_moments", "problems",
]


def _energy(result: Dict[str, Any]) -> Optional[float]:
    return result.get("energy_sigma0") if result["code"] == "vasp" else result.get("energy_ev")


def scf_ok(result: Dict[str, Any]) -> Optional[bool]:
    if result["code"] == "vasp":
        return result.get("electronic_converged")
    return bool(result.get("scf_converged")) and bool(result.get("finished"))


def ionic_ok(result: Dict[str, Any]) -> Optional[bool]:
    """True / False for relaxations, None when the run has no relaxation target."""
    return result.get("ionic_converged") if result["code"] == "vasp" else result.get("relax_converged")


def convergence_problems(result: Dict[str, Any], require: Sequence[str] = ("scf", "ionic")) -> List[str]:
    """Reasons why a parsed run does not meet ``require`` (empty list: it does)."""
    unknown = sorted(set(require) - set(REQUIREMENTS))
    if unknown:
        raise ValueError("unknown requirement %s (use %s)" % (", ".join(unknown), ", ".join(REQUIREMENTS)))
    problems = []
    vasp = result["code"] == "vasp"
    if "scf" in require and not scf_ok(result):
        if not result.get("finished"):
            problems.append(
                "output has no %s: the run did not finish (killed, out of time or crashed)"
                % ("timing block" if vasp else "JOB DONE")
            )
        elif vasp and result.get("electronic_converged") is None:
            problems.append("no SCF iterations in OUTCAR")
        elif vasp:
            problems.append("last SCF loop ended without reaching EDIFF (NELM = %s)" % result.get("nelm"))
        else:
            problems.append("SCF did not converge")
    if "ionic" in require and ionic_ok(result) is False:
        if vasp:
            problems.append(
                "relaxation did not reach EDIFFG after %d ionic step(s)%s"
                % (result.get("ionic_steps") or 0, "" if result.get("nsw") is None else " (NSW = %d)" % result["nsw"])
            )
        else:
            problems.append("relaxation (BFGS) did not converge")
    if "scf-all" in require and vasp and result.get("nelm_hits"):
        problems.append("%d SCF loop(s) ended without reaching EDIFF" % result["nelm_hits"])
    return problems


def status_row(
    result: Optional[Dict[str, Any]],
    problems: Sequence[str],
    step: str,
    directory: "str | Path",
    jobid: str = "",
    exit_code: Optional[int] = None,
    elapsed_s: Optional[float] = None,
    cores: Optional[int] = None,
) -> Dict[str, Any]:
    """One row of ``status/<jobid>.csv``; ``result`` is None when there was no output to parse."""
    result = result or {"code": "none"}
    if elapsed_s is None:
        elapsed_s = result.get("elapsed_s")
    if cores is None:
        cores = result.get("cores")
    sites = result.get("magnetization_sites")

    def flag(value):
        return "" if value is None else ("yes" if value else "no")

    return {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "jobid": jobid,
        "step": step,
        "dir": str(Path(directory).resolve()),
        "exit_code": "" if exit_code is None else exit_code,
        "scf": flag(scf_ok(result)) if result["code"] != "none" else "",
        "ionic": flag(ionic_ok(result)) if result["code"] != "none" else "",
        "energy_ev": _energy(result) if result["code"] != "none" else None,
        "magnetization": result.get("magnetization"),
        "elapsed_s": None if elapsed_s is None else round(elapsed_s),
        "cores": cores,
        "core_hours": None if elapsed_s is None or not cores else round(elapsed_s * cores / 3600.0, 2),
        "site_moments": " ".join("%.3f" % m for m in sites) if sites else "",
        "problems": "; ".join(problems),
    }


def write_status(row: Dict[str, Any], path: "str | Path") -> None:
    """Write one row (with header) to its own CSV; the rename makes it appear complete or not at all."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".%s.%d.tmp" % (path.name, os.getpid()))
    with open(str(tmp), "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=STATUS_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerow(row)
    os.replace(str(tmp), str(path))


def read_status(root: "str | Path") -> List[Dict[str, str]]:
    """All rows of the ``status/*.csv`` files below ``root``, oldest first."""
    rows = []
    for path in sorted(Path(root).rglob("*.csv")):
        if path.parent.name != "status":
            continue
        with open(str(path), newline="") as handle:
            rows.extend(csv.DictReader(handle))
    rows.sort(key=lambda r: (r.get("time", ""), r.get("jobid", "")))
    return rows


def format_status(rows: Sequence[Dict[str, str]], root: "str | Path") -> str:
    root = Path(root).resolve()
    lines = ["%-32s %-10s %4s %4s %5s %16s %8s %8s %8s" % (
        "run", "jobid", "exit", "scf", "ionic", "E [eV]", "mag", "time [h]", "core-h")]
    total = 0.0
    failed = 0
    for r in rows:
        try:
            name = str(Path(r["dir"]).relative_to(root))
        except ValueError:
            name = r["dir"]
        core_hours = float(r["core_hours"]) if r.get("core_hours") else None
        total += core_hours or 0.0
        failed += bool(r.get("problems"))
        lines.append("%-32s %-10s %4s %4s %5s %16s %8s %8s %8s%s" % (
            name, r.get("jobid", ""), r.get("exit_code", ""), r.get("scf") or "-", r.get("ionic") or "-",
            "%.6f" % float(r["energy_ev"]) if r.get("energy_ev") else "-",
            "%.3f" % float(r["magnetization"]) if r.get("magnetization") else "-",
            "%.2f" % (float(r["elapsed_s"]) / 3600.0) if r.get("elapsed_s") else "-",
            "%.1f" % core_hours if core_hours is not None else "-",
            "   <- " + r["problems"] if r.get("problems") else "",
        ))
    lines.append("%d job(s), %d with problems, %.1f core-hours in total." % (len(rows), failed, total))
    return "\n".join(lines)


def write_merged(rows: Sequence[Dict[str, str]], path: "str | Path") -> None:
    with open(str(path), "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=STATUS_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
