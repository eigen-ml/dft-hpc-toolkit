#!/bin/bash
# VASP job for Slurm. Submit from the directory with INCAR/POSCAR/KPOINTS/POTCAR:
#   sbatch slurm/vasp.sbatch
# Change the #SBATCH lines and the two variables below for your cluster.
#SBATCH --job-name=vasp
#SBATCH --partition=research
#SBATCH --nodes=1
#SBATCH --ntasks=16
#SBATCH --time=24:00:00
#SBATCH --output=slurm-%j.out
#SBATCH --error=slurm-%j.err
##SBATCH --account=research
##SBATCH --nodelist=cn1

# How the environment is set up differs per cluster. Two common cases:
#   module load intel/2017 vasp/5.4.1
#   source /opt/intel/compilers_and_libraries_2017/linux/bin/compilervars.sh intel64
VASP_ENV=${VASP_ENV:-}
VASP_CMD=${VASP_CMD:-"mpirun /opt/vasp/vasp.5.4.1/bin/vasp_std"}

set -eu
[ -n "$VASP_ENV" ] && eval "$VASP_ENV"

# VASP needs a large stack; some systems do not allow raising it.
ulimit -s unlimited 2>/dev/null || echo "warning: could not raise stack limit" >&2

for f in INCAR POSCAR KPOINTS POTCAR; do
    [ -f "$f" ] || { echo "missing $f in $(pwd)" >&2; exit 1; }
done

echo "job ${SLURM_JOB_ID:-local} on ${SLURM_JOB_NODELIST:-$(hostname)}, ${SLURM_NTASKS:-?} tasks, $(date)"
start=$(date +%s)
$VASP_CMD > vasp.out 2>&1
echo "finished after $(( $(date +%s) - start )) s"
