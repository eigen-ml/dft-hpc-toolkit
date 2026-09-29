# AUSURF112 scaling test

AUSURF112 is one of the standard Quantum ESPRESSO benchmarks: a gold surface slab with 112 atoms, run with `pw.x`. I ran it in July 2025 during an HPC internship on a single virtual machine to see how the CPU count affected run time.

Machine: Proxmox/QEMU virtual machine, Intel Xeon E5-2697 v2 (2.70 GHz), 8 vCPU, 32 GB RAM, Rocky Linux 8.10. QE built from source with GNU compilers, Open MPI, OpenBLAS and FFTW (see [the build notes](../../docs/qe-build-rocky8.md)). One MPI rank per core, no OpenMP.

| MPI ranks | Time [s] | Speedup | Efficiency |
| --- | --- | --- | --- |
| 1 | 76,620 | 1.00 | 100% |
| 2 | 38,670 | 1.98 | 99% |
| 4 | 20,164 | 3.80 | 95% |
| 8 | 11,003 | 6.96 | 87% |

![speedup and efficiency](scaling.png)

The times are the `PWSCF ... CPU` totals printed at the end of each run, copied from my notes of that week into `timings.csv`; the raw output files are not in this repository. With one MPI rank per core and no oversubscription this is close to the wall time, but it is not the same measurement. A separate 8-rank run in the same notes took 9,712 s, so run-to-run spread on this VM was around 10%.

The absolute times are slow compared with published results for modern hardware. The VM ran on an older CPU (Ivy Bridge, 2013) behind a virtualization layer, and during the first attempts the VM did not expose AVX to the guest, which broke the parallel runs until it was enabled. The first large runs were also killed for running out of memory (8 GB) until the VM was given 32 GB.

For small inputs the picture is different: running the QE test suite with 2, 4 and 8 ranks made the total wall time longer, not shorter (about 1,000 s, 1,080 s and 1,300 s), because those tests are too small for the communication cost to pay off.

Reproduce the plot:

```bash
python benchmarks/ausurf112/plot_scaling.py
```
