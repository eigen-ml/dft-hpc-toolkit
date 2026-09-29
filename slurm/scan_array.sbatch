#!/bin/bash
# Run every directory of a convergence scan as one Slurm array task.
# Create the scan with `dfthpc scan ...`, then:
#   sbatch --array=0-$(( $(wc -l < SCAN/dirs.txt) - 1 )) slurm/scan_array.sbatch SCAN
# Add %N to the array range (e.g. 0-7%2) to limit how many run at once.
#SBATCH --job-name=conv-scan
#SBATCH --partition=research
#SBATCH --nodes=1
#SBATCH --ntasks=16
#SBATCH --time=12:00:00
#SBATCH --output=slurm-%A_%a.out

set -eu
SCAN_DIR=${1:?usage: sbatch --array=0-N scan_array.sbatch SCAN_DIR}
TASK=${SLURM_ARRAY_TASK_ID:?this script must run as an array job}

DIR=$(sed -n "$((TASK + 1))p" "$SCAN_DIR/dirs.txt")
[ -n "$DIR" ] || { echo "no line $((TASK + 1)) in $SCAN_DIR/dirs.txt" >&2; exit 1; }
cd "$SCAN_DIR/$DIR"

if [ -f INCAR ]; then
    ENV_CMD=${VASP_ENV:-}
    RUN_CMD=${VASP_CMD:-"mpirun /opt/vasp/vasp.5.4.1/bin/vasp_std"}
    OUT=vasp.out
    ulimit -s unlimited 2>/dev/null || echo "warning: could not raise stack limit" >&2
elif [ -f pw.in ]; then
    ENV_CMD=${QE_ENV:-}
    RUN_CMD="${PW_CMD:-mpirun -np ${SLURM_NTASKS:-1} pw.x} -in pw.in"
    OUT=pw.out
    export OMP_NUM_THREADS=${SLURM_CPUS_PER_TASK:-1}
else
    echo "neither INCAR nor pw.in in $(pwd)" >&2
    exit 1
fi
[ -n "$ENV_CMD" ] && eval "$ENV_CMD"

echo "task $TASK: $DIR on ${SLURM_JOB_NODELIST:-$(hostname)}, $(date)"
$RUN_CMD > "$OUT" 2>&1
