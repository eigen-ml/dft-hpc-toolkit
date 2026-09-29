"""Read the numbers you usually need from a VASP OUTCAR.

Written against VASP 5.4.1 output. Only plain-text parsing, no dependencies,
so it also runs with the older Python found on cluster login nodes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional

_FLOAT = r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[EeDd][-+]?\d+)?"

_PATTERNS = {
    "vasp_version": re.compile(r"^\s*(vasp\.\S+)"),
    "cores": re.compile(r"running on\s+(\d+)\s+total cores"),
    "nkpts": re.compile(r"NKPTS\s*=\s*(\d+)"),
    "nions": re.compile(r"NIONS\s*=\s*(\d+)"),
    "ispin": re.compile(r"^\s*ISPIN\s*=\s*(\d+)"),
    "encut_ev": re.compile(r"^\s*ENCUT\s*=\s*(" + _FLOAT + r")\s*eV"),
    "nelm": re.compile(r"^\s*NELM\s*=\s*(\d+)"),
    "ediff": re.compile(r"^\s*EDIFF\s*=\s*(" + _FLOAT + ")"),
}
_ITERATION = re.compile(r"Iteration\s+(\d+)\(\s*(\d+)\)")
_TOTEN = re.compile(r"free\s+energy\s+TOTEN\s*=\s*(" + _FLOAT + r")\s*eV")
_SIGMA0 = re.compile(r"energy\(sigma->0\)\s*=\s*(" + _FLOAT + ")")
_EFERMI = re.compile(r"E-fermi\s*:\s*(" + _FLOAT + ")")
_MAGNETIZATION = re.compile(r"number of electron\s+" + _FLOAT + r"\s+magnetization\s+(" + _FLOAT + ")")
_ELAPSED = re.compile(r"Elapsed time \(sec\):\s*(" + _FLOAT + ")")
_MEMORY = re.compile(r"Maximum memory used \(kb\):\s*(" + _FLOAT + ")")


def _num(text: str) -> float:
    return float(text.replace("D", "E").replace("d", "e"))


def parse_outcar(path: "str | Path") -> Dict[str, Any]:
    """Return a flat dict of run settings, final energies and convergence flags.

    Energies are in eV. ``electronic_converged`` refers to the last ionic step
    and is True when VASP stopped the SCF loop before hitting NELM.
    ``ionic_converged`` is only meaningful for relaxations (IBRION >= 0 with NSW > 0);
    it is True when VASP printed "reached required accuracy".
    """
    result: Dict[str, Any] = {key: None for key in _PATTERNS}
    result.update(
        energy_toten=None,
        energy_sigma0=None,
        efermi=None,
        magnetization=None,
        ionic_steps=0,
        electronic_steps_last=0,
        ionic_converged=False,
        electronic_converged=None,
        finished=False,
        elapsed_s=None,
        max_memory_kb=None,
    )
    last_ionic = 0
    ediff_reached_in_last = False
    in_ion_block = False

    with open(path, "r", errors="replace") as handle:
        for line in handle:
            for key, pattern in _PATTERNS.items():
                if result[key] is None:
                    match = pattern.search(line)
                    if match:
                        value = match.group(1)
                        result[key] = value if key == "vasp_version" else (
                            int(value) if value.isdigit() else _num(value)
                        )
            match = _ITERATION.search(line)
            if match:
                ionic, electronic = int(match.group(1)), int(match.group(2))
                if ionic != last_ionic:
                    last_ionic = ionic
                    ediff_reached_in_last = False
                result["electronic_steps_last"] = electronic
                continue
            if "aborting loop because EDIFF is reached" in line:
                ediff_reached_in_last = True
                continue
            # The same energy lines are printed for every SCF iteration; only
            # the block after this header holds the converged ionic-step values.
            if "FREE ENERGIE OF THE ION-ELECTRON SYSTEM" in line:
                in_ion_block = True
                result["ionic_steps"] += 1
                continue
            if in_ion_block:
                match = _TOTEN.search(line)
                if match:
                    result["energy_toten"] = _num(match.group(1))
                    continue
                match = _SIGMA0.search(line)
                if match:
                    result["energy_sigma0"] = _num(match.group(1))
                    in_ion_block = False
                    continue
            match = _EFERMI.search(line)
            if match:
                result["efermi"] = _num(match.group(1))
                continue
            match = _MAGNETIZATION.search(line)
            if match:
                result["magnetization"] = _num(match.group(1))
                continue
            if "reached required accuracy" in line:
                result["ionic_converged"] = True
            elif "General timing and accounting" in line:
                result["finished"] = True
            else:
                match = _ELAPSED.search(line) or _MEMORY.search(line)
                if match:
                    key = "elapsed_s" if "Elapsed" in line else "max_memory_kb"
                    result[key] = _num(match.group(1))

    if last_ionic:
        result["electronic_converged"] = ediff_reached_in_last or (
            result["nelm"] is not None and result["electronic_steps_last"] < result["nelm"]
        )
    if result["energy_sigma0"] is not None and result["nions"]:
        result["energy_per_atom"] = result["energy_sigma0"] / result["nions"]
    else:
        result["energy_per_atom"] = None
    result["code"] = "vasp"
    return result


def final_energy(path: "str | Path") -> Optional[float]:
    """Energy(sigma->0) of the last ionic step in eV, or None if absent."""
    return parse_outcar(path)["energy_sigma0"]
