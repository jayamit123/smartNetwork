# An Endpoint-Based Low-Overhead Framework for Detecting and Remediating Intermittent Internet Connectivity Degradation

The historical sections below document the original desktop implementation
and its development phases. The default entry point (`python app.py`) runs
the web application; the Tkinter version remains available via
`python desktop_app.py`.

## Web application

The project now has a browser-based dashboard backed by the existing Python
monitoring and diagnosis modules. The FastAPI service exposes network status,
monitoring controls, measurement history, and diagnosis endpoints. The React
dashboard polls the service for live metrics and displays session history.
SQLite remains the default local database; set `NETWORK_DIAGNOSIS_DB_PATH` to
use a different SQLite file. PostgreSQL is not configured yet.
Monitoring and dashboard refresh default to once per second. Diagnosis uses
a six-measurement analysis window, so its first full-window assessment needs
about six seconds of monitoring data; this is the diagnosis warm-up window,
not the measurement interval. Gateway, internet, DNS and HTTP probes run in
parallel, with one ping per host and short request timeouts by default.
Jitter is derived from the absolute change between successive successful
internet latency measurements (the first reading has no jitter value), so it
remains measurable with one ping per monitoring cycle.
Network timeouts can still cause measurements to take longer than one second.
Restart the API after changing monitoring settings so the new values are
loaded.

### Run locally on Windows

1. Install the Python dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

2. Start the API from the repository root:

   ```powershell
   python app.py
   ```

3. In a second terminal, install and start the React development server:

   ```powershell
   cd frontend
   npm install
   npm run dev
   ```

4. Open `http://127.0.0.1:5173`. The Vite development server forwards `/api`
   requests to FastAPI at `http://127.0.0.1:8000`.

For a production-style single server, build the React application with
`cd frontend; npm run build`, then run `python app.py`.
FastAPI serves the built frontend when `frontend/dist` exists. The API docs
are available at `http://127.0.0.1:8000/docs`.

The API can use a custom SQLite database path by setting
`$env:NETWORK_DIAGNOSIS_DB_PATH = "C:\path\to\network.db"` before launching
Uvicorn. DNS-cache remediation is the only automated action and is off by
default. The Diagnosis page can enable it with explicit confirmation; it runs
only after three consecutive DNS failures while external internet and HTTP
checks remain healthy. Manual execution also requires confirmation. Both
modes flush only the Windows DNS cache (no DNS settings or adapter resets),
record an audit entry, and evaluate the next three measurements for recovery.
The action applies to the computer running the API. The preference resets to
off when the API process restarts.

### Web application endpoints

- `GET /api/health`, `/api/network`, `/api/status`
- `POST /api/monitor/start`, `/api/monitor/stop`
- `GET /api/measurements`, `/api/sessions`, `/api/sessions/{session_id}`
- `GET /api/sessions/{session_id}/export.csv` downloads a session's measurements.
- `DELETE /api/sessions` clears all saved session history; monitoring must be stopped.
- `GET /api/diagnosis`
- `POST /api/chat/remediation` requests safe, step-by-step remediation advice from Gemini.
- `GET/POST /api/remediation/settings` inspect or explicitly enable/disable opt-in DNS automation.
- `POST /api/remediation/flush-dns` manually flushes DNS after three isolated consecutive DNS failures.
- `GET /api/report.pdf` downloads a formatted PDF with diagnosis, measurement, remediation, and verification data.

**Full title:** An Endpoint-Based Low-Overhead Framework for Detecting and Remediating
Intermittent Internet Connectivity Degradation

> This README is a living document. It is expanded at the end of every
> development phase so that, once Phase 7 is complete, it contains all
> sections required by the project specification (abstract, methodology,
> algorithms, database design, testing procedure, performance metrics,
> limitations, future work, references, etc.). It currently documents
> **Phases 1, 2 and 3**.

---

## 1. Abstract

Most consumer-facing network diagnostic tools report a single point-in-time
measurement ("ping succeeded", "speed test result") and most academic
approaches focus on one diagnostic dimension in isolation (latency
monitoring, or DNS testing, or packet-loss measurement) rather than
combining them. Intermittent connectivity degradation â€” brief periods of
high latency, packet loss or DNS slowness that come and go â€” is
particularly hard to notice and diagnose this way, because a single
snapshot measurement can look perfectly normal moments before or after the
problem occurs.

