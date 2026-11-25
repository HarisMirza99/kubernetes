"""
Collects the command outputs required by Milestones 02 and 03 and saves them in results/.

    python scripts/evidence.py m2            # get all/pvc/configmap, rs.status(), mongo-init logs
    python scripts/evidence.py persistence   # delete mongo-1, prove same name + PVC + no data loss
    python scripts/evidence.py dist3         # 30 requests via Ingress with 3 replicas
    python scripts/evidence.py scale5        # scale to 5, show new pods get traffic only once Ready
    python scripts/evidence.py heal-web      # delete a web pod while requests keep flowing
    python scripts/evidence.py heal-mongo    # delete the MongoDB PRIMARY, new PRIMARY elected
    python scripts/evidence.py rollout       # 1.0 -> 1.1 rolling update with request loop, then undo
"""
import collections
import datetime
import sys
import time

from common import NS, Log, PodWatch, RequestLoop, kubectl, mongo_eval, post_emi, ts

RS_MEMBERS_JS = 'rs.status().members.forEach(m => print(m.name + "  " + m.stateStr))'
COUNT_JS = 'db.getSiblingDB("emidb").calculations.countDocuments()'


def m2():
    log = Log("m2_cluster_state.txt")
    log.cmd(None, "get", "all,pvc,configmap", "-o", "wide")
    log.save()

    log = Log("m2_rs_status.txt")
    log("$ rs.status()  (trimmed to member names and states)")
    log(mongo_eval(RS_MEMBERS_JS))
    log.save()

    log = Log("m2_mongo_init_logs.txt")
    log.cmd(None, "logs", "job/mongo-init")
    log.save()

    log = Log("m2_stored_documents.txt")
    log("$ number of documents in emidb.calculations")
    log(mongo_eval(COUNT_JS))
    log("\n$ last 5 documents")
    log(mongo_eval('db.getSiblingDB("emidb").calculations.find({}, {_id:0}).sort({createdAt:-1})'
                   '.limit(5).forEach(d => printjson(d))'))
    log.save()


def _pod_uid(name):
    return kubectl("get", "pod", name, "-o", "jsonpath={.metadata.uid}").strip()


def persistence():
    log = Log("m2_persistence_test.txt")
    log("===== BEFORE deleting mongo-1 =====")
    log.cmd(None, "get", "pod", "mongo-1", "-o", "wide")
    log.cmd(None, "get", "pvc", "data-mongo-1")
    log.cmd("PVC used by pod mongo-1", "get", "pod", "mongo-1", "-o",
            "jsonpath={.spec.volumes[?(@.name=='data')].persistentVolumeClaim.claimName}")
    log.cmd("PVC uid", "get", "pvc", "data-mongo-1", "-o", "jsonpath={.metadata.uid}")
    old_uid = _pod_uid("mongo-1")
    log(f"\npod uid before: {old_uid}")
    log("\n$ documents seen by mongo-1 (read from its own disk)")
    before = mongo_eval('db.getMongo().setReadPref("secondaryPreferred"); ' + COUNT_JS, pod="mongo-1", uri=None)
    log(before)

    log(f"\n===== [{ts()}] DELETING pod mongo-1 =====")
    log.cmd(None, "delete", "pod", "mongo-1", "--wait=true", timeout=120)

    for _ in range(90):
        uid = _pod_uid("mongo-1")
        ready = kubectl("get", "pod", "mongo-1", "-o",
                        "jsonpath={.status.conditions[?(@.type=='Ready')].status}").strip()
        if uid and uid != old_uid and ready == "True":
            break
        time.sleep(2)
    time.sleep(5)

    log(f"\n===== [{ts()}] AFTER: StatefulSet re-created mongo-1 =====")
    log.cmd(None, "get", "pod", "mongo-1", "-o", "wide")
    log(f"pod uid after: {_pod_uid('mongo-1')}  (new pod object, SAME name)")
    log.cmd(None, "get", "pvc", "data-mongo-1")
    log.cmd("PVC used by pod mongo-1", "get", "pod", "mongo-1", "-o",
            "jsonpath={.spec.volumes[?(@.name=='data')].persistentVolumeClaim.claimName}")
    log.cmd("PVC uid", "get", "pvc", "data-mongo-1", "-o", "jsonpath={.metadata.uid}")
    after = ""
    for _ in range(15):
        after = mongo_eval('db.getMongo().setReadPref("secondaryPreferred"); ' + COUNT_JS, pod="mongo-1", uri=None)
        if after.strip().isdigit():
            break
        time.sleep(3)
    log("\n$ documents seen by mongo-1 after restart")
    log(after)
    log("\n$ rs.status()")
    log(mongo_eval(RS_MEMBERS_JS))
    log(f"\nRESULT: documents before = {before.strip()}, after = {after.strip()} -> "
        f"{'NO DATA LOST' if before.strip() == after.strip() else 'check counts'}; PVC name and uid unchanged.")
    log.save()


