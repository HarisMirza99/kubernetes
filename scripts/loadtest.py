"""
Milestone 04 - fixed-replica experiments.
For replicas 1, 2, 3 and rates 10, 25, 50, 100, 200 req/s (60 s each) it runs httperf through the
Ingress, profiles pods (every 15 s) and host CPU (every 1 s), and writes:
    results/fixed_replicas_summary.csv
    results/httperf_r<R>_rate<X>.txt        (raw httperf output)
    results/profile_pods_r<R>_rate<X>.csv / profile_host_r<R>_rate<X>.csv

    python scripts/loadtest.py                         # full 15 runs (~19 minutes)
    python scripts/loadtest.py --replicas 3 --rates 100  # a single run
"""
import argparse
import csv
import os
import time

from common import RESULTS, kubectl, ts
from httperf_runner import httperf, parse, target_ip
from profiler import Profiler

SUMMARY = os.path.join(RESULTS, "fixed_replicas_summary.csv")
FIELDS = ["timestamp", "replicas", "target_rate", "duration_s", "avg_response_ms", "achieved_req_rate",
          "requests", "replies", "error_count", "client_timeouts", "status_2xx", "status_4xx", "status_5xx"]


def scale_to(n):
    print(f"\n[{ts()}] scaling emi-web to {n} replicas")
    kubectl("scale", "deployment", "emi-web", f"--replicas={n}")
    for _ in range(120):
        ready = kubectl("get", "deploy", "emi-web", "-o", "jsonpath={.status.readyReplicas}").strip() or "0"
        total = kubectl("get", "pods", "-l", "app=emi-web", "--no-headers").strip().splitlines()
        if ready == str(n) and len(total) == n:
            break
        time.sleep(2)
    time.sleep(15)  # let the pods settle and metrics-server catch up


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replicas", type=int, nargs="+", default=[1, 2, 3])
    ap.add_argument("--rates", type=int, nargs="+", default=[10, 25, 50, 100, 200])
    ap.add_argument("--duration", type=int, default=60)
    a = ap.parse_args()

    print(kubectl("delete", "hpa", "emi-web", "--ignore-not-found"))   # no autoscaler during fixed runs
    ip = target_ip()
    print("load target:", ip, "Host: emi.local")
    new = not os.path.exists(SUMMARY)
    with open(SUMMARY, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        for rep in a.replicas:
            scale_to(rep)
            for rate in a.rates:
                label = f"r{rep}_rate{rate}"
                print(f"[{ts()}] run {label}: {rate} req/s for {a.duration}s on {rep} replica(s)")
                prof = Profiler(label).start()
                cmd, out = httperf(rate, a.duration, ip)
                prof.stop()
                with open(os.path.join(RESULTS, f"httperf_{label}.txt"), "w") as rf:
                    rf.write(f"# {ts()}\n$ {cmd}\n\n{out}")
                p = parse(out)
                row = {"timestamp": ts(), "replicas": rep, "target_rate": rate, "duration_s": a.duration,
                       "avg_response_ms": p["avg_response_ms"], "achieved_req_rate": p["request_rate"],
                       "requests": int(p["requests"]), "replies": int(p["replies"]),
                       "error_count": p["error_count"], "client_timeouts": int(p["client_timeouts"]),
                       "status_2xx": int(p["status_2xx"]), "status_4xx": int(p["status_4xx"]),
                       "status_5xx": int(p["status_5xx"])}
                w.writerow(row)
                f.flush()
                print(f"    avg response {row['avg_response_ms']} ms, errors {row['error_count']}, "
                      f"replies {row['replies']}/{row['requests']}")
                if p["requests"] == 0:
                    print("    !!! httperf sent nothing - check the raw output file:\n", out[-1500:])
                time.sleep(5)
    print(f"\nsaved {SUMMARY}")


if __name__ == "__main__":
    main()
