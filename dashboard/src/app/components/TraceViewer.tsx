"use client";

import { useState } from "react";

interface TraceStep {
  step: number;
  action: string;
  input: string;
  output: string;
  duration_ms: number;
}

export default function TraceViewer({ scenarioId, steps }: { scenarioId: string; steps: TraceStep[] }) {
  const [open, setOpen] = useState<number | null>(null);

  return (
    <div>
      <p className="text-[11px] uppercase tracking-wider mb-2" style={{ color: 'var(--text-3)' }}>Execution trace</p>
      <div className="rounded-md border overflow-hidden" style={{ borderColor: 'var(--border-subtle)', background: 'var(--bg-2)' }}>
        {steps.map((s, i) => (
          <div key={s.step} className={i > 0 ? "border-t" : ""} style={{ borderColor: 'var(--border-subtle)' }}>
            <button
              onClick={() => setOpen(open === s.step ? null : s.step)}
              className="w-full flex items-center gap-3 px-3 py-2 text-left transition-colors"
              onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-3)'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            >
              <span className="mono text-[11px] w-4 text-center" style={{ color: 'var(--text-3)' }}>{s.step}</span>
              <span className="text-[12px] flex-1" style={{ color: 'var(--text-0)' }}>{s.action}</span>
              <span className="mono text-[11px]" style={{ color: 'var(--text-3)' }}>{s.duration_ms}ms</span>
            </button>
            {open === s.step && (
              <div className="px-3 pb-3 pl-10 space-y-2 animate-enter">
                <div>
                  <p className="text-[10px] uppercase" style={{ color: 'var(--text-3)' }}>in</p>
                  <pre className="text-[11px] mono mt-0.5 p-2 rounded" style={{ background: 'var(--bg-0)', color: 'var(--text-1)' }}>{s.input}</pre>
                </div>
                <div>
                  <p className="text-[10px] uppercase" style={{ color: 'var(--text-3)' }}>out</p>
                  <pre className="text-[11px] mono mt-0.5 p-2 rounded" style={{ background: 'var(--bg-0)', color: 'var(--text-1)' }}>{s.output}</pre>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
