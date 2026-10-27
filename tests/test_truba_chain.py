"""Run slurm/truba_vasp.sbatch and slurm/submit_chain.sh with bash, without Slurm or VASP.

VASP is replaced by a script that copies a test OUTCAR and writes CONTCAR = POSCAR.
sbatch is replaced by a script that runs each job at once and, like Slurm with
--dependency=afterok --kill-on-invalid-dep=yes, cancels a job whose dependency failed.
"""

import csv
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from dfthpc.poscar import read_poscar
from dfthpc.scan import get_incar_tag

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(__file__).parent / "data"
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="bash not available")

FAKE_VASP = """#!/bin/bash
# copy the OUTCAR prepared for this step, as if VASP had written it
touch vasp_started
while [ -n "${WAIT_FOR_STOPCAR:-}" ] && [ ! -f STOPCAR ]; do sleep 0.1; done
cp "$FAKE_OUTCARS/$(basename "$PWD")" OUTCAR
cp POSCAR CONTCAR
echo fake-vasp
"""

FAKE_SBATCH = """#!{python}
import json, os, subprocess, sys
from pathlib import Path

state = Path(os.environ["FAKE_SLURM"])
args, script = sys.argv[1:-1], sys.argv[-1]
opts = dict(zip(args, args[1:] + [""]))
jobid = str(len(list(state.glob("*.json"))) + 1)
env = dict(os.environ, SLURM_JOB_ID=jobid, SLURM_NTASKS=opts["-n"], SLURM_CPUS_PER_TASK="1")
record = {{"args": args, "env": {{k: env.get(k, "") for k in
          ("STEP", "PREV_DIR", "RESUME", "SUPERCELL", "MIN_VACUUM", "REQUIRE", "STATUS_DIR")}}}}
dep = opts.get("--dependency", "")
if dep and json.loads((state / (dep.split(":")[1] + ".json")).read_text())["exit"] != 0:
    record["exit"] = "cancelled"
else:
    with open(os.path.join(opts["-D"], "slurm-%s.out" % jobid), "w") as out:
        record["exit"] = subprocess.call(["bash", script], cwd=opts["-D"], env=env, stdout=out, stderr=subprocess.STDOUT)
(state / (jobid + ".json")).write_text(json.dumps(record))
print(jobid + ";arf")
"""


def _write_inputs(directory, incar="ISPIN = 2\n", poscar=True):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "INCAR").write_text(incar)
    shutil.copy(str(DATA / "vasp_template" / "KPOINTS"), str(directory / "KPOINTS"))
    (directory / "POTCAR").write_text("fake POTCAR\n")
    if poscar:
        shutil.copy(str(DATA / "POSCAR_2d_layer"), str(directory / "POSCAR"))


