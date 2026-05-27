"use client";

import { useState, useEffect, useMemo } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const COLORS = ["#60a5fa", "#4ade80", "#fbbf24", "#f87171", "#c084fc", "#fb923c", "#a78bfa", "#34d399"];

interface TrendPoint {
  run_id: string;
  score: number;
  baseline: number | null;
  severity: string | null;
  passed: boolean;
  scenarios_total: number;
  scenarios_passed: number;
  created_at: string | null;
  commit: string;
  pr: number | null;
}

export default function TrendsPage() {
  const [trends, setTrends] = useState<TrendPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchTrends() {
      try {
        const apiKey = localStorage.getItem("agentci_api_key") || "";
        const resp = await fetch(`${API_BASE}/api/trends?limit=30`, {
          headers: apiKey ? { "X-API-Key": apiKey } : {},
        });
        if (!resp.ok) throw new Error(`API returned ${resp.status}`);
        const data = await resp.json();
        setTrends(data.trends || []);
        setError(null);
      } catch (e: any) {
        setError(e.message || "Failed to load trends");
      } finally {
        setLoading(false);
      }
    }
    fetchTrends();
  }, []);

  const chartData = useMemo(() =>
    trends.map((t, i) => ({
      run: i + 1,
      score: t.score,
      baseline: t.baseline,
      commit: t.commit,
      pr: t.pr,
    })).reverse(),
  [trends]);

  if (loading) {
    return (
      <div className="max-w-[1100px] mx-auto px-6 py-8 animate-enter">
        <div className="mb-6">
          <h1 className="text-[15px] font-semibold" style={{ color: 'var(--text-0)' }}>Trends</h1>
          <p className="text-[13px] mt-0.5" style={{ color: 'var(--text-2)' }}>Loading…</p>
        </div>
        <div className="rounded-lg border p-5" style={{ borderColor: 'var(--border-subtle)', background: 'var(--bg-1)' }}>
          <div className="h-[340px] flex items-center justify-center">
            <span className="text-[13px]" style={{ color: 'var(--text-3)' }}>Loading chart data…</span>
          </div>
        </div>
      </div>
    );
  }

  if (trends.length === 0) {
    return (
      <div className="max-w-[1100px] mx-auto px-6 py-8 animate-enter">
        <div className="mb-6">
          <h1 className="text-[15px] font-semibold" style={{ color: 'var(--text-0)' }}>Trends</h1>
        </div>
        <div className="rounded-lg border p-8 text-center" style={{ borderColor: 'var(--border-subtle)', background: 'var(--bg-1)' }}>
          <p className="text-[14px] mb-1" style={{ color: 'var(--text-1)' }}>No evaluation history yet.</p>
          <p className="text-[13px]" style={{ color: 'var(--text-3)' }}>Run your first evaluation to see trends.</p>
        </div>
      </div>
    );
  }

  // Compute stats
  const scores = trends.map(t => t.score);
  const mean = scores.reduce((a, b) => a + b, 0) / scores.length;
  const latest = scores[0];
  const delta5 = scores.length > 5 ? latest - scores[5] : 0;

  return (
    <div className="max-w-[1100px] mx-auto px-6 py-8 animate-enter">
      <div className="mb-6">
        <h1 className="text-[15px] font-semibold" style={{ color: 'var(--text-0)' }}>Trends</h1>
        <p className="text-[13px] mt-0.5" style={{ color: 'var(--text-2)' }}>Score over last {trends.length} runs</p>
      </div>

      {error && (
        <div className="rounded-md border px-4 py-3 mb-4" style={{ borderColor: 'var(--red)', background: 'var(--red)11' }}>
          <span className="text-[13px]" style={{ color: 'var(--red)' }}>{error}</span>
        </div>
      )}

      {/* Chart */}
      <div className="rounded-lg border p-5 mb-6" style={{ borderColor: 'var(--border-subtle)', background: 'var(--bg-1)' }}>
        <ResponsiveContainer width="100%" height={340}>
          <LineChart data={chartData}>
            <XAxis dataKey="run" stroke="var(--text-3)" tick={{ fontSize: 10 }} axisLine={{ stroke: 'var(--border-subtle)' }} tickLine={false} />
            <YAxis domain={[0.3, 1.0]} stroke="var(--text-3)" tick={{ fontSize: 10 }} axisLine={{ stroke: 'var(--border-subtle)' }} tickLine={false} width={32} />
            <Tooltip
              contentStyle={{ background: 'var(--bg-2)', border: '1px solid var(--border-default)', borderRadius: 6, fontSize: 11, color: 'var(--text-0)' }}
              labelStyle={{ color: 'var(--text-2)', fontSize: 10 }}
            />
            <ReferenceLine y={0.85} stroke="var(--amber)" strokeDasharray="4 4" strokeOpacity={0.4} />
            <Line type="monotone" dataKey="score" stroke={COLORS[0]} strokeWidth={1.5} dot={false} activeDot={{ r: 3, strokeWidth: 0 }} name="Score" />
            <Line type="monotone" dataKey="baseline" stroke={COLORS[1]} strokeWidth={1} dot={false} strokeDasharray="4 4" name="Baseline" />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-2">
        <div className="rounded-md border p-3" style={{ borderColor: 'var(--border-subtle)', background: 'var(--bg-1)' }}>
          <p className="text-[10px]" style={{ color: 'var(--text-3)' }}>Mean Score</p>
          <p className="mono text-[13px]" style={{ color: 'var(--text-0)' }}>{mean.toFixed(3)}</p>
        </div>
        <div className="rounded-md border p-3" style={{ borderColor: 'var(--border-subtle)', background: 'var(--bg-1)' }}>
          <p className="text-[10px]" style={{ color: 'var(--text-3)' }}>Latest</p>
          <p className="mono text-[13px]" style={{ color: 'var(--text-0)' }}>{latest.toFixed(3)}</p>
        </div>
        <div className="rounded-md border p-3" style={{ borderColor: 'var(--border-subtle)', background: 'var(--bg-1)' }}>
          <p className="text-[10px]" style={{ color: 'var(--text-3)' }}>5-run Δ</p>
          <p className="mono text-[13px]" style={{ color: delta5 >= 0 ? 'var(--green)' : 'var(--red)' }}>
            {delta5 >= 0 ? '+' : ''}{delta5.toFixed(3)}
          </p>
        </div>
      </div>
    </div>
  );
}
