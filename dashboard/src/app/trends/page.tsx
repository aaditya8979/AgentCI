"use client";

import { useState, useMemo } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";

const SCENARIOS = ["greeting_001", "refund_002", "safety_003", "compliance_004", "tool_use_005"];
const COLORS = ["#60a5fa", "#4ade80", "#fbbf24", "#f87171", "#c084fc"];

function seed(s: string) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  return h;
}

function genData(id: string) {
  const base = id.includes("safety") ? 0.88 : id.includes("compliance") ? 0.82 : 0.91;
  const s = seed(id);
  return Array.from({ length: 30 }, (_, i) => {
    const noise = (((s * (i + 1) * 9301 + 49297) % 233280) / 233280 - 0.5) * 0.12;
    const drop = i > 22 && id.includes("compliance") ? -0.25 : 0;
    return { run: i + 1, score: Math.max(0.3, Math.min(1.0, base + noise + drop)) };
  });
}

const DATA: Record<string, { run: number; score: number }[]> = {};
SCENARIOS.forEach(s => { DATA[s] = genData(s); });

export default function TrendsPage() {
  const [selected, setSelected] = useState<string[]>(SCENARIOS.slice(0, 3));

  const merged = useMemo(() =>
    Array.from({ length: 30 }, (_, i) => {
      const pt: Record<string, number> = { run: i + 1 };
      selected.forEach(s => { pt[s] = DATA[s][i].score; });
      return pt;
    }),
  [selected]);

  const toggle = (id: string) => setSelected(p => p.includes(id) ? p.filter(x => x !== id) : [...p, id]);

  return (
    <div className="max-w-[1100px] mx-auto px-6 py-8 animate-enter">
      <div className="mb-6">
        <h1 className="text-[15px] font-semibold" style={{ color: 'var(--text-0)' }}>Trends</h1>
        <p className="text-[13px] mt-0.5" style={{ color: 'var(--text-2)' }}>Score over last 30 runs per scenario</p>
      </div>

      {/* Scenario pills */}
      <div className="flex gap-1.5 mb-5">
        {SCENARIOS.map((s, i) => {
          const active = selected.includes(s);
          return (
            <button key={s} onClick={() => toggle(s)}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[12px] mono transition-colors border"
              style={{
                borderColor: active ? COLORS[i] + '44' : 'var(--border-subtle)',
                background: active ? COLORS[i] + '0d' : 'transparent',
                color: active ? 'var(--text-0)' : 'var(--text-3)',
              }}
            >
              <span className="w-1.5 h-1.5 rounded-full" style={{ background: active ? COLORS[i] : 'var(--text-3)' }} />
              {s}
            </button>
          );
        })}
      </div>

      {/* Chart */}
      <div className="rounded-lg border p-5 mb-6" style={{ borderColor: 'var(--border-subtle)', background: 'var(--bg-1)' }}>
        <ResponsiveContainer width="100%" height={340}>
          <LineChart data={merged}>
            <XAxis dataKey="run" stroke="var(--text-3)" tick={{ fontSize: 10 }} axisLine={{ stroke: 'var(--border-subtle)' }} tickLine={false} />
            <YAxis domain={[0.3, 1.0]} stroke="var(--text-3)" tick={{ fontSize: 10 }} axisLine={{ stroke: 'var(--border-subtle)' }} tickLine={false} width={32} />
            <Tooltip
              contentStyle={{ background: 'var(--bg-2)', border: '1px solid var(--border-default)', borderRadius: 6, fontSize: 11, color: 'var(--text-0)' }}
              labelStyle={{ color: 'var(--text-2)', fontSize: 10 }}
            />
            <ReferenceLine y={0.85} stroke="var(--amber)" strokeDasharray="4 4" strokeOpacity={0.4} />
            {selected.map((s, idx) => {
              const ci = SCENARIOS.indexOf(s);
              return (
                <Line key={s} type="monotone" dataKey={s} stroke={COLORS[ci]} strokeWidth={1.5} dot={false} activeDot={{ r: 3, strokeWidth: 0 }} />
              );
            })}
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Stats row */}
      <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${selected.length}, 1fr)` }}>
        {selected.map((s, idx) => {
          const ci = SCENARIOS.indexOf(s);
          const scores = DATA[s].map(d => d.score);
          const mean = scores.reduce((a, b) => a + b, 0) / scores.length;
          const latest = scores[scores.length - 1];
          const delta5 = latest - scores[Math.max(0, scores.length - 6)];
          return (
            <div key={s} className="rounded-md border p-3" style={{ borderColor: 'var(--border-subtle)', background: 'var(--bg-1)' }}>
              <div className="flex items-center gap-1.5 mb-2">
                <span className="w-1.5 h-1.5 rounded-full" style={{ background: COLORS[ci] }} />
                <span className="mono text-[11px]" style={{ color: 'var(--text-1)' }}>{s}</span>
              </div>
              <div className="flex gap-4">
                <div><p className="text-[10px]" style={{ color: 'var(--text-3)' }}>Mean</p><p className="mono text-[13px]" style={{ color: 'var(--text-0)' }}>{mean.toFixed(3)}</p></div>
                <div><p className="text-[10px]" style={{ color: 'var(--text-3)' }}>Latest</p><p className="mono text-[13px]" style={{ color: 'var(--text-0)' }}>{latest.toFixed(3)}</p></div>
                <div><p className="text-[10px]" style={{ color: 'var(--text-3)' }}>5-run Δ</p><p className="mono text-[13px]" style={{ color: delta5 >= 0 ? 'var(--green)' : 'var(--red)' }}>{delta5 >= 0 ? '+' : ''}{delta5.toFixed(3)}</p></div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
