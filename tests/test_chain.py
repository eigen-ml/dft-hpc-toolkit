"""dfthpc check / status / potcar / vacuum / supercell (the pieces the TRUBA job chain uses)."""

import csv
import shutil
from pathlib import Path

import pytest

from dfthpc.chain import read_status
from dfthpc.cli import main
from dfthpc.poscar import PoscarError, expand_magmom, read_poscar, supercell, vacuum
from dfthpc.scan import get_incar_tag

DATA = Path(__file__).parent / "data"
LAYER = DATA / "POSCAR_2d_layer"


def _check(*args):
    return main(["check"] + [str(a) for a in args])


def test_check_exit_codes(capsys):
    assert _check(DATA / "OUTCAR_spin_relax") == 0
    assert _check(DATA / "OUTCAR_vasp6_killed_scf_synthetic") == 1
    assert _check(DATA / "OUTCAR_vasp6_nsw_reached_synthetic") == 1
    assert _check(DATA / "OUTCAR_vasp6_nsw_reached_synthetic", "--require", "scf") == 0
    assert _check(DATA / "OUTCAR_vasp6_nsw_reached_synthetic", "--require", "scf,scf-all") == 1
    # no relaxation target: ionic does not fail a DFPT or static run
    assert _check(DATA / "OUTCAR_vasp6_dfpt_synthetic") == 0
    assert _check(DATA / "OUTCAR_vasp6_afm_sites_synthetic", "--require", "scf,ionic,scf-all") == 0
    out = capsys.readouterr().out
    assert "no timing block" in out
    assert "did not reach EDIFFG after 3 ionic step(s) (NSW = 3)" in out
    assert "ionic n/a" in out
    assert "site moments: 3.11 -3.11 -0.05 0.05" in out


def test_check_without_output_is_a_clean_error(tmp_path, capsys):
    assert _check(tmp_path) == 2
    assert "cannot read the output" in capsys.readouterr().out


def test_check_rejects_unknown_requirements(capsys):
    with pytest.raises(SystemExit) as exc:
        _check(DATA / "OUTCAR_spin_relax", "--require", "scf,phonons")
    assert exc.value.code == 2
    assert "unknown requirement phonons" in capsys.readouterr().err


def test_check_fails_on_exit_code_and_small_vacuum(tmp_path, capsys):
    run = tmp_path / "run"
    run.mkdir()
    shutil.copy(str(DATA / "OUTCAR_spin_relax"), str(run / "OUTCAR"))
    shutil.copy(str(LAYER), str(run / "CONTCAR"))
    assert _check(run, "--min-vacuum", "20") == 0
    assert _check(run, "--min-vacuum", "25") == 1
    assert _check(run, "--exit-code", "137") == 1
    out = capsys.readouterr().out
    assert "vacuum in CONTCAR is 21.90 A, below 25 A" in out
    assert "exited with code 137" in out


def test_record_and_status(tmp_path, capsys):
    cand = tmp_path / "CrI3"
    runs = (("1_relax_isif3", "OUTCAR_spin_relax", "101"), ("2_relax_isif2", "OUTCAR_vasp6_killed_scf_synthetic", "102"))
    for step, outcar, jobid in runs:
        run = cand / step
        run.mkdir(parents=True)
        shutil.copy(str(DATA / outcar), str(run / "OUTCAR"))
        _check(run, "--record", cand / "status" / (jobid + ".csv"), "--jobid", jobid,
               "--exit-code", "0", "--elapsed", "7200", "--cores", "56")
    rows = read_status(tmp_path)
    assert [r["jobid"] for r in rows] == ["101", "102"]
    assert [r["step"] for r in rows] == ["1_relax_isif3", "2_relax_isif2"]
    assert (rows[0]["scf"], rows[0]["ionic"], rows[0]["problems"]) == ("yes", "yes", "")
    assert float(rows[0]["energy_ev"]) == pytest.approx(-20.65)
    assert float(rows[0]["core_hours"]) == pytest.approx(112.0)
    assert rows[1]["scf"] == "no" and "timing block" in rows[1]["problems"]

    capsys.readouterr()
    assert main(["status", str(tmp_path), "--csv", str(tmp_path / "all.csv")]) == 0
    out = capsys.readouterr().out
    assert "CrI3/1_relax_isif3" in out
    assert "2 job(s), 1 with problems, 224.0 core-hours in total." in out
    with open(str(tmp_path / "all.csv"), newline="") as handle:
        assert len(list(csv.DictReader(handle))) == 2


