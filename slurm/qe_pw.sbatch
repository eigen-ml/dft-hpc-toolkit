#!/bin/bash
# Quantum ESPRESSO pw.x job for Slurm. Submit from the directory with pw.in:
#   sbatch slurm/qe_pw.sbatch
#SBATCH --job-name=pw
#SBATCH --partition=research
#SBATCH --nodes=1
#SBATCH --ntasks=16
#SBATCH --cpus-per-task=1
#SBATCH --time=24:00:00
#SBATCH --output=slurm-%j.out
#SBATCH --error=slurm-%j.err

QE_ENV=${QE_ENV:-}                  # e.g. "module load qe/7.4.1"
PW_CMD=${PW_CMD:-"mpirun -np ${SLURM_NTASKS:-1} pw.x"}
INPUT=${INPUT:-pw.in}
OUTPUT=${OUTPUT:-pw.out}

set -eu
[ -n "$QE_ENV" ] && eval "$QE_ENV"

# One thread per MPI rank unless OpenMP is wanted on purpose.
export OMP_NUM_THREADS=${SLURM_CPUS_PER_TASK:-1}

# On single-node machines without a fast interconnect Open MPI may fail with
# "PSM3 can't open nic unit" / "fi_endpoint" errors. Forcing TCP fixed it for me:
# export OMPI_MCA_pml=ob1
# export OMPI_MCA_btl=self,tcp

[ -f "$INPUT" ] || { echo "missing $INPUT in $(pwd)" >&2; exit 1; }

echo "job ${SLURM_JOB_ID:-local} on ${SLURM_JOB_NODELIST:-$(hostname)}, ${SLURM_NTASKS:-?} tasks, $(date)"
$PW_CMD -in "$INPUT" > "$OUTPUT" 2>&1
grep -q "JOB DONE" "$OUTPUT" || { echo "pw.x did not finish, see $OUTPUT" >&2; exit 1; }
