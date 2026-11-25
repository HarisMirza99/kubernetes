"""Draws the three graphs required by Milestone 04 into results/graphs/."""
import csv
import os
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import RESULTS

OUT = os.path.join(RESULTS, "graphs")
os.makedirs(OUT, exist_ok=True)
CPU_REQUEST_M = 100.0   # pods request 100m CPU -> utilization % = millicores / 100m * 100


def read(name):
    path = os.path.join(RESULTS, name)
    if not os.path.exists(path):
        print("missing", path)
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def graph1():
    rows = read("fixed_replicas_summary.csv")
    if not rows:
        return
    data = defaultdict(dict)
    for r in rows:                         # later runs overwrite earlier ones for the same point
        data[int(r["replicas"])][int(r["target_rate"])] = fnum(r["avg_response_ms"])
    plt.figure(figsize=(8, 5))
    for rep in sorted(data):
        xs = sorted(data[rep])
        plt.plot(xs, [data[rep][x] for x in xs], marker="o", label=f"{rep} replica{'s' if rep > 1 else ''}")
    plt.xlabel("Request rate (req/s)")
    plt.ylabel("Average response time (ms)")
    plt.title("Graph 1: Average response time vs request rate")
    plt.xticks([10, 25, 50, 100, 200])
    plt.grid(alpha=.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(OUT, "graph1_response_time.png"), dpi=150)
    plt.close()


def graph2():
    rows = [r for r in read("profile_pods_r3_rate100.csv") if r["pod"].startswith("emi-web")]
    if not rows:
        return
    t0 = min(fnum(r["epoch"]) for r in rows)
    series = defaultdict(list)
    for r in rows:
        series[r["pod"]].append((fnum(r["epoch"]) - t0, fnum(r["cpu_millicores"]) / CPU_REQUEST_M * 100))
    plt.figure(figsize=(8, 5))
    for pod, pts in sorted(series.items()):
        pts.sort()
        plt.plot([p[0] for p in pts], [p[1] for p in pts], marker="o", label=pod)
    plt.axhline(100, ls="--", c="grey", lw=1)
    plt.text(0, 102, "CPU request (100m)", fontsize=8, color="grey")
    plt.xlabel("Time since start of run (s)")
    plt.ylabel("CPU utilization (% of 100m request)")
    plt.title("Graph 2: Per-pod CPU, 100 req/s with 3 replicas")
    plt.grid(alpha=.3)
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(os.path.join(OUT, "graph2_pod_cpu_r3_100rps.png"), dpi=150)
    plt.close()


def graph3():
    rows = read("autoscale_hpa.csv")
    if not rows:
        return
    t = [fnum(r["elapsed_s"]) / 60 for r in rows]
    fig, ax = plt.subplots(3, 1, figsize=(9, 8), sharex=True)
    ax[0].step(t, [fnum(r["request_rate"]) for r in rows], where="post", color="tab:blue")
    ax[0].set_ylabel("Request rate\n(req/s)")
    ax[1].plot(t, [fnum(r["cpu_utilization_percent"]) for r in rows], marker=".", color="tab:red")
    ax[1].axhline(50, ls="--", c="grey", lw=1)
    ax[1].text(0, 52, "HPA target 50%", fontsize=8, color="grey")
    ax[1].set_ylabel("Avg CPU\nutilization (%)")
    ax[2].step(t, [fnum(r["replicas"]) for r in rows], where="post", color="tab:green")
    ax[2].set_ylabel("Web replicas")
    ax[2].set_ylim(0, 6)
    ax[2].set_xlabel("Time (minutes)")
    for a in ax:
        a.grid(alpha=.3)
        a.axvline(2, c="k", lw=.6, ls=":")
        a.axvline(7, c="k", lw=.6, ls=":")
    fig.suptitle("Graph 3: Autoscaling test (10 -> 100 -> 10 req/s)")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "graph3_autoscaling.png"), dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    graph1()
    graph2()
    graph3()
    print("graphs saved in", OUT)
