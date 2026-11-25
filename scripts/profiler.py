"""
Profiler: records
  * per-pod CPU (millicores) and memory (MiB) from `kubectl top pods -n emi` every 15 s
  * overall host CPU % every 1 s (psutil)
into CSV files with a timestamp column.

Used by loadtest.py / autoscale.py, but can also run on its own:
    python scripts/profiler.py --label manual --duration 120
"""
import argparse
import csv
import os
import threading
import time

from common import NS, RESULTS, run, ts

try:
    import psutil
except ImportError:
    psutil = None


class Profiler:
    def __init__(self, label, pod_interval=15):
        self.label = label
        self.pod_interval = pod_interval
        self.pod_csv = os.path.join(RESULTS, f"profile_pods_{label}.csv")
        self.host_csv = os.path.join(RESULTS, f"profile_host_{label}.csv")
        self._stop = threading.Event()
        self.threads = [threading.Thread(target=self._pods, daemon=True),
                        threading.Thread(target=self._host, daemon=True)]

    def start(self):
        for t in self.threads:
            t.start()
        return self

    def stop(self):
        self._stop.set()
        for t in self.threads:
            t.join(timeout=20)

    def _pods(self):
        with open(self.pod_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["timestamp", "epoch", "pod", "cpu_millicores", "memory_mib"])
            while not self._stop.is_set():
                now, epoch = ts(), time.time()
                out = run(["kubectl", "top", "pods", "-n", NS, "--no-headers"], timeout=14)
                for line in out.splitlines():
                    parts = line.split()
                    if len(parts) >= 3 and parts[1].endswith("m"):
                        mem = parts[2].replace("Mi", "")
                        w.writerow([now, f"{epoch:.0f}", parts[0], parts[1][:-1], mem])
                f.flush()
                self._stop.wait(max(0, self.pod_interval - (time.time() - epoch)))

    def _host(self):
        with open(self.host_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["timestamp", "epoch", "host_cpu_percent"])
            if psutil is None:
                print("WARNING: psutil not installed -> host CPU not recorded (pip install psutil)")
                return
            psutil.cpu_percent(interval=None)
            while not self._stop.is_set():
                val = psutil.cpu_percent(interval=1)
                w.writerow([ts(), f"{time.time():.0f}", val])
                f.flush()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="manual")
    ap.add_argument("--duration", type=int, default=60)
    a = ap.parse_args()
    p = Profiler(a.label).start()
    time.sleep(a.duration)
    p.stop()
    print("saved", p.pod_csv, "and", p.host_csv)