@pytest.fixture
def fake(tmp_path):
    """Environment with the fake VASP and sbatch; set outcars[step] = fixture name."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "vasp").write_text(FAKE_VASP)
    (bin_dir / "sbatch").write_text(FAKE_SBATCH.format(python=sys.executable))
    for name in ("vasp", "sbatch"):
        (bin_dir / name).chmod(0o755)
    (tmp_path / "outcars").mkdir()
    (tmp_path / "slurm").mkdir()
    env = dict(
        os.environ, PATH=str(bin_dir) + os.pathsep + os.environ["PATH"], USER="atozturk",
        VASP_ENV=":", VASP_CMD=str(bin_dir / "vasp"), PYTHON=sys.executable,
        DFTHPC_SRC=str(ROOT / "src"), FAKE_OUTCARS=str(tmp_path / "outcars"), FAKE_SLURM=str(tmp_path / "slurm"),
    )

    def outcar(step, name):
        shutil.copy(str(DATA / name), str(tmp_path / "outcars" / step))

    def jobs():
        return [json.loads((tmp_path / "slurm" / ("%d.json" % i)).read_text())
                for i in range(1, len(list((tmp_path / "slurm").glob("*.json"))) + 1)]

    return env, outcar, jobs


def _job(directory, env, **extra):
    env = dict(env, SLURM_JOB_ID="11", SLURM_NTASKS="4", **extra)
    return subprocess.run([BASH, str(ROOT / "slurm" / "truba_vasp.sbatch")], cwd=str(directory),
                          env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)


def _rows(directory):
    rows = []
    for path in sorted(Path(directory).glob("*.csv")):
        with open(str(path), newline="") as handle:
            rows.extend(csv.DictReader(handle))
    return rows


def test_job_runs_vasp_and_records_its_status(tmp_path, fake):
    env, outcar, _ = fake
    run = tmp_path / "1_relax_isif3"
    _write_inputs(run)
    outcar("1_relax_isif3", "OUTCAR_spin_relax")
    result = _job(run, env, MIN_VACUUM="20")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SLURM_NTASKS=4" in result.stdout
    assert (run / "vasp.out").read_text().strip() == "fake-vasp"
    (row,) = _rows(run / "status")
    assert (row["jobid"], row["step"], row["exit_code"], row["scf"], row["ionic"]) == ("11", "1_relax_isif3", "0", "yes", "yes")
    assert row["cores"] == "4" and row["problems"] == ""


def test_job_fails_with_exit_3_when_not_converged(tmp_path, fake):
    env, outcar, _ = fake
    run = tmp_path / "2_relax_isif2"
    _write_inputs(run)
    outcar("2_relax_isif2", "OUTCAR_vasp6_killed_scf_synthetic")
    result = _job(run, env, CLEAN="1")
    assert result.returncode == 3
    assert "no timing block" in result.stdout
    (row,) = _rows(run / "status")
    assert row["scf"] == "no" and "timing block" in row["problems"]


def test_job_fails_when_the_vacuum_shrank(tmp_path, fake):
    env, outcar, _ = fake
    run = tmp_path / "1_relax_isif3"
    _write_inputs(run)
    outcar("1_relax_isif3", "OUTCAR_spin_relax")
    assert _job(run, env, MIN_VACUUM="23").returncode == 3
    assert "vacuum in CONTCAR is 21.90 A, below 23 A" in _rows(run / "status")[0]["problems"]


def test_clean_removes_large_files_only_after_a_pass(tmp_path, fake):
    env, outcar, _ = fake
    run = tmp_path / "1_relax_isif3"
    _write_inputs(run)
    outcar("1_relax_isif3", "OUTCAR_spin_relax")
    for name in ("WAVECAR", "CHG", "CHGCAR"):
        (run / name).write_text("big\n")
    assert _job(run, env, CLEAN="1").returncode == 0
    assert not any((run / name).exists() for name in ("WAVECAR", "CHG", "CHGCAR"))
    assert (run / "OUTCAR").exists() and (run / "CONTCAR").exists()


def test_usr1_before_the_time_limit_writes_stopcar(tmp_path, fake):
    env, outcar, _ = fake
    run = tmp_path / "1_relax_isif3"
    _write_inputs(run)
    (run / "STOPCAR").write_text("LSTOP = .TRUE.\n")  # left over: must be removed at the start
    outcar("1_relax_isif3", "OUTCAR_spin_relax")
    env = dict(env, SLURM_JOB_ID="12", SLURM_NTASKS="4", WAIT_FOR_STOPCAR="1")
    proc = subprocess.Popen([BASH, str(ROOT / "slurm" / "truba_vasp.sbatch")], cwd=str(run), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    deadline = time.time() + 20
    while not (run / "vasp_started").exists() and time.time() < deadline:
        time.sleep(0.05)
    assert not (run / "STOPCAR").exists()
    proc.send_signal(signal.SIGUSR1)
    stdout, stderr = proc.communicate(timeout=30)
    assert proc.returncode == 0, stdout + stderr
    assert "wrote STOPCAR" in stdout
    assert (run / "STOPCAR").read_text().strip() == "LSTOP = .TRUE."
    assert "STOPCAR present" in stdout


def test_phonon_job_builds_the_supercell_of_the_previous_contcar(tmp_path, fake):
    env, outcar, _ = fake
    relax = tmp_path / "2_relax_isif2"
    relax.mkdir()
    shutil.copy(str(DATA / "POSCAR_2d_layer"), str(relax / "CONTCAR"))
    phonon = tmp_path / "3_phonon"
    _write_inputs(phonon, incar="IBRION = 8\nISPIN = 2\nMAGMOM = 3 -3 6*0.1\n", poscar=False)
    outcar("3_phonon", "OUTCAR_vasp6_dfpt_synthetic")
    result = _job(phonon, env, PREV_DIR=str(relax), SUPERCELL="4x4x1", REQUIRE="scf,ionic,scf-all")
    assert result.returncode == 0, result.stdout + result.stderr
    assert read_poscar(phonon / "POSCAR")["counts"] == [32, 96]
    assert (phonon / "POSCAR-unitcell").read_text() == (relax / "CONTCAR").read_text()
    assert get_incar_tag((phonon / "INCAR").read_text(), "MAGMOM") == "16*3 16*-3 96*0.1"


def test_chain_hands_contcar_on_and_runs_all_steps(tmp_path, fake):
    env, outcar, jobs = fake
    cand = tmp_path / "CrI3"
    _write_inputs(cand / "1_relax_isif3")
    _write_inputs(cand / "2_relax_isif2", poscar=False)
    _write_inputs(cand / "3_phonon", incar="IBRION = 8\nMAGMOM = 2*3 6*0\n", poscar=False)
    outcar("1_relax_isif3", "OUTCAR_spin_relax")
    outcar("2_relax_isif2", "OUTCAR_spin_relax")
    outcar("3_phonon", "OUTCAR_vasp6_dfpt_synthetic")
    result = subprocess.run([BASH, str(ROOT / "slurm" / "submit_chain.sh"), str(cand)],
                            env=dict(env, PHONON_PARTITION="orfoz"),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "3_phonon: job 3 on orfoz, 112 cores, 3-00:00:00, after 2" in result.stdout

    first, second, third = jobs()
    assert [j["exit"] for j in (first, second, third)] == [0, 0, 0]
    args = first["args"]
    assert args[:2] == ["-M", "arf"] and "--parsable" in args
    for flag, value in (("-A", "atozturk"), ("-p", "hamsi"), ("-n", "56"), ("-c", "1"), ("--time", "3-00:00:00"),
                        ("--signal", "B:USR1@900")):
        assert args[args.index(flag) + 1] == value
    assert "--dependency" not in args
    assert second["args"][second["args"].index("--dependency") + 1] == "afterok:1"
    assert third["args"][third["args"].index("--dependency") + 1] == "afterok:2"
    assert "--kill-on-invalid-dep=yes" in third["args"]
    assert third["args"][third["args"].index("-n") + 1] == "112"
    assert first["env"]["MIN_VACUUM"] == "20" and second["env"]["MIN_VACUUM"] == ""
    assert second["env"]["PREV_DIR"] == str(cand.resolve() / "1_relax_isif3")
    assert (third["env"]["SUPERCELL"], third["env"]["REQUIRE"]) == ("4x4x1", "scf,ionic,scf-all")

    assert (cand / "2_relax_isif2" / "POSCAR").read_text() == (cand / "1_relax_isif3" / "CONTCAR").read_text()
    assert read_poscar(cand / "3_phonon" / "POSCAR")["counts"] == [32, 96]
    rows = _rows(cand / "status")
    assert [r["step"] for r in rows] == ["1_relax_isif3", "2_relax_isif2", "3_phonon"]
    assert all(r["problems"] == "" for r in rows)


def test_chain_stops_after_a_step_that_did_not_converge(tmp_path, fake):
    env, outcar, jobs = fake
    cand = tmp_path / "CrI3"
    _write_inputs(cand / "1_relax_isif3")
    _write_inputs(cand / "2_relax_isif2", poscar=False)
    _write_inputs(cand / "3_phonon", poscar=False)
    outcar("1_relax_isif3", "OUTCAR_vasp6_nsw_reached_synthetic")
    result = subprocess.run([BASH, str(ROOT / "slurm" / "submit_chain.sh"), str(cand)], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert [j["exit"] for j in jobs()] == [3, "cancelled", "cancelled"]
    assert not (cand / "2_relax_isif2" / "OUTCAR").exists()
    (row,) = _rows(cand / "status")
    assert row["ionic"] == "no" and "EDIFFG" in row["problems"]


def test_chain_options_and_input_checks(tmp_path, fake):
    env, outcar, jobs = fake
    cand = tmp_path / "CrI3"
    _write_inputs(cand / "1_relax_isif3")
    _write_inputs(cand / "2_relax_isif2", poscar=False)
    _write_inputs(cand / "3_phonon", poscar=False)

    def chain(*args, **extra):
        return subprocess.run([BASH, str(ROOT / "slurm" / "submit_chain.sh")] + list(args) + [str(cand)],
                              env=dict(env, **extra), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True)

    # --from 2 needs the CONTCAR of step 1; nothing is submitted when an input is missing
    result = chain("--from", "2")
    assert result.returncode == 1 and "1_relax_isif3/CONTCAR (--from 2)" in result.stderr
    (cand / "3_phonon" / "POTCAR").unlink()
    result = chain()
    assert result.returncode == 1 and "missing" in result.stderr and "3_phonon/POTCAR" in result.stderr
    assert jobs() == []
    assert chain("--from", "4").returncode == 2

    # debug partition (a test run): 4 cores, 4 hours, only the phonon step
    _write_inputs(cand / "3_phonon", poscar=False)
    shutil.copy(str(DATA / "POSCAR_2d_layer"), str(cand / "2_relax_isif2" / "CONTCAR"))
    outcar("3_phonon", "OUTCAR_vasp6_dfpt_synthetic")
    result = chain("--from", "3", PARTITION="debug", ACCOUNT="other", MAIL_USER="me@example.org")
    assert result.returncode == 0, result.stdout + result.stderr
    (job,) = jobs()
    args = job["args"]
    for flag, value in (("-p", "debug"), ("-n", "4"), ("--time", "04:00:00"), ("-A", "other"),
                        ("--mail-user", "me@example.org")):
        assert args[args.index(flag) + 1] == value
    assert job["exit"] == 0

    # --resume: step 1 goes on from its own CONTCAR
    (cand / "1_relax_isif3" / "CONTCAR").write_text((cand / "1_relax_isif3" / "POSCAR").read_text().replace(
        "Synthetic", "Stopped run of a synthetic", 1))
    outcar("1_relax_isif3", "OUTCAR_spin_relax")
    outcar("2_relax_isif2", "OUTCAR_spin_relax")
    result = chain("--resume", PARTITION="debug")
    assert result.returncode == 0, result.stdout + result.stderr
    assert jobs()[1]["env"]["RESUME"] == "1" and jobs()[2]["env"]["RESUME"] == "0"
    assert (cand / "1_relax_isif3" / "POSCAR").read_text().startswith("Stopped run")
    assert (cand / "1_relax_isif3" / "POSCAR.orig").read_text().startswith("Synthetic")
