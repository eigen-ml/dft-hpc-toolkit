from pathlib import Path

import pytest

from dfthpc.watch import format_history, history

DATA = Path(__file__).parent / "data"


def test_vasp_history_flags_nelm_and_running_scf():
    hist = history(DATA / "vasp_watch")
    assert hist["limit"] == 3
    first, second = hist["steps"]
    assert (first["scf_steps"], first["hit_limit"]) == (2, False)
    assert (second["scf_steps"], second["hit_limit"]) == (3, True)
    assert second["energy"] == pytest.approx(-20.65)
    assert second["magnetization"] == pytest.approx(3.0)
    assert len(hist["running_scf"]) == 1
    text = format_history(hist)
    assert "hit SCF limit (3)" in text and "current SCF: 1 iterations" in text


def test_qe_history_counts_the_converged_iteration():
    hist = history(DATA / "pw_scf_iter.out")
    (step,) = hist["steps"]
    assert step["scf_steps"] == 3
    assert step["energy"] == pytest.approx(-15.844)
    assert step["last_dE"] == pytest.approx(5e-7)
    assert hist["running_scf"] == []


def test_qe_not_converged_is_flagged():
    hist = history(DATA / "pw_notconv.out")
    assert hist["steps"][0]["hit_limit"] is True
