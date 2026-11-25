"""
Builds report.pdf from everything in app/, k8s/, results/ and screenshots/.
Missing items are shown as a red [MISSING ...] line so you can see what is left.

    python scripts/make_report.py --name "Your Name" --roll "Your Roll No" --repo "https://github.com/you/emi-k8s"
"""
import argparse
import csv
import glob
import os
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from common import RESULTS, ROOT

A4 = (8.27, 11.69)
LINES_PER_PAGE = 88
WRAP = 118


def shot(name):
    for ext in (".png", ".jpg", ".jpeg"):
        p = os.path.join(ROOT, "screenshots", name + ext)
        if os.path.exists(p):
            return p
    return os.path.join(ROOT, "screenshots", name + ".png")


class Report:
    def __init__(self, path):
        self.pdf = PdfPages(path)
        self.missing = []

    def text_page(self, heading, text, mono=True):
        lines = []
        for raw in text.splitlines() or [""]:
            lines += textwrap.wrap(raw, WRAP, replace_whitespace=False, drop_whitespace=False) or [""]
        chunks = [lines[i:i + LINES_PER_PAGE] for i in range(0, len(lines), LINES_PER_PAGE)] or [[]]
        for i, chunk in enumerate(chunks):
            fig = plt.figure(figsize=A4)
            fig.text(0.06, 0.965, heading + (f" (cont. {i + 1})" if i else ""), fontsize=12,
                     weight="bold", va="top", parse_math=False)
            fig.text(0.06, 0.94, "\n".join(chunk), fontsize=6.6 if mono else 9, va="top",
                     family="monospace" if mono else "sans-serif", parse_math=False, linespacing=1.25)
            self.pdf.savefig(fig)
            plt.close(fig)

    def file(self, heading, path, max_lines=None):
        if not os.path.exists(path):
            self.missing.append(os.path.relpath(path, ROOT))
            return self.text_page(heading, f"[MISSING: {os.path.relpath(path, ROOT)}]")
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        if max_lines and len(lines) > max_lines:
            lines = lines[:max_lines] + [f"... ({len(lines) - max_lines} more lines in {os.path.relpath(path, ROOT)})"]
        self.text_page(heading, "\n".join(lines))

    def image(self, heading, path, caption=""):
        fig = plt.figure(figsize=A4)
        fig.text(0.06, 0.965, heading, fontsize=12, weight="bold", va="top", parse_math=False)
        if os.path.exists(path):
            ax = fig.add_axes([0.05, 0.08, 0.9, 0.84])
            ax.imshow(plt.imread(path))
            ax.axis("off")
        else:
            self.missing.append(os.path.relpath(path, ROOT))
            fig.text(0.06, 0.9, f"[MISSING: {os.path.relpath(path, ROOT)}]", color="red", parse_math=False)
        if caption:
            fig.text(0.06, 0.05, caption, fontsize=9, parse_math=False, wrap=True)
        self.pdf.savefig(fig)
        plt.close(fig)

    def close(self):
        self.pdf.close()


def table_text(csv_path, cols):
    if not os.path.exists(csv_path):
        return f"[MISSING: {os.path.relpath(csv_path, ROOT)}]"
    rows = list(csv.DictReader(open(csv_path, newline="")))
    out = ["  ".join(f"{c:>18}" for c in cols)]
    for r in rows:
        out.append("  ".join(f"{str(r.get(c, '')):>18}" for c in cols))
    return "\n".join(out)


