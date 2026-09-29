from pathlib import Path

import pytest

from dfthpc.vasp import parse_outcar

DATA = Path(__file__).parent / "data"


def test_relaxation_reads_last_ionic_step_only():
    r = parse_outcar(DATA / "OUTCAR_spin_relax")
    assert r["vasp_version"] == "vasp.5.4.1"
    assert (r["nions"], r["nkpts"], r["ispin"], r["cores"]) == (3, 12, 2, 16)
    assert r["encut_ev"] == 500.0
    assert r["ediff"] == pytest.approx(1e-6)
    # SCF-iteration energies must not be counted as ionic steps
    assert r["ionic_steps"] == 2
    assert r["energy_toten"] == pytest.approx(-20.6)
    assert r["energy_sigma0"] == pytest.approx(-20.65)
    assert r["energy_per_atom"] == pytest.approx(-20.65 / 3)
    assert r["efermi"] == pytest.approx(-1.2345)
    assert r["magnetization"] == pytest.approx(3.0)
    assert r["electronic_steps_last"] == 3
    assert r["electronic_converged"] is True
    assert r["ionic_converged"] is True
    assert r["finished"] is True
    assert r["elapsed_s"] == pytest.approx(123.456)
    assert r["max_memory_kb"] == 250000.0


def test_scf_that_hit_nelm_is_flagged():
    r = parse_outcar(DATA / "OUTCAR_unconverged")
    assert r["electronic_steps_last"] == 3
    assert r["nelm"] == 3
    assert r["electronic_converged"] is False
    assert r["finished"] is False
    assert r["magnetization"] is None
