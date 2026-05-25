# Kubernetes Deployment — Lio

Primary target: **OrbStack** (shares host Docker daemon, no registry needed).
Fallback: Minikube (requires `eval $(minikube docker-env)` before building images).

## Prerequisites

- OrbStack running with Kubernetes enabled (Settings → Kubernetes → Enable)
- `kubectl` context set to OrbStack: `kubectl config use-context orbstack`

## 1. Build images

Run from the repo root. OrbStack's K8s cluster uses the same Docker daemon, so built images are immediately available with `imagePullPolicy: Never`.

```bash
docker build -t lio-backend:latest -f apps/backend/Dockerfile .
docker build -t lio-ingestor:latest -f workers/ingestor/Dockerfile .
# VITE_API_BASE must match the LoadBalancer IP assigned to the backend service.
# Build with a placeholder first, then update after step 3 if needed.
docker build -t lio-frontend:latest \
  --build-arg VITE_API_BASE=http://localhost:8000 \
  -f apps/frontend/Dockerfile .
```

## 2. Create secrets

```bash
cp deployments/k8s/01-secrets.template.yaml deployments/k8s/secrets.yaml
# Edit secrets.yaml — fill in API keys
kubectl apply -f deployments/k8s/secrets.yaml
```

`secrets.yaml` is gitignored.

## 3. Deploy

```bash
kubectl apply -f deployments/k8s/00-namespace.yaml
kubectl apply -f deployments/k8s/02-postgres.yaml
kubectl apply -f deployments/k8s/03-redis.yaml
kubectl apply -f deployments/k8s/04-kafka.yaml
kubectl apply -f deployments/k8s/05-backend.yaml
kubectl apply -f deployments/k8s/06-ingestor.yaml
kubectl apply -f deployments/k8s/07-frontend.yaml
```

Or apply all at once (namespace + secrets first):

```bash
kubectl apply -f deployments/k8s/00-namespace.yaml
kubectl apply -f deployments/k8s/secrets.yaml
kubectl apply -f deployments/k8s/
```

## 4. Access the services

OrbStack assigns real IPs to LoadBalancer services:

```bash
kubectl get svc -n lio
```

| Service  | Type         | Port |
|----------|--------------|------|
| backend  | LoadBalancer | 8000 |
| frontend | LoadBalancer | 8080 |

OrbStack also registers DNS under `*.orb.local` — the frontend is accessible at `http://frontend.lio.orb.local:8080` and the backend at `http://backend.lio.orb.local:8000`.

If the frontend was built with `VITE_API_BASE=http://localhost:8000` and the backend LoadBalancer is not at `localhost:8000`, use `kubectl port-forward` as a shortcut:

```bash
kubectl port-forward -n lio svc/backend 8000:8000
kubectl port-forward -n lio svc/frontend 8080:80
```

## 5. Verify 2-replica Pattern C (distributed cancellation)

```bash
kubectl get pods -n lio -l app=backend
# NAME                      READY   STATUS
# backend-xxxxxxx-aaa       1/1     Running
# backend-xxxxxxx-bbb       1/1     Running

# Both replicas subscribe to Redis pub/sub cancel channel.
# A cancel request hitting replica A will propagate to replica B's active stream.
```

## Tear down

```bash
kubectl delete namespace lio
```

This removes all resources including the PVC (Postgres data is lost).

---

### Minikube fallback

```bash
eval $(minikube docker-env)   # point Docker CLI at Minikube's daemon
# then build images as above — they land in Minikube's registry
# service IPs: use `minikube service backend -n lio --url` to get the URL
```
