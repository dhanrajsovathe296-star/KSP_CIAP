import React, { useState, useEffect, useMemo, useRef, useCallback } from "react";
import {
  AreaChart, Area, BarChart, Bar, Cell, LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, Legend
} from "recharts";
import {
  ShieldAlert, MapPin, Network, TrendingUp, Bell, Database,
  Radio, Lock, ChevronRight, X, Search, Users, Crosshair, Clock, LogOut
} from "lucide-react";
import { useAuth } from "./lib/AuthContext.jsx";
import { UnauthorizedError, ApiError } from "./lib/api.js";
import { latLonToXY } from "./lib/geo.js";
import * as api from "./lib/api.js";

/* ---------------------------------------------------------
   KSP CIAP — Crime Intelligence & Analytical Platform
   Connected to the FastAPI backend: geospatial hotspots,
   link analysis, predictive risk scoring, alerting, and RBAC
   are all backed by live API data (see src/lib/api.js).
--------------------------------------------------------- */

const ROLE_LABELS = {
  officer: "Field Officer",
  analyst: "Intelligence Analyst",
  admin: "Administrator",
};

// ---------- Force-directed graph (lightweight, no d3 dependency) ----------
function ForceGraph({ data, width = 640, height = 420, onSelect, selected }) {
  const [positions, setPositions] = useState(null);
  const rafRef = useRef(null);

  useEffect(() => {
    if (!data || data.nodes.length === 0) {
      setPositions([]);
      return;
    }
    let seed = 7;
    function rnd() {
      seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    }
    let nodes = data.nodes.map(n => ({
      ...n,
      x: width / 2 + (rnd() - 0.5) * width * 0.7,
      y: height / 2 + (rnd() - 0.5) * height * 0.7,
      vx: 0, vy: 0,
    }));
    const idIndex = Object.fromEntries(nodes.map((n, i) => [n.id, i]));
    const links = data.links.map(l => ({ ...l, s: idIndex[l.source], t: idIndex[l.target] }));

    let tick = 0;
    function step() {
      tick++;
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i], b = nodes[j];
          let dx = a.x - b.x, dy = a.y - b.y;
          let dist2 = dx * dx + dy * dy || 0.01;
          let force = 900 / dist2;
          let dist = Math.sqrt(dist2);
          dx /= dist; dy /= dist;
          a.vx += dx * force; a.vy += dy * force;
          b.vx -= dx * force; b.vy -= dy * force;
        }
      }
      links.forEach(l => {
        const a = nodes[l.s], b = nodes[l.t];
        if (!a || !b) return;
        let dx = b.x - a.x, dy = b.y - a.y;
        let dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
        const target = 90;
        let force = (dist - target) * 0.02;
        dx /= dist; dy /= dist;
        a.vx += dx * force; a.vy += dy * force;
        b.vx -= dx * force; b.vy -= dy * force;
      });
      nodes.forEach(n => {
        n.vx += (width / 2 - n.x) * 0.001;
        n.vy += (height / 2 - n.y) * 0.001;
        n.vx *= 0.85; n.vy *= 0.85;
        n.x += n.vx; n.y += n.vy;
        n.x = Math.max(24, Math.min(width - 24, n.x));
        n.y = Math.max(24, Math.min(height - 24, n.y));
      });
      if (tick < 220) {
        rafRef.current = requestAnimationFrame(step);
        if (tick % 3 === 0) setPositions(nodes.map(n => ({ ...n })));
      } else {
        setPositions(nodes.map(n => ({ ...n })));
      }
    }
    step();
    return () => cancelAnimationFrame(rafRef.current);
  }, [data, width, height]);

  if (!positions) return <div className="flex items-center justify-center h-full text-slate-500 text-sm font-mono">initializing graph…</div>;
  if (positions.length === 0) return <div className="flex items-center justify-center h-full text-slate-500 text-sm font-mono">no linked entities yet</div>;

  const byId = Object.fromEntries(positions.map(n => [n.id, n]));

  return (
    <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} className="select-none">
      {data.links.map((l, i) => {
        const a = byId[l.source], b = byId[l.target];
        if (!a || !b) return null;
        const dim = selected && a.id !== selected && b.id !== selected;
        return (
          <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
            stroke={l.assoc ? "#F2A93C" : "#3E8E8A"}
            strokeOpacity={dim ? 0.08 : 0.45}
            strokeWidth={Math.min(4, 0.6 + l.weight * 0.35)} />
        );
      })}
      {positions.map(n => {
        const dim = selected && n.id !== selected && !data.links.some(l =>
          (l.source === selected && l.target === n.id) || (l.target === selected && l.source === n.id));
        return (
          <g key={n.id} transform={`translate(${n.x},${n.y})`} className="cursor-pointer"
             onClick={() => onSelect(n.id === selected ? null : n.id)}>
            <circle r={n.type === "suspect" ? 9 : 7}
              fill={n.type === "suspect" ? "#D64545" : "#2A8C8C"}
              fillOpacity={dim ? 0.25 : 0.9}
              stroke={n.id === selected ? "#F2A93C" : "transparent"} strokeWidth={2.5} />
            <text x={0} y={n.type === "suspect" ? 20 : 18} textAnchor="middle"
              fontSize="9" fontFamily="IBM Plex Mono, monospace"
              fill={dim ? "#4a5568" : "#cbd5e1"}>{n.label}</text>
          </g>
        );
      })}
    </svg>
  );
}

