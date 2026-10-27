"""Read the numbers you usually need from a VASP OUTCAR.

Written against VASP 5.4.1 output and the VASP 6 line formats. Only plain-text
parsing, no dependencies and no syntax newer than Python 3.6, so it also runs
with the older Python found on cluster login and compute nodes.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

_FLOAT = r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[EeDd][-+]?\d+)?"

_PATTERNS = {
    "vasp_version": re.compile(r"^\s*(vasp\.\S+)"),
    "nkpts": re.compile(r"NKPTS\s*=\s*(\d+)"),
    "nions": re.compile(r"NIONS\s*=\s*(\d+)"),
    "ispin": re.compile(r"^\s*ISPIN\s*=\s*(\d+)"),
    "encut_ev": re.compile(r"^\s*ENCUT\s*=\s*(" + _FLOAT + r")\s*eV"),
    "nelm": re.compile(r"^\s*NELM\s*=\s*(\d+)"),
    "ediff": re.compile(r"^\s*EDIFF\s*=\s*(" + _FLOAT + ")"),
    "nsw": re.compile(r"^\s*NSW\s*=\s*(\d+)"),
    "ibrion": re.compile(r"^\s*IBRION\s*=\s*(-?\d+)"),
    "isif": re.compile(r"^\s*ISIF\s*=\s*(\d+)"),
}
# VASP 5: "running on   16 total cores"; VASP 6: "running  112 mpi-ranks, with    1 threads/rank, on    1 nodes"
_CORES = re.compile(r"running on\s+(\d+)\s+total cores")
_RANKS = re.compile(r"running\s+(\d+)\s+mpi-ranks(?:,\s*with\s+(\d+)\s+threads/rank)?")
_ITERATION = re.compile(r"Iteration\s+(\d+)\(\s*(\d+)\)")
_TOTEN = re.compile(r"free\s+energy\s+TOTEN\s*=\s*(" + _FLOAT + r")\s*eV")
_SIGMA0 = re.compile(r"energy\(sigma->0\)\s*=\s*(" + _FLOAT + ")")
_EFERMI = re.compile(r"E-fermi\s*:\s*(" + _FLOAT + ")")
_MAGNETIZATION = re.compile(r"number of electron\s+" + _FLOAT + r"\s+magnetization\s+(" + _FLOAT + ")")
_SITE_ROW = re.compile(r"^\s*\d+\s+(?:" + _FLOAT + r"\s+)*(" + _FLOAT + r")\s*$")
_ELAPSED = re.compile(r"Elapsed time \(sec\):\s*(" + _FLOAT + ")")
_MEMORY = re.compile(r"Maximum memory used \(kb\):\s*(" + _FLOAT + ")")

# IBRION values without a relaxation target: no ionic update, MD, finite differences, DFPT
_NOT_RELAXATION = (-1, 0, 5, 6, 7, 8)


def _num(text: str) -> float:
    return float(text.replace("D", "E").replace("d", "e"))


def _value(text: str):
    try:
        return int(text)
    except ValueError:
        return _num(text)


def parse_outcar(path: "str | Path") -> Dict[str, Any]:
    """Return a flat dict of run settings, final energies and convergence flags.

    Energies are in eV. ``electronic_converged`` is True only when the last SCF
    loop printed "EDIFF is reached" and the OUTCAR ends with the timing block,
    so a job killed in the middle of an SCF loop is not counted as converged.
    For DFPT runs (IBRION=7/8) the linear-response loops count as SCF loops too.
    ``nelm_hits`` counts the SCF loops that ended without reaching EDIFF.

    ``ionic_converged`` is True when VASP printed "reached required accuracy",
    False for a relaxation that did not, and None when the run has no
    relaxation target (NSW=0, IBRION=-1/0/5/6/7/8).

    ``magnetization_sites`` is the "tot" column of the last "magnetization (x)"
    block (one moment per ion, printed with LORBIT), None if there is none.
    """
    result: Dict[str, Any] = {key: None for key in _PATTERNS}
    result.update(
        cores=None,
        energy_toten=None,
        energy_sigma0=None,
        efermi=None,
        magnetization=None,
        magnetization_sites=None,
        ionic_steps=0,
        electronic_steps_last=0,
        nelm_hits=0,
        ionic_converged=False,
        electronic_converged=None,
        finished=False,
        elapsed_s=None,
        max_memory_kb=None,
    )
    # "open": inside an SCF loop that has not reached EDIFF yet; "done" / "failed": the loop ended
    loop_state = None
    loop_ionic = None
    in_ion_block = False
    sites: Optional[List[float]] = None

    with open(path, "r", errors="replace") as handle:
        for line in handle:
            for key, pattern in _PATTERNS.items():
                if result[key] is None:
                    match = pattern.search(line)
                    if match:
                        value = match.group(1)
                        result[key] = value if key == "vasp_version" else _value(value)
            if result["cores"] is None:
                match = _CORES.search(line)
                if match:
                    result["cores"] = int(match.group(1))
                    continue
                match = _RANKS.search(line)
                if match:
                    result["cores"] = int(match.group(1)) * int(match.group(2) or 1)
                    continue
            if sites is not None:
                stripped = line.strip()
                if not stripped or stripped[0] in "#-":
                    continue
                match = _SITE_ROW.match(line)
                if match:
                    sites.append(_num(match.group(1)))
                    continue
                if stripped.startswith("tot"):
                    result["magnetization_sites"] = sites
                sites = None
            match = _ITERATION.search(line)
            if match:
                ionic, electronic = int(match.group(1)), int(match.group(2))
                if loop_state != "open" or electronic == 1 or ionic != loop_ionic:
                    if loop_state == "open":
                        result["nelm_hits"] += 1
                    loop_state, loop_ionic = "open", ionic
                result["electronic_steps_last"] = electronic
                continue
            if "aborting loop because EDIFF is reached" in line:
                if loop_state == "open":
                    loop_state = "done"
                continue
            # The same energy lines are printed for every SCF iteration; only
            # the block after this header holds the converged ionic-step values.
            if "FREE ENERGIE OF THE ION-ELECTRON SYSTEM" in line:
                if loop_state == "open":
                    result["nelm_hits"] += 1
                    loop_state = "failed"
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
            if line.startswith(" magnetization (x)"):
                sites = []
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

    if loop_state == "open" and result["finished"]:
        result["nelm_hits"] += 1  # the last loop ran out of iterations
    if loop_state is not None:
        result["electronic_converged"] = loop_state == "done" and result["finished"]
    if result["nsw"] == 0 or result["ibrion"] in _NOT_RELAXATION:
        result["ionic_converged"] = None
    if result["energy_sigma0"] is not None and result["nions"]:
        result["energy_per_atom"] = result["energy_sigma0"] / result["nions"]
    else:
        result["energy_per_atom"] = None
    result["code"] = "vasp"
    return result


def final_energy(path: "str | Path") -> Optional[float]:
    """Energy(sigma->0) of the last ionic step in eV, or None if absent."""
    return parse_outcar(path)["energy_sigma0"]