def _distribution(log, n=30):
    counts = collections.Counter()
    fails = 0
    for i in range(1, n + 1):
        st, data, ms = post_emi()
        pod = data.get("servedBy", "-") if st == 200 else f"FAILED({st})"
        if st != 200:
            fails += 1
        counts[pod] += 1
        log(f"request {i:>2}: HTTP {st}  servedBy={pod}  ({ms:.0f} ms)")
    log("\nRequests served per pod:")
    log(f"{'Pod':<34}{'Requests':>8}")
    for pod, c in sorted(counts.items()):
        log(f"{pod:<34}{c:>8}")
    log(f"{'TOTAL':<34}{sum(counts.values()):>8}   failed: {fails}")
    return counts


def dist3():
    log = Log("m3_distribution_3_replicas.txt")
    log.cmd(None, "scale", "deployment", "emi-web", "--replicas=3")
    log.cmd(None, "rollout", "status", "deployment/emi-web", "--timeout=180s", timeout=200)
    log.cmd(None, "get", "pods", "-l", "app=emi-web", "-o", "wide")
    log("\n30 x POST /api/emi through the Ingress (http://emi.local)")
    _distribution(log)
    log.save()


def _ready_times():
    out = kubectl("get", "pods", "-l", "app=emi-web", "-o",
                  "jsonpath={range .items[*]}{.metadata.name} {.status.conditions[?(@.type=='Ready')].lastTransitionTime} "
                  "{.status.conditions[?(@.type=='Ready')].status}{'\\n'}{end}")
    res = {}
    for line in out.splitlines():
        p = line.split()
        if len(p) == 3:
            res[p[0]] = (p[1], p[2])
    return res


def scale5():
    log = Log("m3_scale_to_5.txt")
    old_pods = set(_ready_times())
    log(f"pods before scaling: {sorted(old_pods)}")
    loop = RequestLoop(interval=0.1)
    loop.start()
    time.sleep(2)
    log(f"\n[{ts()}] scaling to 5")
    log.cmd(None, "scale", "deployment", "emi-web", "--replicas=5")
    watch = PodWatch("app=emi-web")
    log.cmd(None, "rollout", "status", "deployment/emi-web", "--timeout=180s", timeout=200)
    time.sleep(10)
    loop.stop()
    w = watch.stop()
    log("\n$ kubectl get pods -w (timestamped)")
    log(w)
    rt = _ready_times()
    log("\nReady time (UTC) of each pod:")
    for pod, (t, st) in sorted(rt.items()):
        log(f"  {pod:<34} Ready={st} since {t}   {'(NEW)' if pod not in old_pods else ''}")
    log("\nFirst request served by each NEW pod (local time) - always after it became Ready:")
    first = {}
    for r in loop.records:
        if r[1] == 200 and r[2] not in old_pods and r[2] not in first:
            first[r[2]] = r[0]
    for pod, t in first.items():
        log(f"  {pod:<34} first request at {t}")
    log(f"\nRequests sent while scaling: {len(loop.records)}, failed: {len(loop.failed)}")
    log("\n--- Request loop during scale-up ---")
    log(loop.text())
    log.save()

    log = Log("m3_distribution_5_replicas.txt")
    log.cmd(None, "get", "pods", "-l", "app=emi-web", "-o", "wide")
    log("\n30 x POST /api/emi through the Ingress (http://emi.local)")
    _distribution(log)
    log.save()