def test_record_without_output_still_writes_a_row(tmp_path):
    assert _check(tmp_path, "--record", tmp_path / "status" / "7.csv", "--jobid", "7", "--exit-code", "139") == 2
    (row,) = read_status(tmp_path)
    assert row["exit_code"] == "139"
    assert "cannot read the output" in row["problems"] and "code 139" in row["problems"]


def test_status_records_site_moments(tmp_path):
    _check(DATA / "OUTCAR_vasp6_afm_sites_synthetic", "--record", tmp_path / "status" / "1.csv")
    assert read_status(tmp_path)[0]["site_moments"] == "3.112 -3.112 -0.051 0.051"


def test_status_without_files(tmp_path, capsys):
    assert main(["status", str(tmp_path)]) == 1
    assert "no status/*.csv" in capsys.readouterr().err


def _library(root, *entries):
    for name, titel, enmax in entries:
        (root / name).mkdir(parents=True)
        (root / name / "POTCAR").write_text(
            "  %s\n   TITEL  = %s\n   ENMAX  =  %.3f; ENMIN  =  100.000 eV\n End of Dataset\n" % (titel, titel, enmax)
        )
    return root


def test_potcar_follows_the_poscar_species(tmp_path, capsys):
    lib = _library(tmp_path / "PP_GGA", ("Cr", "PAW_PBE Cr 06Sep2000", 227.0),
                   ("Cr_pv", "PAW_PBE Cr_pv 02Aug2007", 265.725), ("I", "PAW_PBE I 08Apr2002", 175.647))
    run = tmp_path / "run"
    run.mkdir()
    shutil.copy(str(LAYER), str(run / "POSCAR"))
    assert main(["potcar", str(run / "POSCAR"), "--root", str(lib), "--use", "Cr=Cr_pv"]) == 0
    titels = [line.split("=", 1)[1].strip() for line in (run / "POTCAR").read_text().splitlines() if "TITEL" in line]
    assert titels == ["PAW_PBE Cr_pv 02Aug2007", "PAW_PBE I 08Apr2002"]
    out = capsys.readouterr().out
    assert "Largest ENMAX 265.725 eV" in out and "345 eV" in out


def test_potcar_errors(tmp_path, capsys):
    lib = _library(tmp_path / "lib", ("Cr", "PAW_PBE Cr 06Sep2000", 227.0), ("I", "PAW_PBE Br 06Sep2000", 216.0))
    assert main(["potcar", str(LAYER), "--root", str(lib), "-o", str(tmp_path / "POTCAR")]) == 1
    assert "is for 'PAW_PBE Br 06Sep2000', but the POSCAR species is I" in capsys.readouterr().err
    assert main(["potcar", str(LAYER), "--root", str(tmp_path / "nothing"), "-o", str(tmp_path / "POTCAR")]) == 1
    assert "no POTCAR for Cr" in capsys.readouterr().err
    vasp4 = tmp_path / "POSCAR4"
    vasp4.write_text("".join(line for i, line in enumerate(LAYER.read_text().splitlines(True)) if i != 5))
    assert main(["potcar", str(vasp4), "--root", str(lib)]) == 1
    assert "no species names" in capsys.readouterr().err
    assert not (tmp_path / "POTCAR").exists()
    with pytest.raises(SystemExit):
        main(["potcar", str(LAYER), "--root", str(lib), "--use", "Cr"])


def test_vacuum_of_a_layer():
    report = vacuum(read_poscar(LAYER))
    assert report["height"] == pytest.approx(25.0)
    assert report["thickness"] == pytest.approx(0.124 * 25.0)
    assert report["vacuum"] == pytest.approx(25.0 - 0.124 * 25.0)


def _rewrite(structure, path, cartesian=False, scale=1.0, shift=0.0, tilt=0.0):
    lattice = [list(v) for v in structure["lattice"]]
    lattice[2][0] += tilt
    lines = [structure["comment"], "%.10f" % scale]
    lines += ["%.10f %.10f %.10f" % tuple(x / scale for x in v) for v in lattice]
    lines += [" ".join(structure["species"]), " ".join(map(str, structure["counts"]))]
    lines.append("Cartesian" if cartesian else "Direct")
    for x, y, z in structure["positions"]:
        frac = [x, y, z + shift]
        if cartesian:
            cart = [sum(frac[i] * lattice[i][k] for i in range(3)) / scale for k in range(3)]
            lines.append("%.10f %.10f %.10f" % tuple(cart))
        else:
            lines.append("%.10f %.10f %.10f" % tuple(frac))
    path.write_text("\n".join(lines) + "\n")
    return path


