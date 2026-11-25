"""Shared helpers for all assignment scripts."""
import datetime
import json
import os
import random
import subprocess
import threading
import time
import urllib.error
import urllib.request

NS = "emi"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "results")
os.makedirs(RESULTS, exist_ok=True)
BASE_URL = os.environ.get("BASE_URL", "http://emi.local").rstrip("/")
RS_URI = ("mongodb://mongo-0.mongo:27017,mongo-1.mongo:27017,mongo-2.mongo:27017/"
          "emidb?replicaSet=rs0")


def ts():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def run(cmd, timeout=120):
    """Run a command (list), return combined stdout/stderr text."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return f"[timeout after {timeout}s: {' '.join(cmd)}]"
    except FileNotFoundError:
        return f"[command not found: {cmd[0]}]"


def kubectl(*args, timeout=120):
    return run(["kubectl", "-n", NS, *args], timeout=timeout)


class Log:
    """Collects console output and writes it into results/<name>."""
    def __init__(self, name):
        self.path = os.path.join(RESULTS, name)
        self.lines = []

    def __call__(self, text=""):
        print(text, flush=True)
        self.lines.append(text)

    def cmd(self, title, *args, timeout=120):
        self(f"\n$ kubectl -n {NS} {' '.join(args)}" if title is None else f"\n$ {title}")
        out = kubectl(*args, timeout=timeout).rstrip()
        self(out)
        return out

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("\n".join(self.lines) + "\n")
        print(f"\n>>> saved {self.path}")


def mongo_eval(js, pod=None, uri=RS_URI, timeout=60):
    """Run mongosh inside a mongo pod. Tries mongo-0/1/2 until one answers."""
    pods = [pod] if pod else ["mongo-0", "mongo-1", "mongo-2"]
    out = ""
    for p in pods:
        cmd = ["exec", p, "--", "mongosh"] + ([uri] if uri else []) + ["--quiet", "--eval", js]
        out = kubectl(*cmd, timeout=timeout).strip()
        if out and "error" not in out.lower() and "not found" not in out.lower():
            return out
    return out


_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # ignore system proxies


def random_inputs():
    return random.randint(10_000, 5_000_000), round(random.uniform(5, 25), 2), random.randint(6, 360)


def post_emi(P=None, rate=None, n=None, timeout=5):
    """POST /api/emi through the Ingress. Returns (status, json, latency_ms)."""
    if P is None:
        P, rate, n = random_inputs()
    body = json.dumps({"P": P, "rate": rate, "n": n}).encode()
    req = urllib.request.Request(f"{BASE_URL}/api/emi", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with _opener.open(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}"), (time.time() - t0) * 1000
    except urllib.error.HTTPError as e:
        try:
            data = json.loads(e.read() or b"{}")
        except Exception:
            data = {}
        return e.code, data, (time.time() - t0) * 1000
    except Exception as e:  # connection refused, timeout ...
        return 0, {"error": str(e)}, (time.time() - t0) * 1000


class RequestLoop(threading.Thread):
    """Sends POST /api/emi continuously in the background and logs every result."""
    def __init__(self, interval=0.1):
        super().__init__(daemon=True)
        self.interval = interval
        self.records = []      # (ts, status, servedBy, version, ms)
        self._halt = threading.Event()

    def run(self):
        while not self._halt.is_set():
            st, data, ms = post_emi()
            self.records.append((ts(), st, data.get("servedBy", "-"), data.get("version", "-"), round(ms, 1)))
            time.sleep(self.interval)

    def stop(self):
        self._halt.set()
        self.join(timeout=10)

    @property
    def failed(self):
        return [r for r in self.records if r[1] != 200]

    def text(self):
        lines = [f"{r[0]}  HTTP {r[1]:>3}  servedBy={r[2]:<28} version={r[3]:<4} {r[4]} ms" for r in self.records]
        lines.append(f"\nTOTAL requests: {len(self.records)}   OK: {len(self.records) - len(self.failed)}"
                     f"   FAILED: {len(self.failed)}")
        return "\n".join(lines)


class PodWatch:
    """Runs `kubectl get pods -w` and prefixes every line with a timestamp."""
    def __init__(self, selector=None):
        args = ["kubectl", "-n", NS, "get", "pods", "-w", "-o", "wide"]
        if selector:
            args += ["-l", selector]
        self.lines = []
        self.proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.t = threading.Thread(target=self._read, daemon=True)
        self.t.start()

    def _read(self):
        for line in self.proc.stdout:
            self.lines.append(f"[{ts()}] {line.rstrip()}")

    def stop(self):
        self.proc.terminate()
        self.t.join(timeout=5)
        return "\n".join(self.lines)
