#!/bin/bash
# VASP 6.6.0 job on TRUBA (arf cluster). Usually submitted by slurm/submit_chain.sh, which
# sets the partition, cores, account and the hand-over between steps. By hand, from a run
# directory under /arf/scratch (jobs cannot be submitted from /arf/home):
#   sbatch -A $USER -p hamsi -n 56 /arf/scratch/$USER/dft-hpc-toolkit/slurm/truba_vasp.sbatch
# Full nodes: orfoz 112 cores, hamsi 56, barbun 40; debug runs up to 4 hours (test runs).
# #SBATCH lines cannot hold variables; -p, -n, -A and --time given to sbatch override them.
# --signal: 15 minutes before the time limit Slurm sends USR1 to this script (see the trap).
#SBATCH -M arf
#SBATCH -C weka
#SBATCH -p hamsi
#SBATCH -J vasp
#SBATCH -N 1
#SBATCH -n 56
#SBATCH -c 1
#SBATCH --time=3-00:00:00
#SBATCH --mail-type=END,FAIL
#SBATCH --signal=B:USR1@900
#SBATCH --output=slurm-%j.out
#SBATCH --error=slurm-%j.err

VASP_BIN=${VASP_BIN:-/arf/scratch/$USER/vasp.6.6.0/bin_cpu/vasp_std}
# This VASP is built with Intel oneAPI MPI. Do not add lib/openmpi/*: with two MPI
# libraries in one job VASP crashes at start-up or runs silently slow.
VASP_ENV=${VASP_ENV:-"module load comp/oneapi/2024 lib/hdf5/1.14.3-oneapi-2024"}
VASP_CMD=${VASP_CMD:-"mpirun -np ${SLURM_NTASKS:-1} $VASP_BIN"}
# dfthpc runs from its source tree on the standard library only (no pip on TRUBA), with
# any python3 >= 3.6. PYTHON_MODULE is loaded for those calls only, never for VASP.
DFTHPC_SRC=${DFTHPC_SRC:-/arf/scratch/$USER/dft-hpc-toolkit/src}
PYTHON=${PYTHON:-python3}
PYTHON_MODULE=${PYTHON_MODULE:-}
# Set per step by submit_chain.sh:
STEP=${STEP:-$(basename "$PWD")}
PREV_DIR=${PREV_DIR:-}          # POSCAR = CONTCAR of this directory (the step before)
RESUME=${RESUME:-0}             # 1: go on from this step's own CONTCAR instead
SUPERCELL=${SUPERCELL:-}        # e.g. 4x4x1: POSCAR = phonopy supercell of that CONTCAR
REQUIRE=${REQUIRE:-scf,ionic}   # passed to dfthpc check --require
MIN_VACUUM=${MIN_VACUUM:-}      # e.g. 20: also fail if the vacuum of CONTCAR is below 20 A
STATUS_DIR=${STATUS_DIR:-status}
CLEAN=${CLEAN:-0}               # 1: delete CLEAN_FILES after a passing check
CLEAN_FILES=${CLEAN_FILES:-"WAVECAR CHG CHGCAR WAVEDER"}

# The module scripts use unset variables, so -u is switched on only afterwards.
set +u
if [ -r /usr/share/Modules/init/bash ]; then
    # shellcheck source=/dev/null
    . /usr/share/Modules/init/bash
fi
eval "$VASP_ENV" || { echo "environment setup failed: $VASP_ENV" >&2; exit 1; }
set -euo pipefail

dfthpc() {
    # in a subshell, so the Python module does not change the environment of VASP
    (
        set +u
        if [ -n "$PYTHON_MODULE" ]; then module load "$PYTHON_MODULE" || exit 1; fi
        set -u
        PYTHONPATH="$DFTHPC_SRC${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" -m dfthpc "$@"
    )
}

echo "job ${SLURM_JOB_ID:-local} ($STEP) on ${SLURM_JOB_NODELIST:-$(hostname)}: SLURM_NTASKS=${SLURM_NTASKS:-unset}, $(date)"

rm -f STOPCAR  # left over from a stopped run, it would stop this one at once
if [ -n "$SUPERCELL" ]; then
    if [ -n "$PREV_DIR" ]; then
        [ -s "$PREV_DIR/CONTCAR" ] || { echo "no CONTCAR in $PREV_DIR" >&2; exit 1; }
        cp "$PREV_DIR/CONTCAR" POSCAR-unitcell
    fi
    [ -s POSCAR-unitcell ] || { echo "no POSCAR-unitcell for the $SUPERCELL supercell" >&2; exit 1; }
    dfthpc supercell POSCAR-unitcell "$SUPERCELL" -o POSCAR --incar INCAR
elif [ "$RESUME" = 1 ]; then
    [ -s CONTCAR ] || { echo "RESUME=1 but no CONTCAR in $(pwd)" >&2; exit 1; }
    [ -f POSCAR.orig ] || [ ! -f POSCAR ] || cp POSCAR POSCAR.orig
    cp CONTCAR POSCAR
elif [ -n "$PREV_DIR" ]; then
    [ -s "$PREV_DIR/CONTCAR" ] || { echo "no CONTCAR in $PREV_DIR" >&2; exit 1; }
    cp "$PREV_DIR/CONTCAR" POSCAR
fi
for f in INCAR POSCAR KPOINTS POTCAR; do
    [ -s "$f" ] || { echo "missing $f in $(pwd)" >&2; exit 1; }
done

ulimit -s unlimited 2>/dev/null || echo "warning: could not raise the stack limit" >&2
ulimit -l unlimited 2>/dev/null || echo "warning: could not raise the locked-memory limit" >&2
export OMP_NUM_THREADS=1

# USR1 (15 min before the limit): VASP stops after the current ionic step, so a relaxation
# leaves a usable CONTCAR. VASP runs in the background because bash runs traps only while
# it waits; wait then returns early (> 128) and is called again until VASP has ended.
trap 'echo "LSTOP = .TRUE." > STOPCAR; echo "$(date): close to the time limit, wrote STOPCAR"' USR1
# On TERM (time limit, scancel) the script goes on to record the job; Slurm kills it after KillWait.
trap 'echo "$(date): got SIGTERM (time limit or scancel)"' TERM
start=$(date +%s)
$VASP_CMD > vasp.out 2>&1 &
pid=$!
while :; do
    rc=0
    wait "$pid" || rc=$?
    if [ "$rc" -gt 128 ] && kill -0 "$pid" 2>/dev/null; then continue; fi
    break
done
elapsed=$(( $(date +%s) - start ))
echo "VASP exit code $rc after $elapsed s"

# A failed check fails the job, so the next step of the chain (afterok) never starts.
check_args=(--require "$REQUIRE" --exit-code "$rc" --step "$STEP" --jobid "${SLURM_JOB_ID:-local}"
            --elapsed "$elapsed" --cores $(( ${SLURM_NTASKS:-1} * ${SLURM_CPUS_PER_TASK:-1} ))
            --record "$STATUS_DIR/${SLURM_JOB_ID:-local}.csv")
if [ -n "$MIN_VACUUM" ]; then check_args+=(--min-vacuum "$MIN_VACUUM"); fi
dfthpc check . "${check_args[@]}" || exit 3

if [ "$CLEAN" = 1 ]; then
    # CLEAN_FILES is a list of names, split on purpose
    # shellcheck disable=SC2086
    rm -f $CLEAN_FILES
    echo "removed $CLEAN_FILES"
fi
echo "done $(date)"
