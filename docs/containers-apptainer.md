# Conda, Docker and Apptainer on Rocky Linux 8

Notes from installing Conda, Docker Engine and Apptainer on the same Rocky Linux 8.10 VM used for [the QE build](qe-build-rocky8.md), and from trying to run Quantum ESPRESSO inside an Apptainer container. The container part only partly worked; what failed is listed at the end.

Why both Docker and Apptainer: Docker is convenient for building and testing images, but on shared HPC systems the usual choice is Apptainer (formerly Singularity), because containers run as the calling user without a root daemon and it reads Docker images directly.

## Conda

```bash
wget https://repo.anaconda.com/archive/Anaconda3-2025.06-0-Linux-x86_64.sh
bash Anaconda3-2025.06-0-Linux-x86_64.sh      # install prefix: /opt/anaconda3
```

When the installer asks whether to run `conda init`, answering `no` keeps `(base)` from activating in every shell. It can be changed later with `conda config --set auto_activate_base false` or undone with `conda init --reverse $SHELL`. If `conda` is not found, add `/opt/anaconda3/bin` to `PATH`.

```bash
conda create --name dft python=3.10
conda activate dft
conda install numpy pandas matplotlib
```

`CondaError: Run 'conda init' before 'conda activate'` means the shell hook is missing; `conda init bash` (or `conda init fish`) and a new shell fixes it.

## Docker Engine

Following <https://docs.docker.com/engine/install/rhel/>. Remove old or conflicting packages first (Rocky ships `podman` and `runc`):

```bash
sudo dnf remove docker docker-client docker-client-latest docker-common \
    docker-latest docker-latest-logrotate docker-logrotate docker-engine podman runc
sudo dnf -y install dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo
sudo dnf install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker run hello-world
sudo usermod -aG docker "$USER"      # log out and in again
```

Commands I used most: `docker ps -a`, `docker logs --tail 10 <id>`, `docker exec -it <id> bash`.

## Apptainer

Built from source (<https://github.com/apptainer/apptainer/blob/main/INSTALL.md>). It needs a recent Go.

```bash
sudo dnf groupinstall -y 'Development Tools'
sudo dnf install -y epel-release
sudo dnf install -y libseccomp-devel fakeroot cryptsetup wget git
sudo dnf --enablerepo=devel install -y shadow-utils-subid-devel

export GOVERSION=1.23.6 OS=linux ARCH=amd64
wget -O /tmp/go${GOVERSION}.${OS}-${ARCH}.tar.gz https://dl.google.com/go/go${GOVERSION}.${OS}-${ARCH}.tar.gz
sudo rm -rf /usr/local/go && sudo tar -C /usr/local -xzf /tmp/go${GOVERSION}.${OS}-${ARCH}.tar.gz
export PATH=$PATH:/usr/local/go/bin

git clone https://github.com/apptainer/apptainer.git && cd apptainer
./mconfig && cd builddir && make && sudo make install
apptainer --version
```

Builds need a lot of temporary space. Point it to a directory with room:

```bash
mkdir -p ~/tmp && export APPTAINER_TMPDIR=$HOME/tmp
```

(`SINGULARITY_TMPDIR` still works but prints a warning.)

Quick test:

```bash
apptainer build alpine.sif docker://alpine
apptainer exec alpine.sif cat /etc/os-release
```

## Quantum ESPRESSO in a container

A cleaned-up version of the definition file I used (Ubuntu 22.04 base, Open MPI, QE built inside the image):

```text
Bootstrap: docker
From: ubuntu:22.04

%post
    apt-get update && apt-get install -y build-essential gfortran openmpi-bin libopenmpi-dev \
        libblas-dev liblapack-dev libfftw3-dev wget
    cd /opt
    wget https://gitlab.com/QEF/q-e/-/archive/qe-7.4.1/q-e-qe-7.4.1.tar.gz
    tar -xzf q-e-qe-7.4.1.tar.gz && cd q-e-qe-7.4.1
    ./configure --enable-parallel --prefix=/opt/qe
    make -j"$(nproc)" pw && make install

%environment
    export PATH=/opt/qe/bin:$PATH
    export OMP_NUM_THREADS=1

%runscript
    exec pw.x "$@"
```

```bash
apptainer build qe.sif qe.def
apptainer exec qe.sif pw.x -in scf.in > scf.out
mpirun -np 4 apptainer exec qe.sif pw.x -in scf.in > scf_4.out     # host MPI launches the ranks
```

The last line uses the host's `mpirun` to start ranks inside the container. This only works when the MPI inside the image is compatible with the host MPI (same implementation, close versions).

## What did not work

- **Out of space during `apptainer build`.** The QE compile inside the build filled `/tmp`. Setting `APPTAINER_TMPDIR` to a larger directory is the right fix; as a quick workaround I built as root, which is not recommended.
- **Permission and path errors** when running the built image as a normal user after building it as root, and files not found because the working directory was not bound into the container. Working under `$HOME`, which Apptainer binds by default, avoided the missing-file errors; `--bind` does the same for other directories.
- I tried around fifteen variations of the definition file. The container setup was only partly working when the internship ended, and running QE through the container under Slurm was not finished.

These are notes, not a tested recipe; the definition above has not been rebuilt for this repository.
