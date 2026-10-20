import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  Cable,
  Check,
  ChevronRight,
  CircleHelp,
  CircleDot,
  Clock3,
  Download,
  FileSearch,
  Gauge,
  Globe2,
  History,
  LayoutDashboard,
  LoaderCircle,
  Network,
  Play,
  RefreshCw,
  Router,
  ShieldCheck,
  Signal,
  Square,
  Trash2,
  Wifi,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";

type Measurement = {
  id: number;
  timestamp: string;
  overall_status: string;
  gateway_latency_ms: number | null;
  gateway_packet_loss: number | null;
  internet_latency_ms: number | null;
  internet_packet_loss: number | null;
  jitter_ms: number | null;
  dns_response_time_ms: number | null;
  http_response_time_ms: number | null;
  http_status_code: number | null;
  gateway_reachable: number | null;
  internet_reachable: number | null;
  dns_success: number | null;
  interface_name: string | null;
  ipv4_address: string | null;
};

type NetworkInfo = {
  interface: string | null;
  connection_type: string | null;
  status: string;
  ipv4: string | null;
  gateway: string | null;
  dns_servers: string[];
};

type Session = {
  session_id: number;
  start_time: string;
  end_time: string | null;
  measurement_count: number;
  final_status: string;
  event_count: number;
  interface_name: string | null;
  ipv4_address: string | null;
};

type SessionDetail = {
  session: Session;
  measurements: Measurement[];
  events: Record<string, unknown>[];
  diagnoses: Record<string, unknown>[];
  remediation_actions: Record<string, unknown>[];
  verification_results: Record<string, unknown>[];
};

type RemediationStatus = {
  automatic_dns_enabled: boolean;
  automatic_dns_supported: boolean;
  eligible: boolean;
  eligibility_reason: string;
  consecutive_dns_failures: number;
  latest_action: { action_name: string; executed_at: string | null; result: string | null } | null;
  latest_verification: { metric: string; before_value: string; after_value: string; result: string; verified_at: string } | null;
};

type Diagnosis = {
  detection: {
    analysis_status: string;
    severity: string;
    severity_score: number;
    symptoms: string[];
    measurements_analyzed: number;
    intermittent: boolean;
    persistent: boolean;
  };
  correlation: {
    status: string;
    probable_category: string;
    evidence: string[];
    correlated_symptoms: string[];
  };
  recommendations: {
    root_cause: string;
    explanation: string;
    severity: string;
    suggested_fixes: string[];
    verification_steps: string[];
  };
};

type DashboardData = {
  status: {
    monitoring: boolean;
    session_id: number | null;
    measurement_count: number;
    latest_measurement: Measurement | null;
  };
  measurements: Measurement[];
  network: NetworkInfo | null;
  diagnosis: Diagnosis | null;
  remediation: RemediationStatus | null;
  sessions: Session[];
};

