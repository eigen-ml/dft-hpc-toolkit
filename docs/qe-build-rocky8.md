# Building Quantum ESPRESSO 7.4.1 on Rocky Linux 8

How QE 7.4.1 was built with the GNU toolchain and Open MPI on a Rocky Linux 8.10 virtual machine (Proxmox/QEMU, Xeon E5-2697 v2, 32 GB RAM) in July 2025. It took several attempts; the errors that came up are listed at the end.

Official documentation: <https://www.quantum-espresso.org/Doc/user_guide/>

## 1. Packages

```bash
sudo dnf groupinstall -y "Development Tools"
sudo dnf install -y gcc-c++ gcc-gfortran make cmake wget \
    openmpi openmpi-devel \
    openblas-devel lapack-devel fftw-devel \
    scalapack-openmpi-devel
# optional
sudo dnf install -y libxc hdf5 hdf5-openmpi-devel
```

If a package name is not found, `dnf search <name>` usually shows the variant the repository has (for example a differently named OpenBLAS package). `rpm -q <name>` checks what is installed.

Open MPI on Rocky is not on the default path:

```bash
export PATH=/usr/lib64/openmpi/bin:$PATH
export LD_LIBRARY_PATH=/usr/lib64/openmpi/lib:$LD_LIBRARY_PATH
which mpif90              # should point to /usr/lib64/openmpi/bin/mpif90
```

I kept these exports in a small file that I `source` before building, not in `~/.bashrc`. A `.bashrc` full of old exports broke one of the builds.

## 2. Configure

```bash
export LC_ALL=C
wget https://gitlab.com/QEF/q-e/-/archive/qe-7.4.1/q-e-qe-7.4.1.tar.gz
tar -xzf q-e-qe-7.4.1.tar.gz && cd q-e-qe-7.4.1
./configure --enable-parallel --prefix=/opt/qe-7.4.1
```

At the end configure lists the libraries it found. On this machine it looked like:

```text
BLAS_LIBS= -lopenblas
LAPACK_LIBS= -lopenblas
SCALAPACK_LIBS=-lscalapack
FFT_LIBS= -lfftw3
```

If a library is missing or wrong, run `make distclean` before configuring again; otherwise the old `make.inc` is reused.

## 3. Build and install

```bash
make -j"$(nproc)" all
sudo make install        # copies pw.x and the other binaries to /opt/qe-7.4.1/bin
```

`make clean` keeps the configuration; `make veryclean` or `make distclean` removes it.

## 4. Test

As a normal user:

```bash
cd test-suite
make run-tests                  # serial
make run-tests NPROCS=2         # checks the MPI build
```

Failed tests leave `test.out.*` and `test.err.*` files in the test folder (for example `test-suite/pw_atom/`). A single run by hand:

```bash
mpirun -np 2 /opt/qe-7.4.1/bin/pw.x -in atom.in > atom.out
```

If the pseudopotentials are not found, set `pseudo_dir` in the `&CONTROL` namelist.

## 5. Errors I ran into

**`Illegal instruction`** when running in parallel. The CPU exposed to the VM had no AVX, and the OpenBLAS build assumed it. Only `NPROCS=1` worked. `lscpu | grep -i avx` shows whether AVX is there. Building OpenBLAS from source for the actual CPU, and later enabling AVX in the VM's CPU settings, fixed it.

**`SIGNAL 9 (Killed)`** in the large benchmark run: the VM ran out of memory. `htop` showed it; raising the VM from 8 to 32 GB solved it. Long runs were then started inside `tmux` so they survived a dropped SSH session.

**Open MPI `PSM3 can't open nic unit` / `fi_endpoint` errors** on a single machine without an InfiniBand/Omni-Path card. Forcing the TCP transport fixed it:

```bash
export OMPI_MCA_pml=ob1
export OMPI_MCA_btl=self,tcp
```

**`mpirun has detected an attempt to run as root`**: run tests and calculations as a normal user; give that user ownership of the test folder (`chown -R user:user /opt/qe-7.4.1/test-suite`) or copy the inputs to the home directory.

**`undefined reference to dgemm_`** during configure when it picked up Intel MKL paths without the MKL environment. Either load the environment (`source /opt/intel/oneapi/setvars.sh`) or configure without MKL so it uses OpenBLAS.

**`pw.x: command not found`**: the install prefix is not on `PATH`; add `/opt/qe-7.4.1/bin` or call it with the full path.