def test_vacuum_across_the_boundary_cartesian_scaled_and_tilted(tmp_path):
    structure = read_poscar(LAYER)
    expected = vacuum(structure)["vacuum"]
    variants = [
        dict(shift=0.5),  # the layer now sits across z = 0
        dict(cartesian=True),
        dict(cartesian=True, scale=2.0, shift=0.5),
        dict(tilt=1.5),  # c not normal to the layer: the height is still 25 A
    ]
    for i, kwargs in enumerate(variants):
        report = vacuum(read_poscar(_rewrite(structure, tmp_path / ("POSCAR%d" % i), **kwargs)))
        assert report["vacuum"] == pytest.approx(expected, abs=1e-6), kwargs
        assert report["height"] == pytest.approx(25.0)


def test_vacuum_cli(capsys):
    assert main(["vacuum", str(LAYER)]) == 0
    assert main(["vacuum", str(LAYER), "--min", "22"]) == 1
    out = capsys.readouterr().out
    assert "layer thickness 3.10 A, vacuum 21.90 A" in out and "FAILED" in out


def test_read_poscar_errors(tmp_path):
    bad = tmp_path / "POSCAR"
    bad.write_text("x\n1.0\n1 0 0\n0 1 0\n0 0 1\nCr I\n2\nDirect\n0 0 0\n0 0 0.5\n")
    with pytest.raises(PoscarError, match="2 species names but 1 atom counts"):
        read_poscar(bad)


def test_supercell_uses_the_phonopy_order():
    unit = read_poscar(LAYER)
    cell = supercell(unit, [2, 2, 1])
    assert cell["counts"] == [8, 24]
    assert cell["lattice"][0] == pytest.approx([13.8, 0.0, 0.0])
    # all images of the first Cr, the a index running fastest, then the second Cr
    first = [[round(x, 6) for x in p] for p in cell["positions"][:5]]
    assert first == [[0.166667, 0.333333, 0.5], [0.666667, 0.333333, 0.5],
                     [0.166667, 0.833333, 0.5], [0.666667, 0.833333, 0.5], [0.333333, 0.166667, 0.5]]


def test_supercell_matches_phonopy():
    pytest.importorskip("phonopy")
    import numpy as np
    from phonopy.interface.vasp import read_vasp
    from phonopy.structure.cells import get_supercell

    for dim in ([4, 4, 1], [2, 3, 1]):
        expected = get_supercell(read_vasp(str(LAYER)), np.diag(dim))
        cell = supercell(read_poscar(LAYER), dim)
        diff = np.array(cell["positions"]) - expected.scaled_positions
        assert np.abs(diff - np.rint(diff)).max() < 1e-12
        assert np.allclose(cell["lattice"], expected.cell)


def test_expand_magmom():
    incar = "ISPIN = 2\nMAGMOM = 3 -3 6*0.5   # AFM\n"
    new, message = expand_magmom(incar, 8, 4)
    assert get_incar_tag(new, "MAGMOM") == "4*3 4*-3 24*0.5"
    assert "# AFM" in new and message == "MAGMOM expanded from 8 to 32 values"
    assert expand_magmom(new, 8, 4) == (new, "MAGMOM already has 32 values")
    assert expand_magmom("ISPIN = 1\n", 8, 4)[1] == "no MAGMOM in INCAR"
    with pytest.raises(PoscarError, match="MAGMOM has 3 values"):
        expand_magmom("MAGMOM = 1 2 3\n", 8, 4)


def test_supercell_cli(tmp_path, capsys):
    incar = tmp_path / "INCAR"
    incar.write_text("MAGMOM = 2*3.0 6*0.6\n")
    out = tmp_path / "POSCAR"
    assert main(["supercell", str(LAYER), "4x4x1", "-o", str(out), "--incar", str(incar)]) == 0
    cell = read_poscar(out)
    assert cell["species"] == ["Cr", "I"] and cell["counts"] == [32, 96]
    expected = supercell(read_poscar(LAYER), [4, 4, 1])["positions"]
    assert [x for p in cell["positions"] for x in p] == pytest.approx([x for p in expected for x in p])
    assert get_incar_tag(incar.read_text(), "MAGMOM") == "32*3.0 96*0.6"
    assert "128 atoms" in capsys.readouterr().out
    assert main(["supercell", str(LAYER), "4x4", "-o", str(tmp_path / "X")]) == 1
    assert not (tmp_path / "X").exists()