// ---------- Risk gauge (signature element) ----------
function RiskGauge({ score, label, pulsing }) {
  const pct = Math.min(100, Math.max(0, score));
  const r = 46, c = 2 * Math.PI * r;
  const offset = c - (pct / 100) * c;
  const color = pct > 75 ? "#D64545" : pct > 45 ? "#F2A93C" : "#2A8C8C";
  return (
    <div className="flex flex-col items-center gap-1">
      <div className="relative w-28 h-28">
        {pulsing && pct > 75 && (
          <div className="absolute inset-0 rounded-full animate-ping bg-red-500/20" />
        )}
        <svg width="112" height="112" viewBox="0 0 112 112" className="-rotate-90">
          <circle cx="56" cy="56" r={r} fill="none" stroke="#1E2733" strokeWidth="10" />
          <circle cx="56" cy="56" r={r} fill="none" stroke={color} strokeWidth="10"
            strokeDasharray={c} strokeDashoffset={offset} strokeLinecap="round"
            style={{ transition: "stroke-dashoffset 0.6s ease" }} />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="font-mono text-2xl font-semibold" style={{ color }}>{Math.round(pct)}</span>
          <span className="text-[9px] text-slate-500 tracking-wider">RISK</span>
        </div>
      </div>
      <span className="text-xs text-slate-400 font-medium tracking-wide">{label}</span>
    </div>
  );
}