This project implements an endpoint-based framework that continuously,
and cheaply, watches multiple network-health parameters over time,
statistically distinguishes a true intermittent-degradation *event* from
normal jitter, correlates several parameters together to classify a
**probable fault category**, automatically remediates the fault when (and
only when) it is something the local machine can safely fix, and then
objectively verifies whether the remediation actually worked by
re-measuring the network â€” rather than assuming success just because a
Windows command exited without error.

## 2. Problem Statement

Home and small-office users frequently experience "the internet is slow"
or "it keeps cutting out" problems that are transient and hard to
reproduce for a technician or ISP support call. Existing tools either:

- give a single instantaneous reading (ping once, run one speed test), or
- monitor continuously but only one parameter (e.g. an uptime pinger), or
- require specialized/expensive hardware taps on the network path.

None of them combine continuous low-overhead observation, temporal
pattern detection, multi-parameter correlation, safe local remediation
and post-remediation verification into a single endpoint-only tool.

## 3. Existing Systems

- **One-shot diagnostic tools** (`ping`, `tracert`, online speed-test
  sites): give a snapshot, not a history; cannot detect intermittent
  problems that are not occurring at the exact moment the tool is run.
- **Uptime/latency monitors** (e.g. simple ping-loggers): continuous, but
  single-parameter, and generally do not attempt fault classification or
  remediation.
- **ISP-side / router-side diagnostics**: not available to an ordinary
  end-user endpoint application, and cannot be relied upon.

## 4. Existing System Limitations

- No temporal reasoning â€” a single failed ping is treated the same as a
  sustained outage.
- No correlation across gateway / DNS / internet / HTTP layers, so the
  probable location of the fault (local vs. ISP vs. destination) is not
  identified.
- No automatic, safe, verified remediation step.
- No explicit distinction between "probable fault category" (what an
  endpoint can actually infer) and "exact root cause" (which requires
  visibility the endpoint does not have).

## 5. Research Gap

Combine, in one lightweight endpoint tool:

1. Continuous low-overhead monitoring
2. Temporal detection of intermittent degradation
3. Multi-parameter correlation
4. Probable fault classification
5. Separation of local vs. external faults
6. Automatic remediation of supported local faults
7. Post-remediation verification

## 6. Proposed System

A Windows desktop application (Python + Tkinter + SQLite) that follows the
pipeline:

```
OBSERVE -> DETECT -> CORRELATE -> LOCALIZE -> REMEDIATE -> RE-TEST -> VERIFY
```

