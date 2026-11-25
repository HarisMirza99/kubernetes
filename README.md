# Loan EMI Calculator on Kubernetes (Minikube) - DS-584 Assignment 4

Node.js/Express + jQuery/Bootstrap web app, MongoDB 7.0 replica set (StatefulSet + PVCs),
NGINX Ingress (`emi.local`) and a Horizontal Pod Autoscaler.

```
app/        web application, Dockerfile, .dockerignore
k8s/        all manifests (kubectl apply -f k8s/)   k8s/hpa/ = autoscaler (Milestone 04 only)
scripts/    evidence collection, load tests (httperf), profiler, graphs, report builder
results/    raw outputs, CSVs and graphs
```

## API
| Method | Path | Description |
|---|---|---|
| POST | `/api/emi` | body `{P, rate, n}` (JSON or form) -> EMI, total payment, total interest, `servedBy` (pod name from `HOSTNAME`), `podIP` |
| GET | `/api/history` | last 10 calculations, newest first |
| GET | `/health` | 200 only when MongoDB is reachable (readiness + liveness probe) |

The MongoDB connection string is read from `MONGO_URL` (ConfigMap `emi-config`).

## Bring the whole system up on a fresh Minikube cluster

```bash
minikube start --cpus=4 --memory=6144 --driver=docker
minikube addons enable ingress
minikube addons enable metrics-server

docker build -t emi-web:1.0 app/
docker build --build-arg APP_VERSION=1.1 -t emi-web:1.1 app/
minikube image load emi-web:1.0
minikube image load emi-web:1.1

kubectl apply -f k8s/
kubectl get pods -n emi -w          # wait: mongo-0/1/2 Running, mongo-init Completed, emi-web x3 1/1 Ready
kubectl logs job/mongo-init -n emi  # shows 1 PRIMARY + 2 SECONDARY
```

Open the app:
* Port-forward: `kubectl port-forward svc/emi-web 8080:80 -n emi` -> http://localhost:8080
* Ingress: add `emi.local` to the hosts file
  * Linux: `<output of minikube ip>  emi.local` in `/etc/hosts`
  * Windows / macOS (Docker driver): run `minikube tunnel` (keep it open) and add `127.0.0.1  emi.local`
    (Windows: `C:\Windows\System32\drivers\etc\hosts`, edit as Administrator)
  * then open http://emi.local

## Scripts (Python 3, `pip install -r scripts/requirements.txt`)
| Command | What it does |
|---|---|
| `python scripts/evidence.py m2` | cluster state, `rs.status()`, mongo-init logs, stored documents |
| `python scripts/evidence.py persistence` | deletes `mongo-1`, proves same name, same PVC, no data lost |
| `python scripts/evidence.py dist3` / `scale5` | 30 requests via Ingress, per-pod counts (3 and 5 replicas) |
| `python scripts/evidence.py heal-web` / `heal-mongo` | self-healing tests with `kubectl get pods -w` |
| `python scripts/evidence.py rollout` | 1.0 -> 1.1 rolling update + `rollout undo` with a request loop |
| `docker build -t emi-loadgen scripts/loadgen` | builds the httperf load generator image |
| `python scripts/loadtest.py` | 15 fixed-replica runs (1/2/3 replicas x 10/25/50/100/200 req/s, 60 s) |
| `python scripts/autoscale.py` | applies the HPA, 10-minute 10 -> 100 -> 10 req/s test |
| `python scripts/profiler.py` | per-pod CPU/memory every 15 s + host CPU every 1 s -> CSV (used by the two above) |
| `python scripts/graphs.py` | Graph 1, 2, 3 -> `results/graphs/` |
| `python scripts/make_report.py --name .. --roll .. --repo ..` | builds `report.pdf` |

The load generator runs httperf in a container on the `minikube` Docker network and sends
`Host: emi.local` to the node's Ingress (port 80), so the traffic goes through the NGINX Ingress
exactly like the browser. Every request is `POST /api/emi` with random valid inputs (writes to MongoDB).
With a non-Docker driver, install httperf and use `LOADGEN=native`.

## Clean up
```bash
kubectl delete namespace emi
minikube delete
```