def observations():
    p = os.path.join(RESULTS, "fixed_replicas_summary.csv")
    if not os.path.exists(p):
        return ""
    rows = list(csv.DictReader(open(p, newline="")))
    d = {(int(r["replicas"]), int(r["target_rate"])): r for r in rows}
    o = []
    for rate in (100, 200):
        parts = [f"{rep} replica(s): {float(d[(rep, rate)]['avg_response_ms']):.1f} ms / "
                 f"{d[(rep, rate)]['error_count']} errors" for rep in (1, 2, 3) if (rep, rate) in d]
        if parts:
            o.append(f"At {rate} req/s -> " + "; ".join(parts) + ".")
    a = os.path.join(RESULTS, "autoscale_hpa.csv")
    if os.path.exists(a):
        ar = list(csv.DictReader(open(a, newline="")))
        reps = [int(r["replicas"]) for r in ar if r["replicas"].isdigit()]
        if reps:
            o.append(f"Autoscaling: replicas went from {reps[0]} up to a maximum of {max(reps)} during the "
                     f"100 req/s phase and ended at {reps[-1]} after the cool-down.")
    return "\n".join(o)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="<Your Name>")
    ap.add_argument("--roll", default="<Roll No>")
    ap.add_argument("--repo", default="<Git repository link>")
    a = ap.parse_args()
    R = lambda *p: os.path.join(RESULTS, *p)
    K = lambda *p: os.path.join(ROOT, "k8s", *p)
    out = os.path.join(ROOT, "report.pdf")
    rep = Report(out)

    rep.text_page("DS-584 Cloud Computing - Assignment 4", textwrap.dedent(f"""
        Deploying, Load Balancing and Autoscaling a Web Application with MongoDB on Kubernetes (Minikube)

        Name:        {a.name}
        Roll number: {a.roll}
        Git repo:    {a.repo}

        Stack: Node.js 20 + Express, jQuery + Bootstrap 5 (AJAX, no postback), MongoDB 7.0 replica set rs0
        (StatefulSet, 3 x 1Gi PVC), NGINX Ingress (host emi.local), HPA autoscaling/v2 (1-5 pods @ 50% CPU).

        Contents
          Milestone 01 - EMI calculator UI and source code
          Milestone 02 - Dockerfile, manifests, cluster state, replica set, persistence test
          Milestone 03 - Ingress, load distribution, scaling, self-healing, rolling update / rollback
          Milestone 04 - Load tests, profiling, autoscaling and graphs
    """), mono=False)

    # Milestone 1
    rep.image("Milestone 01 - UI result for P=500000, rate=12%, n=24 with history", shot("m1_ui"),
              "Expected EMI = 23,536.74 ; total payment = 564,881.76 ; total interest = 64,881.76")
    rep.text_page("Milestone 01 - Source code", f"Git repository: {a.repo}\n\nKey files: app/server.js (API), "
                  "app/public/index.html + app/public/app.js (UI, AJAX)", mono=False)
    rep.file("app/server.js", os.path.join(ROOT, "app", "server.js"))

    # Milestone 2
    rep.file("Milestone 02 - app/Dockerfile", os.path.join(ROOT, "app", "Dockerfile"))
    rep.file("Milestone 02 - app/.dockerignore", os.path.join(ROOT, "app", ".dockerignore"))
    manifests = "\n\n".join(f"# ===== k8s/{os.path.basename(f)} =====\n" + open(f).read()
                            for f in sorted(glob.glob(K("*.yaml"))))
    rep.text_page("Milestone 02 - Kubernetes manifests (k8s/)", manifests)
    rep.file("kubectl get all,pvc,configmap -n emi -o wide", R("m2_cluster_state.txt"))
    rep.file("rs.status() (members and states)", R("m2_rs_status.txt"))
    rep.file("kubectl logs job/mongo-init -n emi", R("m2_mongo_init_logs.txt"))
    rep.image("App via kubectl port-forward svc/emi-web 8080:80 -n emi", shot("m2_portforward"))
    rep.file("Documents stored in MongoDB", R("m2_stored_documents.txt"))
    rep.file("Persistence test - delete mongo-1", R("m2_persistence_test.txt"))

    # Milestone 3
    rep.file("Milestone 03 - Ingress manifest", K("07-ingress.yaml"))
    rep.image("App at http://emi.local", shot("m3_emi_local"))
    rep.file("Load distribution - 3 replicas", R("m3_distribution_3_replicas.txt"))
    rep.file("Scaling to 5 - new pods get traffic only after Ready", R("m3_scale_to_5.txt"), max_lines=150)
    rep.file("Load distribution - 5 replicas", R("m3_distribution_5_replicas.txt"))
    rep.file("Self-healing - web pod deleted", R("m3_selfheal_web.txt"), max_lines=200)
    rep.file("Self-healing - MongoDB PRIMARY deleted", R("m3_selfheal_mongo.txt"), max_lines=200)
    rep.file("Rolling update 1.0 -> 1.1 and rollback", R("m3_rollout.txt"))

    # Milestone 4
    rep.file("Milestone 04 - HPA manifest (k8s/hpa/hpa.yaml)", K("hpa", "hpa.yaml"))
    rep.text_page("Fixed-replica load tests (httperf, 60 s each)",
                  table_text(R("fixed_replicas_summary.csv"),
                             ["replicas", "target_rate", "avg_response_ms", "achieved_req_rate", "error_count"])
                  + "\n\nObservations\n" + observations())
    rep.image("Graph 1", R("graphs", "graph1_response_time.png"))
    rep.image("Graph 2", R("graphs", "graph2_pod_cpu_r3_100rps.png"),
              "CPU from kubectl top pods every 15 s; utilization = millicores / 100m request.")
    rep.image("Graph 3", R("graphs", "graph3_autoscaling.png"))
    rep.file("Autoscaling - kubectl get hpa every 15 s", R("autoscale_hpa.csv"))
    rep.file("Autoscaling - phase results and kubectl describe hpa", R("autoscale_summary.txt"))
    rep.text_page("Profiling script and raw outputs", "Profiling: scripts/profiler.py (kubectl top pods every 15 s, "
                  "host CPU every 1 s via psutil, CSV with timestamp column).\nAll raw outputs: results/ in the "
                  f"Git repository ({a.repo}).\n\nFiles in results/:\n" +
                  "\n".join(sorted(os.listdir(RESULTS))), mono=False)
    rep.close()
    print("report written to", out)
    if rep.missing:
        print("\nSTILL MISSING:")
        for m in rep.missing:
            print("  -", m)


if __name__ == "__main__":
    main()
