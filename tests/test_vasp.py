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
    assert r["nelm_hits"] == 1


# VASP 6 style excerpts below are synthetic (see the first lines of each file).


def test_job_killed_in_the_middle_of_an_scf_loop_is_not_converged():
    # 5 SCF steps < NELM=100 used to count as converged
    r = parse_outcar(DATA / "OUTCAR_vasp6_killed_scf_synthetic")
    assert r["vasp_version"] == "vasp.6.6.0"
    assert r["cores"] == 112  # "running  112 mpi-ranks, with 1 threads/rank"
    assert (r["nsw"], r["ibrion"], r["isif"], r["nelm"]) == (200, 2, 3, 100)
    assert r["electronic_steps_last"] == 5
    assert r["electronic_converged"] is False
    assert r["finished"] is False
    assert r["ionic_converged"] is False
    assert r["nelm_hits"] == 0


def test_relaxation_that_used_up_nsw_counts_the_nelm_step():
    r = parse_outcar(DATA / "OUTCAR_vasp6_nsw_reached_synthetic")
    assert r["ionic_steps"] == 3
    assert r["electronic_converged"] is True  # the last SCF loop reached EDIFF
    assert r["nelm_hits"] == 1  # ionic step 2 stopped at NELM=4
    assert r["ionic_converged"] is False
    assert r["finished"] is True
    assert r["energy_sigma0"] == pytest.approx(-40.15)


def test_dfpt_run_has_no_ionic_target():
    r = parse_outcar(DATA / "OUTCAR_vasp6_dfpt_synthetic")
    assert (r["ibrion"], r["nsw"], r["nions"]) == (8, 1, 128)
    assert r["ionic_converged"] is None
    assert r["ionic_steps"] == 1
    assert r["electronic_converged"] is True
    assert r["nelm_hits"] == 0
    assert r["energy_sigma0"] == pytest.approx(-640.0)


def test_unconverged_linear_response_loop_is_caught(tmp_path):
    text = (DATA / "OUTCAR_vasp6_dfpt_synthetic").read_text()
    # drop the "EDIFF is reached" line of the last linear-response loop
    head, _, tail = text.rpartition("aborting loop because EDIFF is reached")
    (tmp_path / "OUTCAR").write_text(head.rsplit("\n", 1)[0] + tail.split("\n", 1)[1])
    r = parse_outcar(tmp_path / "OUTCAR")
    assert r["finished"] is True
    assert r["electronic_converged"] is False
    assert r["nelm_hits"] == 1


def test_static_afm_run_reads_site_moments():
    r = parse_outcar(DATA / "OUTCAR_vasp6_afm_sites_synthetic")
    assert r["cores"] == 56  # 28 ranks x 2 threads
    assert (r["nsw"], r["ibrion"]) == (0, -1)
    assert r["ionic_converged"] is None
    assert r["electronic_converged"] is True
    assert r["magnetization"] == pytest.approx(0.0)
    assert r["magnetization_sites"] == pytest.approx([3.112, -3.112, -0.051, 0.051])


def test_no_site_moments_without_the_block():
    assert parse_outcar(DATA / "OUTCAR_spin_relax")["magnetization_sites"] is None
