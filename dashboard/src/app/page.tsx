"use client";

import { useState, useEffect } from "react";
import EvalTable from "./components/EvalTable";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Stats {
  total_runs: number;
  completed_runs: number;
  pass_rate: number;
  avg_score: number;
  regressions: number;
  repos: number;
}

export default function HomePage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchStats() {
      try {
        const apiKey = localStorage.getItem("agentci_api_key") || "";
        const resp = await fetch(`${API_BASE}/api/stats`, {
          headers: apiKey ? { "X-API-Key": apiKey } : {},
        });
        if (resp.ok) {
          setStats(await resp.json());
        }
      } catch {
        // Stats are non-critical — table still loads
      } finally {
        setLoading(false);
      }
    }
    fetchStats();
  }, []);

  return (
    <div className="max-w-[1200px] mx-auto px-6 py-8 animate-enter">
      {/* Header */}
      <div className="flex items-end justify-between mb-6">
        <div>
          <h1 className="text-[15px] font-semibold" style={{ color: 'var(--text-0)' }}>Evaluation Runs</h1>
          <p className="text-[13px] mt-0.5" style={{ color: 'var(--text-2)' }}>
            {loading ? "Loading…" : stats
              ? `${stats.total_runs} runs across ${stats.repos} repositories`
              : "No data available"}
          </p>
        </div>
        <div className="flex items-center gap-4">
          <Stat label="Pass rate" value={loading ? "—" : stats ? `${(stats.pass_rate * 100).toFixed(0)}%` : "—"} />
          <Stat label="Avg score" value={loading ? "—" : stats ? stats.avg_score.toFixed(2) : "—"} />
          <Stat label="Regressions" value={loading ? "—" : stats ? String(stats.regressions) : "—"} alert={!!stats && stats.regressions > 0} />
        </div>
      </div>

      <EvalTable />
    </div>
  );
}

function Stat({ label, value, alert }: { label: string; value: string; alert?: boolean }) {
  return (
    <div className="text-right">
      <p className="text-[11px] uppercase tracking-wider" style={{ color: 'var(--text-3)' }}>{label}</p>
      <p className="text-[15px] font-semibold mono tabular" style={{ color: alert ? 'var(--red)' : 'var(--text-0)' }}>{value}</p>
    </div>
  );
}
