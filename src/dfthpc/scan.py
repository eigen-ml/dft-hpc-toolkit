"""Create one directory per value for cutoff and k-point convergence tests.

Each scan writes ``dirs.txt`` (one directory per line, used by the Slurm array
script) and ``scan.json`` (parameter and value for each directory).
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Dict, List, Sequence

VASP_INPUTS = ("INCAR", "POSCAR", "KPOINTS", "POTCAR")


class ScanError(ValueError):
    pass


def parse_mesh(text: str) -> List[int]:
    """'8x8x1' or '8,8,1' -> [8, 8, 1]."""
    parts = re.split(r"[x,\s]+", text.strip().lower())
    try:
        mesh = [int(p) for p in parts if p]
    except ValueError as exc:
        raise ScanError("k-point mesh must look like 8x8x1, got %r" % text) from exc
    if len(mesh) != 3 or min(mesh) < 1:
        raise ScanError("k-point mesh must have three positive integers, got %r" % text)
    return mesh


def set_incar_tag(incar: str, tag: str, value: str) -> str:
    """Replace ``TAG = old`` (keeping any comment) or append the tag."""
    pattern = re.compile(r"^(\s*%s\s*=\s*)([^#!\n]*)" % re.escape(tag), re.IGNORECASE | re.MULTILINE)
    if pattern.search(incar):
        return pattern.sub(lambda m: m.group(1) + value + " ", incar, count=1).replace(" \n", "\n")
    if not incar.endswith("\n"):
        incar += "\n"
    return incar + "%s = %s\n" % (tag, value)


def set_kpoints_mesh(kpoints: str, mesh: Sequence[int]) -> str:
    """Change the mesh of an automatic (Gamma / Monkhorst-Pack) KPOINTS file."""
    lines = kpoints.splitlines()
    if len(lines) < 4 or lines[1].strip() != "0" or lines[2].strip()[:1].lower() not in ("g", "m"):
        raise ScanError("KPOINTS scans need an automatic Gamma or Monkhorst-Pack KPOINTS file")
    lines[3] = " ".join(str(k) for k in mesh)
    return "\n".join(lines) + "\n"


def set_qe_namelist_value(text: str, key: str, value: str) -> str:
    pattern = re.compile(r"^(\s*%s\s*=\s*)([^,\n]*)" % re.escape(key), re.IGNORECASE | re.MULTILINE)
    if not pattern.search(text):
        raise ScanError("%s not found in the pw.x input" % key)
    return pattern.sub(lambda m: m.group(1) + value, text, count=1)


def get_qe_namelist_value(text: str, key: str):
    match = re.search(r"^\s*%s\s*=\s*([^,\n]*)" % re.escape(key), text, re.IGNORECASE | re.MULTILINE)
    return float(match.group(1).replace("d", "e").replace("D", "E")) if match else None


def set_qe_kpoints(text: str, mesh: Sequence[int]) -> str:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().upper().startswith("K_POINTS"):
            if "automatic" not in line.lower():
                raise ScanError("k-point scans need 'K_POINTS automatic' in the pw.x input")
            shifts = lines[i + 1].split()[3:6] or ["0", "0", "0"]
            lines[i + 1] = " ".join([str(k) for k in mesh] + shifts)
            return "\n".join(lines) + "\n"
    raise ScanError("K_POINTS card not found in the pw.x input")


def _write_manifest(out_dir: Path, entries: List[Dict[str, str]]) -> None:
    (out_dir / "dirs.txt").write_text("".join(e["dir"] + "\n" for e in entries))
    (out_dir / "scan.json").write_text(json.dumps(entries, indent=2) + "\n")


def _prepare_out(out_dir: Path) -> None:
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ScanError("%s is not empty; choose a new directory" % out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)


def vasp_scan(template: "str | Path", out_dir: "str | Path", parameter: str, values: Sequence[str]) -> List[Dict[str, str]]:
    """Copy a VASP input set once per value, changing ENCUT or the k-mesh."""
    template, out_dir = Path(template), Path(out_dir)
    parameter = parameter.upper()
    if parameter not in ("ENCUT", "KPOINTS"):
        raise ScanError("VASP scans support ENCUT or KPOINTS")
    missing = [name for name in ("INCAR", "POSCAR", "KPOINTS") if not (template / name).is_file()]
    if missing:
        raise ScanError("template directory is missing: " + ", ".join(missing))
    _prepare_out(out_dir)

    entries = []
    for raw in values:
        if parameter == "ENCUT":
            value = str(int(float(raw))) if float(raw).is_integer() else str(float(raw))
            name = "ENCUT_%s" % value
        else:
            mesh = parse_mesh(raw)
            value = "x".join(str(k) for k in mesh)
            name = "KPOINTS_%s" % value
        target = out_dir / name
        target.mkdir()
        for filename in VASP_INPUTS:
            if (template / filename).is_file():
                shutil.copy2(template / filename, target / filename)
        if parameter == "ENCUT":
            incar = (target / "INCAR").read_text()
            (target / "INCAR").write_text(set_incar_tag(incar, "ENCUT", value))
        else:
            kpoints = (target / "KPOINTS").read_text()
            (target / "KPOINTS").write_text(set_kpoints_mesh(kpoints, mesh))
        entries.append({"dir": name, "parameter": parameter, "value": value})
    _write_manifest(out_dir, entries)
    return entries


def qe_scan(
    template_input: "str | Path",
    out_dir: "str | Path",
    parameter: str,
    values: Sequence[str],
    keep_dual: bool = True,
) -> List[Dict[str, str]]:
    """Copy a pw.x input once per value, changing ecutwfc or the k-mesh.

    With ``keep_dual`` the ecutrho/ecutwfc ratio of the template is kept when
    ecutwfc changes (if the template sets ecutrho).
    """
    template_input, out_dir = Path(template_input), Path(out_dir)
    parameter = parameter.lower()
    if parameter not in ("ecutwfc", "kpoints"):
        raise ScanError("QE scans support ecutwfc or kpoints")
    text = template_input.read_text()
    _prepare_out(out_dir)
    ecutwfc = get_qe_namelist_value(text, "ecutwfc")
    ecutrho = get_qe_namelist_value(text, "ecutrho")

    entries = []
    for raw in values:
        new = text
        if parameter == "ecutwfc":
            value = "%g" % float(raw)
            new = set_qe_namelist_value(new, "ecutwfc", value)
            if keep_dual and ecutwfc and ecutrho:
                new = set_qe_namelist_value(new, "ecutrho", "%g" % (float(raw) * ecutrho / ecutwfc))
            name = "ecutwfc_%s" % value
        else:
            mesh = parse_mesh(raw)
            value = "x".join(str(k) for k in mesh)
            new = set_qe_kpoints(new, mesh)
            name = "kpoints_%s" % value
        target = out_dir / name
        target.mkdir()
        (target / "pw.in").write_text(new)
        entries.append({"dir": name, "parameter": parameter, "value": value})
    _write_manifest(out_dir, entries)
    return entries
