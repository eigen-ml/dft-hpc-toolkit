# dft-hpc-toolkit

[![tests](https://github.com/eigen-ml/dft-hpc-toolkit/actions/workflows/tests.yml/badge.svg)](https://github.com/eigen-ml/dft-hpc-toolkit/actions/workflows/tests.yml)

Small tools I use around VASP and Quantum ESPRESSO runs on Slurm clusters:

- **Slurm job templates** for VASP, pw.x and job arrays over a convergence scan
- **Convergence scans**: one directory per cutoff or k-point mesh, from a template input
- **Output parsers** for VASP `OUTCAR` and pw.x output (final energy, SCF/relaxation status, Fermi level, magnetization, timing)
- **`dfthpc watch`**: SCF history of a running or finished job, with steps that hit the iteration limit marked
- **A scaling benchmark** (AUSURF112 with 1–8 MPI ranks) from an HPC internship
- **Notes** on building QE, single-node Slurm and containers (Docker / Apptainer) on Rocky Linux 8

Pure Python standard library (3.9+), so it runs on cluster login nodes without installing anything else. Plotting is optional and needs matplotlib.

## Install

```bash
git clone https://github.com/eigen-ml/dft-hpc-toolkit.git
cd dft-hpc-toolkit
pip install --user .          # or: pip install --user ".[plot]"
```

Without pip, `PYTHONPATH=src python -m dfthpc ...` works the same way.

## Example: ENCUT convergence with VASP

```bash
# template/ holds INCAR, POSCAR, KPOINTS, POTCAR
dfthpc scan vasp template/ encut_scan ENCUT 400 450 500 550 600 700

# one Slurm array task per directory
sbatch --array=0-5 slurm/scan_array.sbatch encut_scan

# when the jobs are done
dfthpc summary encut_scan --tol 1 --csv encut.csv --plot encut.png
```

`summary` prints the energy per atom of each run, its difference to the most expensive setting (highest cutoff or densest mesh) in meV/atom, whether the SCF converged, and the first setting from which all later ones stay within the tolerance. Output from a real graphene ENCUT scan of mine (VASP 5.4.1):

```text
dir                value           E/atom [eV]    dE [meV/at]    scf  time [s]
ENCUT500           ENCUT500          -9.223424          9.705   True        35
ENCUT600           ENCUT600          -9.225680          7.448   True        42
ENCUT700           ENCUT700          -9.230307          2.822   True         3
ENCUT800           ENCUT800          -9.232348          0.781   True         3
ENCUT900           ENCUT900          -9.232947          0.181   True         5
ENCUT1000          ENCUT1000         -9.233129          0.000   True         8
Converged within 1 meV/atom from ENCUT800 on (relative to the last row).
```

Directories not created by `dfthpc scan` also work; they are ordered by the number or k-mesh in their names.

The same works for k-points (`dfthpc scan vasp template/ k_scan KPOINTS 6x6x1 9x9x1 12x12x1`, needs an automatic Gamma/Monkhorst-Pack `KPOINTS`) and for QE (`dfthpc scan qe pw.in ecut_scan ecutwfc 30 40 50 60`, keeps the `ecutrho/ecutwfc` ratio of the template unless `--no-keep-dual`; `kpoints` needs `K_POINTS automatic`).

## Parsing

```bash
dfthpc parse run1/OUTCAR run2/pw.out
```

```python
from dfthpc import parse_outcar, parse_pw_output

r = parse_outcar("OUTCAR")
r["energy_sigma0"], r["ionic_converged"], r["electronic_converged"], r["elapsed_s"]
```

VASP fields: version, cores, NIONS, NKPTS, ISPIN, ENCUT, NELM, EDIFF, energy (TOTEN and sigma→0) of the last ionic step, energy per atom, number of ionic steps, SCF steps in the last ionic step, E-fermi, magnetization (spin-polarized runs), relaxation reached, SCF stopped before NELM, finished, elapsed time, peak memory.

pw.x fields: version, calculation type (scf / relax / nscf-bands), atoms, ecutwfc, k-points, last `!` total energy in Ry and eV, number of SCF cycles, iterations of the last one, SCF converged, Fermi energy (or highest occupied level; spin up/down Fermi energies when printed), total magnetization, BFGS converged, finished (`JOB DONE`), wall time.

## Watching a job

```bash
dfthpc watch run_dir/            # VASP: reads OSZICAR (and NELM from INCAR)
dfthpc watch pw.out -f           # pw.x output, refresh every 30 s
```

```text
 ionic   scf scf acc. [Ry]        energy [Ry]      mag
     1    15      7.00e-09       -43.12301771        -
     2     9      1.30e-09       -43.08067584        -
     3    10      1.60e-09       -43.12635026        -
     4     6      8.00e-10       -43.12647146        -
     5     8      7.00e-11       -43.12647356        -
```

(Output for the `relax-el` reference run of the QE test suite.) For VASP the column is the last `dE` of each SCF loop in eV and the magnetization from `OSZICAR`; a step whose SCF count reached NELM is marked, since its energy is not converged.

## Slurm templates

| File | Use |
| --- | --- |
| `slurm/vasp.sbatch` | one VASP run in the submit directory |
| `slurm/qe_pw.sbatch` | one pw.x run (`pw.in` → `pw.out`), fails if `JOB DONE` is missing |
| `slurm/scan_array.sbatch` | array job over the directories in `SCAN/dirs.txt`, VASP or QE detected per directory |

Edit the `#SBATCH` lines for your cluster. The program and environment are set by variables (`VASP_CMD`, `VASP_ENV`, `PW_CMD`, `QE_ENV`) so they can be changed without editing the script, e.g. `sbatch --export=ALL,VASP_ENV="module load vasp/6.4" slurm/vasp.sbatch`. The VASP defaults come from the scripts I used on our university cluster (VASP 5.4.1 built with Intel 2017 compilers and MPI).

## What is tested

- Parsers: unit tests on short OUTCAR and pw.x excerpts (`tests/data/`; line formats copied from real output, numbers made up). Outside CI, the VASP parser was run on 109 OUTCARs from my own calculations: final energies match `OSZICAR` to its printed precision and ionic step counts match for all 105 runs that have an `OSZICAR`. The pw.x parser was checked against 12 reference outputs from the Quantum ESPRESSO test suite (scf, lsda, relax, bands). Those files are not included here.
- Scans, summary and watch: unit tests on generated directories and short excerpts.
- Slurm templates: `bash -n` and shellcheck, and CI runs them with bash using a fake command in place of VASP/pw.x (checks directory selection, input checks and the `JOB DONE` check). CI does not have Slurm, VASP or QE, so real submissions are not tested there.

```bash
pip install ".[test]"
pytest
```

## Benchmark

[`benchmarks/ausurf112`](benchmarks/ausurf112): the AUSURF112 QE benchmark on an 8-vCPU Xeon E5-2697 v2 virtual machine, 1 to 8 MPI ranks. Speedup 6.96 on 8 ranks (87% parallel efficiency), with notes on what limited it.

## Notes

- [Single-node Slurm on Rocky Linux 8](docs/slurm-single-node-rocky8.md)
- [Building Quantum ESPRESSO 7.4.1 on Rocky Linux 8](docs/qe-build-rocky8.md) ([Türkçe](docs/tr/qe-derleme-rocky8.md))
- [Conda, Docker and Apptainer on Rocky Linux 8](docs/containers-apptainer.md)

These come from documentation I wrote during an HPC internship in 2025.

## License

MIT. VASP and its POTCAR files are licensed separately; never commit POTCARs (they are in `.gitignore`).