export default function CIAPDashboard() {
  const { user, logout } = useAuth();
  const [tab, setTab] = useState("geo");
  const [hour, setHour] = useState(21);
  const [playing, setPlaying] = useState(false);
  const [selectedNode, setSelectedNode] = useState(null);
  const [now, setNow] = useState(new Date());

  // --- live data state ---
  const [districts, setDistricts] = useState([]);
  const [hotspotMatrix, setHotspotMatrix] = useState([]);
  const [riskByDistrict, setRiskByDistrict] = useState([]);
  const [trendData, setTrendData] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [graphData, setGraphData] = useState({ nodes: [], links: [] });
  const [ingestStatus, setIngestStatus] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => setHour(h => (h + 1) % 24), 700);
    return () => clearInterval(t);
  }, [playing]);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [districtsRes, matrixRes, riskRes, trendRes, alertsRes, graphRes, ingestRes] =
        await Promise.all([
          api.getDistricts(),
          api.getHotspotMatrix(),
          api.getRiskScores(),
          api.getIncidentsTrend(24),
          api.getAlerts(),
          api.getFullGraph(),
          api.getIngestStatus(),
        ]);
      setDistricts(districtsRes);
      setHotspotMatrix(matrixRes);
      setRiskByDistrict(riskRes);
      setTrendData(trendRes);
      setAlerts(alertsRes);
      setGraphData(graphRes);
      setIngestStatus(ingestRes);
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        logout();
        return;
      }
      setLoadError(err.message || "Failed to load dashboard data");
    } finally {
      setLoading(false);
    }
  }, [logout]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  // districts positioned on the 0-100 map using real lat/lon
  const positionedDistricts = useMemo(
    () => districts.map(d => ({ ...d, ...latLonToXY(d.lat ?? 14.5, d.lon ?? 76) })),
    [districts]
  );

  // merge the precomputed 24h hotspot matrix with district positions for the
  // selected hour — purely local, so the time-slider/animation never refetches
  const heatData = useMemo(() => {
    return positionedDistricts.map(d => {
      const row = hotspotMatrix.find(m => m.district === d.name);
      const value = row ? row.hours[hour] : 0;
      return { ...d, value };
    });
  }, [positionedDistricts, hotspotMatrix, hour]);
  const maxVal = Math.max(1, ...heatData.map(d => d.value));

  async function handleAckAlert(id) {
    try {
      const updated = await api.ackAlert(id);
      setAlerts(a => a.map(al => (al.id === id ? updated : al)));
    } catch (err) {
      if (err instanceof UnauthorizedError) logout();
      else setLoadError(err.message);
    }
  }

  const permissions = user?.permissions || [];
  const canAssign = permissions.includes("assign");
  const canDismiss = permissions.includes("dismiss");

  const NAV = [
    { id: "geo", label: "Geospatial Hotspots", icon: MapPin },
    { id: "graph", label: "Link Analysis", icon: Network },
    { id: "predict", label: "Predictive Risk", icon: TrendingUp },
    { id: "alerts", label: "Alert Center", icon: Bell, badge: alerts.filter(a => !a.acknowledged).length },
    { id: "ingest", label: "Data Ingestion", icon: Database },
  ];

  const topRiskDistricts = useMemo(
    () => [...riskByDistrict].sort((a, b) => b.score - a.score).slice(0, 4),
    [riskByDistrict]
  );

  return (
    <div className="w-full min-h-screen bg-[#0B0F14] text-slate-200" style={{ fontFamily: "Inter, system-ui, sans-serif" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=IBM+Plex+Mono:wght@400;500;600&family=Inter:wght@400;500;600&display=swap');
        .font-display { font-family: 'Barlow Condensed', sans-serif; }
        .font-mono-c { font-family: 'IBM Plex Mono', monospace; }
      `}</style>

      {/* Top status bar */}
      <div className="flex items-center justify-between px-5 py-2.5 border-b border-slate-800 bg-[#0D1218]">
        <div className="flex items-center gap-3">
          <ShieldAlert className="w-5 h-5 text-amber-400" />
          <div className="leading-tight">
            <div className="font-display text-lg tracking-wide text-slate-100">KSP · CIAP</div>
            <div className="text-[10px] text-slate-500 -mt-1 font-mono-c">CRIME INTELLIGENCE &amp; ANALYTICAL PLATFORM</div>
          </div>
        </div>
        <div className="flex items-center gap-5">
          <div className="hidden sm:flex items-center gap-1.5 text-[11px] font-mono-c text-slate-400">
            <Clock className="w-3.5 h-3.5" />
            {now.toLocaleTimeString("en-IN", { hour12: false })}
          </div>
          <div className="flex items-center gap-1.5 text-[11px] font-mono-c">
            <Radio className="w-3.5 h-3.5 text-emerald-400" />
            <span className="text-emerald-400">LIVE</span>
          </div>
          <div className="flex items-center gap-2 bg-[#161D26] border border-slate-700 rounded px-2.5 py-1 text-xs text-slate-200">
            <span>{user ? ROLE_LABELS[user.role] || user.role : ""}</span>
            <span className="text-slate-600">·</span>
            <span className="text-slate-400">{user?.full_name}</span>
          </div>
          <button
            onClick={logout}
            title="Sign out"
            className="flex items-center gap-1.5 text-[11px] font-mono-c text-slate-500 hover:text-amber-400 transition-colors"
          >
            <LogOut className="w-3.5 h-3.5" /> SIGN OUT
          </button>
        </div>
      </div>

      {loadError && (
        <div className="px-5 py-2 bg-red-500/10 border-b border-red-500/30 text-xs text-red-400 flex items-center justify-between">
          <span>{loadError}</span>
          <button onClick={loadAll} className="font-mono-c underline hover:text-red-300">retry</button>
        </div>
      )}

      <div className="flex">
        {/* Sidebar */}
        <div className="w-56 border-r border-slate-800 min-h-[calc(100vh-49px)] bg-[#0D1218] py-4">
          {NAV.map(item => {
            const Icon = item.icon;
            const active = tab === item.id;
            return (
              <button key={item.id} onClick={() => setTab(item.id)}
                className={`w-full flex items-center gap-2.5 px-5 py-3 text-sm text-left transition-colors relative
                  ${active ? "text-amber-400 bg-amber-400/[0.06]" : "text-slate-400 hover:text-slate-200 hover:bg-white/[0.02]"}`}>
                {active && <span className="absolute left-0 top-0 bottom-0 w-[3px] bg-amber-400" />}
                <Icon className="w-4 h-4" />
                <span className="font-medium">{item.label}</span>
                {item.badge > 0 && (
                  <span className="ml-auto text-[10px] font-mono-c bg-red-500/20 text-red-400 px-1.5 py-0.5 rounded">{item.badge}</span>
                )}
              </button>
            );
          })}
          <div className="mt-6 mx-5 p-3 rounded bg-[#141B24] border border-slate-800">
            <div className="flex items-center gap-1.5 text-[10px] text-slate-500 font-mono-c mb-1">
              <Lock className="w-3 h-3" /> ACCESS LEVEL
            </div>
            <div className="text-xs text-slate-300">{permissions.join(" · ") || "—"}</div>
          </div>
        </div>

        {/* Main content */}
        <div className="flex-1 p-6 overflow-x-hidden">
          {loading && (
            <div className="flex items-center justify-center h-64 text-slate-500 text-sm font-mono-c">
              loading dashboard data…
            </div>
          )}

          {!loading && tab === "geo" && (
            <section>
              <Header title="Geospatial Hotspot Engine" sub="24-hour crime density across districts" />
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 mt-5">
                <div className="lg:col-span-2 bg-[#101620] border border-slate-800 rounded-lg p-4">
                  <div className="relative w-full aspect-[4/3] bg-[#0B0F14] rounded overflow-hidden border border-slate-800">
                    <svg viewBox="0 0 100 100" className="w-full h-full">
                      <defs>
                        <radialGradient id="hot" cx="50%" cy="50%" r="50%">
                          <stop offset="0%" stopColor="#D64545" stopOpacity="0.9" />
                          <stop offset="100%" stopColor="#D64545" stopOpacity="0" />
                        </radialGradient>
                      </defs>
                      {heatData.map(d => {
                        const intensity = d.value / maxVal;
                        return (
                          <g key={d.id}>
                            <circle cx={d.x} cy={d.y} r={6 + intensity * 14} fill="url(#hot)" opacity={0.35 + intensity * 0.5} />
                            <circle cx={d.x} cy={d.y} r={1.6} fill={intensity > 0.7 ? "#F2A93C" : "#3E8E8A"} />
                          </g>
                        );
                      })}
                    </svg>
                    <div className="absolute bottom-2 right-2 text-[10px] font-mono-c text-slate-500 bg-black/40 px-2 py-1 rounded">
                      {String(hour).padStart(2, "0")}:00 IST · live incident data
                    </div>
                  </div>
                  <div className="flex items-center gap-3 mt-4">
                    <button onClick={() => setPlaying(p => !p)}
                      className="text-xs font-mono-c px-3 py-1.5 rounded bg-amber-400/10 text-amber-400 border border-amber-400/30 hover:bg-amber-400/20">
                      {playing ? "PAUSE" : "PLAY"} 24H
                    </button>
                    <input type="range" min={0} max={23} value={hour}
                      onChange={e => setHour(Number(e.target.value))}
                      className="flex-1 accent-amber-400" />
                    <span className="font-mono-c text-sm text-slate-300 w-14 text-right">{String(hour).padStart(2, "0")}:00</span>
                  </div>
                </div>
                <div className="bg-[#101620] border border-slate-800 rounded-lg p-4">
                  <div className="text-xs text-slate-500 font-mono-c mb-3">DISTRICT DENSITY — THIS HOUR</div>
                  <div className="space-y-2.5 max-h-[360px] overflow-y-auto pr-1">
                    {[...heatData].sort((a, b) => b.value - a.value).map(d => (
                      <div key={d.id} className="flex items-center gap-2">
                        <span className="text-xs text-slate-300 w-28 truncate">{d.name}</span>
                        <div className="flex-1 h-2 bg-[#0B0F14] rounded overflow-hidden">
                          <div className="h-full rounded" style={{
                            width: `${(d.value / maxVal) * 100}%`,
                            background: d.value / maxVal > 0.7 ? "#D64545" : "#3E8E8A"
                          }} />
                        </div>
                        <span className="text-xs font-mono-c text-slate-400 w-8 text-right">{d.value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </section>
          )}

          {!loading && tab === "graph" && (
            <section>
              <Header title="Graph-Based Link Analysis" sub="Suspects, recurring locations, and associative patterns" />
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 mt-5">
                <div className="lg:col-span-2 bg-[#101620] border border-slate-800 rounded-lg p-2">
                  <ForceGraph data={graphData} onSelect={setSelectedNode} selected={selectedNode} />
                </div>
                <div className="bg-[#101620] border border-slate-800 rounded-lg p-4">
                  <div className="text-xs text-slate-500 font-mono-c mb-3">NODE INSPECTOR</div>
                  {selectedNode ? (
                    <NodeInspector id={selectedNode} data={graphData} />
                  ) : (
                    <div className="text-sm text-slate-500 flex items-center gap-2"><Crosshair className="w-4 h-4" /> Select a node to inspect connections</div>
                  )}
                  <div className="mt-5 pt-4 border-t border-slate-800 text-[11px] text-slate-500 space-y-1.5">
                    <div className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-red-500 inline-block" /> Suspect</div>
                    <div className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-teal-500 inline-block" /> Location</div>
                    <div className="flex items-center gap-1.5"><span className="w-3 h-0.5 bg-amber-400 inline-block" /> Suspect association</div>
                    <div className="flex items-center gap-1.5"><span className="w-3 h-0.5 bg-teal-600 inline-block" /> Location visit</div>
                  </div>
                </div>
              </div>
            </section>
          )}

          {!loading && tab === "predict" && (
            <section>
              <Header title="AI Predictive Dashboard" sub="Risk scoring vs. historical baseline, anomaly triggers" />
              <div className="flex flex-wrap gap-6 mt-5 bg-[#101620] border border-slate-800 rounded-lg p-5">
                {topRiskDistricts.map((d, i) => (
                  <RiskGauge key={d.district} score={d.score} label={d.district} pulsing={i === 0} />
                ))}
              </div>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 mt-5">
                <div className="bg-[#101620] border border-slate-800 rounded-lg p-4">
                  <div className="text-xs text-slate-500 font-mono-c mb-3">CRIME TREND VS BASELINE (24H)</div>
                  <ResponsiveContainer width="100%" height={220}>
                    <AreaChart data={trendData}>
                      <CartesianGrid stroke="#1E2733" strokeDasharray="3 3" />
                      <XAxis dataKey="hour" tick={{ fontSize: 10, fill: "#64748b" }} interval={3} />
                      <YAxis tick={{ fontSize: 10, fill: "#64748b" }} />
                      <Tooltip contentStyle={{ background: "#141B24", border: "1px solid #2a3441", fontSize: 12 }} />
                      <Area type="monotone" dataKey="baseline" stroke="#3E8E8A" fill="#3E8E8A" fillOpacity={0.15} />
                      <Area type="monotone" dataKey="actual" stroke="#D64545" fill="#D64545" fillOpacity={0.25} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
                <div className="bg-[#101620] border border-slate-800 rounded-lg p-4">
                  <div className="text-xs text-slate-500 font-mono-c mb-3">RISK SCORE BY DISTRICT</div>
                  <ResponsiveContainer width="100%" height={220}>
                    <BarChart data={riskByDistrict.map(r => ({ name: r.district, score: r.score }))}>
                      <CartesianGrid stroke="#1E2733" strokeDasharray="3 3" />
                      <XAxis dataKey="name" tick={{ fontSize: 10, fill: "#64748b" }} />
                      <YAxis tick={{ fontSize: 10, fill: "#64748b" }} />
                      <Tooltip contentStyle={{ background: "#141B24", border: "1px solid #2a3441", fontSize: 12 }} />
                      <Bar dataKey="score" radius={[3, 3, 0, 0]}>
                        {riskByDistrict.map((r, i) => (
                          <Cell key={i} fill={r.score > 75 ? "#D64545" : r.score > 50 ? "#F2A93C" : "#3E8E8A"} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </section>
          )}

          {!loading && tab === "alerts" && (
            <section>
              <Header title="Alert Center" sub="Real-time anomaly notifications requiring triage" />
              <div className="mt-5 space-y-3">
                {alerts.map(a => (
                  <div key={a.id} className={`flex items-start gap-3 p-4 rounded-lg border bg-[#101620] transition-opacity
                    ${a.acknowledged ? "opacity-40 border-slate-800" : a.level === "critical" ? "border-red-500/40" : a.level === "warning" ? "border-amber-500/30" : "border-slate-800"}`}>
                    <span className={`mt-0.5 w-2 h-2 rounded-full flex-shrink-0
                      ${a.level === "critical" ? "bg-red-500 animate-pulse" : a.level === "warning" ? "bg-amber-400" : "bg-slate-500"}`} />
                    <div className="flex-1">
                      <div className="flex items-center gap-2 text-sm">
                        <span className="font-medium text-slate-100">{a.district}</span>
                        <span className="text-[10px] font-mono-c text-slate-500">{new Date(a.created_at).toLocaleString("en-IN")}</span>
                      </div>
                      <div className="text-sm text-slate-400 mt-0.5">{a.message}</div>
                    </div>
                    {!a.acknowledged && canDismiss && (
                      <button onClick={() => handleAckAlert(a.id)}
                        className="text-[11px] font-mono-c px-2.5 py-1 rounded border border-slate-700 text-slate-400 hover:text-amber-400 hover:border-amber-400/40 flex items-center gap-1">
                        <X className="w-3 h-3" /> ACK
                      </button>
                    )}
                    {!a.acknowledged && !canDismiss && (
                      <span className="text-[10px] font-mono-c text-slate-600">view only</span>
                    )}
                  </div>
                ))}
                {alerts.length === 0 && (
                  <div className="text-sm text-slate-500 font-mono-c">No alerts.</div>
                )}
              </div>
            </section>
          )}

          {!loading && tab === "ingest" && (
            <section>
              <Header title="Data Ingestion Layer" sub="District Excel/CSV feeds → cleaned → central store" />
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-5">
                {ingestStatus.map(f => (
                  <div key={f.district} className="flex items-center justify-between bg-[#101620] border border-slate-800 rounded-lg px-4 py-3">
                    <div>
                      <div className="text-sm text-slate-200">{f.district} district feed</div>
                      <div className="text-[11px] font-mono-c text-slate-500">
                        {f.minutes_ago === null ? "no sync recorded" : `last sync ${f.minutes_ago} min ago`} · {f.rows} rows
                      </div>
                    </div>
                    <span className={`text-[10px] font-mono-c px-2 py-1 rounded ${f.status === "SYNCED" ? "bg-teal-500/10 text-teal-400" : f.status === "SCHEMA DRIFT" ? "bg-red-500/10 text-red-400" : "bg-slate-500/10 text-slate-400"}`}>
                      {f.status}
                    </span>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

function NodeInspector({ id, data }) {
  const node = data.nodes.find(n => n.id === id);
  const connections = data.links.filter(l => l.source === id || l.target === id);
  if (!node) return null;
  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        {node.type === "suspect" ? <Users className="w-4 h-4 text-red-400" /> : <MapPin className="w-4 h-4 text-teal-400" />}
        <span className="text-sm font-medium text-slate-100">{node.label}</span>
      </div>
      <div className="text-[11px] text-slate-500 font-mono-c mb-2">{connections.length} LINKED ENTITIES</div>
      <div className="space-y-1.5">
        {connections.map((c, i) => {
          const otherId = c.source === id ? c.target : c.source;
          const other = data.nodes.find(n => n.id === otherId);
          return (
            <div key={i} className="flex items-center gap-2 text-xs text-slate-400">
              <ChevronRight className="w-3 h-3 text-slate-600" />
              {other?.label} <span className="text-slate-600 font-mono-c">×{c.weight}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Header({ title, sub }) {
  return (
    <div>
      <h1 className="font-display text-3xl text-slate-100 tracking-wide">{title}</h1>
      <p className="text-sm text-slate-500 mt-0.5">{sub}</p>
    </div>
  );
}
