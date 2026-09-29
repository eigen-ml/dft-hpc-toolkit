"""Read the numbers you usually need from a Quantum ESPRESSO pw.x output."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional

RY_TO_EV = 13.605693122994  # CODATA 2018

_FLOAT = r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[EeDd][-+]?\d+)?"

_VERSION = re.compile(r"Program PWSCF\s+(v\.\S+)")
_NATOMS = re.compile(r"number of atoms/cell\s*=\s*(\d+)")
_ECUT = re.compile(r"kinetic-energy cutoff\s*=\s*(" + _FLOAT + r")\s*Ry")
_NKPTS = re.compile(r"number of k points\s*=\s*(\d+)")
_ENERGY = re.compile(r"^!\s+total energy\s*=\s*(" + _FLOAT + r")\s*Ry")
_SCF_DONE = re.compile(r"convergence has been achieved in\s+(\d+)\s+iterations")
_FERMI = re.compile(r"the Fermi energy is\s+(" + _FLOAT + r")\s*ev")
_HOMO = re.compile(r"highest occupied(?:, lowest unoccupied)? level \(ev\):\s+(" + _FLOAT + ")")
_FERMI_UPDW = re.compile(
    r"spin up/dw Fermi energies are\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s*ev"
)
_MAG = re.compile(r"total magnetization\s*=\s*(" + _FLOAT + ")")
_WALL = re.compile(r"PWSCF\s*:.*CPU\s+(.+?)\s+WALL")
_TIME_PART = re.compile(r"(" + _FLOAT + r")\s*([hms])")


def _wall_seconds(text: str) -> Optional[float]:
    """Convert QE time strings such as '2.99s', '1m23.45s' or '1h 2m' to seconds."""
    parts = _TIME_PART.findall(text)
    if not parts:
        return None
    scale = {"h": 3600.0, "m": 60.0, "s": 1.0}
    return sum(float(value) * scale[unit] for value, unit in parts)


def parse_pw_output(path: "str | Path") -> Dict[str, Any]:
    """Return a flat dict with the final energy, SCF/relax status and timing.

    ``energy_ry``/``energy_ev`` are from the last line starting with "!".
    ``relax_converged`` is None for single-point runs.
    """
    result: Dict[str, Any] = {
        "code": "qe",
        "calculation": "scf",
        "qe_version": None,
        "natoms": None,
        "ecutwfc_ry": None,
        "nkpts": None,
        "energy_ry": None,
        "scf_cycles": 0,
        "scf_iterations_last": None,
        "scf_converged": None,
        "efermi": None,
        "efermi_up_down": None,
        "magnetization": None,
        "relax_converged": None,
        "finished": False,
        "elapsed_s": None,
    }
    with open(path, "r", errors="replace") as handle:
        for line in handle:
            for key, pattern in (
                ("qe_version", _VERSION),
                ("natoms", _NATOMS),
                ("ecutwfc_ry", _ECUT),
                ("nkpts", _NKPTS),
            ):
                if result[key] is None:
                    match = pattern.search(line)
                    if match:
                        value = match.group(1)
                        result[key] = value if key == "qe_version" else (
                            int(value) if value.isdigit() else float(value)
                        )
            if "Self-consistent Calculation" in line:
                result["scf_converged"] = False
                continue
            match = _ENERGY.search(line)
            if match:
                result["energy_ry"] = float(match.group(1))
                result["scf_cycles"] += 1
                continue
            match = _SCF_DONE.search(line)
            if match:
                result["scf_iterations_last"] = int(match.group(1))
                result["scf_converged"] = True
                continue
            if "convergence NOT achieved" in line:
                result["scf_converged"] = False
                continue
            if "Band Structure Calculation" in line:
                result["calculation"] = "nscf/bands"
                continue
            match = _FERMI_UPDW.search(line)
            if match:
                result["efermi_up_down"] = (float(match.group(1)), float(match.group(2)))
                continue
            match = _FERMI.search(line) or _HOMO.search(line)
            if match:
                result["efermi"] = float(match.group(1))
                continue
            match = _MAG.search(line)
            if match:
                result["magnetization"] = float(match.group(1))
                continue
            if "BFGS Geometry Optimization" in line:
                result["calculation"] = "relax"
            if "BFGS Geometry Optimization" in line or "bfgs converged" in line:
                if "End of BFGS" in line or "bfgs converged" in line:
                    result["relax_converged"] = True
                elif result["relax_converged"] is None:
                    result["relax_converged"] = False
                continue
            if "The maximum number of steps has been reached" in line:
                result["relax_converged"] = False
                continue
            match = _WALL.search(line)
            if match:
                result["elapsed_s"] = _wall_seconds(match.group(1))
                continue
            if "JOB DONE" in line:
                result["finished"] = True

    energy = result["energy_ry"]
    result["energy_ev"] = energy * RY_TO_EV if energy is not None else None
    result["energy_per_atom"] = (
        result["energy_ev"] / result["natoms"]
        if result["energy_ev"] is not None and result["natoms"]
        else None
    )
    return result
