# HyperCore Cluster Balancer

**Reactive, Predictive & Affinity-Based Load Balancing for Scale Computing HyperCore**

The HyperCore Cluster Balancer is a containerized solution that automatically distributes virtual machine workloads across Scale Computing HyperCore cluster nodes. It monitors resource usage in real time, enforces VM placement rules, writes telemetry to InfluxDB, and can use predictive forecasting to prevent future overloads before they happen.

This fork is customized for deployments that already have **external InfluxDB** and **external Grafana** endpoints. The application stack runs only the balancer, collector, and built-in dashboard containers. InfluxDB and Grafana are not launched locally by this compose stack.

---

## Features

- **Reactive Balancing** — Continuously monitors node CPU and RAM usage via sliding-window averages. When a node exceeds configurable thresholds, a suitable VM can be live-migrated to a less-loaded node.
- **Predictive Balancing (The Oracle)** — Uses [Facebook Prophet](https://facebook.github.io/prophet/) to forecast per-VM CPU load 24 hours ahead. Predictive recommendations run in a background thread with parallel workers so the reactive engine is not blocked.
- **Forecast Export / Debugging** — Optional forecast CSV output can be written to `/models` for review and tuning. A debug mode can limit forecasting to a single VM.
- **Affinity Enforcement** — Highest-priority engine that enforces VM placement rules via HyperCore tags:
  - `node_<suffix>` — Pin a VM to a specific node, for example `node_241` pins to the node whose IP ends in `.241`
  - `anti_<vm_name>` — Prevent two VMs from sharing the same node, for example `anti_dc02` on `dc01`
- **Session-Based HyperCore Authentication** — Collector and balancer use cached HyperCore API session cookies instead of logging in repeatedly. Sessions refresh after a configurable interval, defaulting to 12 hours.
- **Live Configuration** — Tunable settings are stored in a shared SQLite database. After first startup, many settings can be changed through the dashboard UI without restarting containers.
- **Built-in Dashboard** — Web-based UI on port `5000` showing node/VM performance, drive health, VSD I/O, migration event log, modules, tools, and live configuration.
- **External Grafana Link** — The dashboard Tools tab can open an existing Grafana instance using `GRAFANA_URL` from `.env`.
- **Metrics Collection** — HyperCore telemetry is written to an external InfluxDB v2 instance.

---

## Architecture

```text
┌────────────┐       ┌──────────────────┐       ┌─────────────┐
│ Collector  │──────▶│ External InfluxDB │◀─────│ Dashboard   │
│ (30s poll) │       │ (metrics bucket)  │       │ (port 5000) │
└────────────┘       └─────────┬────────┘       └──────┬──────┘
                               │                       │
                               │                       ▼
                               │              External Grafana
                               │              via GRAFANA_URL
                               │
                         ┌─────▼───────┐
                         │  Balancer   │──────▶ HyperCore REST API
                         │ reactive +  │       cached session auth
                         │ predictive +│
                         │ affinity    │
                         └─────────────┘
```

| Container | Role |
|-----------|------|
| **Collector** | Polls the HyperCore REST API and writes telemetry to external InfluxDB |
| **Balancer** | Decision engine for affinity, reactive, and predictive balancing |
| **Dashboard** | Built-in web UI for monitoring, settings, modules, and Grafana launch link |
| **InfluxDB** | External service; not launched by this compose stack |
| **Grafana** | External service; not launched by this compose stack |

---

## Quick Start

```bash
git clone <repository-url> HyperCoreBalancer
cd HyperCoreBalancer

cp .env.template .env
# Edit .env:
# - Set HyperCore credentials
# - Set external InfluxDB connection values
# - Set GRAFANA_URL if using the dashboard Grafana button
# - Change all CHANGE_ME values

docker compose up --build -d
```

Check the active services:

```bash
docker compose config --services
```

Expected:

```text
balancer
collector
dashboard
```

The built-in dashboard is available at:

```text
http://localhost:5000
```

> **Important:** Start with `SC_DRY_RUN=true`. This logs balancing decisions without executing live migrations. Leave dry-run enabled until you have reviewed collector data, balancer logs, and predictive recommendations.

---

## Required External Services

### InfluxDB v2

Create or provide an existing InfluxDB v2 bucket.

Required `.env` values:

```env
INFLUX_URL=https://influxdb.example.org
INFLUX_TOKEN=CHANGE_ME
INFLUX_ORG=hypercore
INFLUX_BUCKET=metrics
```

The token must allow the collector and balancer to write metrics/events to the selected bucket. The dashboard needs read access to display data.

If the token does not have bucket-management permissions, the collector may warn that it cannot set retention. That is usually acceptable for externally managed InfluxDB deployments.

### Grafana

Grafana is expected to be externally hosted. Configure Grafana manually with an InfluxDB v2 Flux datasource pointing to the same InfluxDB bucket.

Required only for the dashboard Tools button:

```env
GRAFANA_URL=https://grafana.example.org
```

Grafana authentication, including SSO, remains handled by Grafana. A Grafana API token is not required for normal balancer operation unless you are automating datasource or dashboard provisioning.

---

## Configuration

All settings are defined in `.env` and seeded into a shared SQLite config database on first startup. After that, many tunables are read from the database and can be changed live through the dashboard.

> **Note:** If an existing deployment already has `/config` populated, changing `.env` defaults may not override values already stored in SQLite. Update settings through the dashboard or reset the config volume if intentionally reseeding.

### Key Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `SC_DRY_RUN` | `true` | Logs decisions without executing migrations |
| `SC_HOST` | `https://CHANGE_ME` | HyperCore cluster endpoint |
| `SC_VERIFY_SSL` | `false` | Whether to verify the HyperCore TLS certificate |
| `SC_SESSION_MAX_AGE_SECONDS` | `43200` | Cached HyperCore API session lifetime; default 12 hours |
| `INFLUX_URL` | `https://CHANGE_ME` | External InfluxDB URL |
| `INFLUX_BUCKET` | `metrics` | InfluxDB bucket for metrics and migration events |
| `GRAFANA_URL` | `https://CHANGE_ME` | External Grafana URL for dashboard Tools tab |
| `SC_CPU_UPPER_THRESHOLD_PERCENT` | `50.0` | Node CPU percentage that triggers reactive balancing |
| `SC_RAM_UPPER_THRESHOLD_PERCENT` | `65.0` | Node RAM percentage that triggers reactive balancing |
| `SC_RAM_LIMIT_PERCENT` | `85.0` | Hard RAM ceiling for target nodes |
| `SC_MAX_VCPU_RATIO` | `2.0` | Maximum vCPU-to-thread overcommit ratio |
| `SC_PREDICTIVE_BALANCING_ENABLED` | `true` | Enable or disable predictive balancing |
| `SC_PREDICTIVE_INTERVAL_SECONDS` | `43200` | How often the Oracle runs |
| `SC_PREDICTIVE_MAX_WORKERS` | `4` | Parallel forecast workers |
| `SC_EXCLUDE_NODE_IPS` | *(empty)* | Comma-separated node LAN IPs excluded from balancing |

---

## Session-Based HyperCore Authentication

Collector and balancer use cached HyperCore API session cookies.

Recommended compose configuration uses separate session files per service:

```yaml
collector:
  environment:
    - SC_SESSION_FILE=/config/session/collector_scale_session.p
    - SC_SESSION_MAX_AGE_SECONDS=${SC_SESSION_MAX_AGE_SECONDS}

balancer:
  environment:
    - SC_SESSION_FILE=/config/session/balancer_scale_session.p
    - SC_SESSION_MAX_AGE_SECONDS=${SC_SESSION_MAX_AGE_SECONDS}
```

The session helper will:

1. Reuse a valid cached session file.
2. Refresh the session when it is older than `SC_SESSION_MAX_AGE_SECONDS`.
3. Retry once with a new session if the HyperCore API returns `401` or `403`.

Check session files:

```bash
docker exec sc_collector ls -lh /config/session
docker exec sc_balancer ls -lh /config/session
```

---

## Predictive Engine / The Oracle

The predictive engine runs inside the balancer container. It queries historical VM CPU metrics from InfluxDB, fits Prophet models, and returns migration recommendations.

Important settings:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `SC_PREDICTIVE_BALANCING_ENABLED` | `true` | Master switch for predictive balancing |
| `SC_PREDICTIVE_INTERVAL_SECONDS` | `43200` | Forecast interval; default 12 hours |
| `SC_PREDICTIVE_THRESHOLD` | `80.0` | Predicted future CPU threshold for action |
| `SC_PREDICTIVE_MIN_HISTORY_HOURS` | `336` | Required history before forecasting a VM |
| `SC_PREDICTIVE_LOOKBACK_DAYS` | `90` | Historical lookback queried from InfluxDB |
| `SC_PREDICTIVE_MAX_WORKERS` | `4` | Parallel VM forecast workers |
| `SC_PREDICTIVE_LEAD_TIME_HOURS` | `1` | Execute recommendation before predicted peak |
| `SC_PREDICTIVE_RESERVATION_MINUTES` | `5` | Reserve source node after predicted peak |
| `SC_PREDICTIVE_JITTER_PERCENT` | `0.1` | Optional random delay added to interval |

### Forecast Export

Forecast CSV export can be enabled for troubleshooting and model tuning:

```env
SC_PREDICTIVE_MODEL_CACHE_DIR=/models
SC_PREDICTIVE_SAVE_FORECASTS=true
SC_PREDICTIVE_DEBUG_VM_NAME=
```

The balancer service should mount:

```yaml
volumes:
  - sc-config:/config
  - sc-model-cache:/models
```

Forecast files can be inspected with:

```bash
docker exec sc_balancer ls -lh /models
```

To export them:

```bash
docker cp sc_balancer:/models ./models-export
```

To forecast a single VM for testing, set:

```env
SC_PREDICTIVE_DEBUG_VM_NAME=Exact VM Name
```

Leave it blank to forecast all eligible VMs.

---

## VM Placement Tags

Placement rules are defined as tags on VMs in HyperCore.

| Tag Format | Effect | Example |
|------------|--------|---------|
| `node_<suffix>` | Pin VM to the node whose LAN IP ends with `<suffix>` | `node_241` |
| `anti_<vm_name>` | Prevent this VM from sharing a node with another named VM | `anti_dc02` |

Affinity enforcement has the highest priority. It can bypass normal balancing cooldowns to correct placement violations.

---

## Grafana Dashboard Button

The built-in dashboard Modules/Tools tab includes an **Open Grafana** button. It is driven by:

```env
GRAFANA_URL=https://grafana.example.org
```

The dashboard container must receive this environment variable:

```yaml
dashboard:
  environment:
    - GRAFANA_URL=${GRAFANA_URL}
```

Test the dashboard API:

```bash
curl -u "$SC_DASHBOARD_USER:$SC_DASHBOARD_PASSWORD" \
  http://localhost:5000/api/tools/grafana
```

Expected response:

```json
{
  "enabled": true,
  "url": "https://grafana.example.org",
  "status": "External",
  "message": "Grafana is configured externally."
}
```

---

## Common Operations

### Start the stack

```bash
docker compose up --build -d
```

### Rebuild one service

```bash
docker compose up --build -d dashboard
docker compose up --build -d collector
docker compose up --build -d balancer
```

### Force recreate a service

```bash
docker compose rm -sf dashboard
docker compose up --build -d dashboard
```

### View logs

```bash
docker compose logs -f collector balancer dashboard
```

### Check running services

```bash
docker compose ps
```

### Verify service environment

```bash
docker exec sc_dashboard printenv | grep GRAFANA
docker exec sc_collector printenv | grep SC_SESSION
docker exec sc_balancer printenv | grep SC_SESSION
```

### Test HyperCore session auth from a container

```bash
docker exec -it sc_collector python - <<'PY'
import os
import scale_session

host = os.getenv("SC_HOST", "").rstrip("/")
if not host.endswith("/rest/v1"):
    host = f"{host}/rest/v1"

r = scale_session.get(f"{host}/Node")
print("HTTP", r.status_code)
print(r.text[:300])
PY
```

---

## Troubleshooting

### `ModuleNotFoundError: No module named 'scale_session'`

The file was not copied into the container image.

Make sure both files exist:

```text
Collector/scale_session.py
Balancer/scale_session.py
```

If the Dockerfiles copy individual files, add:

```dockerfile
COPY scale_session.py .
```

Then rebuild without cache:

```bash
docker compose build --no-cache collector balancer
docker compose up -d collector balancer
```

### Dashboard still says `Set GRAFANA_URL in .env`

Check that the dashboard container has the variable:

```bash
docker exec sc_dashboard printenv | grep GRAFANA
```

If empty, add this under `dashboard.environment` in `docker-compose.yaml`:

```yaml
- GRAFANA_URL=${GRAFANA_URL}
```

Then recreate:

```bash
docker compose rm -sf dashboard
docker compose up --build -d dashboard
```

### Docker Compose warns that a variable is not set

If a password or token contains `$`, wrap it in single quotes in `.env`:

```env
INFLUX_TOKEN='token$with$dollar'
SC_PASSWORD='password$with$dollar'
```

### Collector warns about InfluxDB retention

For external InfluxDB, the token may not have permission to update bucket retention. This is acceptable if retention is managed externally.

---

## Dark-Site / Air-Gapped Deployment

Build on an internet-connected machine:

```bash
docker compose build
docker save $(docker compose config --images) -o hypercore-balancer-images.tar
```

Transfer the tarball to the air-gapped machine, then:

```bash
docker load -i hypercore-balancer-images.tar
docker compose up -d
```

The runtime machine still needs network access to:

- HyperCore REST API
- External InfluxDB
- External Grafana, if using the dashboard button

---

## Resource Requirements

| VMs | Min. vCPUs | Recommended RAM | Approx. Metrics Disk |
|-----|------------|-----------------|----------------------|
| 5   | 2          | 1 GB            | 2 GB                 |
| 50  | 2          | 1 GB            | 12 GB                |
| 100 | 2          | 2 GB            | 23 GB                |
| 500 | 4          | 4 GB            | 112 GB               |

The balancer’s memory and CPU usage peak during predictive forecasting. Lower `SC_PREDICTIVE_MAX_WORKERS` if the host is resource constrained.

---

## Project Structure

```text
├── docker-compose.yaml
├── .env.template
├── .gitignore
├── Collector/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── config_db.py
│   ├── scale_session.py       # Cached HyperCore session helper
│   └── collector.py
├── Balancer/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── config_db.py
│   ├── scale_session.py       # Cached HyperCore session helper
│   ├── HyperCore_balancer.py  # Main decision engine
│   └── predictive_engine.py   # Prophet forecasting engine
└── dashboard/
    ├── Dockerfile
    ├── requirements.txt
    ├── config_db.py
    ├── app.py                 # Flask API
    └── static/
        └── index.html         # Single-page dashboard
```

---

## Documentation

The complete installation, configuration, and operations manual is available as a Word document:

[HyperCore Cluster Balancer Manual v2.0](HyperCore_Cluster_Balancer_Manual_v2.docx)

---

## Disclaimer

**USE AT YOUR OWN RISK.** This project can initiate live VM migrations when dry-run mode is disabled. Validate behavior carefully in dry-run mode before enabling live actions. The software is provided "as is" without warranty of any kind, express or implied.

---

## License

MIT License

Copyright (c) 2026 Scale Computing, Inc.

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
