import React, { useState } from "react";
import { ShieldAlert, Lock, AlertTriangle } from "lucide-react";
import { useAuth } from "./lib/AuthContext.jsx";

export default function LoginScreen() {
  const { login, error } = useAuth();
  const [badgeNumber, setBadgeNumber] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!badgeNumber || !password) return;
    setSubmitting(true);
    await login(badgeNumber, password);
    setSubmitting(false);
  }

  return (
    <div
      className="w-full min-h-screen bg-[#0B0F14] text-slate-200 flex items-center justify-center px-4"
      style={{ fontFamily: "Inter, system-ui, sans-serif" }}
    >
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=IBM+Plex+Mono:wght@400;500;600&family=Inter:wght@400;500;600&display=swap');
        .font-display { font-family: 'Barlow Condensed', sans-serif; }
        .font-mono-c { font-family: 'IBM Plex Mono', monospace; }
      `}</style>

      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center gap-2 mb-8">
          <ShieldAlert className="w-8 h-8 text-amber-400" />
          <div className="font-display text-2xl tracking-wide text-slate-100">KSP · CIAP</div>
          <div className="text-[11px] text-slate-500 font-mono-c text-center">
            CRIME INTELLIGENCE &amp; ANALYTICAL PLATFORM
          </div>
        </div>

        <form
          onSubmit={handleSubmit}
          className="bg-[#101620] border border-slate-800 rounded-lg p-6 space-y-4"
        >
          <div>
            <label className="text-[11px] font-mono-c text-slate-500 block mb-1.5">BADGE NUMBER</label>
            <input
              autoFocus
              value={badgeNumber}
              onChange={(e) => setBadgeNumber(e.target.value)}
              placeholder="KSP-1001"
              className="w-full bg-[#161D26] border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 outline-none focus:border-amber-500"
            />
          </div>
          <div>
            <label className="text-[11px] font-mono-c text-slate-500 block mb-1.5">PASSWORD</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              className="w-full bg-[#161D26] border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 outline-none focus:border-amber-500"
            />
          </div>

          {error && (
            <div className="flex items-start gap-2 text-xs text-red-400 bg-red-500/10 border border-red-500/30 rounded px-3 py-2">
              <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full flex items-center justify-center gap-2 text-sm font-medium px-3 py-2.5 rounded bg-amber-400/10 text-amber-400 border border-amber-400/30 hover:bg-amber-400/20 disabled:opacity-50 transition-colors"
          >
            <Lock className="w-3.5 h-3.5" />
            {submitting ? "Authenticating…" : "Sign in"}
          </button>
        </form>

        <div className="mt-5 text-[11px] text-slate-600 font-mono-c text-center leading-relaxed">
          Demo credentials — Officer: KSP-1001 / officer123 · Analyst: KSP-2002 / analyst123
          <br />
          Admin: KSP-3003 / admin123
        </div>
      </div>
    </div>
  );
}
