# Single-node Slurm on Rocky Linux 8

Notes from setting up Slurm on one Rocky Linux 8.10 virtual machine during an HPC internship in 2025. The goal was a machine where a normal user can submit DFT jobs with `sbatch`; there are no compute nodes, no provisioning and no job accounting. These are the steps that worked on that machine, not a general installer.

Slurm version at the end: 23.11 (from the OpenHPC 2 / EPEL packages).

## What each piece does

| Component | Role | Needed here |
| --- | --- | --- |
| `slurmctld` | controller: queue, scheduling, node state | yes |
| `slurmd` | runs jobs on a compute node (here the same machine) | yes |
| `munge` | authentication between Slurm daemons (shared `munge.key`) | yes |
| `slurmdbd` + MariaDB | job accounting database | no |
| xCAT / Warewulf | provisioning of compute nodes over the network | no |
| NFS exports of `/home`, `/opt/ohpc/pub` | shared filesystem for compute nodes | no |

## 1. Repositories and base packages

```bash
sudo dnf install -y epel-release dnf-plugins-core
sudo dnf config-manager --set-enabled powertools
sudo dnf groupinstall -y "Development Tools"
# OpenHPC 2 release package for EL8 (x86_64)
sudo dnf install -y http://repos.openhpc.community/OpenHPC/2/EL_8/x86_64/ohpc-release-2-1.el8.x86_64.rpm
sudo dnf install -y ohpc-base
```

Time sync (Slurm and munge are sensitive to clock drift):

```bash
sudo systemctl enable --now chronyd
```

The machine's hostname must resolve. On the VM this meant adding the machine's IP and hostname to `/etc/hosts` and checking with `ping $(hostname)`.

## 2. Munge

```bash
sudo dnf install -y munge munge-libs munge-devel
sudo create-munge-key
sudo chown munge:munge /etc/munge/munge.key
sudo chmod 400 /etc/munge/munge.key
sudo systemctl enable --now munge
munge -n | unmunge        # should print STATUS: Success
```

## 3. Slurm packages and directories

```bash
sudo dnf install -y ohpc-slurm-server
sudo mkdir -p /var/spool/slurmd /var/spool/slurmctld /var/log/slurm
sudo chown slurm:slurm /var/spool/slurmctld /var/log/slurm
sudo chmod 750 /var/log/slurm
```

## 4. `/etc/slurm/slurm.conf`

Based on the file used on the VM (4 cores, 8 GB RAM), with log paths tidied up. Set `CPUs` and `RealMemory` for your machine; `slurmd -C` prints the values Slurm detects.

```ini
ClusterName=cluster
SlurmctldHost=localhost
SlurmUser=slurm
SlurmdUser=root
SlurmctldPidFile=/var/run/slurmctld.pid
SlurmdPidFile=/var/run/slurmd.pid
SlurmdSpoolDir=/var/spool/slurmd
StateSaveLocation=/var/spool/slurmctld
SchedulerType=sched/backfill
SelectType=select/cons_tres
SelectTypeParameters=CR_Core_Memory
ReturnToService=1
ProctrackType=proctrack/cgroup
TaskPlugin=task/affinity
SwitchType=switch/none
InactiveLimit=0
KillWait=30
MinJobAge=300
SlurmctldTimeout=120
SlurmdTimeout=300
Waittime=0
SlurmctldDebug=info
SlurmctldLogFile=/var/log/slurm/slurmctld.log
SlurmdDebug=info
SlurmdLogFile=/var/log/slurm/slurmd.log
# no slurmdbd
AccountingStorageType=accounting_storage/none
JobAcctGatherType=jobacct_gather/none
JobCompType=jobcomp/filetxt
PropagateResourceLimitsExcept=MEMLOCK
NodeName=localhost CPUs=4 RealMemory=4000 State=UNKNOWN
PartitionName=normal Nodes=localhost Default=YES MaxTime=24:00:00 State=UP OverSubscribe=EXCLUSIVE
```

`cgroup.conf` was copied from the example that comes with the package (`cp /etc/slurm/cgroup.conf.example /etc/slurm/cgroup.conf`).

## 5. Start and check

```bash
sudo systemctl enable --now slurmctld slurmd
sinfo                     # partition "normal" should be idle
scontrol show node localhost
srun -n 1 hostname
```

The package also installs `slurmdbd`; without a database it fails on start, so it was stopped and disabled (`sudo systemctl disable --now slurmdbd`).

Logs are in `/var/log/slurm/`. The most common problems on the VM were wrong ownership of the log/spool directories and munge not running.

## 6. Users

Run DFT jobs as a normal user, not root: create a user, keep inputs and outputs under its home directory, install the codes under `/opt`, and submit with `sbatch` as that user. Open MPI also refuses to run as root unless forced, which is a good reason to keep it that way.