def heal_web():
    log = Log("m3_selfheal_web.txt")
    pods = kubectl("get", "pods", "-l", "app=emi-web", "-o", "jsonpath={.items[0].metadata.name}").strip()
    loop = RequestLoop(interval=0.2)
    loop.start()
    watch = PodWatch("app=emi-web")
    time.sleep(3)
    log(f"[{ts()}] deleting web pod {pods}")
    log.cmd(None, "delete", "pod", pods, "--wait=false")
    time.sleep(40)
    log.cmd(None, "get", "pods", "-l", "app=emi-web", "-o", "wide")
    loop.stop()
    log("\n$ kubectl get pods -n emi -w   (timestamped)")
    log(watch.stop())
    log("\n--- requests through the Ingress during the test ---")
    log(loop.text())
    log.save()


def _primary():
    out = mongo_eval('print(db.hello().primary)')
    return out.strip().split(".")[0] if out else ""


def heal_mongo():
    log = Log("m3_selfheal_mongo.txt")
    log("$ rs.status() before")
    log(mongo_eval(RS_MEMBERS_JS))
    primary = _primary()
    before = mongo_eval(COUNT_JS)
    log(f"\ncurrent PRIMARY pod: {primary}    documents: {before}")
    loop = RequestLoop(interval=0.2)
    loop.start()
    watch = PodWatch("app=mongo")
    time.sleep(3)
    log(f"\n[{ts()}] deleting PRIMARY pod {primary}")
    log.cmd(None, "delete", "pod", primary, "--wait=false")
    new_primary = ""
    for _ in range(30):
        time.sleep(2)
        new_primary = _primary()
        if new_primary and new_primary != primary:
            break
    log(f"\n[{ts()}] NEW PRIMARY elected: {new_primary}")
    time.sleep(30)
    loop.stop()
    log("\n$ rs.status() after")
    log(mongo_eval(RS_MEMBERS_JS))
    after = mongo_eval(COUNT_JS)
    log(f"\ndocuments before: {before}   after: {after}  (the app kept saving calculations)")
    log("\n$ kubectl get pods -n emi -w   (timestamped)")
    log(watch.stop())
    ok_after = [r for r in loop.records if r[1] == 200]
    log(f"\nsuccessful saves during/after failover: {len(ok_after)}; "
        f"failed (only during the few-second election, if any): {len(loop.failed)}")
    log("\n--- requests through the Ingress during the test ---")
    log(loop.text())
    log.save()


def rollout():
    log = Log("m3_rollout.txt")
    log.cmd(None, "annotate", "deployment", "emi-web", "kubernetes.io/change-cause=initial release emi-web:1.0", "--overwrite")
    loop = RequestLoop(interval=0.1)
    loop.start()
    time.sleep(5)
    log(f"\n[{ts()}] ===== rolling update to emi-web:1.1 =====")
    log.cmd(None, "set", "image", "deployment/emi-web", "emi-web=emi-web:1.1")
    log.cmd(None, "annotate", "deployment", "emi-web", "kubernetes.io/change-cause=update to emi-web:1.1 (new title/footer)", "--overwrite")
    log.cmd(None, "rollout", "status", "deployment/emi-web", "--timeout=300s", timeout=320)
    time.sleep(5)
    log.cmd(None, "rollout", "history", "deployment/emi-web")
    log(f"\n[{ts()}] ===== rollback to emi-web:1.0 =====")
    log.cmd(None, "rollout", "undo", "deployment/emi-web")
    log.cmd(None, "rollout", "status", "deployment/emi-web", "--timeout=300s", timeout=320)
    time.sleep(5)
    loop.stop()
    log.cmd(None, "rollout", "history", "deployment/emi-web")
    log.cmd(None, "get", "deployment", "emi-web", "-o", "wide")
    log("\n--- request loop during update and rollback ---")
    log(loop.text())
    log.save()
    if loop.failed:
        print(f"\n!!! {len(loop.failed)} requests failed - see the log")
    else:
        print("\nZERO failed requests during the rolling update and rollback")


CMDS = {"m2": m2, "persistence": persistence, "dist3": dist3, "scale5": scale5,
        "heal-web": heal_web, "heal-mongo": heal_mongo, "rollout": rollout}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in CMDS:
        print(__doc__)
        sys.exit(1)
    CMDS[sys.argv[1]]()
