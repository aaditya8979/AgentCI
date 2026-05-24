import EvalTable from "./components/EvalTable";

export default function HomePage() {
  return (
    <div className="max-w-[1200px] mx-auto px-6 py-8 animate-enter">
      {/* Header */}
      <div className="flex items-end justify-between mb-6">
        <div>
          <h1 className="text-[15px] font-semibold" style={{ color: 'var(--text-0)' }}>Evaluation Runs</h1>
          <p className="text-[13px] mt-0.5" style={{ color: 'var(--text-2)' }}>8 runs across 3 repositories</p>
        </div>
        <div className="flex items-center gap-4">
          <Stat label="Pass rate" value="75%" />
          <Stat label="Avg score" value="0.85" />
          <Stat label="Regressions" value="2" alert />
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
