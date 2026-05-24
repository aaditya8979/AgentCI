"use client";

interface ScoreBarProps {
  score: number;
  label?: string;
}

export default function ScoreBar({ score, label }: ScoreBarProps) {
  const pct = Math.min(100, Math.max(0, score * 100));
  const color = score >= 0.85 ? 'var(--green)' : score >= 0.7 ? 'var(--amber)' : 'var(--red)';

  return (
    <div className="flex items-center gap-2">
      {label && <span className="text-[12px] w-28 shrink-0 truncate" style={{ color: 'var(--text-2)' }}>{label}</span>}
      <div className="flex-1 h-1 rounded-full overflow-hidden" style={{ background: 'var(--bg-3)' }}>
        <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="mono tabular text-[12px] w-10 text-right" style={{ color: 'var(--text-1)' }}>{score.toFixed(2)}</span>
    </div>
  );
}
