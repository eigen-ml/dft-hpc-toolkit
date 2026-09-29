from pathlib import Path

import pytest

from dfthpc.qe import RY_TO_EV, _wall_seconds, parse_pw_output

DATA = Path(__file__).parent / "data"


def test_relax_output():
    r = parse_pw_output(DATA / "pw_relax.out")
    assert r["qe_version"] == "v.7.4.1"
    assert (r["natoms"], r["nkpts"], r["ecutwfc_ry"]) == (2, 4, 40.0)
    assert r["calculation"] == "relax"
    assert r["scf_cycles"] == 2
    assert r["energy_ry"] == pytest.approx(-30.1)
    assert r["energy_ev"] == pytest.approx(-30.1 * RY_TO_EV)
    assert r["scf_iterations_last"] == 5
    assert r["scf_converged"] is True
    assert r["relax_converged"] is True
    assert r["efermi"] == pytest.approx(5.25)
    assert r["magnetization"] == pytest.approx(1.1)
    assert r["elapsed_s"] == pytest.approx(65.25)
    assert r["finished"] is True


def test_scf_not_converged():
    r = parse_pw_output(DATA / "pw_notconv.out")
    assert r["scf_converged"] is False
    assert r["energy_ry"] is None
    assert r["finished"] is False
    assert r["relax_converged"] is None


@pytest.mark.parametrize(
    "text, seconds",
    [("2.99s", 2.99), ("1m23.45s", 83.45), ("1h 2m", 3720.0), ("0h58m", 3480.0)],
)
def test_wall_time_formats(text, seconds):
    assert _wall_seconds(text) == pytest.approx(seconds)
