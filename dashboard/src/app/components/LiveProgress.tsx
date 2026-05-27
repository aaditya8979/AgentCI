"use client";

import { useState, useEffect, useRef } from "react";

interface ProgressEvent {
  type: string;
  scenario_id?: string;
  passed?: boolean;
  score?: number;
  progress?: number;
  timestamp?: string;
}

export default function LiveProgress({ runId }: { runId: string }) {
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = process.env.NEXT_PUBLIC_API_URL
      ? new URL(process.env.NEXT_PUBLIC_API_URL).host
      : window.location.host;
    const url = `${protocol}//${host}/ws/runs/${runId}`;

    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        setError(null);
      };

      ws.onmessage = (event) => {
        try {
          const data: ProgressEvent = JSON.parse(event.data);
          setEvents(prev => [...prev, data]);
        } catch {
          // Ignore malformed messages
        }
      };

      ws.onerror = () => {
        setError("Live updates unavailable. Page will not auto-refresh.");
        setConnected(false);
      };

      ws.onclose = () => {
        setConnected(false);
      };
    } catch {
      setError("Live updates unavailable. Page will not auto-refresh.");
    }

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [runId]);

  if (error) {
    return (
      <div className="rounded-md border px-3 py-2 text-[12px]"
           style={{ borderColor: 'var(--border-subtle)', color: 'var(--text-3)' }}>
        {error}
      </div>
    );
  }

  return (
    <div className="rounded-lg border p-4" style={{ borderColor: 'var(--border-subtle)', background: 'var(--bg-1)' }}>
      <div className="flex items-center gap-2 mb-3">
        <span className={`w-2 h-2 rounded-full ${connected ? 'bg-[var(--green)] animate-pulse' : 'bg-[var(--text-3)]'}`} />
        <p className="text-[11px] font-medium uppercase tracking-wider" style={{ color: 'var(--text-3)' }}>
          Live Progress {connected ? "" : "(disconnected)"}
        </p>
      </div>

      {events.length === 0 ? (
        <p className="text-[12px]" style={{ color: 'var(--text-3)' }}>Waiting for events…</p>
      ) : (
        <div className="space-y-1 max-h-[300px] overflow-y-auto">
          {events.map((e, i) => (
            <div key={i} className="flex items-center gap-2 text-[12px]">
              {e.type === "scenario_completed" && (
                <>
                  <span className={`w-1.5 h-1.5 rounded-full ${e.passed ? 'bg-[var(--green)]' : 'bg-[var(--red)]'}`} />
                  <span className="mono" style={{ color: 'var(--text-1)' }}>{e.scenario_id}</span>
                  {e.score !== undefined && (
                    <span className="mono" style={{ color: e.score >= 0.85 ? 'var(--green)' : 'var(--amber)' }}>
                      {e.score.toFixed(2)}
                    </span>
                  )}
                </>
              )}
              {e.type === "scenario_started" && (
                <>
                  <span className="w-1.5 h-1.5 rounded-full bg-[var(--blue)] animate-pulse" />
                  <span className="mono" style={{ color: 'var(--text-2)' }}>{e.scenario_id} running…</span>
                </>
              )}
              {e.type === "run_completed" && (
                <>
                  <span className="w-1.5 h-1.5 rounded-full bg-[var(--green)]" />
                  <span style={{ color: 'var(--green)' }}>Evaluation complete</span>
                </>
              )}
              {e.type === "run_failed" && (
                <>
                  <span className="w-1.5 h-1.5 rounded-full bg-[var(--red)]" />
                  <span style={{ color: 'var(--red)' }}>Evaluation failed</span>
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
