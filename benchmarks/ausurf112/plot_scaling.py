"""Speedup and parallel efficiency plot for the AUSURF112 timings in timings.csv."""

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent


def main() -> None:
    with open(HERE / "timings.csv") as handle:
        rows = [(int(r["mpi_ranks"]), float(r["pwscf_cpu_time_s"])) for r in csv.DictReader(handle)]
    ranks = [n for n, _ in rows]
    t1 = rows[0][1]
    speedup = [t1 / t for _, t in rows]
    efficiency = [s / n for s, n in zip(speedup, ranks)]

    print("ranks  time[s]   speedup  efficiency")
    for (n, t), s, e in zip(rows, speedup, efficiency):
        print(f"{n:5d} {t:9.1f} {s:9.2f} {e:10.0%}")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(8, 3.4))
    ax1.plot(ranks, ranks, "--", color="0.6", label="ideal")
    ax1.plot(ranks, speedup, "o-", label="measured")
    ax1.set_xlabel("MPI ranks")
    ax1.set_ylabel("speedup vs 1 rank")
    ax1.set_xticks(ranks)
    ax1.legend(frameon=False)
    ax2.plot(ranks, [e * 100 for e in efficiency], "o-")
    ax2.set_xlabel("MPI ranks")
    ax2.set_ylabel("parallel efficiency [%]")
    ax2.set_xticks(ranks)
    ax2.set_ylim(0, 105)
    fig.suptitle("AUSURF112 (pw.x), Xeon E5-2697 v2 VM, 8 vCPU")
    fig.tight_layout()
    fig.savefig(HERE / "scaling.png", dpi=150)


if __name__ == "__main__":
    main()
