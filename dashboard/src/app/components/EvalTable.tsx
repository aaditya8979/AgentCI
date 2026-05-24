"use client";

import { useState } from "react";
import Link from "next/link";

interface EvalRun {
  id: string;
  repo: string;
  pr: number | null;
  commit: string;
  suite: string;
  score: number;
  baseline: number | null;
  delta: number | null;
  status: "completed" | "running" | "failed";
  passed: boolean;
  duration: string;
  time: string;
  scenarios: string;
}

const RUNS: EvalRun[] = [
  { id: "a1b2c3d4", repo: "acme/support-agent", pr: 142, commit: "f8e2a1b", suite: "full", score: 0.94, baseline: 0.91, delta: 0.03, status: "completed", passed: true, duration: "2m 14s", time: "3m", scenarios: "24/24" },
  { id: "e5f6g7h8", repo: "acme/support-agent", pr: 141, commit: "3d4c5b6", suite: "full", score: 0.72, baseline: 0.91, delta: -0.19, status: "completed", passed: false, duration: "3m 01s", time: "28m", scenarios: "17/24" },
  { id: "i9j0k1l2", repo: "acme/search-bot", pr: 89, commit: "9a8b7c6", suite: "safety", score: 0.88, baseline: 0.85, delta: 0.03, status: "completed", passed: true, duration: "1m 45s", time: "1h", scenarios: "12/12" },
  { id: "m3n4o5p6", repo: "acme/code-reviewer", pr: 203, commit: "1b2c3d4", suite: "full", score: 0, baseline: null, delta: null, status: "running", passed: false, duration: "—", time: "now", scenarios: "12/50" },
  { id: "q7r8s9t0", repo: "acme/support-agent", pr: 140, commit: "5e6f7g8", suite: "full", score: 0.91, baseline: 0.90, delta: 0.01, status: "completed", passed: true, duration: "2m 08s", time: "2h", scenarios: "24/24" },
  { id: "u1v2w3x4", repo: "acme/search-bot", pr: 88, commit: "h9i0j1k", suite: "full", score: 0.96, baseline: 0.93, delta: 0.03, status: "completed", passed: true, duration: "1m 32s", time: "3h", scenarios: "18/18" },
  { id: "y5z6a7b8", repo: "acme/code-reviewer", pr: 202, commit: "2l3m4n5", suite: "compliance", score: 0.45, baseline: 0.89, delta: -0.44, status: "completed", passed: false, duration: "4m 12s", time: "5h", scenarios: "12/30" },
  { id: "c9d0e1f2", repo: "acme/support-agent", pr: null, commit: "main", suite: "full", score: 0.93, baseline: 0.91, delta: 0.02, status: "completed", passed: true, duration: "2m 20s", time: "6h", scenarios: "24/24" },
];

function StatusDot({ status, passed }: { status: string; passed: boolean }) {
  if (status === "running") return <span className="inline-block w-2 h-2 rounded-full bg-[var(--blue)] animate-pulse" />;
  if (!passed) return <span className="inline-block w-2 h-2 rounded-full bg-[var(--red)]" />;
  return <span className="inline-block w-2 h-2 rounded-full bg-[var(--green)]" />;
}

export default function EvalTable() {
  const [q, setQ] = useState("");
  const filtered = RUNS.filter(r => !q || r.repo.includes(q) || r.suite.includes(q));

  const cols = ["", "Repository", "PR", "SHA", "Suite", "Score", "Δ", "Scenarios", "Duration", "Age"];

  return (
    <div>
      <div className="mb-3">
        <input
          type="text" placeholder="Filter…" value={q} onChange={e => setQ(e.target.value)}
          className="w-64 px-3 py-1.5 rounded-md text-[13px] border outline-none transition-colors"
          style={{ background: 'var(--bg-2)', borderColor: 'var(--border-default)', color: 'var(--text-0)' }}
          onFocus={e => e.currentTarget.style.borderColor = 'var(--border-strong)'}
          onBlur={e => e.currentTarget.style.borderColor = 'var(--border-default)'}
        />
      </div>
      <div className="rounded-lg border overflow-hidden" style={{ borderColor: 'var(--border-subtle)' }}>
        <table className="w-full">
          <thead>
            <tr style={{ background: 'var(--bg-2)' }}>
              {cols.map(c => (
                <th key={c} className="px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wider" style={{ color: 'var(--text-3)' }}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map(r => (
              <tr key={r.id} className="border-t group cursor-pointer transition-colors"
                  style={{ borderColor: 'var(--border-subtle)' }}
                  onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-2)'}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
              >
                <td className="px-3 py-2.5 w-8"><StatusDot status={r.status} passed={r.passed} /></td>
                <td className="px-3 py-2.5">
                  <Link href={`/runs/${r.id}`} className="text-[13px] font-medium hover:underline" style={{ color: 'var(--text-0)' }}>{r.repo}</Link>
                </td>
                <td className="px-3 py-2.5 text-[13px]" style={{ color: r.pr ? 'var(--text-1)' : 'var(--text-3)' }}>{r.pr ? `#${r.pr}` : "—"}</td>
                <td className="px-3 py-2.5 mono text-[12px]" style={{ color: 'var(--text-2)' }}>{r.commit}</td>
                <td className="px-3 py-2.5"><span className="text-[11px] px-1.5 py-0.5 rounded" style={{ background: 'var(--bg-3)', color: 'var(--text-2)' }}>{r.suite}</span></td>
                <td className="px-3 py-2.5 mono tabular text-[13px] font-medium" style={{ color: r.status === 'running' ? 'var(--text-3)' : r.score >= 0.85 ? 'var(--green)' : r.score >= 0.7 ? 'var(--amber)' : 'var(--red)' }}>
                  {r.status === "running" ? "—" : r.score.toFixed(2)}
                </td>
                <td className="px-3 py-2.5 mono tabular text-[12px]" style={{ color: r.delta === null ? 'var(--text-3)' : r.delta >= 0 ? 'var(--green)' : 'var(--red)' }}>
                  {r.delta === null ? "—" : `${r.delta >= 0 ? '+' : ''}${r.delta.toFixed(2)}`}
                </td>
                <td className="px-3 py-2.5 text-[13px]" style={{ color: 'var(--text-1)' }}>{r.scenarios}</td>
                <td className="px-3 py-2.5 text-[13px]" style={{ color: 'var(--text-2)' }}>{r.duration}</td>
                <td className="px-3 py-2.5 text-[12px]" style={{ color: 'var(--text-3)' }}>{r.time}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
