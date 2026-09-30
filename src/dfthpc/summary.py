"""Collect results of a convergence scan into one table."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .qe import parse_pw_output
from .vasp import parse_outcar

QE_OUTPUT_NAMES = ("pw.out", "scf.out", "espresso.out")


def parse_any(path: "str | Path") -> Dict[str, Any]:
    """Parse a VASP OUTCAR or a pw.x output, or a directory containing one."""
    path = Path(path)
    if path.is_dir():
        if (path / "OUTCAR").is_file():
            return parse_outcar(path / "OUTCAR")
        for name in QE_OUTPUT_NAMES:
            if (path / name).is_file():
                return parse_pw_output(path / name)
        raise FileNotFoundError("no OUTCAR or pw.x output (%s) in %s" % (", ".join(QE_OUTPUT_NAMES), path))
    if path.name.startswith("OUTCAR"):
        return parse_outcar(path)
    return parse_pw_output(path)


def _energy_ev(result: Dict[str, Any]) -> Optional[float]:
    return result.get("energy_sigma0") if result["code"] == "vasp" else result.get("energy_ev")


def _natoms(result: Dict[str, Any]) -> Optional[int]:
    return result.get("nions") if result["code"] == "vasp" else result.get("natoms")


def _converged(result: Dict[str, Any]) -> Optional[bool]:
    return result.get("electronic_converged") if result["code"] == "vasp" else result.get("scf_converged")


def _sort_key(value: str):
    """Order by k-mesh size ('12x12x1') or by the number in the name ('ENCUT500')."""
    mesh = re.search(r"(\d+)x(\d+)x(\d+)", value)
    if mesh:
        a, b, c = (int(x) for x in mesh.groups())
        return (0, float(a * b * c), value)
    number = re.search(r"\d+(?:\.\d+)?", value)
    if number:
        return (0, float(number.group()), value)
    return (1, 0.0, value)


def summarize_scan(scan_dir: "str | Path", tolerance_mev: float = 1.0) -> Dict[str, Any]:
    """Energies per atom relative to the most expensive setting of the scan.

    The reference is the last row after sorting by value (highest cutoff or
    densest mesh). ``converged_at`` is the first value from which every
    following row stays within ``tolerance_mev`` meV/atom of the reference.
    """
    scan_dir = Path(scan_dir)
    manifest_path = scan_dir / "scan.json"
    if manifest_path.is_file():
        entries = json.loads(manifest_path.read_text())
    else:
        entries = [{"dir": d.name, "parameter": "", "value": d.name} for d in sorted(scan_dir.iterdir()) if d.is_dir()]

    rows: List[Dict[str, Any]] = []
    for entry in entries:
        row: Dict[str, Any] = {"dir": entry["dir"], "parameter": entry["parameter"], "value": entry["value"]}
        try:
            result = parse_any(scan_dir / entry["dir"])
        except FileNotFoundError:
            row.update(status="missing output")
            rows.append(row)
            continue
        energy, natoms = _energy_ev(result), _natoms(result)
        row.update(
            energy_ev=energy,
            natoms=natoms,
            energy_per_atom_ev=energy / natoms if energy is not None and natoms else None,
            scf_converged=_converged(result),
            finished=result.get("finished"),
            elapsed_s=result.get("elapsed_s"),
            status="ok" if energy is not None else "no energy",
        )
        rows.append(row)

    rows.sort(key=lambda r: _sort_key(str(r["value"])))
    done = [r for r in rows if r.get("energy_per_atom_ev") is not None]
    converged_at = None
    if done:
        reference = done[-1]["energy_per_atom_ev"]
        for r in done:
            r["delta_mev_per_atom"] = (r["energy_per_atom_ev"] - reference) * 1000.0
        for i, r in enumerate(done):
            if all(abs(x["delta_mev_per_atom"]) <= tolerance_mev for x in done[i:]):
                converged_at = r["value"]
                break
    return {"rows": rows, "tolerance_mev": tolerance_mev, "converged_at": converged_at}


def write_csv(rows: List[Dict[str, Any]], path: "str | Path") -> None:
    columns = [
        "dir", "parameter", "value", "status", "energy_ev", "natoms",
        "energy_per_atom_ev", "delta_mev_per_atom", "scf_converged", "finished", "elapsed_s",
    ]
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def plot(summary: Dict[str, Any], path: "str | Path") -> None:
    """Save ΔE/atom vs value. Needs matplotlib (pip install .[plot])."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    done = [r for r in summary["rows"] if r.get("delta_mev_per_atom") is not None]
    if not done:
        raise ValueError("nothing to plot: no finished calculations with an energy")
    labels = [str(r["value"]) for r in done]
    xlabel = done[0]["parameter"]
    if not xlabel:
        # directory names like ENCUT500 / ENCUT600: move the shared prefix to the axis label
        prefix = re.match(r"[A-Za-z_]*", labels[0]).group()
        if prefix and all(label.startswith(prefix) for label in labels):
            labels = [label[len(prefix):].lstrip("_") for label in labels]
            xlabel = prefix.rstrip("_")
    deltas = [r["delta_mev_per_atom"] for r in done]
    fig, ax = plt.subplots(figsize=(5, 3.5))
    ax.plot(range(len(done)), deltas, "o-")
    tol = summary["tolerance_mev"]
    ax.axhspan(-tol, tol, color="0.9", zorder=0, label="±%g meV/atom" % tol)
    ax.set_xticks(range(len(done)))
    rotate = len(labels) > 4 or max(len(label) for label in labels) > 6
    ax.set_xticklabels(labels, rotation=45 if rotate else 0, ha="right" if rotate else "center")
    ax.set_xlabel(xlabel or "setting")
    ax.set_ylabel("E - E(last) [meV/atom]")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
