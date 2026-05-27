"use client";

import { use, useState, useEffect } from "react";
import Link from "next/link";
import ScoreBar from "../../components/ScoreBar";
import TraceViewer from "../../components/TraceViewer";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface ScenarioResult {
  id: string;
  scenario_id: string;
  category: string | null;
  difficulty: string | null;
  consensus_score: number | null;
  passed: boolean;
  ija: number | null;
  tiebreaker_used: boolean;
  tier: string | null;
  duration_ms: number | null;
  cost_usd: number | null;
  agent_output: string;
  agent_error: string | null;
  judge_scores: Record<string, any> | null;
}

interface RunDetail {
  id: string;
  repo: string;
  pr: number | null;
  commit: string;
  suite: string;
  status: string;
  score: number | null;
  baseline: number | null;
  p_value: number | null;
  cohens_d: number | null;
  severity: string | null;
  passed: boolean;
  scenarios_total: number;
  scenarios_passed: number;
  duration_ms: number | null;
  created_at: string | null;
  completed_at: string | null;
  scenarios: ScenarioResult[];
}

export default function RunDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchRun() {
      try {
        const apiKey = localStorage.getItem("agentci_api_key") || "";
        const resp = await fetch(`${API_BASE}/api/runs/${id}`, {
          headers: apiKey ? { "X-API-Key": apiKey } : {},
        });
        if (!resp.ok) throw new Error(resp.status === 404 ? `Run ${id} not found` : `API returned ${resp.status}`);
        setRun(await resp.json());
        setError(null);
      } catch (e: any) {
        setError(e.message || "Failed to load run");
      } finally {
        setLoading(false);
      }
    }
    fetchRun();
  }, [id]);

  if (loading) {
    return (
      <div className="max-w-[1100px] mx-auto px-6 py-8 animate-enter">
        <p className="text-[13px]" style={{ color: 'var(--text-2)' }}>Loading run details…</p>
      </div>
    );
  }

  if (error || !run) {
    return (
      <div className="max-w-[1100px] mx-auto px-6 py-8 animate-enter">
        <div className="rounded-md border px-4 py-3" style={{ borderColor: 'var(--red)', background: 'var(--red)11' }}>
          <span className="text-[13px]" style={{ color: 'var(--red)' }}>{error || "Run not found"}</span>
        </div>
        <Link href="/" className="text-[13px] mt-3 inline-block hover:underline" style={{ color: 'var(--text-2)' }}>← Back to runs</Link>
      </div>
    );
  }

  function formatDuration(ms: number | null): string {
    if (!ms) return "—";
    const s = Math.floor(ms / 1000);
    if (s < 60) return `${s}s`;
    return `${Math.floor(s / 60)}m ${s % 60}s`;
  }

  return (
    <div className="max-w-[1100px] mx-auto px-6 py-8 animate-enter">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 mb-5 text-[13px]">
        <Link href="/" style={{ color: 'var(--text-2)' }} className="hover:underline">Runs</Link>
        <span style={{ color: 'var(--text-3)' }}>/</span>
        <span style={{ color: 'var(--text-1)' }}>{run.repo}</span>
        {run.pr && <>
          <span style={{ color: 'var(--text-3)' }}>/</span>
          <span className="mono" style={{ color: 'var(--text-1)' }}>#{run.pr}</span>
        </>}
      </div>

      {/* Header row */}
      <div className="flex items-start justify-between mb-8">
        <div>
          <div className="flex items-center gap-2.5">
            <span className={`w-2 h-2 rounded-full ${run.passed ? 'bg-[var(--green)]' : 'bg-[var(--red)]'}`} />
            <h1 className="text-[17px] font-semibold" style={{ color: 'var(--text-0)' }}>
              {run.status === "running" ? "Running" : run.passed ? 'Passed' : 'Failed'}
            </h1>
          </div>
          <p className="text-[13px] mt-1 mono" style={{ color: 'var(--text-2)' }}>
            {run.commit.slice(0, 7)} · {formatDuration(run.duration_ms)}
          </p>
        </div>
        <div className="flex gap-6">
          <KV label="Score" value={run.score !== null ? run.score.toFixed(2) : "—"} color={run.passed ? 'var(--green)' : 'var(--red)'} />
          <KV label="Baseline" value={run.baseline !== null ? run.baseline.toFixed(2) : "—"} />
          <KV label="p-value" value={run.p_value !== null ? run.p_value.toFixed(3) : "—"} />
          <KV label="Effect" value={run.cohens_d !== null ? run.cohens_d.toFixed(2) : "—"} />
        </div>
      </div>

      {/* Statistical details */}
      <div className="rounded-lg border p-4 mb-8" style={{ borderColor: 'var(--border-subtle)', background: 'var(--bg-1)' }}>
        <p className="text-[11px] font-medium uppercase tracking-wider mb-3" style={{ color: 'var(--text-3)' }}>Regression Analysis</p>
        <div className="grid grid-cols-4 gap-4 text-[13px]">
          <div><span style={{ color: 'var(--text-2)' }}>p-value</span><p className="mono mt-0.5" style={{ color: 'var(--text-0)' }}>{run.p_value?.toFixed(4) ?? "—"}</p></div>
          <div><span style={{ color: 'var(--text-2)' }}>Cohen&apos;s d</span><p className="mono mt-0.5" style={{ color: 'var(--text-0)' }}>{run.cohens_d?.toFixed(3) ?? "—"}</p></div>
          <div><span style={{ color: 'var(--text-2)' }}>Severity</span><p className="mt-0.5 capitalize" style={{ color: run.severity === 'negligible' ? 'var(--green)' : 'var(--amber)' }}>{run.severity ?? "—"}</p></div>
          <div><span style={{ color: 'var(--text-2)' }}>Scenarios</span><p className="mono mt-0.5" style={{ color: 'var(--text-0)' }}>{run.scenarios_passed}/{run.scenarios_total}</p></div>
        </div>
      </div>

      {/* Scenarios */}
      <p className="text-[11px] font-medium uppercase tracking-wider mb-3" style={{ color: 'var(--text-3)' }}>Scenarios ({run.scenarios.length})</p>
      {run.scenarios.length === 0 ? (
        <p className="text-[13px]" style={{ color: 'var(--text-2)' }}>No scenario results available.</p>
      ) : (
        <div className="space-y-3">
          {run.scenarios.map(s => (
            <details key={s.id} className="group rounded-lg border overflow-hidden" style={{ borderColor: 'var(--border-subtle)', background: 'var(--bg-1)' }}>
              <summary className="flex items-center gap-3 px-4 py-3 cursor-pointer select-none list-none">
                <span className={`w-1.5 h-1.5 rounded-full ${s.passed ? 'bg-[var(--green)]' : 'bg-[var(--red)]'}`} />
                <span className="mono text-[13px] font-medium flex-1" style={{ color: 'var(--text-0)' }}>{s.scenario_id}</span>
                {s.category && <span className="text-[11px] px-1.5 py-0.5 rounded" style={{ background: 'var(--bg-3)', color: 'var(--text-2)' }}>{s.category}</span>}
                {s.tier && <span className="text-[11px] px-1.5 py-0.5 rounded" style={{ background: 'var(--bg-3)', color: 'var(--text-2)' }}>tier {s.tier}</span>}
                <span className="mono tabular text-[13px] font-medium" style={{ color: (s.consensus_score ?? 0) >= 0.85 ? 'var(--green)' : 'var(--amber)' }}>
                  {s.consensus_score !== null ? s.consensus_score.toFixed(2) : "—"}
                </span>
              </summary>
              <div className="border-t px-4 py-4 space-y-5" style={{ borderColor: 'var(--border-subtle)' }}>
                {/* Judge Scores */}
                {s.judge_scores && Object.keys(s.judge_scores).length > 0 && (
                  <div>
                    <p className="text-[11px] uppercase tracking-wider mb-2" style={{ color: 'var(--text-3)' }}>Criteria</p>
                    <div className="space-y-1.5">
                      {Object.entries(s.judge_scores).map(([name, data]: [string, any]) => (
                        <ScoreBar key={name} label={name} score={typeof data === 'object' ? data.score : data} />
                      ))}
                    </div>
                  </div>
                )}
                {/* Agent Output */}
                {s.agent_output && (
                  <div>
                    <p className="text-[11px] uppercase tracking-wider mb-2" style={{ color: 'var(--text-3)' }}>Agent Output</p>
                    <pre className="text-[12px] rounded-md p-3 overflow-x-auto" style={{ background: 'var(--bg-2)', color: 'var(--text-1)' }}>
                      {s.agent_output}
                    </pre>
                  </div>
                )}
                {/* Agent Error */}
                {s.agent_error && (
                  <div>
                    <p className="text-[11px] uppercase tracking-wider mb-2" style={{ color: 'var(--red)' }}>Error</p>
                    <pre className="text-[12px] rounded-md p-3" style={{ background: 'var(--red)11', color: 'var(--red)' }}>
                      {s.agent_error}
                    </pre>
                  </div>
                )}
                {/* Meta */}
                <div className="flex gap-4 text-[12px]" style={{ color: 'var(--text-3)' }}>
                  {s.duration_ms && <span>⏱ {s.duration_ms}ms</span>}
                  {s.cost_usd !== null && s.cost_usd > 0 && <span>💰 ${s.cost_usd.toFixed(4)}</span>}
                  {s.ija !== null && <span>IJA: {s.ija.toFixed(2)}</span>}
                  {s.tiebreaker_used && <span className="text-[var(--amber)]">⚖ Tiebreaker</span>}
                </div>
              </div>
            </details>
          ))}
        </div>
      )}
    </div>
  );
}

function KV({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="text-right">
      <p className="text-[11px] uppercase tracking-wider" style={{ color: 'var(--text-3)' }}>{label}</p>
      <p className="text-[15px] font-semibold mono tabular mt-0.5" style={{ color: color || 'var(--text-0)' }}>{value}</p>
    </div>
  );
}