It reports a **probable fault category** (never an unsupported "exact
root cause" claim), and only attempts remediation for problems that are
genuinely controllable from the local machine (DNS cache, DHCP lease,
local adapter). Everything else is reported to the user as
non-locally-fixable, with evidence.

## 7. Objectives

1. Detect the real, current network configuration automatically (no
   hardcoded IPs).
2. Continuously collect lightweight connectivity measurements without
   perceptible system overhead.
3. Distinguish genuine intermittent-degradation events from normal noise
   using temporal analysis over a configurable baseline.
4. Correlate gateway / internet / DNS / HTTP measurements to classify a
   probable fault category using explainable, rule-based logic (no ML).
5. Automatically remediate only safe, reversible, locally-controllable
   faults, with clear user visibility into what will be executed.
6. Verify remediation objectively by comparing before/after measurements
   against the same thresholds used for detection.
7. Persist full session history (measurements, events, diagnoses,
   remediation actions, verification results) for later review and
   reporting.

## 8. Architecture (current â€” Phases 1-3)

```
smart-network-diagnosis/
â”œâ”€â”€ app.py                        # Entry point; builds the Tk window
â”œâ”€â”€ requirements.txt
â”œâ”€â”€ README.md
â”œâ”€â”€ config/
â”‚   â””â”€â”€ settings.json             # monitoring_interval, ping counts, targets, timeouts
â”œâ”€â”€ data/
â”‚   â””â”€â”€ network_monitor.db        # Created on first run (not committed)
â”œâ”€â”€ logs/
â”‚   â””â”€â”€ application.log           # Created on first run (not committed)
â”œâ”€â”€ monitoring/
â”‚   â”œâ”€â”€ interface_monitor.py      # Wraps network_utils for the GUI (Phase 1)
â”‚   â”œâ”€â”€ latency_monitor.py        # Cross-platform ping runner (Phase 2)
â”‚   â”œâ”€â”€ gateway_monitor.py        # Gateway reachability + avg/min/max latency (Phase 2)
â”‚   â”œâ”€â”€ internet_monitor.py       # Internet reachability + avg/min/max latency (Phase 2)
â”‚   â”œâ”€â”€ packet_loss_monitor.py    # Packet-loss % calculation (Phase 2)
â”‚   â”œâ”€â”€ jitter_monitor.py         # Jitter calculation (Phase 2)
â”‚   â”œâ”€â”€ dns_monitor.py            # DNS availability + response time (Phase 2)
â”‚   â”œâ”€â”€ http_monitor.py           # HTTP/HTTPS reachability + response time (Phase 2)
â”‚   â””â”€â”€ monitor_controller.py     # Background thread orchestrating every round
â”‚                                  # + persisting each round (Phase 2 + Phase 3)
â”œâ”€â”€ database/
â”‚   â””â”€â”€ database.py               # SQLite schema + thread-safe CRUD helpers (Phase 3)
â”œâ”€â”€ gui/
â”‚   â”œâ”€â”€ dashboard.py               # Main window: config panel, controls, live metrics,
â”‚   â”‚                                inline history table, Records Stored counter
â”‚   â”œâ”€â”€ monitoring_view.py         # Live Monitoring page: table + 4 graphs (Phase 2)
â”‚   â””â”€â”€ history_view.py            # Monitoring History page (Phase 3)
â””â”€â”€ utils/
    â”œâ”€â”€ logger.py                  # Centralized logging -> logs/application.log
    â”œâ”€â”€ config_loader.py           # Safe settings.json load/save with defaults
    â””â”€â”€ network_utils.py           # Interface/IPv4/netmask/gateway/DNS/MAC/status detection
```

Later phases add: `analysis/` (baseline, temporal detector, correlation
engine, fault classifier), `remediation/`, `verification/`, the remaining
`gui/*_view.py` pages (diagnosis, remediation, verification, settings),
and `tests/`.

## 9. Methodology

### Phase 1

`utils/network_utils.py` auto-detects, at run time:

- **Gateway + active interface name** â€” on Windows by parsing
  `ipconfig /all`; on Linux/macOS (used here for development/testing) by
  parsing `ip route show default`, falling back to reading
  `/proc/net/route` directly if the `ip` binary is unavailable.
- **IPv4 address / netmask / MAC address / adapter up-down status** â€”
  via `psutil`, keyed off the interface name found above.
- **DNS servers** â€” on Windows by parsing `ipconfig /all`; on Linux/macOS
  by reading `/etc/resolv.conf`.
- **Connection type** (Wi-Fi / Ethernet / VPN / Unknown) â€” heuristically
  guessed from the interface name.

Every detection function is defensive: on any failure (adapter down, no
gateway, command missing, permission denied) it returns `None` /
`"Unknown"` instead of raising, so the GUI always has something sensible
to display and never crashes.

`gui/dashboard.py` displays this snapshot and refreshes it automatically
on a timer (`network_info_refresh_seconds` in `config/settings.json`,
default 5s) as well as on demand via a "Refresh Network Info" button.

### Phase 2 â€” Continuous Network Monitoring

`monitoring/monitor_controller.py` runs entirely on a background
`threading.Thread` (`daemon=True`) so the GUI is never blocked. Every
`monitoring_interval` seconds (configurable in `config/settings.json`,
default 5) it performs one "round":

1. **Interface re-snapshot** (`interface_monitor.py`) â€” cheap, no
   network traffic, so a Wi-Fi roam / adapter change is picked up.
2. **Gateway check** (`gateway_monitor.py`) â€” `gateway_ping_count`
   ICMP packets (default 3) to the auto-detected gateway in one
   subprocess call, yielding average/min/max latency and packet loss.
3. **Internet check** (`internet_monitor.py`) â€” `internet_ping_count`
   ICMP packets (default 3) to a configurable host (`internet_host`,
   default `8.8.8.8`), again in **one** subprocess call. From that same
   round we derive:
   - average/min/max latency (`latency_monitor.py`)
   - packet loss % (`packet_loss_monitor.py`: `lost / sent * 100`)
   - **jitter** (`jitter_monitor.py`): the mean of the absolute
     differences between consecutive successful round-trip-time samples
     â€” e.g. for samples `[10, 15, 12, 20]` the differences are
     `[5, 3, 8]`, averaging to `5.33 ms`. This is a deliberately simple,
     explainable method (no RFC 3550 smoothing/EWMA), exactly as
     specified. `jitter_ms` is `None`/SQL `NULL` whenever fewer than two
     packets came back, since jitter cannot be computed from 0 or 1
     samples.
4. **DNS check** (`dns_monitor.py`) â€” resolves `dns_test_domain`
   (default `google.com`) through the operating system resolver in a
   time-limited subprocess, returning success/failure, response time and
   the resolved IP.
5. **HTTP/HTTPS check** (`http_monitor.py`) â€” a streamed GET (capped at
   2 KB read, so no large downloads) of `http_test_url`
   (default `https://www.google.com`) with `http_timeout`, returning the
   status code, response time and success/failure.

All five results are combined into one `MeasurementRecord` (field names
matching the project's required `MonitoringResult` exactly), plus a
simple, explainable `overall_status` roll-up (`NORMAL` / `DEGRADED` /
`DISCONNECTED`) used only for the live dashboard headline â€” **this is
not fault classification**; it never names a probable cause, and that
logic is explicitly deferred to Phase 5.

**Fault isolation per measurement**: each of the four checks runs
independently and catches its own exceptions. If the gateway ping fails,
the internet/DNS/HTTP checks still run; if DNS fails, HTTP still runs.
Every numeric field that could not be measured is stored as `None`
(SQLite `NULL`) â€” never a placeholder string like `"error"` or `"N/A"`.
The round always produces exactly one complete database record.

**Thread-safety**: the controller never calls into Tkinter directly.
Each `MeasurementRecord` is placed on a `queue.Queue`; `gui/dashboard.py`
drains that queue on a normal Tkinter `after()` timer (every 500ms) and
is the only place that touches widgets with the results.

**Low-overhead design**: both the gateway and internet checks batch all
their ICMP packets into one subprocess call instead of spawning one
process per metric; the HTTP check reads at most 2 KB of the response
body; every ping/DNS/HTTP call has its own configurable timeout so a
single bad measurement can never hang the thread; no packet capture,
network scanning or large downloads are ever performed. Each
measurement's approximate on-wire byte cost (`bytes_used`) is tracked
and summed per session, supporting the project's
*Measurement Overhead = bytes / duration* metric in a later phase.

### Phase 3 â€” Data Storage and Logging

`database/database.py` wraps a single SQLite file at
**`data/network_monitor.db`** (the `data/` folder is created
automatically if missing) with six tables. Phase 3 actively writes to:

- **`network_measurements`** â€” one self-contained row per monitoring
  cycle: timestamp, interface/IPv4, gateway + reachability + avg/min/max
  latency + packet loss, internet host + reachability + avg/min/max
  latency + packet loss, jitter, DNS domain + success + response time +
  resolved IP, HTTP URL + status code + response time, plus
  `overall_status`, `bytes_used` and an optional `session_id`.
  Booleans are stored as SQLite's `0`/`1` convention
  (`gateway_reachable`, `internet_reachable`, `dns_success`).
- **`monitoring_sessions`** â€” one row per Start/Stop cycle (optional
  grouping used by the GUI's history/live-monitoring windows): start
  time, end time, the interface/IPv4/gateway in effect when monitoring
  began, a running `measurement_count` and `overhead_bytes_total`, and a
  `final_status` (`IN_PROGRESS` â†’ `COMPLETED`, or `INTERRUPTED` if the
  app window is closed mid-session).

`detected_events`, `diagnoses`, `remediation_actions` and
`verification_results` are created now with their full intended schema
(so Phases 4-7 need no migration step) but are **not written to yet** â€”
no fabricated rows are inserted into them.

The database module exposes exactly the functions the spec asks for â€”
`initialize_database()`, `insert_measurement(result)`,
`get_recent_measurements(limit=100)`,
`get_measurements(start_time=None, end_time=None)` and
`get_measurement_count()` â€” as well as the extra session-scoped helpers
(`create_session`, `end_session`, `get_sessions`,
`get_session_measurements`) the GUI's history/live-monitoring windows
use. All SQL is parameterized (`?` placeholders) â€” no string
concatenation is used to build queries.

The database uses one shared `sqlite3` connection
(`check_same_thread=False`) guarded by a single `threading.Lock`, since
the monitoring thread writes while the GUI thread reads concurrently.
Tables are created with `CREATE TABLE IF NOT EXISTS`, and the database is
**never reset** on startup â€” all historical data survives an application
restart.

`utils/logger.py` writes to `logs/application.log` (rotated at 2 MB,
3 backups) as well as the console, logging every event the spec
requires: application start, database initialization, monitoring
started/stopped, each measurement collected/stored, and every
gateway/DNS/HTTP failure â€” at `INFO` for normal lifecycle events and
`WARNING`/`ERROR` for failures, so one failed test is visible in the log
without ever stopping the monitoring cycle.

`gui/dashboard.py` shows an inline "Monitoring History (latest)" table
(capped at the most recent 50 rows) and a live **Records Stored** count
read directly from `get_measurement_count()` on every cycle â€” never
faked. `gui/history_view.py` additionally implements the full session
history page (`Session ID | Start Time | End Time | Events | Final
Status`) with a double-click drill-down into that session's raw
measurements. `gui/monitoring_view.py` implements the Live Monitoring
page: a live table plus four graphs (Latency, Packet Loss, Jitter, DNS
Response Time â€” all vs. time), each capped to the most recent 60 points.

## 10. Seven Development Phases

1. **System setup and network information** *(this phase)*
2. Continuous network monitoring (background thread, no GUI blocking)
3. Data storage and logging (SQLite)
4. Temporal analysis and fault detection
5. Multi-parameter correlation and fault classification
6. Automatic remediation
7. Post-remediation verification

## 11. Tools and Technologies

Python 3.12+, Tkinter, SQLite (`sqlite3`), `psutil` (Phase 1);
`subprocess` (system `ping`), `requests`, `matplotlib`,
`threading` + `queue` for the non-blocking background monitor (Phase 2);
`sqlite3` + `threading.Lock` + `logging` for storage and logging
(Phase 3). Latency averages and jitter use plain Python arithmetic
(`sum`/`len`, absolute differences) rather than the `statistics` module,
since the calculations required at this stage are simple enough not to
need it â€” this is called out explicitly since `statistics` was a
suggested (not mandatory) library.

## 12. Algorithms

Documented as they are introduced: temporal event detection (Phase 4),
rule-based fault classification (Phase 5), remediation decision logic
(Phase 6), verification comparison logic (Phase 7).

## 13. Fault Categories

| Code | Meaning |
|------|---------|
| F0 | Normal |
| F1 | Local Endpoint / Configuration Fault |
| F2 | DNS Fault |
| F3 | Gateway / Local Network Fault |
| F4 | Upstream Internet / ISP Fault |
| F5 | Path Performance Degradation |
| F6 | Destination / Service-Specific Fault |

(Classification logic itself is implemented starting Phase 5. **No
measurement is labelled with any of these categories yet** -- Phases 2
and 3 only measure, timestamp, store and display; they never conclude
"ISP problem", "router problem" or "DNS problem" from a single reading.)

## 14â€“17. Remediation / Verification / Database Design (partial)

**Database design** (Phase 3, current):

| Table | Populated since | Key columns |
|---|---|---|
| `network_measurements` | Phase 3 | id (PK), timestamp, interface_name, ipv4_address, gateway_ip, gateway_reachable, gateway_latency_ms (+min/max), gateway_packet_loss, internet_host, internet_reachable, internet_latency_ms (+min/max), internet_packet_loss, jitter_ms, dns_domain, dns_success, dns_response_time_ms, dns_resolved_ip, http_url, http_status_code, http_response_time_ms, overall_status, bytes_used, session_id (FK, nullable) |
| `monitoring_sessions` | Phase 3 | session_id (PK), start_time, end_time, interface_name, ipv4_address, gateway_ip, measurement_count, overhead_bytes_total, final_status |
| `detected_events` | Phase 4 (schema only so far) | event_id, session_id, start_time, end_time, duration_seconds, affected_parameters, severity, evidence |
| `diagnoses` | Phase 5 (schema only so far) | diagnosis_id, session_id, event_id, fault_category, evidence, recommended_action |
| `remediation_actions` | Phase 6 (schema only so far) | remediation_id, session_id, diagnosis_id, action_name, command, requires_admin, result |
| `verification_results` | Phase 7 (schema only so far) | verification_id, session_id, remediation_id, metric, before_value, after_value, result |

`network_measurements` is the primary, self-contained record of every
monitoring cycle (matches the project's required schema exactly, plus a
few harmless extras: `overall_status`, `bytes_used`, `session_id`).
`monitoring_sessions` is an optional grouping used only by the GUI's
"View History" / "View Live Monitoring" windows so one Startâ†’Stop run
can be viewed on its own; every measurement is fully valid and readable
even without a session (`session_id` is nullable).

Remediation and verification process descriptions will be added once
Phases 6 and 7 are implemented.

## 18. Installation

Requires Python 3.12+ on Windows 10/11 (Tkinter and sqlite3 ship with the
standard Python installer; no extra install needed for them).

```bat
py -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## 19. How to Run

```bat
python app.py
```

This opens the Smart Network Diagnosis System window, showing:

- The **Network Configuration** panel (interface, IPv4, netmask, MAC,
  gateway, DNS), auto-refreshing every few seconds (Phase 1).
- **START MONITORING** / **STOP MONITORING** buttons and a **Live
  Network Metrics** panel that updates every monitoring cycle (Phase 2).
- An inline **Monitoring History** table (latest rows) and a
  **Records Stored** counter read live from SQLite (Phase 3), plus
  **View Live Monitoring** (live table + 4 graphs) and **View History**
  (full session list with per-measurement drill-down) windows for a
  closer look.

**Database file:** `data/network_monitor.db` (created automatically on
first run; the `data/` folder is created if missing).

**Log file:** `logs/application.log` (created automatically; rotated at
2 MB, 3 backups kept).

## 20. Testing Procedure

Formal controlled fault-classification scenarios (S1â€“S8) are introduced
starting Phase 4/5, once fault detection and classification exist. For
Phases 1â€“3, manual verification is:

1. Run `python app.py` while connected to a working network â†’ Interface,
   IPv4, Gateway and DNS should all show real, non-empty values and
   Status should read `CONNECTED`.
2. Disable the network adapter â†’ Status should change to `DISCONNECTED`
   / gateway and IPv4 should show "Not detected" / "Not assigned" rather
   than crashing the app.
3. **Test 1 (normal network):** click **START MONITORING**. Within one
   `monitoring_interval`, the Live Network Metrics panel, the inline
   history table and **Records Stored** counter should all update, and
   `data/network_monitor.db` should contain a new `network_measurements`
   row (verify with `python -m database.database` or any SQLite browser).
4. **Test 2 (stop monitoring):** click **STOP MONITORING** â†’ monitoring
   stops, the GUI stays responsive, and the application remains open.
5. **Test 3 (restart persistence):** close and reopen the application â†’
   the **Records Stored** counter and **View History** must still show
   every previously recorded session/measurement; the database is never
   reset on startup (`CREATE TABLE IF NOT EXISTS` only).
6. **Test 4 (DNS failure):** block/point DNS at an unreachable resolver,
   or use a domain that cannot resolve â†’ `DNS` should show `FAILED`
   (`dns_success = 0`, `dns_response_time_ms = NULL`), while monitoring
   continues and a database record is still created for that cycle.
7. **Test 5 (internet failure):** disable internet access (keep the
   gateway reachable) â†’ `Internet` should show `FAILED`
   (`internet_reachable = 0`, `internet_latency_ms = NULL`,
   `internet_packet_loss = 100.0`), the application must not crash, the
   gateway check should still run and typically still PASS, and DNS/HTTP
   should fail gracefully rather than hang (each has its own timeout).
8. Each of `monitoring/gateway_monitor.py`, `internet_monitor.py`,
   `dns_monitor.py`, `http_monitor.py`, `latency_monitor.py`,
   `packet_loss_monitor.py`, `jitter_monitor.py`, `monitor_controller.py`
   and `database/database.py` can be run standalone
   (`python -m monitoring.dns_monitor`, etc.) for an isolated,
   console-only check of that module's logic.

## 21. Performance Metrics

Detection accuracy, classification accuracy, remediation success rate,
verification success and recovery time are all computed starting Phase
4 onward, once there is monitoring data and event detection to compute
them from. **Measurement overhead** (`bytes generated / duration`) is
already tracked per measurement (`network_measurements.bytes_used`,
a conservative estimate of ICMP + DNS + HTTP bytes for that cycle) and
per session (`monitoring_sessions.overhead_bytes_total`), ready for this
calculation once a full session is available to divide by its elapsed
duration. No fabricated numbers are included anywhere in this project.

## 22. Limitations

- Phases 2â€“3 only **measure, timestamp and store** -- they never label a
  measurement as an "ISP problem", "router problem" or "DNS problem"
  from a single reading; that requires the temporal/correlation logic of
  Phases 4â€“5.
- The system cannot guarantee identification of the exact remote physical
  device causing a fault; a future **probable fault category** will be
  based only on endpoint-observable evidence.
- ICMP (ping) can be filtered, rate-limited or deprioritized by
  routers/ISPs, which can bias latency/packet-loss readings.
- DNS results can be affected by local caching and resolver
  configuration, independent of actual DNS server health.
- Automatic remediation is limited to opt-in Windows DNS-cache flushing
  after three consecutive isolated DNS failures, followed by three-check
  verification. It cannot fix ISP, router, or destination-side problems.
- Thresholds/intervals/targets (`monitoring_interval`,
  `gateway_ping_count`, `internet_ping_count`, `internet_host`,
  `dns_test_domain`, `http_test_url`, `http_timeout`, `warning_thresholds`)
  are defaults and may need calibration for a given network; they are
  fully configurable in `config/settings.json` rather than hardcoded,
  specifically to allow this calibration.

## 23. Future Work

- Add PostgreSQL support for multi-user deployments.
- Add authentication and role-based access before exposing the service
  beyond a trusted local network.
- Add automated browser tests and deployment packaging.

## 24. References

To be compiled from networking/diagnostics literature during the final
write-up phase.

---

## How Phase 2 connects to Phase 3

Phase 2's `MonitorController` (`monitoring/monitor_controller.py`) is the
only thing that produces data; Phase 3's `Database`
(`database/database.py`) is the only thing that persists it. They are
connected at exactly one point: at the end of every monitoring round,
`MonitorController._run()` builds one `MeasurementRecord` and immediately
calls `self._database.insert_measurement(record, session_id=self.session_id)`
before doing anything else with it (including before handing it to the
GUI via the update queue). This means:

- **Every** measurement that Phase 2 collects is durably stored before
  the GUI ever sees it -- if the app crashes right after a round, the
  round is already in `data/network_monitor.db`.
- Storage failures are isolated the same way measurement failures are:
  if `insert_measurement()` returns `False` (disk full, DB locked, etc.)
  the round is still pushed to the GUI and monitoring continues; only an
  ERROR is logged, the whole cycle does not abort.
- Phase 3's session bookkeeping (`create_session()` / `end_session()`)
  brackets Phase 2's thread lifetime exactly: `start()` creates the
  session row (and monitoring only begins if that succeeds), and
  `stop()` marks it `COMPLETED` right after the background thread has
  actually joined.
- Everything Phase 4 (temporal analysis) will need is already sitting in
  `network_measurements`, keyed by `timestamp`, ready to be read back
  with `get_measurements(start_time, end_time)` or
  `get_recent_measurements(limit)` -- no schema changes will be required
  to start Phase 4.

## Current Status

The web application is the current user interface. FastAPI exposes the
existing network monitoring, SQLite history, temporal analysis, fault
correlation, and recommendation logic to a React dashboard. The browser
shows live status, measurements, probable diagnoses, safe recommendations,
and session history. Remediation steps are advisory and never executed by
the web application. PostgreSQL support and production authentication remain
future work.