const emptyData: DashboardData = {
  status: { monitoring: false, session_id: null, measurement_count: 0, latest_measurement: null },
  measurements: [],
  diagnosis: null,
  remediation: null,
  network: null,
  sessions: [],
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : `Request failed (${response.status})`;
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

function formatMetric(value: number | null | undefined, unit = "ms") {
  if (value == null || !Number.isFinite(value)) return "—";
  const digits = unit === "%" ? 1 : value >= 100 ? 0 : 1;
  return `${value.toFixed(digits)}${unit}`;
}

function formatTime(timestamp: string | null | undefined) {
  if (!timestamp) return "—";
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime())
    ? timestamp
    : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function formatDate(timestamp: string | null | undefined) {
  if (!timestamp) return "—";
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime())
    ? timestamp
    : date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function prettyCategory(category: string | undefined) {
  return (category ?? "UNDETERMINED").replace(/_/g, " ").toLowerCase()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function remediationResultLabel(result: string | null | undefined) {
  if (!result) return "Result not recorded";
  try {
    const parsed: { status?: string; plan_status?: string } = JSON.parse(result);
    return (parsed.status ?? parsed.plan_status ?? "Result recorded").replace(/_/g, " ");
  } catch {
    return "Result recorded";
  }
}

function MetricCard({
  label,
  value,
  detail,
  icon: Icon,
  tone = "blue",
}: {
  label: string;
  value: string;
  detail: string;
  icon: typeof Activity;
  tone?: string;
}) {
  return (
    <article className="metric-card">
      <div className={`metric-icon ${tone}`}><Icon size={19} strokeWidth={1.9} /></div>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      <div className="metric-detail">{detail}</div>
    </article>
  );
}

function LatencyChart({ measurements }: { measurements: Measurement[] }) {
  const chart = useMemo(() => {
    const rows = measurements.slice(-24);
    const values = rows.map((item) => item.internet_latency_ms).filter((item): item is number => item != null);
    if (values.length < 2) return null;
    const max = Math.max(...values, 1);
    const points = values.map((value, index) => {
      const x = 8 + (index / (values.length - 1)) * 584;
      const y = 148 - (value / max) * 118;
      return `${x},${y}`;
    }).join(" ");
    return { points, max };
  }, [measurements]);

  return (
    <div className="chart-wrap">
      {chart ? (
        <>
          <div className="chart-topline"><span>Latency · ms</span><span>Peak {chart.max.toFixed(1)} ms</span></div>
          <svg className="latency-chart" viewBox="0 0 600 170" role="img" aria-label="Internet latency trend">
            <defs>
              <linearGradient id="chart-fill" x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor="#4f7cff" stopOpacity=".18" />
                <stop offset="100%" stopColor="#4f7cff" stopOpacity="0" />
              </linearGradient>
            </defs>
            {[30, 70, 110, 150].map((y) => <line key={y} x1="8" x2="592" y1={y} y2={y} className="grid-line" />)}
            <polygon points={`8,160 ${chart.points} 592,160`} fill="url(#chart-fill)" />
            <polyline points={chart.points} className="chart-line" />
          </svg>
          <div className="chart-axis"><span>Oldest</span><span>Latest</span></div>
        </>
      ) : (
        <div className="empty-chart"><Activity size={24} /><span>Start monitoring to build your latency timeline.</span></div>
      )}
    </div>
  );
}

export default function App() {
  const [data, setData] = useState(emptyData);
  const [page, setPage] = useState<"overview" | "live" | "diagnosis" | "history" | "session">("overview");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [clearingSessions, setClearingSessions] = useState(false);
  const [flushingDns, setFlushingDns] = useState(false);
  const [updatingAutomation, setUpdatingAutomation] = useState(false);
  const [voiceSpeaking, setVoiceSpeaking] = useState(false);
  const [remediationMessage, setRemediationMessage] = useState("");
  const [error, setError] = useState("");
  const [selectedSession, setSelectedSession] = useState<SessionDetail | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const refresh = useCallback(async (includeNetwork = false) => {
    setRefreshing(true);
    try {
      const [status, measurements, diagnosis, sessions, remediation, network] = await Promise.all([
        request<DashboardData["status"]>("/api/status"),
        request<Measurement[]>("/api/measurements?limit=60"),
        request<Diagnosis>("/api/diagnosis"),
        request<Session[]>("/api/sessions"),
        request<RemediationStatus>("/api/remediation/settings"),
        includeNetwork ? request<NetworkInfo>("/api/network") : Promise.resolve(undefined),
      ]);
      setData((current) => ({
        status,
        measurements,
        diagnosis,
        remediation,
        sessions,
        network: network ?? current.network,
      }));
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not reach the diagnosis service.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void refresh(true);
    const timer = window.setInterval(() => void refresh(), 1000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const controlMonitoring = async () => {
    setBusy(true);
    try {
      await request(data.status.monitoring ? "/api/monitor/stop" : "/api/monitor/start", { method: "POST" });
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not change monitoring state.");
    } finally {
      setBusy(false);
    }
  };

  const openSession = async (sessionId: number) => {
    try {
      const detail = await request<SessionDetail>(`/api/sessions/${sessionId}`);
      setSelectedSession(detail);
      setPage("session");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load session details.");
    }
  };

  const clearSessions = async () => {
    if (data.status.monitoring || clearingSessions) return;
    const confirmed = window.confirm(
      "Clear all saved monitoring sessions and their measurements, diagnoses, events, and verification records? This cannot be undone.",
    );
    if (!confirmed) return;

    setClearingSessions(true);
    try {
      await request<{ cleared: boolean }>("/api/sessions", { method: "DELETE" });
      setSelectedSession(null);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not clear saved sessions.");
    } finally {
      setClearingSessions(false);
    }
  };

  const flushDnsCache = async () => {
    if (flushingDns) return;
    const confirmed = window.confirm(
      "Flush this Windows computer's DNS cache? The action is available only after three consecutive DNS failures while internet and HTTP checks are working. It does not change DNS server settings or reset your network connection.",
    );
    if (!confirmed) return;

    setFlushingDns(true);
    setRemediationMessage("");
    try {
      const result = await request<{ message: string; note: string }>("/api/remediation/flush-dns", { method: "POST" });
      setRemediationMessage(`${result.message} ${result.note}`);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not flush the DNS cache.");
    } finally {
      setFlushingDns(false);
    }
  };

  const toggleAutomaticDns = async () => {
    const enabled = !data.remediation?.automatic_dns_enabled;
    if (enabled && !window.confirm(
      "Enable automatic DNS-cache flushing? While this app is running, it may flush the Windows DNS cache after three consecutive DNS failures when internet and HTTP checks still work. It will not change DNS settings or reset the network adapter.",
    )) return;
    setUpdatingAutomation(true);
    try {
      await request("/api/remediation/settings", {
        method: "POST",
        body: JSON.stringify({ enabled }),
      });
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not update automatic remediation.");
    } finally {
      setUpdatingAutomation(false);
    }
  };

  const speakDiagnosisSteps = () => {
    if (!diagnosis || !("speechSynthesis" in window)) {
      setError("Voice guidance is not supported by this browser.");
      return;
    }

    if (voiceSpeaking) {
      window.speechSynthesis.cancel();
      setVoiceSpeaking(false);
      return;
    }

    const sections = [
      `Diagnosis: ${diagnosis.recommendations.root_cause}. ${diagnosis.recommendations.explanation}`,
      `Recommended steps. ${diagnosis.recommendations.suggested_fixes.join(". ")}`,
      `Verification steps. ${diagnosis.recommendations.verification_steps.join(". ")}`,
    ];
    const utterance = new SpeechSynthesisUtterance(sections.join(". "));
    utterance.rate = 0.95;
    utterance.onend = () => setVoiceSpeaking(false);
    utterance.onerror = () => {
      setVoiceSpeaking(false);
      setError("The browser could not play voice guidance.");
    };
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
    setVoiceSpeaking(true);
  };

  useEffect(() => () => {
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  }, []);

  const latest = data.status.latest_measurement;
  const diagnosis = data.diagnosis;
  const connected = data.network?.status.toLowerCase() === "connected";
  const downloadSessionId = data.status.session_id ?? data.sessions[0]?.session_id ?? null;
  const pageTitle = {
    overview: "Overview",
    live: "Live monitoring",
    diagnosis: "Diagnosis",
    history: "All sessions",
    session: selectedSession ? `Session #${selectedSession.session.session_id}` : "Session details",
  }[page];
  const navItems = [
    { id: "overview" as const, label: "Overview", icon: LayoutDashboard },
    { id: "live" as const, label: "Live monitoring", icon: Signal },
    { id: "diagnosis" as const, label: "Diagnosis & advice", icon: FileSearch },
    { id: "history" as const, label: "All sessions", icon: History },
  ];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><Activity size={22} /></div>
          <div><strong>Netwise</strong><span>NETWORK INTELLIGENCE</span></div>
        </div>
        <div className="nav-caption">WORKSPACE</div>
        <nav className="workspace-nav" aria-label="Workspace pages">
          {navItems.map(({ id, label, icon: Icon }) => (
            <button key={id} className={`nav-link ${page === id ? "active" : ""}`} onClick={() => setPage(id)}>
              <Icon size={17} /> <span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="session-nav-heading">
          <div className="nav-caption">MONITORING SESSIONS</div>
          <span className="session-count">{data.sessions.length}</span>
        </div>
        <div className="session-nav-list">
          {data.sessions.map((session) => (
            <button
              key={session.session_id}
              className={`session-nav-item ${selectedSession?.session.session_id === session.session_id ? "active" : ""}`}
              onClick={() => void openSession(session.session_id)}
              title={`Open session #${session.session_id}`}
            >
              <span className={`session-nav-dot ${session.final_status === "IN_PROGRESS" ? "running" : ""}`} />
              <span className="session-nav-copy">
                <strong>Session #{session.session_id}</strong>
                <small>{formatDate(session.start_time)}</small>
              </span>
              <ChevronRight size={14} className="session-nav-chevron" />
            </button>
          ))}
          {!data.sessions.length && <p className="no-sessions">No sessions yet. Start monitoring to create one.</p>}
        </div>
        <div className="sidebar-bottom">
          <div className={`connection-chip ${connected ? "online" : ""}`}>
            <span className="connection-dot" />
            <span>{data.network ? (connected ? "Network connected" : data.network.status) : "Checking network"}</span>
          </div>
          <span className="sidebar-foot">LOCAL MONITORING CONSOLE</span>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div className="breadcrumb">Workspace <span>/</span> <strong>{pageTitle}</strong></div>
          <div className="top-actions">
            <div className={`live-label ${data.status.monitoring ? "is-live" : ""}`}>
              <span /> {data.status.monitoring ? "LIVE MONITORING" : "MONITORING PAUSED"}
            </div>
            <button className="icon-button" title="Refresh data" onClick={() => void refresh(true)} disabled={refreshing}>
              <RefreshCw size={17} className={refreshing ? "spin" : ""} />
            </button>
            <div className="avatar">SN</div>
          </div>
        </header>

        {error && (
          <div className="error-banner"><AlertTriangle size={17} /><span>{error} Ensure the FastAPI server is running.</span><button onClick={() => setError("")} aria-label="Dismiss"><X size={16} /></button></div>
        )}

        {page === "overview" ? (
          <div className="page-content">
            <section className="welcome-row">
              <div>
                <div className="eyebrow">NETWORK OPERATIONS</div>
                <h1>Network overview</h1>
                <p>Monitor your connection health and diagnose issues as they happen.</p>
              </div>
              <button className={`monitor-button ${data.status.monitoring ? "stop" : ""}`} onClick={() => void controlMonitoring()} disabled={busy || loading}>
                {busy ? <LoaderCircle className="spin" size={17} /> : data.status.monitoring ? <Square size={15} fill="currentColor" /> : <Play size={16} fill="currentColor" />}
                {busy ? "Please wait…" : data.status.monitoring ? "Stop monitoring" : "Start monitoring"}
              </button>
            </section>

            <section className="stats-grid">
              <MetricCard label="Internet latency" value={formatMetric(latest?.internet_latency_ms)} detail="Latest response time" icon={Gauge} tone="blue" />
              <MetricCard label="Packet loss" value={formatMetric(latest?.internet_packet_loss, "%")} detail="External host" icon={ArrowDown} tone="orange" />
              <MetricCard label="Connection quality" value={latest?.overall_status ?? "Waiting"} detail={latest ? "Latest monitoring cycle" : "No measurements yet"} icon={ShieldCheck} tone={latest?.overall_status === "NORMAL" ? "green" : "purple"} />
              <MetricCard label="Measurements" value={String(data.status.measurement_count)} detail="Saved in local database" icon={Activity} tone="teal" />
            </section>

            <section className="content-grid">
              <article className="panel chart-panel">
                <div className="panel-heading">
                  <div><h2>Latency trend</h2><p>Internet response time over recent checks</p></div>
                  <span className="period-tag"><Clock3 size={13} /> Recent</span>
                </div>
                <LatencyChart measurements={data.measurements} />
                <div className="chart-legend"><span className="legend-dot" /> Internet latency</div>
              </article>

              <article className="panel diagnosis-panel">
                <div className="panel-heading">
                  <div><h2>Diagnosis</h2><p>Based on recent measurements</p></div>
                  <div className="diagnosis-icon"><ShieldCheck size={18} /></div>
                </div>
                {diagnosis ? (
                  <>
                    <div className="diagnosis-status">
                      <span className={`severity-dot ${diagnosis.detection.severity.toLowerCase()}`} />
                      <span>{diagnosis.detection.severity ?? "UNKNOWN"} SEVERITY</span>
                      <span className="diagnosis-score">{diagnosis.detection.measurements_analyzed} checks</span>
                    </div>
                    <h3 className="diagnosis-title">{diagnosis.recommendations.root_cause}</h3>
                    <p className="diagnosis-copy">{diagnosis.recommendations.explanation}</p>
                    <div className="category-box">
                      <CircleHelp size={15} />
                      <span>Probable category</span>
                      <strong>{prettyCategory(diagnosis.correlation.probable_category)}</strong>
                    </div>
                    {diagnosis.recommendations.suggested_fixes.length > 0 && (
                      <div className="recommendation"><strong>Suggested next step</strong><span>{diagnosis.recommendations.suggested_fixes[0]}</span></div>
                    )}
                  </>
                ) : <div className="panel-empty">{loading ? "Loading diagnosis…" : "Diagnosis is not available."}</div>}
              </article>
            </section>

            <section className="content-grid lower-grid">
              <article className="panel">
                <div className="panel-heading">
                  <div><h2>Latest checks</h2><p>Most recent network measurements</p></div>
                  <button className="text-button" onClick={() => setPage("history")}>View history <ChevronRight size={15} /></button>
                </div>
                <div className="table-scroll">
                  <table>
                    <thead><tr><th>TIME</th><th>STATUS</th><th>LATENCY</th><th>LOSS</th><th>DNS</th></tr></thead>
                    <tbody>
                      {data.measurements.slice(-5).reverse().map((row) => (
                        <tr key={row.id}>
                          <td>{formatTime(row.timestamp)}</td>
                          <td><span className={`status-badge ${row.overall_status?.toLowerCase() ?? "unknown"}`}><span />{row.overall_status ?? "Unknown"}</span></td>
                          <td>{formatMetric(row.internet_latency_ms)}</td>
                          <td>{formatMetric(row.internet_packet_loss, "%")}</td>
                          <td>{row.dns_success === 1 ? <Check className="good" size={16} /> : row.dns_success === 0 ? <X className="bad" size={16} /> : "—"}</td>
                        </tr>
                      ))}
                      {!data.measurements.length && <tr><td className="empty-cell" colSpan={5}>No measurements yet. Start monitoring to collect data.</td></tr>}
                    </tbody>
                  </table>
                </div>
              </article>

              <article className="panel network-panel">
                <div className="panel-heading"><div><h2>Network details</h2><p>Current device connection</p></div><Network size={18} className="muted-icon" /></div>
                <div className="network-list">
                  <div className="network-item"><span><Wifi size={15} /> Interface</span><strong>{data.network?.interface ?? "Unknown"}</strong></div>
                  <div className="network-item"><span><Globe2 size={15} /> IP address</span><strong>{data.network?.ipv4 ?? "Unknown"}</strong></div>
                  <div className="network-item"><span><Router size={15} /> Gateway</span><strong>{data.network?.gateway ?? "Unknown"}</strong></div>
                  <div className="network-item"><span><ArrowUp size={15} /> DNS servers</span><strong>{data.network?.dns_servers?.join(", ") || "Unknown"}</strong></div>
                </div>
              </article>
            </section>
          </div>
        ) : page === "live" ? (
          <div className="page-content">
            <section className="welcome-row page-intro">
              <div>
                <div className="eyebrow">REAL-TIME HEALTH</div>
                <h1>Live monitoring</h1>
                <p>Follow each measurement as it arrives from this device.</p>
              </div>
              <button className={`monitor-button ${data.status.monitoring ? "stop" : ""}`} onClick={() => void controlMonitoring()} disabled={busy || loading}>
                {busy ? <LoaderCircle className="spin" size={17} /> : data.status.monitoring ? <Square size={15} fill="currentColor" /> : <Play size={16} fill="currentColor" />}
                {busy ? "Please wait…" : data.status.monitoring ? "Stop monitoring" : "Start monitoring"}
              </button>
            </section>
            <div className="live-session-banner">
              <span className={`live-pulse ${data.status.monitoring ? "running" : ""}`} />
              <div><strong>{data.status.monitoring ? `Monitoring session #${data.status.session_id}` : "Monitoring is paused"}</strong><span>{data.status.monitoring ? "Network checks run concurrently and measurements are saved about once per second." : "Start monitoring to create a session and collect live measurements."}</span></div>
              <span className="live-state">{data.status.monitoring ? "RUNNING" : "IDLE"}</span>
            </div>
            <div className="session-actions">
              <div><strong>Session tools</strong><span>Export measurement data or clear saved history. Clear is disabled during monitoring.</span></div>
              <div className="session-action-buttons">
                <a
                  className={`secondary-action ${downloadSessionId === null ? "disabled" : ""}`}
                  href={downloadSessionId === null ? undefined : `/api/sessions/${downloadSessionId}/export.csv`}
                  download={downloadSessionId === null ? undefined : `network-session-${downloadSessionId}.csv`}
                  aria-disabled={downloadSessionId === null}
                  onClick={(event) => {
                    if (downloadSessionId === null) event.preventDefault();
                  }}
                >
                  <Download size={15} /> {data.status.monitoring ? "Download current session" : "Download latest session"}
                </a>
                <button
                  className="danger-action"
                  onClick={() => void clearSessions()}
                  disabled={data.status.monitoring || clearingSessions || data.sessions.length === 0}
                  title={data.status.monitoring ? "Stop monitoring before clearing sessions" : "Delete all saved session history"}
                >
                  {clearingSessions ? <LoaderCircle className="spin" size={15} /> : <Trash2 size={15} />}
                  {clearingSessions ? "Clearing…" : "Clear sessions"}
                </button>
              </div>
            </div>
            <section className="stats-grid live-stats">
              <MetricCard label="Internet latency" value={formatMetric(latest?.internet_latency_ms)} detail="External host response" icon={Gauge} tone="blue" />
              <MetricCard label="Gateway latency" value={formatMetric(latest?.gateway_latency_ms)} detail="Local router response" icon={Router} tone="purple" />
              <MetricCard label="Jitter" value={formatMetric(latest?.jitter_ms)} detail="Variation in delay" icon={Activity} tone="teal" />
              <MetricCard label="Packet loss" value={formatMetric(latest?.internet_packet_loss, "%")} detail="External host" icon={ArrowDown} tone="orange" />
            </section>
            <article className="panel live-chart-panel">
              <div className="panel-heading"><div><h2>Connection performance</h2><p>Recent internet response times from this device</p></div><span className="period-tag"><Activity size={13} /> {data.measurements.length} recent checks</span></div>
              <LatencyChart measurements={data.measurements} />
              <div className="chart-legend"><span className="legend-dot" /> Internet latency</div>
            </article>
            <article className="panel live-table-panel">
              <div className="panel-heading"><div><h2>Measurement stream</h2><p>Newest measurements appear first</p></div><span className="period-tag"><Clock3 size={13} /> Auto-refresh · 1 sec</span></div>
              <div className="table-scroll">
                <table className="wide-table">
                  <thead><tr><th>TIME</th><th>OVERALL</th><th>GATEWAY</th><th>INTERNET</th><th>PACKET LOSS</th><th>JITTER</th><th>DNS</th><th>HTTP</th></tr></thead>
                  <tbody>{data.measurements.slice().reverse().map((row) => (
                    <tr key={row.id}>
                      <td>{formatTime(row.timestamp)}</td>
                      <td><span className={`status-badge ${row.overall_status?.toLowerCase() ?? "unknown"}`}><span />{row.overall_status ?? "Unknown"}</span></td>
                      <td>{formatMetric(row.gateway_latency_ms)}</td><td>{formatMetric(row.internet_latency_ms)}</td>
                      <td>{formatMetric(row.internet_packet_loss, "%")}</td><td>{formatMetric(row.jitter_ms)}</td>
                      <td>{row.dns_success === 1 ? <span className="check-label"><Check size={14} /> Pass</span> : row.dns_success === 0 ? <span className="fail-label"><X size={14} /> Fail</span> : "—"}</td>
                      <td>{row.http_status_code ?? "—"}</td>
                    </tr>
                  ))}{!data.measurements.length && <tr><td className="empty-cell" colSpan={8}>No measurements yet. Start monitoring to see live results.</td></tr>}</tbody>
                </table>
              </div>
            </article>
          </div>
        ) : page === "diagnosis" ? (
          <div className="page-content">
            <section className="welcome-row page-intro">
              <div><div className="eyebrow">EVIDENCE-BASED ANALYSIS</div><h1>Diagnosis & advice</h1><p>See what the latest measurements suggest and what to check next.</p></div>
              <span className={`severity-pill ${diagnosis?.detection.severity.toLowerCase() ?? "unknown"}`}><span />{diagnosis?.detection.severity ?? "UNKNOWN"} SEVERITY</span>
            </section>
            {diagnosis ? <>
              <section className="diagnosis-hero">
                <div className="diagnosis-hero-icon"><ShieldCheck size={24} /></div>
                <div className="diagnosis-hero-copy">
                  <div className="eyebrow">CURRENT ASSESSMENT · {diagnosis.detection.measurements_analyzed} CHECKS ANALYZED</div>
                  <h2>{diagnosis.recommendations.root_cause}</h2>
                  <p>{diagnosis.recommendations.explanation}</p>
                </div>
                <div className={`severity-score ${diagnosis.detection.severity.toLowerCase()}`}><strong>{diagnosis.detection.severity_score}</strong><span>severity score</span></div>
              </section>
              <section className="diagnosis-grid">
                <article className="panel">
                  <div className="panel-heading"><div><h2>Probable category</h2><p>A hypothesis based on endpoint measurements</p></div><CircleHelp size={18} className="muted-icon" /></div>
                  <div className="category-large">{prettyCategory(diagnosis.correlation.probable_category)}</div>
                  <div className="assessment-tags">
                    <span>{diagnosis.detection.persistent ? "Persistent pattern" : diagnosis.detection.intermittent ? "Intermittent pattern" : "No persistent pattern"}</span>
                    <span>{diagnosis.correlation.status === "ANALYZED" ? "Analysis complete" : "More data needed"}</span>
                  </div>
                </article>
                <article className="panel">
                  <div className="panel-heading"><div><h2>Symptoms observed</h2><p>Signals detected in the analysis window</p></div><Activity size={18} className="muted-icon" /></div>
                  {diagnosis.correlation.correlated_symptoms.length ? (
                    <ul className="evidence-list">{diagnosis.correlation.correlated_symptoms.map((symptom) => <li key={symptom}><span className="evidence-bullet" />{prettyCategory(symptom)}</li>)}</ul>
                  ) : <div className="quiet-empty"><Check size={16} /> No repeated warning symptoms were detected.</div>}
                </article>
              </section>
              <section className="diagnosis-grid advice-grid">
                <article className="panel advice-panel">
                  <div className="panel-heading"><div><h2>Recommended checks</h2><p>One low-risk DNS action is available; other steps remain advisory.</p></div><FileSearch size={18} className="muted-icon" /></div>
                  <div className="voice-guidance">
                    <div>
                      <strong>Voice guidance</strong>
                      <span>Listen to the diagnosis, recommended actions, and verification steps.</span>
                    </div>
                    <button className="secondary-action" onClick={speakDiagnosisSteps} disabled={!diagnosis || !("speechSynthesis" in window)}>
                      {voiceSpeaking ? <VolumeX size={16} /> : <Volume2 size={16} />}
                      {voiceSpeaking ? "Stop speaking" : "Read steps aloud"}
                    </button>
                  </div>
                  <ol className="advice-list">{diagnosis.recommendations.suggested_fixes.map((item, index) => <li key={item}><span>{String(index + 1).padStart(2, "0")}</span><p>{item}</p></li>)}</ol>
                  {data.remediation?.automatic_dns_supported && (
                    <div className="remediation-action">
                      <p>Automatic remediation is limited to flushing this computer's DNS cache. It requires three consecutive DNS failures while internet and HTTP checks remain healthy, and is off by default.</p>
                      <button
                        className="secondary-action"
                        onClick={() => void toggleAutomaticDns()}
                        disabled={updatingAutomation}
                      >
                        {updatingAutomation ? <LoaderCircle className="spin" size={15} /> : <ShieldCheck size={15} />}
                        {data.remediation.automatic_dns_enabled ? "Disable automatic DNS fix" : "Enable automatic DNS fix"}
                      </button>
                      <p>{data.remediation.automatic_dns_enabled ? "Enabled for this API process; it resets to off when the server restarts." : data.remediation.eligibility_reason}</p>
                    </div>
                  )}
                  {diagnosis.correlation.probable_category === "DNS_RESOLUTION" && data.remediation?.eligible && (
                    <div className="remediation-action">
                      <p>Three consecutive DNS checks failed while internet and HTTP are working. You can manually clear the DNS cache; a successful command is not treated as a fix until three new checks verify recovery.</p>
                      <button className="secondary-action" onClick={() => void flushDnsCache()} disabled={flushingDns}>
                        {flushingDns ? <LoaderCircle className="spin" size={15} /> : <RefreshCw size={15} />}
                        {flushingDns ? "Flushing DNS cache…" : "Flush DNS cache"}
                      </button>
                      {remediationMessage && <p className="remediation-result" role="status">{remediationMessage}</p>}
                    </div>
                  )}
                  {data.remediation?.latest_verification && (
                    <div className="remediation-action" role="status">
                      <strong>Latest remediation verification: {data.remediation.latest_verification.result.replace(/_/g, " ")}</strong>
                      <p>DNS before: {data.remediation.latest_verification.before_value}; after: {data.remediation.latest_verification.after_value}.</p>
                    </div>
                  )}
                  {data.remediation?.latest_action && (
                    <div className="remediation-action">
                      <strong>{data.remediation.latest_action.action_name}: {remediationResultLabel(data.remediation.latest_action.result)}</strong>
                      <p>Action time: {formatDate(data.remediation.latest_action.executed_at)}. Verification status is recorded separately below when enough new measurements arrive.</p>
                    </div>
                  )}
                  <a className="secondary-action report-download" href="/api/report.pdf" download="network-diagnostic-report.pdf">
                    <Download size={15} /> Download PDF report
                  </a>
                </article>
                <article className="panel advice-panel">
                  <div className="panel-heading"><div><h2>How to verify</h2><p>Check whether the connection recovers</p></div><ShieldCheck size={18} className="muted-icon" /></div>
                  <ol className="advice-list verification-list">{diagnosis.recommendations.verification_steps.map((item) => <li key={item}><span><Check size={14} /></span><p>{item}</p></li>)}</ol>
                  <p className="diagnosis-disclaimer">These are probable categories, not a guaranteed root cause. The app only observes this device's connection.</p>
                </article>
              </section>
              <article className="panel evidence-panel">
                <div className="panel-heading"><div><h2>Supporting evidence</h2><p>Reasons behind the current assessment</p></div><CircleDot size={18} className="muted-icon" /></div>
                {diagnosis.correlation.evidence.length ? <ul className="evidence-list">{diagnosis.correlation.evidence.map((item) => <li key={item}><span className="evidence-bullet" />{item}</li>)}</ul> : <div className="quiet-empty">Collect measurements to build an evidence-based assessment.</div>}
              </article>
            </> : <article className="panel"><div className="quiet-empty">{loading ? "Analyzing recent measurements…" : "Diagnosis is not available."}</div></article>}
          </div>
        ) : page === "history" ? (
          <div className="page-content">
            <section className="welcome-row">
              <div><div className="eyebrow">PAST MONITORING</div><h1>All sessions</h1><p>Every saved monitoring session is listed below and in the sidebar.</p></div>
              <button className="icon-button history-refresh" title="Refresh sessions" onClick={() => void refresh()}><RefreshCw size={17} /></button>
            </section>
            <div className="history-summary">
              <div className="history-summary-icon"><History size={19} /></div>
              <div><strong>{data.sessions.length} saved sessions</strong><span>Session history is stored locally and survives app restarts.</span></div>
              <button className="text-button" onClick={() => setPage("live")}>Go to live monitoring <ChevronRight size={15} /></button>
            </div>
            <article className="panel history-panel">
              <div className="panel-heading"><div><h2>Monitoring sessions</h2><p>Select any session to inspect its measurements and recorded analysis.</p></div></div>
              <div className="table-scroll">
                <table>
                  <thead><tr><th>SESSION</th><th>STARTED</th><th>DURATION</th><th>MEASUREMENTS</th><th>STATUS</th><th /></tr></thead>
                  <tbody>
                    {data.sessions.map((session) => (
                      <tr key={session.session_id}>
                        <td><strong className="session-id">#{session.session_id}</strong></td><td>{formatDate(session.start_time)}</td>
                        <td>{session.end_time ? `${Math.max(0, Math.round((new Date(session.end_time).getTime() - new Date(session.start_time).getTime()) / 60000))} min` : "In progress"}</td>
                        <td>{session.measurement_count}</td>
                        <td><span className={`status-badge ${session.final_status === "IN_PROGRESS" ? "degraded" : "normal"}`}><span />{session.final_status}</span></td>
                        <td><button className="row-action" onClick={() => void openSession(session.session_id)}>Open session <ChevronRight size={14} /></button></td>
                      </tr>
                    ))}
                    {!data.sessions.length && <tr><td className="empty-cell" colSpan={6}>No saved sessions yet. Start monitoring to create one.</td></tr>}
                  </tbody>
                </table>
              </div>
            </article>
          </div>
        ) : (
          <div className="page-content">
            {selectedSession ? <>
              <section className="welcome-row page-intro">
                <div><div className="eyebrow">SESSION DETAILS</div><h1>Session #{selectedSession.session.session_id}</h1><p>Started {formatDate(selectedSession.session.start_time)}</p></div>
                <button className="text-button back-button" onClick={() => setPage("history")}><ChevronRight className="back-chevron" size={15} /> All sessions</button>
              </section>
              <section className="stats-grid session-stats">
                <MetricCard label="Measurements" value={String(selectedSession.session.measurement_count)} detail="Saved for this session" icon={Activity} tone="blue" />
                <MetricCard label="Session status" value={selectedSession.session.final_status} detail={selectedSession.session.end_time ? `Ended ${formatTime(selectedSession.session.end_time)}` : "Currently running"} icon={Clock3} tone="green" />
                <MetricCard label="Detected events" value={String(selectedSession.session.event_count)} detail="Recorded event count" icon={AlertTriangle} tone="orange" />
                <MetricCard label="Interface" value={selectedSession.session.interface_name ?? "Unknown"} detail={selectedSession.session.ipv4_address ?? "No IP captured"} icon={Cable} tone="teal" />
              </section>
              <article className="panel session-measurements">
                <div className="panel-heading"><div><h2>Session measurements</h2><p>{selectedSession.measurements.length} records · oldest to newest</p></div><span className="period-tag"><Clock3 size={13} />{formatDate(selectedSession.session.start_time)}</span></div>
                <div className="table-scroll"><table className="wide-table"><thead><tr><th>TIME</th><th>STATUS</th><th>GATEWAY</th><th>INTERNET</th><th>LOSS</th><th>JITTER</th><th>DNS</th><th>HTTP</th></tr></thead>
                  <tbody>{selectedSession.measurements.map((row) => <tr key={row.id}><td>{formatTime(row.timestamp)}</td><td><span className={`status-badge ${row.overall_status?.toLowerCase() ?? "unknown"}`}><span />{row.overall_status ?? "Unknown"}</span></td><td>{formatMetric(row.gateway_latency_ms)}</td><td>{formatMetric(row.internet_latency_ms)}</td><td>{formatMetric(row.internet_packet_loss, "%")}</td><td>{formatMetric(row.jitter_ms)}</td><td>{row.dns_success === 1 ? "Pass" : row.dns_success === 0 ? "Fail" : "—"}</td><td>{row.http_status_code ?? "—"}</td></tr>)}
                    {!selectedSession.measurements.length && <tr><td className="empty-cell" colSpan={8}>This session has no measurements.</td></tr>}
                  </tbody></table></div>
              </article>
              <article className="panel session-records">
                <div className="panel-heading"><div><h2>Session records</h2><p>Events, diagnoses, and follow-up records saved for this session</p></div></div>
                <div className="record-grid">
                  <div className="record-tile"><strong>{selectedSession.events.length}</strong><span>Detected events</span></div>
                  <div className="record-tile"><strong>{selectedSession.diagnoses.length}</strong><span>Diagnoses saved</span></div>
                  <div className="record-tile"><strong>{selectedSession.remediation_actions.length}</strong><span>Action reviews</span></div>
                  <div className="record-tile"><strong>{selectedSession.verification_results.length}</strong><span>Verification results</span></div>
                </div>
              </article>
            </> : <article className="panel"><div className="quiet-empty">Choose a session from the sidebar or history list to open its details.</div></article>}
          </div>
        )}
        <footer className="page-footer"><span>NETWISE · SMART NETWORK DIAGNOSIS</span><span>Updates every second</span></footer>
      </main>
    </div>
  );
}
