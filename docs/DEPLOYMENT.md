# EDGAR-X — Deployment Guide (Layer 7)

> **Status: deployment-ready infrastructure as code — NOT deployed.**
> Every artifact below is written, reviewable, and validated offline at zero
> cost. **None of it has been applied to a cloud account.** There is no running
> cluster, no provisioned VPC, no ECR registry, no Prometheus/Grafana instance.
> Running the apply steps would create **billable AWS resources** (EKS control
> plane, NAT gateway, EC2 nodes, etc.). They are documented here, not executed.

## What exists in the repo

| Area | Path | What it is |
|---|---|---|
| Infrastructure (Terraform-compatible HCL) | [`infrastructure/terraform/`](../infrastructure/terraform) | VPC + subnets, EKS cluster + node group, ECR repos, IAM (incl. IRSA), Secrets Manager containers |
| Kubernetes workloads | [`infrastructure/kubernetes/`](../infrastructure/kubernetes) | Namespace, IRSA service account, ConfigMap, Secret template, Airflow scheduler/webserver, backfill Job, retraining CronJob |
| Monitoring config | [`infrastructure/monitoring/`](../infrastructure/monitoring) | Prometheus scrape config + Grafana dashboard JSON |
| CI/CD | [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) | Lint + test + dbt — **the one piece that genuinely runs**; image build/push job is disabled |

## How each piece was validated (accurate tool descriptions)

The standard CLIs were either unavailable as free installs (`terraform` is no
longer in homebrew-core under HashiCorp's BSL license) or require a live cluster
(`kubectl --dry-run=client` performs server API discovery and cannot run
clusterless). So validation used the equivalent free, offline tools — described
here honestly rather than overclaiming:

- **Terraform HCL** — validated with **OpenTofu** (`tofu init -backend=false`,
  `tofu fmt`, `tofu validate`). OpenTofu is the open-source, Terraform-compatible
  engine; it parses and validates the **identical HCL** Terraform would. Result:
  `fmt` clean, `validate` → *"Success! The configuration is valid."*, and **no
  state file written — nothing applied.** It is `terraform`-compatible HCL; I did
  not run `terraform` itself.
- **Kubernetes manifests** — validated with **kubeconform** in `-strict` mode
  against the published **Kubernetes 1.30** API schemas (matching the EKS version
  in the Terraform). Result: **9/9 resources valid**. This is offline schema
  validation; I did not run `kubectl` against a cluster (there is none).
- **CI workflow** — the lint/test/dbt jobs were run locally first and all pass:
  `ruff check` clean, `pytest` 195 passed at ~92% coverage (gate is 80%), and
  `dbt parse` + `dbt compile` against the DuckDB dev target exit 0.

## The deploy path (reference — NOT executed)

The following is the sequence a real deployment would run. **It has not been
run.** Each step that costs money is marked 💸.

### 1. Provision infrastructure (💸 creates billable resources)

```bash
cd infrastructure/terraform
cp terraform.tfvars.example terraform.tfvars   # adjust; contains no secrets
# Uncomment the S3 backend block in main.tf and create the state bucket first.
terraform init
terraform plan
terraform apply        # 💸 EKS, NAT gateway, EC2 nodes, etc. — NOT run here
```

Outputs include the cluster name, ECR repo URLs, and the IRSA role ARN.

### 2. Inject secrets out-of-band (no secret ever in repo or state)

The Terraform creates **empty** Secrets Manager containers. Populate them
separately — values never live in code:

```bash
aws secretsmanager put-secret-value --secret-id edgar-x-prod/snowflake \
  --secret-string '{"account":"...","user":"...","private_key":"...","warehouse":"EDGAR_X_WH","database":"EDGAR_X","schema":"MARTS"}'
aws secretsmanager put-secret-value --secret-id edgar-x-prod/anthropic \
  --secret-string '{"api_key":"..."}'
```

### 3. Build & push images (💸 + requires the disabled CI job)

The `build-and-push-image` job in CI is disabled (`if: false`). Enabling it
requires an AWS OIDC role and the provisioned ECR registry from step 1, then it
builds the `agents` / `api` / `dashboard` / `jobs` images and pushes them.

### 4. Deploy workloads to the cluster

```bash
aws eks update-kubeconfig --name <cluster_name> --region us-east-1
# Replace <ACCOUNT_ID> placeholders in the manifests with the real account id.
# Provide the Secret via the AWS Secrets Store CSI driver (preferred, uses the
# IRSA role) or `kubectl create secret generic edgar-x-secrets -n edgar-x ...`.
kubectl apply -f infrastructure/kubernetes/   # NOT run here — no cluster exists
```

### 5. Monitoring

Install kube-prometheus-stack, load
[`infrastructure/monitoring/prometheus.yml`](../infrastructure/monitoring/prometheus.yml)
as the scrape config, and import
[`infrastructure/monitoring/grafana_dashboard.json`](../infrastructure/monitoring/grafana_dashboard.json).
**Honesty note:** the application metrics emitter
(`monitoring/prometheus/metrics.py`) is currently a placeholder, so the
dashboard panels (pipeline throughput, agent cost, model performance) define the
intended metric contract but will only render data once the services export
those series.

## Teardown

```bash
terraform destroy     # removes everything provisioned in step 1
```

---

Nothing in this guide has been executed against a cloud account. The deliverable
is reviewable, validated infrastructure as code — deployment-ready, not deployed.
