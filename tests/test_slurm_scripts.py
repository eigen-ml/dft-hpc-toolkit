"""Run the Slurm templates with bash, replacing the DFT codes with a fake command."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from dfthpc.scan import qe_scan, vasp_scan

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(__file__).parent / "data"
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="bash not available")


def _run(script, args, cwd, **env):
    full_env = dict(os.environ, **env)
    return subprocess.run(
        [BASH, str(ROOT / "slurm" / script)] + list(args),
        cwd=str(cwd), env=full_env, capture_output=True, text=True,
    )


def test_scripts_parse():
    scripts = sorted((ROOT / "slurm").glob("*.sbatch")) + sorted((ROOT / "slurm").glob("*.sh"))
    for script in scripts:
        assert subprocess.run([BASH, "-n", str(script)]).returncode == 0, script


def test_array_task_runs_the_right_directory(tmp_path, vasp_template):
    vasp_scan(vasp_template, tmp_path / "scan", "ENCUT", ["400", "500"])
    result = _run("scan_array.sbatch", ["scan"], tmp_path,
                  SLURM_ARRAY_TASK_ID="1", VASP_CMD="echo fake-vasp")
    assert result.returncode == 0, result.stderr
    assert "ENCUT_500" in result.stdout
    assert (tmp_path / "scan" / "ENCUT_500" / "vasp.out").read_text().strip() == "fake-vasp"
    assert not (tmp_path / "scan" / "ENCUT_400" / "vasp.out").exists()


def test_array_task_runs_qe(tmp_path):
    qe_scan(DATA / "qe_template" / "pw.in", tmp_path / "scan", "ecutwfc", ["30"])
    result = _run("scan_array.sbatch", ["scan"], tmp_path,
                  SLURM_ARRAY_TASK_ID="0", PW_CMD="echo fake-pw")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "scan" / "ecutwfc_30" / "pw.out").read_text().strip() == "fake-pw -in pw.in"


def test_vasp_job_stops_without_inputs(tmp_path):
    result = _run("vasp.sbatch", [], tmp_path, VASP_CMD="echo fake-vasp")
    assert result.returncode == 1
    assert "missing INCAR" in result.stderr


def test_qe_job_checks_job_done(tmp_path):
    (tmp_path / "pw.in").write_text("&CONTROL\n/\n")
    ok = _run("qe_pw.sbatch", [], tmp_path, PW_CMD="echo JOB DONE.")
    assert ok.returncode == 0, ok.stderr
    bad = _run("qe_pw.sbatch", [], tmp_path, PW_CMD="echo crashed")
    assert bad.returncode == 1
