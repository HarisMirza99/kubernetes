"""Runs httperf against http://emi.local and parses its output.

By default httperf runs in a small Docker container (image emi-loadgen) attached to the
"minikube" Docker network, so it works the same on Windows, macOS and Linux with the
Docker driver. It sends the Host header emi.local, so every request goes through the
NGINX Ingress exactly like the browser does.

Set LOADGEN=native to use an httperf installed on your machine instead
(then make sure `minikube ip` is reachable, e.g. on Linux).
"""
import os
import re
import subprocess

from common import run

LOADGEN = os.environ.get("LOADGEN", "docker")
NETWORK = os.environ.get("LOADGEN_NETWORK", "minikube")
HEADER = "Content-Type: application/x-www-form-urlencoded\\n"   # literal \n required by httperf
_SESSIONS_NATIVE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "loadgen", "sessions.txt")


def target_ip():
    ip = os.environ.get("TARGET_IP") or run(["minikube", "ip"]).strip().splitlines()[-1]
    return ip


def httperf(rate, duration, ip):
    sessions = int(rate * duration)
    args = ["--hog", "--server", ip, "--server-name", "emi.local", "--port", os.environ.get("TARGET_PORT", "80"),
            "--add-header", HEADER, "--rate", str(rate), "--timeout", "5"]
    if LOADGEN == "native":
        if not os.path.exists(_SESSIONS_NATIVE):
            subprocess.run(["python3", "make_sessions.py"], cwd=os.path.dirname(_SESSIONS_NATIVE))
        cmd = ["httperf"] + args + [f"--wsesslog={sessions},0,{_SESSIONS_NATIVE}"]
    else:
        cmd = ["docker", "run", "--rm", "--network", NETWORK, "emi-loadgen"] + args + \
              [f"--wsesslog={sessions},0,/work/sessions.txt"]
    out = run(cmd, timeout=duration + 120)
    return " ".join(cmd), out


def parse(out):
    def num(pattern, default=float("nan")):
        m = re.search(pattern, out)
        return float(m.group(1)) if m else default
    r = {
        "avg_response_ms": num(r"Reply time \[ms\]: response ([\d.]+)"),
        "request_rate": num(r"Request rate: ([\d.]+) req/s"),
        "replies": num(r"Total: connections \d+ requests \d+ replies (\d+)", 0),
        "requests": num(r"Total: connections \d+ requests (\d+)", 0),
        "errors_total": num(r"Errors: total (\d+)", 0),
        "client_timeouts": num(r"client-timo (\d+)", 0),
        "status_2xx": num(r"2xx=(\d+)", 0),
        "status_4xx": num(r"4xx=(\d+)", 0),
        "status_5xx": num(r"5xx=(\d+)", 0),
    }
    r["error_count"] = int(r["errors_total"] + r["status_4xx"] + r["status_5xx"])
    return r
