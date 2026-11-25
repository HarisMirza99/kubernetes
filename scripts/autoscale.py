"""
Milestone 04 - autoscaling test (10 minutes):
    2 min at 10 req/s -> 5 min at 100 req/s -> 3 min at 10 req/s
Records `kubectl get hpa emi-web -n emi` every 15 s, plus pod and host CPU.
Outputs: results/autoscale_hpa.csv, results/autoscale_hpa_raw.txt, results/autoscale_httperf_*.txt,
         results/profile_pods_autoscale.csv, results/profile_host_autoscale.csv
"""
import csv
import os
import threading
import time

from common import NS, RESULTS, ROOT, kubectl, run, ts
from httperf_runner import httperf, parse, target_ip
from profiler import Profiler

PHASES = [(10, 120), (100, 300), (10, 180)]
state = {"rate": 0}


def recorder(stop, t0):
    raw = open(os.path.join(RESULTS, "autoscale_hpa_raw.txt"), "w")
    with open(os.path.join(RESULTS, "autoscale_hpa.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "elapsed_s", "request_rate", "replicas", "cpu_utilization_percent", "desired_replicas"])
        while not stop.is_set():
            now = time.time()
            text = kubectl("get", "hpa", "emi-web")
            raw.write(f"[{ts()}] elapsed={now - t0:.0f}s rate={state['rate']}\n{text}\n")
            raw.flush()
            vals = kubectl("get", "hpa", "emi-web", "-o",
                           "jsonpath={.status.currentReplicas} {.status.desiredReplicas} "
                           "{.status.currentMetrics[0].resource.current.averageUtilization}").split()
            cur = vals[0] if vals else ""
            des = vals[1] if len(vals) > 1 else ""
            cpu = vals[2] if len(vals) > 2 else ""
            w.writerow([ts(), f"{now - t0:.0f}", state["rate"], cur, cpu, des])
            f.flush()
            print(f"  [{now - t0:5.0f}s] rate={state['rate']:>3} replicas={cur} cpu={cpu}% desired={des}")
            stop.wait(max(0, 15 - (time.time() - now)))
    raw.close()


def main():
    ip = target_ip()
    print("resetting: delete HPA, scale to 1")
    kubectl("delete", "hpa", "emi-web", "--ignore-not-found")
    kubectl("scale", "deployment", "emi-web", "--replicas=1")
    for _ in range(90):
        if len(kubectl("get", "pods", "-l", "app=emi-web", "--no-headers").strip().splitlines()) == 1:
            break
        time.sleep(2)
    print(run(["kubectl", "apply", "-f", os.path.join(ROOT, "k8s", "hpa", "hpa.yaml")]))
    print("waiting for the HPA to read CPU metrics ...")
    for _ in range(40):
        cpu = kubectl("get", "hpa", "emi-web", "-o",
                      "jsonpath={.status.currentMetrics[0].resource.current.averageUtilization}").strip()
        if cpu:
            break
        time.sleep(3)

    stop = threading.Event()
    t0 = time.time()
    prof = Profiler("autoscale").start()
    rec = threading.Thread(target=recorder, args=(stop, t0), daemon=True)
    rec.start()
    summary = []
    for i, (rate, dur) in enumerate(PHASES, 1):
        state["rate"] = rate
        print(f"\n[{ts()}] phase {i}: {rate} req/s for {dur}s")
        cmd, out = httperf(rate, dur, ip)
        with open(os.path.join(RESULTS, f"autoscale_httperf_phase{i}_{rate}rps.txt"), "w") as rf:
            rf.write(f"# {ts()}\n$ {cmd}\n\n{out}")
        p = parse(out)
        summary.append(f"phase {i}: {rate} req/s x {dur}s -> avg response {p['avg_response_ms']} ms, "
                       f"errors {p['error_count']}")
        print("   ", summary[-1])
    stop.set()
    rec.join(timeout=20)
    prof.stop()
    with open(os.path.join(RESULTS, "autoscale_summary.txt"), "w") as f:
        f.write("\n".join(summary) + "\n\n" + kubectl("describe", "hpa", "emi-web"))
    print("\nautoscaling test finished; outputs in results/")


if __name__ == "__main__":
    main()
