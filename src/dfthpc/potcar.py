"""Join POTCARs from a pseudopotential library in the species order of a POSCAR.

The library is a directory with one ``<name>/POTCAR`` per element or variant
(``Cr``, ``Cr_pv``, ...), as in the VASP distribution (``PP_GGA`` on TRUBA).
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

_FLOAT = r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[EeDd][-+]?\d+)?"
_TITEL = re.compile(r"^\s*TITEL\s*=\s*(.+?)\s*$", re.MULTILINE)
_ENMAX = re.compile(r"ENMAX\s*=\s*(" + _FLOAT + ")")


class PotcarError(ValueError):
    pass


def _element(name: str) -> str:
    """'Cr_pv' -> 'Cr', 'H.75' -> 'H'."""
    return re.match(r"[A-Za-z]+", name).group()


def assemble_potcar(
    species: Sequence[str], root: "str | Path", use: Optional[Mapping[str, str]] = None
) -> Tuple[str, List[Dict[str, Any]]]:
    """Return the joined POTCAR text and, per species, the file, TITEL and ENMAX.

    ``use`` maps a species to another library entry, e.g. {"Cr": "Cr_pv"}.
    Fails if a file is missing or its TITEL names a different element.
    """
    root = Path(root)
    use = dict(use or {})
    parts, info = [], []
    for name in species:
        entry = use.get(name, name)
        path = root / entry / "POTCAR"
        if not path.is_file():
            raise PotcarError("no POTCAR for %s: %s does not exist" % (name, path))
        text = path.read_text(errors="replace")
        titel = _TITEL.search(text)
        enmax = _ENMAX.search(text)
        if titel is None or enmax is None:
            raise PotcarError("%s has no TITEL or ENMAX line; is it a POTCAR?" % path)
        if len(_TITEL.findall(text)) != 1:
            raise PotcarError("%s holds more than one potential" % path)
        label = titel.group(1).split()
        if len(label) < 2 or _element(label[1]) != _element(name):
            raise PotcarError("%s is for %r, but the POSCAR species is %s" % (path, titel.group(1), name))
        parts.append(text if text.endswith("\n") else text + "\n")
        info.append({"species": name, "path": str(path), "titel": titel.group(1), "enmax": float(enmax.group(1))})
    unused = sorted(set(use) - set(species))
    if unused:
        raise PotcarError("--use given for species not in the POSCAR: " + ", ".join(unused))
    return "".join(parts), info
