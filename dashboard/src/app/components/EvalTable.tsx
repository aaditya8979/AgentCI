"use client";

import { useState, useEffect } from "react";
import Link from "next/link";

interface EvalRun {
  id: string;
  repo: string;
  pr: number | null;
  commit: string;
  suite: string;
  score: number | null;
  baseline: number | null;
  delta: number | null;
  status: "completed" | "running" | "failed" | "pending";
  passed: boolean;
  duration_ms: number | null;
  scenarios_total: number;
  scenarios_passed: number;
  created_at: string | null;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function StatusDot({ status, passed }: { status: string; passed: boolean }) {
  if (status === "running") return <span className="inline-block w-2 h-2 rounded-full bg-[var(--blue)] animate-pulse" />;
  if (status === "pending") return <span className="inline-block w-2 h-2 rounded-full bg-[var(--text-3)]" />;
  if (status === "failed" || !passed) return <span className="inline-block w-2 h-2 rounded-full bg-[var(--red)]" />;
  return <span className="inline-block w-2 h-2 rounded-full bg-[var(--green)]" />;
}

function SkeletonRow() {
  return (
    <tr className="border-t" style={{ borderColor: 'var(--border-subtle)' }}>
      {Array.from({ length: 10 }).map((_, i) => (
        <td key={i} className="px-3 py-2.5">
          <div className="h-3 rounded" style={{ background: 'var(--bg-3)', width: `${40 + Math.random() * 40}%` }} />
        </td>
      ))}
    </tr>
  );
}

function formatDuration(ms: number | null): string {
  if (!ms) return "—";
  if (ms < 1000) return `${ms}ms`;
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

function formatAge(iso: string | null): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

export default function EvalTable() {
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");

  async function fetchRuns() {
    try {
      const apiKey = typeof window !== "undefined" ? localStorage.getItem("agentci_api_key") || "" : "";
      const resp = await fetch(`${API_BASE}/api/runs?limit=50`, {
        headers: apiKey ? { "X-API-Key": apiKey } : {},
      });
      if (!resp.ok) throw new Error(`API returned ${resp.status}`);
      const data = await resp.json();
      setRuns(data.runs || []);
      setError(null);
    } catch (e: any) {
      setError(e.message || "Failed to load runs");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchRuns();
    const interval = setInterval(fetchRuns, 30000);
    return () => clearInterval(interval);
  }, []);

  const filtered = runs.filter(r => !q || r.repo.includes(q) || r.suite.includes(q));
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

      {error && (
        <div className="rounded-md border px-4 py-3 mb-3 flex items-center justify-between"
             style={{ borderColor: 'var(--red)', background: 'var(--red)11' }}>
          <span className="text-[13px]" style={{ color: 'var(--red)' }}>{error}</span>
          <button onClick={fetchRuns} className="text-[12px] px-2 py-1 rounded"
                  style={{ background: 'var(--bg-3)', color: 'var(--text-1)' }}>Retry</button>
        </div>
      )}

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
            {loading ? (
              <>
                <SkeletonRow />
                <SkeletonRow />
                <SkeletonRow />
              </>
            ) : filtered.length === 0 ? (
              <tr>
                <td colSpan={10} className="px-4 py-8 text-center text-[13px]" style={{ color: 'var(--text-2)' }}>
                  {q ? "No runs match your filter." : "No evaluation runs yet. Run your first evaluation to see results."}
                </td>
              </tr>
            ) : filtered.map(r => (
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
                <td className="px-3 py-2.5 mono tabular text-[13px] font-medium" style={{ color: r.status === 'running' ? 'var(--text-3)' : (r.score ?? 0) >= 0.85 ? 'var(--green)' : (r.score ?? 0) >= 0.7 ? 'var(--amber)' : 'var(--red)' }}>
                  {r.status === "running" || r.score === null ? "—" : r.score.toFixed(2)}
                </td>
                <td className="px-3 py-2.5 mono tabular text-[12px]" style={{ color: r.delta === null ? 'var(--text-3)' : r.delta >= 0 ? 'var(--green)' : 'var(--red)' }}>
                  {r.delta === null ? "—" : `${r.delta >= 0 ? '+' : ''}${r.delta.toFixed(2)}`}
                </td>
                <td className="px-3 py-2.5 text-[13px]" style={{ color: 'var(--text-1)' }}>{r.scenarios_passed}/{r.scenarios_total}</td>
                <td className="px-3 py-2.5 text-[13px]" style={{ color: 'var(--text-2)' }}>{formatDuration(r.duration_ms)}</td>
                <td className="px-3 py-2.5 text-[12px]" style={{ color: 'var(--text-3)' }}>{formatAge(r.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
