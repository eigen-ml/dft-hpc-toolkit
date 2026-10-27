"""Read and write POSCAR files: vacuum of 2D cells and supercells for phonopy.

Plain Python like the rest of the package (3.6+, no numpy), so it runs inside
a job on the cluster.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from .scan import get_incar_tag, set_incar_tag


class PoscarError(ValueError):
    pass


def _floats(line: str, n: int, what: str) -> List[float]:
    try:
        values = [float(x) for x in line.split()[:n]]
    except ValueError:
        values = []
    if len(values) != n:
        raise PoscarError("cannot read %s from %r" % (what, line.strip()))
    return values


def _cross(a: Sequence[float], b: Sequence[float]) -> List[float]:
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def read_poscar(path: "str | Path") -> Dict[str, Any]:
    """Return the lattice (Å, scaling applied), species, counts and fractional positions.

    Reads the VASP 5 format (species names on line 6) and the VASP 4 format
    without them (``species`` is then None). Selective dynamics flags and
    velocities are dropped.
    """
    lines = Path(path).read_text(errors="replace").splitlines()
    if len(lines) < 8:
        raise PoscarError("%s is too short for a POSCAR" % path)
    scale = [float(x) for x in lines[1].split()[:3] if re.match(r"^[-+]?[\d.]", x)]
    lattice = [_floats(lines[i], 3, "a lattice vector") for i in (2, 3, 4)]
    if len(scale) == 1 and scale[0] < 0:
        # a negative scaling factor is the cell volume
        scale = [(-scale[0] / abs(_dot(lattice[0], _cross(lattice[1], lattice[2])))) ** (1.0 / 3.0)]
    if len(scale) == 1 and scale[0] > 0:
        scale = scale * 3
    if len(scale) != 3:
        raise PoscarError("cannot read the scaling factor from %r" % lines[1].strip())
    # the scaling applies per Cartesian component, to the lattice and to Cartesian positions
    lattice = [[v[k] * scale[k] for k in range(3)] for v in lattice]

    row = 5
    species = None
    if not lines[row].split():
        raise PoscarError("line 6 of %s is empty" % path)
    if not lines[row].split()[0].isdigit():
        # VASP 6 may write "Cr_pv/<hash>"; keep the name before the slash
        species = [name.split("/")[0] for name in lines[row].split()]
        row += 1
    try:
        counts = [int(x) for x in lines[row].split()]
    except ValueError:
        raise PoscarError("cannot read the atom counts from %r" % lines[row].strip())
    if species is not None and len(species) != len(counts):
        raise PoscarError("%d species names but %d atom counts" % (len(species), len(counts)))
    row += 1
    if lines[row].strip()[:1].lower() == "s":
        row += 1  # Selective dynamics
    cartesian = lines[row].strip()[:1].lower() in ("c", "k")
    row += 1

    natoms = sum(counts)
    if len(lines) < row + natoms:
        raise PoscarError("%s lists %d atoms but has only %d position lines" % (path, natoms, len(lines) - row))
    positions = [_floats(lines[row + i], 3, "a position") for i in range(natoms)]
    if cartesian:
        # fractional coordinate k = r . (b_i x b_j) / volume
        volume = _dot(lattice[0], _cross(lattice[1], lattice[2]))
        normals = [_cross(lattice[1], lattice[2]), _cross(lattice[2], lattice[0]), _cross(lattice[0], lattice[1])]
        positions = [[_dot([r[k] * scale[k] for k in range(3)], n) / volume for n in normals] for r in positions]
    return {
        "comment": lines[0].strip(),
        "lattice": lattice,
        "species": species,
        "counts": counts,
        "positions": positions,
    }


def write_poscar(structure: Dict[str, Any], path: "str | Path") -> None:
    """Write a VASP 5 POSCAR with scaling factor 1 and fractional coordinates."""
    out = [structure["comment"] or "POSCAR", "   1.0"]
    out += ["  %21.16f %21.16f %21.16f" % tuple(v) for v in structure["lattice"]]
    if structure["species"]:
        out.append("  " + " ".join("%-4s" % s for s in structure["species"]).rstrip())
    out.append("  " + " ".join("%4d" % n for n in structure["counts"]))
    out.append("Direct")
    out += ["  %20.16f %20.16f %20.16f" % tuple(p) for p in structure["positions"]]
    Path(path).write_text("\n".join(out) + "\n")


def vacuum(structure: Dict[str, Any]) -> Dict[str, float]:
    """Layer thickness and vacuum of a 2D cell along the normal of the a-b plane, in Å.

    The vacuum is the largest gap between neighbouring atoms along c (also
    across the cell boundary, so a layer split by the boundary is handled).
    """
    a, b, c = structure["lattice"]
    normal = _cross(a, b)
    height = abs(_dot(c, normal)) / _dot(normal, normal) ** 0.5
    heights = sorted(p[2] % 1.0 for p in structure["positions"])
    gaps = [heights[i + 1] - heights[i] for i in range(len(heights) - 1)]
    gaps.append(heights[0] + 1.0 - heights[-1])
    gap = max(gaps) * height
    return {"height": height, "thickness": height - gap, "vacuum": gap}


def supercell(structure: Dict[str, Any], dim: Sequence[int]) -> Dict[str, Any]:
    """Diagonal supercell with atoms in the order phonopy uses for SPOSCAR.

    All images of the first atom come first, then those of the second atom,
    and so on; within one atom the a index runs fastest. Fractional positions
    are wrapped into [0, 1). With this order ``phonopy --fc vasprun.xml`` maps
    the force constants of a DFPT run on this cell correctly.
    """
    n1, n2, n3 = dim
    images = [(i, j, k) for k in range(n3) for j in range(n2) for i in range(n1)]
    positions = []
    for x, y, z in structure["positions"]:
        for i, j, k in images:
            positions.append([((x + i) / n1) % 1.0, ((y + j) / n2) % 1.0, ((z + k) / n3) % 1.0])
    lattice = [[x * n for x in v] for v, n in zip(structure["lattice"], dim)]
    return {
        "comment": "%s %dx%dx%d supercell" % (structure["comment"], n1, n2, n3),
        "lattice": lattice,
        "species": structure["species"],
        "counts": [count * len(images) for count in structure["counts"]],
        "positions": positions,
    }


def _expand_tokens(text: str) -> List[str]:
    """'2*3.0 -3' -> ['3.0', '3.0', '-3']."""
    values = []
    for token in text.split():
        if "*" in token:
            count, value = token.split("*", 1)
            values += [value] * int(count)
        else:
            values.append(token)
    return values


def _compress_tokens(values: Sequence[str]) -> str:
    groups: List[Tuple[int, str]] = []
    for value in values:
        if groups and groups[-1][1] == value:
            groups[-1] = (groups[-1][0] + 1, value)
        else:
            groups.append((1, value))
    return " ".join(value if count == 1 else "%d*%s" % (count, value) for count, value in groups)


def expand_magmom(incar: str, natoms_unit: int, ncells: int) -> Tuple[str, str]:
    """Repeat each MAGMOM value ``ncells`` times, in the supercell order of :func:`supercell`.

    Returns the new INCAR text and a short message. An INCAR without MAGMOM,
    or whose MAGMOM already has one value per supercell atom, is returned as is.
    """
    text = get_incar_tag(incar, "MAGMOM")
    if text is None:
        return incar, "no MAGMOM in INCAR"
    try:
        values = _expand_tokens(text)
    except ValueError:
        raise PoscarError("cannot read MAGMOM = %s" % text)
    if len(values) == natoms_unit * ncells:
        return incar, "MAGMOM already has %d values" % len(values)
    if len(values) != natoms_unit:
        raise PoscarError(
            "MAGMOM has %d values; expected %d (unit cell) or %d (supercell)"
            % (len(values), natoms_unit, natoms_unit * ncells)
        )
    expanded = [value for value in values for _ in range(ncells)]
    message = "MAGMOM expanded from %d to %d values" % (len(values), len(expanded))
    return set_incar_tag(incar, "MAGMOM", _compress_tokens(expanded)), message
