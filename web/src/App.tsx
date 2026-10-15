import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Area, AreaChart, CartesianGrid, Line, LineChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts';
import type { AnomalyResponse, CopilotResponse, ForecastResponse, KPIResponse, Recommendation, RecommendationPlan, ReportResponse } from './contracts';

type Screen = 'Live floor' | 'Twin simulation' | 'Recommendations' | 'Analytics' | 'Impact report';
type Frame = { timestamp: string; meter_kw: number | null; twin_state: Array<{ equipment_id: string; state: string; power_kw_estimate: number; confidence?: number }>; cv_events: Array<Record<string, unknown>>; recommendations: Array<Record<string, unknown>> };
type Scenario = { id: string; name: string };
type Tariff = { currency: string; energy_inr_per_kwh: { off_peak: number; normal: number; peak: number }; peak_windows: string[]; synthetic: true };
type Notice = { kind: 'error' | 'success'; text: string };
const API = import.meta.env.VITE_API_URL || '';
const fmt = (n?: number | null, digits = 1) => typeof n === 'number' && Number.isFinite(n) ? n.toLocaleString('en-IN', { maximumFractionDigits: digits }) : '—';
const money = (n?: number | null) => typeof n === 'number' ? `₹${fmt(n, 0)}` : '—';
const titleCase = (v: string) => v.toLowerCase().replaceAll('_', ' ');

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${API}${path}`);
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}
async function post<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${API}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}

function Icon({ children }: { children: string }) { return <span className="icon" aria-hidden="true">{children}</span>; }
function Badge() { return <span className="synthetic"><i /> SYNTHETIC DATA <span>· simulation-based projections</span></span>; }
function Metric({ label, value, unit, detail, accent = false }: { label: string; value: string; unit?: string; detail?: string; accent?: boolean }) {
  return <article className={`metric ${accent ? 'metric-accent' : ''}`}><div className="metric-label">{label}</div><div className="metric-value">{value}<small>{unit}</small></div>{detail && <div className="metric-detail">{detail}</div>}</article>;
}
function SectionTitle({ eyebrow, title, right }: { eyebrow?: string; title: string; right?: React.ReactNode }) {
  return <div className="section-title"><div>{eyebrow && <div className="eyebrow">{eyebrow}</div>}<h2>{title}</h2></div>{right}</div>;
}

export default function App() {
  const [screen, setScreen] = useState<Screen>('Live floor');
  const [scenario, setScenario] = useState('S2');
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [tariff, setTariff] = useState<Tariff | null>(null);
  const [seed, setSeed] = useState(42);
  const [kpis, setKpis] = useState<KPIResponse | null>(null);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [forecast, setForecast] = useState<ForecastResponse | null>(null);
  const [anomalies, setAnomalies] = useState<AnomalyResponse | null>(null);
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [frame, setFrame] = useState<Frame | null>(null);
  const [history, setHistory] = useState<Array<{ time: string; meter: number; twin: number }>>([]);
  const [socketState, setSocketState] = useState<'connecting' | 'live' | 'offline' | 'complete'>('offline');
  const [speed, setSpeed] = useState(30);
  const [paused, setPaused] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [chatQuery, setChatQuery] = useState('What is the energy use and how can I reduce it?');
  const [chat, setChat] = useState<Array<{ role: 'user' | 'assistant'; text: string }>>([]);
  const [chatBusy, setChatBusy] = useState(false);
  const [reportMarkdown, setReportMarkdown] = useState('');
  const socket = useRef<WebSocket | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [kpi, rec, fc, an, rp, tariffConfig] = await Promise.all([
        get<KPIResponse>('/kpis'), get<{ recommendations: Recommendation[] }>('/recommendations'),
        get<ForecastResponse>('/forecast?horizon_steps=24'), get<AnomalyResponse>('/anomalies'), get<ReportResponse>('/report'), get<Tariff>('/tariff'),
      ]);
      setKpis(kpi); setRecommendations(rec.recommendations || []); setForecast(fc); setAnomalies(an); setReport(rp); setReportMarkdown(rp.markdown); setTariff(tariffConfig);
      return true;
    } catch (error) { setNotice({ kind: 'error', text: `Data is not ready. Start a synthetic run to load the dashboard. ${String(error).slice(0, 160)}` }); return false; }
  }, []);

  useEffect(() => {
    get<Scenario[]>('/scenarios').then(setScenarios).catch(() => setNotice({ kind: 'error', text: 'API is unavailable. Start the EnergySense API at http://127.0.0.1:8000.' }));
    void refresh();
  }, [refresh]);

  const run = async (selected = scenario) => {
    setBusy(true); setNotice(null); setSocketState('connecting');
    try {
      await post('/run', { scenario: selected, seed, days: 1, cv_mode: 'simulated' });
      setScenario(selected); setHistory([]); setFrame(null);
      await refresh();
      setNotice({ kind: 'success', text: `${selected} synthetic run is ready.` });
    } catch (error) { setNotice({ kind: 'error', text: String(error) }); }
    finally { setBusy(false); }
  };

  useEffect(() => {
    if (!kpis) { setSocketState('offline'); return; }
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${API ? API.replace(/^http/, 'ws') : `${protocol}//${window.location.host}`}/ws/replay`);
    socket.current = ws; setSocketState('connecting');
    ws.onopen = () => { setSocketState('live'); ws.send(JSON.stringify({ type: 'speed', value: speed })); };
    ws.onmessage = (event) => {
      const message = JSON.parse(event.data) as { type: string; frame?: Frame };
      if (message.type === 'frame' && message.frame) {
        const next = message.frame; setFrame(next);
        setHistory((items) => {
          const value = { time: new Date(next.timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }), meter: next.meter_kw || 0, twin: next.twin_state.reduce((sum, machine) => sum + (machine.power_kw_estimate || 0), 0) };
          return [...items.slice(-95), value];
        });
      } else if (message.type === 'complete') setSocketState('complete');
    };
    ws.onerror = () => setSocketState('offline'); ws.onclose = () => setSocketState((state) => state === 'complete' ? state : 'offline');
    return () => { ws.close(); if (socket.current === ws) socket.current = null; };
  }, [kpis, speed]);

  useEffect(() => { if (socket.current?.readyState === WebSocket.OPEN) socket.current.send(JSON.stringify({ type: 'pause', value: paused })); }, [paused]);
  const machines = frame?.twin_state || [];
  const totalPower = frame?.meter_kw ?? (kpis ? kpis.peak_15min_kw : null);
  const currentHour = new Date(frame?.timestamp || Date.now()).getHours();
  const tariffLabel = currentHour >= 9 && currentHour < 12 || currentHour >= 18 && currentHour < 22 ? 'PEAK TARIFF' : currentHour >= 22 || currentHour < 6 ? 'OFF-PEAK' : 'NORMAL TARIFF';
  const displayedDate = new Date(frame?.timestamp || Date.now()).toLocaleDateString('en-IN', { weekday: 'long', day: '2-digit', month: 'long', year: 'numeric' }).toUpperCase();
  const currentRate = tariffLabel === 'PEAK TARIFF' ? tariff ? tariff.energy_inr_per_kwh.peak : null : tariffLabel === 'OFF-PEAK' ? tariff ? tariff.energy_inr_per_kwh.off_peak : null : tariff ? tariff.energy_inr_per_kwh.normal : null;
  const currentCost = totalPower == null || currentRate == null ? null : totalPower * currentRate;
  const nav: Array<{ label: Screen; icon: string }> = [
    { label: 'Live floor', icon: '◈' }, { label: 'Twin simulation', icon: '⌁' }, { label: 'Recommendations', icon: '✳' }, { label: 'Analytics', icon: '▥' }, { label: 'Impact report', icon: '▤' },
  ];
  const dataReady = !!kpis;

  const decide = async (rec: Recommendation, action: 'apply' | 'reject' | 'schedule') => {
    try {
      if (action === 'schedule') {
        const scheduled = new Date(Date.now() + 60 * 60 * 1000).toISOString();
        await post(`/recommendations/${encodeURIComponent(rec.id)}/schedule`, { scheduled_for: scheduled });
      } else await post(`/recommendations/${encodeURIComponent(rec.id)}/${action}`);
      setNotice({ kind: 'success', text: action === 'apply' ? 'Approved for human review; no plant command was sent.' : action === 'schedule' ? 'Scheduled in this API session; no plant command was sent.' : 'Recommendation dismissed.' });
    } catch (error) { setNotice({ kind: 'error', text: String(error) }); }
  };

  const askCopilot = async (event: React.FormEvent) => {
    event.preventDefault(); if (!chatQuery.trim()) return;
    const query = chatQuery.trim(); setChat((items) => [...items, { role: 'user', text: query }]); setChatQuery(''); setChatBusy(true);
    try { const response = await post<CopilotResponse>('/copilot', { query }); setChat((items) => [...items, { role: 'assistant', text: `${response.answer}${response.tool === 'what_if' ? `\n\nProjection: ${JSON.stringify(response.result)}` : ''}` }]); }
    catch (error) { setChat((items) => [...items, { role: 'assistant', text: `I couldn't complete that request: ${String(error)}` }]); }
    finally { setChatBusy(false); }
  };

  const exportMarkdown = () => {
    const blob = new Blob([reportMarkdown], { type: 'text/markdown;charset=utf-8' }); const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = `energysense-impact-${scenario.toLowerCase()}.md`; anchor.click(); URL.revokeObjectURL(url);
  };
  const analyticsData = useMemo(() => (forecast?.points || []).map((point) => ({ time: new Date(point.timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }), forecast: point.predicted_kw })), [forecast]);

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">E<span>↗</span></div><div><b>ENERGYSENSE</b><small>TWIN CONTROL</small></div></div>
      <div className="plant-switch"><span className="plant-dot" /> <div><small>ACTIVE FACILITY</small><b>Northstar · Bay 01</b></div><span className="chevron">⌄</span></div>
      <div className="nav-caption">WORKSPACE</div>
      <nav>{nav.map((item) => <button className={`nav-item ${screen === item.label ? 'active' : ''}`} key={item.label} onClick={() => setScreen(item.label)}><Icon>{item.icon}</Icon>{item.label}{item.label === 'Recommendations' && recommendations.length > 0 && <span className="nav-count">{recommendations.length}</span>}</button>)}</nav>
      <div className="sidebar-bottom"><div className="help-card"><div className="help-icon">?</div><b>Need a hand?</b><p>Explore a scenario with Twin Copilot.</p><button onClick={() => document.getElementById('copilot-input')?.focus()}>Ask Copilot <span>↗</span></button></div><div className="user-row"><div className="avatar">AS</div><div><b>Arjun Sharma</b><small>Energy manager</small></div><span className="more">···</span></div></div>
    </aside>

    <main className="main-area">
      <header className="topbar"><div className="breadcrumbs">Facilities <span>/</span> Northstar Manufacturing <span>/</span> <b>Bay 01</b></div><div className="top-actions"><Badge /><span className="top-divider"/><button className="icon-button" aria-label="Notifications">♧<i /></button><div className="top-avatar">AS</div></div></header>
      {notice && <div className={`notice ${notice.kind}`} role="status"><span>{notice.kind === 'error' ? '!' : '✓'}</span>{notice.text}<button onClick={() => setNotice(null)}>×</button></div>}
      <div className="content">
        <div className="page-heading"><div><div className="eyebrow">{displayedDate} <span className="live-pill"><i /> LIVE TWIN</span></div><h1>{screen === 'Live floor' ? 'Good morning, Arjun' : screen}</h1><p>{screen === 'Live floor' ? 'Here’s what’s happening across your facility right now.' : 'Explore synthetic plant projections, observations, and decisions.'}</p></div><div className="run-controls"><label className="select-wrap"><span>SCENARIO</span><select value={scenario} onChange={(e) => setScenario(e.target.value)}>{(scenarios.length ? scenarios : [{ id: 'S2', name: 'S2 · Production day' }]).map((item) => <option value={item.id} key={item.id}>{item.id} · {item.name}</option>)}</select></label><label className="seed-wrap"><span>SEED</span><input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))}/></label><button className="primary-button" disabled={busy} onClick={() => void run()}>{busy ? <><span className="spinner"/> Running</> : <>▶ <span>Run simulation</span></>}</button></div></div>

        {screen === 'Live floor' && <>
          <div className="metric-grid"><Metric label="ENERGY TODAY" value={fmt(kpis?.energy_kwh, 0)} unit="kWh" detail="Metered · synthetic run" accent/><Metric label="PEAK DEMAND" value={fmt(kpis?.peak_15min_kw)} unit="kW" detail="15-minute interval"/><Metric label="ENERGY COST" value={money(kpis?.cost_inr)} detail="Tariff-weighted estimate"/><Metric label="CARBON FOOTPRINT" value={fmt(kpis?.co2_kg)} unit="kg CO₂e" detail="Grid factor assumption"/></div>
          <div className="live-layout"><section className="panel floor-panel"><SectionTitle eyebrow="PLANT OVERVIEW" title="Live floor" right={<div className="panel-tools"><span className={`stream-status ${socketState}`}><i />{socketState === 'live' ? 'STREAMING' : socketState.toUpperCase()}</span><button className="text-button" onClick={() => setPaused((v) => !v)}>{paused ? '▶ Resume' : 'Ⅱ Pause'}</button></div>}/>
            <div className="floor-meta"><span><i className="legend-dot run-dot"/> Running</span><span><i className="legend-dot idle-dot"/> Idle / standby</span><span><i className="legend-dot alert-dot"/> Alert</span><span className="floor-timestamp">{frame ? new Date(frame.timestamp).toLocaleString('en-IN') : 'Waiting for replay frame'}</span></div>
            <div className="floor-map"><div className="bay-label">ASSEMBLY BAY 01 <span>· 850 m²</span></div><div className="floor-grid">{(machines.length ? machines : [{ equipment_id: 'CNC-01', state: '—', power_kw_estimate: 0 }, { equipment_id: 'CNC-02', state: '—', power_kw_estimate: 0 }, { equipment_id: 'COMP-01', state: '—', power_kw_estimate: 0 }, { equipment_id: 'HVAC', state: '—', power_kw_estimate: 0 }]).map((machine) => <div className={`machine-card state-${machine.state.toLowerCase()}`} key={machine.equipment_id}><div className="machine-top"><span className="machine-symbol">{machine.equipment_id.startsWith('CNC') ? '▦' : machine.equipment_id === 'HVAC' ? '❄' : '◉'}</span><span className="machine-state"><i/>{titleCase(machine.state)}</span></div><b>{machine.equipment_id}</b><div className="machine-power">{fmt(machine.power_kw_estimate)} <small>kW</small></div><div className="machine-footer"><span>Digital twin estimate</span><span>{machine.confidence ? `${fmt(machine.confidence * 100, 0)}%` : '—'}</span></div></div>)}</div><div className="floor-bottom"><span>⌖ <b>{frame?.cv_events?.filter((event) => event.operator_present).length || 0}</b> operator observations</span><span>▧ {frame?.cv_events?.length || 0} CV events this minute</span><span className="floor-tariff">◉ {tariffLabel}</span></div></div>
          <div className="replay-row"><div><b>Replay controls</b><small>Stream through the synthetic operating day</small></div><div className="replay-buttons"><button className="icon-button small" onClick={() => socket.current?.send(JSON.stringify({ type: 'seek', index: 0 }))}>↶</button>{[1, 10, 30, 60].map((value) => <button key={value} className={`speed-button ${speed === value ? 'selected' : ''}`} onClick={() => setSpeed(value)}>{value}×</button>)}<input aria-label="Replay position" type="range" min="0" max="1439" value={Math.min(1439, history.length)} onChange={(e) => socket.current?.send(JSON.stringify({ type: 'seek', index: Number(e.target.value) }))}/></div></div>
          </section>
          <section className="panel meter-panel"><SectionTitle eyebrow="POWER & COST" title="Main meter" right={<button className="more-button">···</button>}/><div className="meter-number">{fmt(totalPower)}<small>kW</small></div><div className="meter-caption"><span className="meter-pulse"/> Live facility demand</div><div className="meter-chart"><ResponsiveContainer width="100%" height="100%"><AreaChart data={history}><defs><linearGradient id="meterFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#29c88a" stopOpacity={0.28}/><stop offset="95%" stopColor="#29c88a" stopOpacity={0}/></linearGradient></defs><Area type="monotone" dataKey="meter" stroke="#25bd80" strokeWidth={2} fill="url(#meterFill)" isAnimationActive={false}/></AreaChart></ResponsiveContainer></div><div className="meter-axis"><span>REPLAY</span><span>NOW</span></div><div className="cost-callout"><div><small>EST. RUN-RATE COST</small><b>{money(currentCost)}<small> / hour</small></b></div><span>{tariffLabel}</span></div><div className="meter-foot"><span>Tariff rate assumption</span><b>{currentRate == null ? '—' : `₹${fmt(currentRate, 2)}`} / kWh</b></div></section></div>
          <div className="bottom-grid"><section className="panel chart-panel"><SectionTitle eyebrow="TWIN PERFORMANCE" title="Meter vs twin estimate" right={<span className="chart-legend"><i className="legend-line green"/> Main meter <i className="legend-line gray"/> Twin equipment</span>}/><div className="small-chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={history}><CartesianGrid strokeDasharray="3 5" vertical={false}/><XAxis dataKey="time" tickLine={false} axisLine={false}/><YAxis width={42} tickLine={false} axisLine={false}/><Tooltip/><Line dataKey="meter" name="Observed meter kW" stroke="#20bd81" strokeWidth={2} dot={false}/><Line dataKey="twin" name="Estimated equipment kW" stroke="#a4adb6" strokeWidth={1.5} strokeDasharray="5 4" dot={false}/></LineChart></ResponsiveContainer></div><div className="chart-note">Live main-meter load and estimated equipment load. These distinct series are not a validated AI-policy counterfactual.</div></section><section className="panel alert-panel"><SectionTitle eyebrow="ATTENTION" title="Latest observations" right={<button className="text-button" onClick={() => setScreen('Analytics')}>View analytics ↗</button>}/>{frame?.cv_events?.length ? frame.cv_events.slice(0, 3).map((event, index) => <div className="observation" key={`${String(event.timestamp)}-${index}`}><span className="observation-icon">⌖</span><div><b>{String(event.machine_id || event.camera_id || 'Camera observation')}</b><small>{String(event.state || 'operator / zone activity')} · confidence {fmt(Number(event.confidence) * 100, 0)}%</small></div><time>NOW</time></div>) : <div className="empty-state compact"><span>◉</span><b>No CV events in this frame</b><small>Event observations appear here during replay.</small></div>}<div className="alert-foot"><span>Alert threshold baseline</span><b>{anomalies?.events.length || 0} meter events</b></div></section></div>
        </>}

        {screen === 'Twin simulation' && <><div className="metric-grid"><Metric label="BASELINE ENERGY" value={fmt(kpis?.energy_kwh, 0)} unit="kWh" detail="Metered synthetic day"/><Metric label="IDLE WASTE" value={fmt(kpis?.idle_waste_kwh)} unit="kWh" detail="Twin-estimated opportunity" accent/><Metric label="RESTARTS" value={fmt(kpis?.restarts, 0)} detail="State transition estimate"/><Metric label="COMFORT VIOLATIONS" value={fmt(kpis?.comfort_violation_min, 0)} unit="min" detail="Occupied minutes outside band"/></div><section className="panel twin-chart-panel"><SectionTitle eyebrow="LOAD PROJECTION" title="Observed vs equipment estimate" right={<div className="chart-legend"><i className="legend-line green"/> Main meter <i className="legend-line gray"/> Equipment estimate</div>}/><div className="large-chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={history}><CartesianGrid strokeDasharray="3 5" vertical={false}/><XAxis dataKey="time" tickLine={false} axisLine={false}/><YAxis tickLine={false} axisLine={false}/><Tooltip/><Line dataKey="meter" name="Main meter kW" stroke="#20bd81" strokeWidth={2.5} dot={false}/><Line dataKey="twin" name="Twin equipment estimate kW" stroke="#89949d" strokeWidth={2} strokeDasharray="6 4" dot={false}/></LineChart></ResponsiveContainer></div><p className="chart-note">These series are different measurements: facility meter and sum of estimated equipment loads. No validated AI-policy counterfactual or confidence interval is served by the current API.</p></section><div className="twin-info-grid"><section className="panel info-card"><span className="info-icon">⌁</span><div><h3>Replay configuration</h3><p>Scenario <b>{scenario}</b> · seed <b>{seed}</b> · {speed}× speed</p><p>Replay state: <span className={`stream-status ${socketState}`}><i/>{socketState}</span></p></div></section><section className="panel info-card"><span className="info-icon blue">◷</span><div><h3>Predicted vs realized</h3><p>One-day KPI totals are calculated from generated meter, telemetry, schedule, CV, and HVAC data.</p><p>Forecast calibration intervals and realized-policy validation are not available through this API.</p></div></section></div></>}

        {screen === 'Recommendations' && <><div className="recommendation-summary"><div><div className="eyebrow">HUMAN REVIEW QUEUE</div><h2>{recommendations.length} proposals for this run</h2><p>Each action is a twin projection. Approval records intent only; it never actuates equipment.</p></div><span className="review-tag">⌕ REVIEW BEFORE ACTION</span></div>{recommendations.length ? <div className="recommendation-list">{recommendations.map((rec) => <article className="panel recommendation-card" key={rec.id}><div className="rec-heading"><div className="rec-icon">✳</div><div className="rec-title"><span className="eyebrow">{rec.equipment} · {titleCase(rec.action)}</span><h3>{rec.action.replaceAll('_', ' ').toLowerCase().replace(/^\w/, (letter) => letter.toUpperCase())}</h3><p>{rec.duration_min} min · starts {new Date(rec.start).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })}</p></div><span className="confidence">{fmt(rec.confidence * 100, 0)}%<small>CONFIDENCE</small></span></div><div className="rec-impact"><div><small>PROJECTED ENERGY</small><b>{fmt(rec.projected.energy_kwh)} <em>kWh</em></b></div><div><small>PROJECTED SAVINGS</small><b>{money(rec.projected.cost_inr)} <em>est.</em></b></div><div><small>RANGE (P05–P95)</small><b>{fmt(rec.interval.p05.energy_kwh)}–{fmt(rec.interval.p95.energy_kwh)} <em>kWh</em></b></div></div><div className="constraints"><b>Constraint checks</b>{rec.constraints.slice(0, 3).map((item, i) => <span key={i} className={item.passed ? 'passed' : 'failed'}>{item.passed ? '✓' : '!' } {item.rule}</span>)}</div><div className="rec-evidence"><span>Evidence: {Object.keys(rec.evidence || {}).length ? Object.entries(rec.evidence).slice(0, 2).map(([key, value]) => `${key}: ${String(value)}`).join(' · ') : 'No CV thumbnail attached'}</span><span>Revert: {rec.revert_if?.[0] || 'review before execution'}</span></div><div className="rec-actions"><button className="subtle-button" onClick={() => void decide(rec, 'reject')}>Dismiss</button><button className="subtle-button" onClick={() => void decide(rec, 'schedule')}>◷ Schedule +1h</button><button className="primary-button" onClick={() => void decide(rec, 'apply')}>Approve proposal ↗</button></div></article>)}</div> : <div className="panel empty-state"><span>✳</span><b>No proposals available</b><small>Run a scenario to generate its constraint-checked recommendation plan.</small></div>}</>}

        {screen === 'Analytics' && <><div className="analytics-grid"><section className="panel analytics-wide"><SectionTitle eyebrow="SHORT-TERM LOAD" title="Forecast preview" right={<span className="status-tag">{forecast?.method || 'Unavailable'}</span>}/><div className="forecast-chart"><ResponsiveContainer width="100%" height="100%"><AreaChart data={analyticsData}><defs><linearGradient id="forecastFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#4d83f1" stopOpacity={0.22}/><stop offset="95%" stopColor="#4d83f1" stopOpacity={0}/></linearGradient></defs><CartesianGrid strokeDasharray="3 5" vertical={false}/><XAxis dataKey="time" tickLine={false} axisLine={false}/><YAxis tickLine={false} axisLine={false}/><Tooltip/><Area dataKey="forecast" name="Forecast kW" stroke="#4d83f1" fill="url(#forecastFill)" strokeWidth={2}/></AreaChart></ResponsiveContainer></div><p className="chart-note">Moving-average preview only. Forecast intervals and actual holdout comparison are not part of the current REST response.</p></section><section className="panel anomaly-panel"><SectionTitle eyebrow="METER MONITORING" title="Threshold alerts"/><div className="anomaly-count">{anomalies?.events.length ?? '—'}<small>events above 35 kW</small></div><div className="event-list">{anomalies?.events.slice(0, 6).map((event, index) => <div className="event-row" key={`${event.timestamp}-${index}`}><span className="event-dot"/><div><b>{fmt(event.main_kw)} kW</b><small>{new Date(event.timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })} · {event.detector}</small></div><span className="event-score">{fmt(event.score * 100, 0)}%</span></div>) || <div className="empty-state compact"><small>Generate a run to inspect meter alerts.</small></div>}</div></section><section className="panel evaluation-panel"><SectionTitle eyebrow="MODEL EVALUATION" title="Validation coverage"/><div className="validation-row"><span>Forecast vs naive baseline</span><b>Run offline evaluation</b></div><div className="validation-row"><span>CV confusion matrix</span><b>Held-out clips required</b></div><div className="validation-row"><span>Confidence calibration</span><b>Not served by API</b></div><div className="validation-note">The current API does not expose evaluation artifacts. No accuracy, confusion matrix, or calibration scores are inferred from live replay data.</div></section><section className="panel cv-panel"><SectionTitle eyebrow="COMPUTER VISION" title="Recent event signals"/><div className="cv-events">{frame?.cv_events?.slice(0, 5).map((event, index) => <div className="cv-event" key={index}><div className="camera-tile">⌖<small>CV</small></div><div><b>{String(event.camera_id || event.machine_id || event.zone_id || 'Camera')}</b><small>{String(event.state || 'activity')} · {fmt(Number(event.confidence) * 100, 0)}% confidence</small></div></div>) || <p className="muted">Start replay to see machine and zone signals.</p>}</div><div className="validation-note">Event stream contains synthetic observations; video imagery and evidence thumbnails are not provided by this API.</div></section></div></>}

        {screen === 'Impact report' && <><section className="impact-hero"><div className="impact-orbit">↗</div><div><div className="eyebrow">SYNTHETIC RUN · {scenario} · SEED {seed}</div><h2>Facility impact snapshot</h2><p>One-day summary calculated from the selected synthetic scenario.</p></div><button className="primary-button" onClick={exportMarkdown}>⇩ <span>Export Markdown</span></button></section><div className="impact-metrics"><Metric label="TOTAL ENERGY" value={fmt(kpis?.energy_kwh, 0)} unit="kWh"/><Metric label="ENERGY COST" value={money(kpis?.cost_inr)}/><Metric label="CARBON" value={fmt(kpis?.co2_kg)} unit="kg CO₂e"/><Metric label="IDLE WASTE" value={fmt(kpis?.idle_waste_kwh)} unit="kWh"/></div><div className="report-layout"><section className="panel report-panel"><SectionTitle eyebrow="GENERATED REPORT" title="Run summary" right={<button className="text-button" onClick={exportMarkdown}>Download .md ↓</button>}/><pre className="report-text">{report?.markdown || 'Run a scenario to generate the report.'}</pre></section><section className="panel assumptions-panel"><SectionTitle eyebrow="READ THIS FIRST" title="Assumptions & scope"/><div className="assumption-item"><span>01</span><div><b>Synthetic measurements</b><p>All telemetry, events, and outputs are generated for simulation.</p></div></div><div className="assumption-item"><span>02</span><div><b>Projection only</b><p>Recommendations are non-actuating proposals. No equipment commands are issued.</p></div></div><div className="assumption-item"><span>03</span><div><b>Configured tariff</b><p>Cost and carbon use local assumptions, not a live utility or grid feed.</p></div></div><div className="assumption-item"><span>04</span><div><b>Estimated twin state</b><p>Machine states are estimated from generated telemetry and CV event inputs.</p></div></div><div className="assumption-item"><span>05</span><div><b>PDF export</b><p>PDF generation is not available in this dashboard. Export Markdown for sharing.</p></div></div></section></div></>}

        <footer className="footer"><span>ENERGYSENSE TWIN <i>·</i> LOCAL SIMULATION</span><span>All projections are synthetic and for evaluation only.</span></footer>
      </div>
    </main>
    <aside className="copilot"><div className="copilot-head"><div className="copilot-avatar">✳</div><div><b>Twin Copilot</b><small><i/> Connected to synthetic twin</small></div><button className="more-button">···</button></div><div className="copilot-intro"><div className="eyebrow">ENERGY ASSISTANT</div><h2>How can I help?</h2><p>Ask about this run, explore a what-if, or investigate an anomaly.</p></div><div className="chat-area">{chat.length === 0 ? <div className="suggestions"><small>TRY ASKING</small>{['What are today’s KPIs?', 'Show anomalies', 'What if CNC-01 goes to standby?'].map((q) => <button key={q} onClick={() => setChatQuery(q)}>{q}<span>↗</span></button>)}</div> : chat.map((message, index) => <div className={`chat-message ${message.role}`} key={index}>{message.role === 'assistant' && <span className="chat-symbol">✳</span>}<p>{message.text}</p></div>)}{chatBusy && <div className="typing">Copilot is thinking<span>···</span></div>}</div><form className="chat-form" onSubmit={(e) => void askCopilot(e)}><textarea id="copilot-input" placeholder="Ask your twin anything…" value={chatQuery} onChange={(e) => setChatQuery(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void askCopilot(e); } }}/><div className="chat-form-bottom"><span>↵ Enter to send</span><button disabled={chatBusy || !dataReady} aria-label="Send question">↑</button></div></form><div className="copilot-foot">AI can make mistakes. Verify important decisions.</div></aside>
  </div>;
}
