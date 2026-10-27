#!/bin/bash
# Submit the relax -> relax -> phonon chain of one candidate on TRUBA (arf):
#   slurm/submit_chain.sh [--from N] [--resume] CANDIDATE_DIR
#
# CANDIDATE_DIR/1_relax_isif3, 2_relax_isif2 and 3_phonon each hold INCAR, KPOINTS and
# POTCAR; 1_relax_isif3 also the POSCAR. A job starts only after the one before passed
# `dfthpc check` (--dependency=afterok); a failed step cancels the rest of the chain.
# Each job takes the CONTCAR of the step before as its POSCAR. The phonon job builds the
# SUPERCELL of it in phonopy order (POSCAR-unitcell -> POSCAR) and expands MAGMOM in its
# INCAR. Every job writes CANDIDATE_DIR/status/<jobid>.csv; see `dfthpc status`.
#
#   --from N    start at step N (1-3) instead of 1; the step before needs a CONTCAR
#   --resume    the first step goes on from its own CONTCAR (it was stopped by STOPCAR)
#
# Settings (environment variables):
#   PARTITION=hamsi    orfoz (112 cores/node), hamsi (56), barbun (40), debug (4 h, test runs)
#   NTASKS             MPI ranks (default: a full node of PARTITION, 4 on debug)
#   TIME               time limit (default 3-00:00:00, 04:00:00 on debug)
#   PHONON_PARTITION, PHONON_NTASKS, PHONON_TIME   the same for 3_phonon (default: as above)
#   ACCOUNT=$USER      Slurm account (-A)
#   MAIL_USER          address for the END/FAIL mails (default: Slurm's)
#   SUPERCELL=4x4x1    phonon supercell
#   MIN_VACUUM=20      vacuum (A) required in the CONTCAR of 1_relax_isif3
#   STOP_MARGIN=900    seconds before the time limit at which STOPCAR is written; raise it
#                      when one ionic step takes longer than that
#   CLEAN=1            delete WAVECAR, CHG, CHGCAR, WAVEDER after each passing step
#   VASP_BIN, PYTHON, PYTHON_MODULE   passed on to slurm/truba_vasp.sbatch
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
STEPS=(1_relax_isif3 2_relax_isif2 3_phonon)
usage="usage: $0 [--from N] [--resume] CANDIDATE_DIR"

FROM=1
RESUME=0
while [ $# -gt 0 ]; do
    case $1 in
        --from) FROM=${2:-}; shift 2 || { echo "$usage" >&2; exit 2; } ;;
        --resume) RESUME=1; shift ;;
        -h|--help) echo "$usage"; exit 0 ;;
        -*) echo "unknown option $1; $usage" >&2; exit 2 ;;
        *) break ;;
    esac
done
[ $# -eq 1 ] || { echo "$usage" >&2; exit 2; }
case $FROM in 1|2|3) ;; *) echo "--from takes 1, 2 or 3" >&2; exit 2 ;; esac
[ -d "$1" ] || { echo "no directory $1" >&2; exit 2; }
CAND=$(cd "$1" && pwd)

full_node() {
    case $1 in
        orfoz) echo 112 ;;
        hamsi) echo 56 ;;
        barbun) echo 40 ;;
        debug) echo 4 ;;
        *) echo "unknown partition $1: set NTASKS (and PHONON_NTASKS)" >&2; return 1 ;;
    esac
}
default_time() {
    if [ "$1" = debug ]; then echo 04:00:00; else echo 3-00:00:00; fi
}
PARTITION=${PARTITION:-hamsi}
NTASKS=${NTASKS:-$(full_node "$PARTITION")}
TIME=${TIME:-$(default_time "$PARTITION")}
PHONON_PARTITION=${PHONON_PARTITION:-$PARTITION}
PHONON_NTASKS=${PHONON_NTASKS:-$(full_node "$PHONON_PARTITION")}
PHONON_TIME=${PHONON_TIME:-$(default_time "$PHONON_PARTITION")}
ACCOUNT=${ACCOUNT:-$USER}
MAIL_USER=${MAIL_USER:-}
SUPERCELL=${SUPERCELL:-4x4x1}
MIN_VACUUM=${MIN_VACUUM:-20}
STOP_MARGIN=${STOP_MARGIN:-900}
CLEAN=${CLEAN:-0}
DFTHPC_SRC=${DFTHPC_SRC:-$(cd "$HERE/.." && pwd)/src}

# Check all inputs before anything is submitted.
missing=0
need() {
    [ -s "$1" ] || { echo "missing $1${2:+ ($2)}" >&2; missing=1; }
}
for n in 1 2 3; do
    if [ "$n" -lt "$FROM" ]; then continue; fi
    for f in INCAR KPOINTS POTCAR; do need "$CAND/${STEPS[n-1]}/$f"; done
done
if [ "$RESUME" = 1 ] && [ "$FROM" -lt 3 ]; then
    need "$CAND/${STEPS[FROM-1]}/CONTCAR" "--resume"
elif [ "$FROM" -eq 1 ]; then
    need "$CAND/${STEPS[0]}/POSCAR"
else
    need "$CAND/${STEPS[FROM-2]}/CONTCAR" "--from $FROM"
fi
[ "$missing" = 0 ] || exit 1

name=$(basename "$CAND")
dep=""
for n in 1 2 3; do
    if [ "$n" -lt "$FROM" ]; then continue; fi
    step=${STEPS[n-1]}
    part=$PARTITION ntasks=$NTASKS limit=$TIME
    prev="" resume=0 supercell="" min_vacuum="" require=scf,ionic
    if [ "$n" -gt 1 ]; then prev=$CAND/${STEPS[n-2]}; fi
    if [ "$n" -eq "$FROM" ]; then resume=$RESUME; fi
    if [ "$n" -eq 1 ]; then min_vacuum=$MIN_VACUUM; fi
    if [ "$n" -eq 3 ]; then
        part=$PHONON_PARTITION ntasks=$PHONON_NTASKS limit=$PHONON_TIME
        supercell=$SUPERCELL require=scf,ionic,scf-all
    fi
    args=(-M arf --parsable -A "$ACCOUNT" -p "$part" -N 1 -n "$ntasks" -c 1 --time "$limit"
          --signal "B:USR1@$STOP_MARGIN" -D "$CAND/$step" -J "$name-${step%%_*}" --export=ALL)
    if [ -n "$MAIL_USER" ]; then args+=(--mail-user "$MAIL_USER"); fi
    if [ -n "$dep" ]; then args+=(--dependency "afterok:$dep" --kill-on-invalid-dep=yes); fi
    # --parsable prints "jobid;cluster" when -M is given
    jid=$(STEP=$step PREV_DIR=$prev RESUME=$resume SUPERCELL=$supercell MIN_VACUUM=$min_vacuum \
          REQUIRE=$require STATUS_DIR=$CAND/status CLEAN=$CLEAN DFTHPC_SRC=$DFTHPC_SRC \
          sbatch "${args[@]}" "$HERE/truba_vasp.sbatch" | cut -d';' -f1)
    [ -n "$jid" ] || { echo "sbatch returned no job ID for $step" >&2; exit 1; }
    echo "$step: job $jid on $part, $ntasks cores, $limit${dep:+, after $dep}"
    dep=$jid
done
echo "Follow with: squeue -M arf -u $USER   and   PYTHONPATH=$DFTHPC_SRC python3 -m dfthpc status $CAND"
