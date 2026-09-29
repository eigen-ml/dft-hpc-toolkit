import json
import shutil
from pathlib import Path

import pytest

from dfthpc.scan import ScanError, parse_mesh, qe_scan, set_incar_tag, vasp_scan
from dfthpc.summary import summarize_scan

DATA = Path(__file__).parent / "data"


def test_set_incar_tag_replaces_and_appends():
    assert set_incar_tag("ENCUT = 400   # cutoff\n", "ENCUT", "520") == "ENCUT = 520 # cutoff\n"
    assert set_incar_tag("ISMEAR = 0", "ENCUT", "520") == "ISMEAR = 0\nENCUT = 520\n"


def test_parse_mesh():
    assert parse_mesh("12x12x1") == [12, 12, 1]
    assert parse_mesh("6,6,2") == [6, 6, 2]
    with pytest.raises(ScanError):
        parse_mesh("6x6")


def test_vasp_encut_scan(tmp_path):
    entries = vasp_scan(DATA / "vasp_template", tmp_path / "scan", "ENCUT", ["400", "500"])
    assert [e["dir"] for e in entries] == ["ENCUT_400", "ENCUT_500"]
    assert "ENCUT = 500" in (tmp_path / "scan" / "ENCUT_500" / "INCAR").read_text()
    assert (tmp_path / "scan" / "dirs.txt").read_text() == "ENCUT_400\nENCUT_500\n"
    with pytest.raises(ScanError):
        vasp_scan(DATA / "vasp_template", tmp_path / "scan", "ENCUT", ["600"])  # not empty


def test_vasp_kpoints_scan(tmp_path):
    vasp_scan(DATA / "vasp_template", tmp_path / "k", "KPOINTS", ["9x9x1"])
    lines = (tmp_path / "k" / "KPOINTS_9x9x1" / "KPOINTS").read_text().splitlines()
    assert lines[2] == "Gamma" and lines[3] == "9 9 1"


def test_qe_ecut_scan_keeps_dual(tmp_path):
    qe_scan(DATA / "qe_template" / "pw.in", tmp_path / "q", "ecutwfc", ["40"])
    text = (tmp_path / "q" / "ecutwfc_40" / "pw.in").read_text()
    assert "ecutwfc = 40" in text and "ecutrho = 320" in text


def test_qe_kpoints_scan(tmp_path):
    qe_scan(DATA / "qe_template" / "pw.in", tmp_path / "q", "kpoints", ["6x6x6"])
    lines = (tmp_path / "q" / "kpoints_6x6x6" / "pw.in").read_text().splitlines()
    assert lines[lines.index("K_POINTS automatic") + 1] == "6 6 6 0 0 0"


def _fake_pw_output(energy_ry, natoms=2):
    return (
        "     number of atoms/cell      =            %d\n"
        "!    total energy              =     %.8f Ry\n"
        "     convergence has been achieved in   6 iterations\n"
        "   JOB DONE.\n" % (natoms, energy_ry)
    )


def test_summary_finds_first_converged_value(tmp_path):
    scan = tmp_path / "q"
    qe_scan(DATA / "qe_template" / "pw.in", scan, "ecutwfc", ["20", "30", "40", "50"])
    # per-atom differences to the 50 Ry row: about 73, 0.68, 0.27 and 0 meV/atom
    for value, e in {"20": -15.8386, "30": -15.84389, "40": -15.84392, "50": -15.84394}.items():
        (scan / ("ecutwfc_" + value) / "pw.out").write_text(_fake_pw_output(e * 2))
    summary = summarize_scan(scan, tolerance_mev=1.0)
    assert summary["converged_at"] == "30"
    assert summary["rows"][-1]["delta_mev_per_atom"] == pytest.approx(0.0)
    assert summary["rows"][0]["delta_mev_per_atom"] > 1.0


def test_summary_reports_missing_output(tmp_path):
    scan = tmp_path / "v"
    vasp_scan(DATA / "vasp_template", scan, "ENCUT", ["400", "500"])
    shutil.copy(DATA / "OUTCAR_spin_relax", scan / "ENCUT_500" / "OUTCAR")
    rows = summarize_scan(scan)["rows"]
    assert rows[0]["status"] == "missing output"
    assert rows[1]["status"] == "ok"
    assert json.loads((scan / "scan.json").read_text())[1]["value"] == "500"
