"""SCF history of a running or finished calculation (VASP OSZICAR or pw.x output).

Meant for checking a job on the cluster: how many SCF steps each ionic step
needed, how the energy change is falling, and whether a step ran into the
iteration limit.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

_FLOAT = r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[EeDd][-+]?\d+)?"
_OSZ_SCF = re.compile(r"^(DAV|RMM|CG|DIA|SDA)\S*:\s+(\d+)\s+(" + _FLOAT + r")\s+(" + _FLOAT + ")")
_OSZ_ION = re.compile(r"^\s*(\d+)\s+F=\s*(" + _FLOAT + r")\s+E0=\s*(" + _FLOAT + r")(?:.*mag=\s*(" + _FLOAT + "))?")
_NELM = re.compile(r"^\s*NELM\s*=\s*(\d+)", re.IGNORECASE | re.MULTILINE)

_QE_ITER = re.compile(r"iteration #\s*(\d+)")
_QE_ENERGY = re.compile(r"^\s+total energy\s*=\s*(" + _FLOAT + r")\s*Ry")
_QE_ACC = re.compile(r"estimated scf accuracy\s*<\s*(" + _FLOAT + r")\s*Ry")
_QE_FINAL = re.compile(r"^!\s+total energy\s*=\s*(" + _FLOAT + r")\s*Ry")
_QE_MAXSTEP = re.compile(r"electron_maxstep\s*=\s*(\d+)", re.IGNORECASE)


def _f(text: str) -> float:
    return float(text.replace("D", "E").replace("d", "e"))


def vasp_history(directory: "str | Path") -> Dict[str, Any]:
    """Read OSZICAR (and NELM from INCAR if present) in a VASP run directory."""
    directory = Path(directory)
    nelm = 60
    incar = directory / "INCAR"
    if incar.is_file():
        match = _NELM.search(incar.read_text(errors="replace"))
        if match:
            nelm = int(match.group(1))
    steps: List[Dict[str, Any]] = []
    current: List[Dict[str, float]] = []
    with open(directory / "OSZICAR", errors="replace") as handle:
        for line in handle:
            match = _OSZ_SCF.match(line)
            if match:
                current.append({"iter": int(match.group(2)), "energy": _f(match.group(3)), "dE": _f(match.group(4))})
                continue
            match = _OSZ_ION.match(line)
            if match:
                steps.append({
                    "ionic_step": int(match.group(1)),
                    "scf_steps": len(current),
                    "last_dE": current[-1]["dE"] if current else None,
                    "energy": _f(match.group(3)),
                    "magnetization": _f(match.group(4)) if match.group(4) else None,
                    "hit_limit": len(current) >= nelm,
                })
                current = []
    return {"code": "vasp", "limit": nelm, "steps": steps, "running_scf": current}


def qe_history(path: "str | Path") -> Dict[str, Any]:
    """Read the SCF iterations of a pw.x output file."""
    limit = 100  # pw.x default electron_maxstep
    steps: List[Dict[str, Any]] = []
    current: List[Dict[str, Any]] = []
    iteration: Optional[int] = None
    with open(path, errors="replace") as handle:
        for line in handle:
            match = _QE_MAXSTEP.search(line)
            if match:
                limit = int(match.group(1))
            match = _QE_ITER.search(line)
            if match:
                iteration = int(match.group(1))
                continue
            match = _QE_ENERGY.match(line)
            if match and iteration is not None:
                current.append({"iter": iteration, "energy": _f(match.group(1)), "dE": None})
                continue
            match = _QE_ACC.search(line)
            if match and current:
                current[-1]["dE"] = _f(match.group(1))
                continue
            match = _QE_FINAL.match(line)
            if match:
                # the converged iteration is printed with "!" instead of the plain line
                current.append({"iter": iteration or len(current) + 1, "energy": _f(match.group(1)), "dE": None})
                continue
            if "convergence has been achieved" in line:
                steps.append({
                    "ionic_step": len(steps) + 1,
                    "scf_steps": len(current),
                    "last_dE": current[-1]["dE"] if current else None,
                    "energy": current[-1]["energy"] if current else None,
                    "magnetization": None,
                    "hit_limit": False,
                })
                current, iteration = [], None
                continue
            if "convergence NOT achieved" in line:
                steps.append({
                    "ionic_step": len(steps) + 1,
                    "scf_steps": len(current),
                    "last_dE": current[-1]["dE"] if current else None,
                    "energy": current[-1]["energy"] if current else None,
                    "magnetization": None,
                    "hit_limit": True,
                })
                current, iteration = [], None
    return {"code": "qe", "limit": limit, "steps": steps, "running_scf": current}


def history(path: "str | Path") -> Dict[str, Any]:
    path = Path(path)
    if path.is_dir():
        if (path / "OSZICAR").is_file():
            return vasp_history(path)
        for name in ("pw.out", "scf.out", "espresso.out"):
            if (path / name).is_file():
                return qe_history(path / name)
        raise FileNotFoundError("no OSZICAR or pw.x output in %s" % path)
    if path.name == "OSZICAR":
        return vasp_history(path.parent)
    return qe_history(path)


def format_history(hist: Dict[str, Any], last: int = 20) -> str:
    unit = "eV" if hist["code"] == "vasp" else "Ry"
    dlabel = "last dE" if hist["code"] == "vasp" else "scf acc."
    lines = ["%6s %5s %13s %18s %8s" % ("ionic", "scf", dlabel + " [" + unit + "]", "energy [" + unit + "]", "mag")]
    for step in hist["steps"][-last:]:
        lines.append(
            "%6d %5d %13s %18s %8s%s" % (
                step["ionic_step"], step["scf_steps"],
                "%.2e" % step["last_dE"] if step["last_dE"] is not None else "-",
                "%.8f" % step["energy"] if step["energy"] is not None else "-",
                "%.3f" % step["magnetization"] if step["magnetization"] is not None else "-",
                "   <- hit SCF limit (%d)" % hist["limit"] if step["hit_limit"] else "",
            )
        )
    running = hist["running_scf"]
    if running:
        tail = running[-1]
        lines.append(
            "   ... current SCF: %d iterations, last %s = %s"
            % (len(running), dlabel, "%.2e" % tail["dE"] if tail["dE"] is not None else "-")
        )
    hits = sum(1 for s in hist["steps"] if s["hit_limit"])
    if hits:
        lines.append("%d ionic step(s) reached the SCF iteration limit." % hits)
    return "\n".join(lines)
