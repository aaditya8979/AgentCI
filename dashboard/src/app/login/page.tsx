"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function LoginPage() {
  const [apiKey, setApiKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      // Validate the key by making a test request
      const resp = await fetch(`${API_BASE}/api/stats`, {
        headers: { "X-API-Key": apiKey.trim() },
      });

      if (resp.status === 401) {
        setError("Invalid API key.");
        return;
      }

      if (!resp.ok) {
        setError(`API error: ${resp.status}`);
        return;
      }

      // Store the key and redirect
      localStorage.setItem("agentci_api_key", apiKey.trim());
      router.push("/");
    } catch (e: any) {
      setError("Cannot connect to AgentCI API. Is the server running?");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center" style={{ background: 'var(--bg-0)' }}>
      <div className="w-[360px] rounded-lg border p-6" style={{ borderColor: 'var(--border-subtle)', background: 'var(--bg-1)' }}>
        <div className="text-center mb-6">
          <h1 className="text-[17px] font-semibold" style={{ color: 'var(--text-0)' }}>AgentCI</h1>
          <p className="text-[13px] mt-1" style={{ color: 'var(--text-2)' }}>Enter your API key to continue</p>
        </div>

        <form onSubmit={handleSubmit}>
          <input
            type="password"
            placeholder="API key"
            value={apiKey}
            onChange={e => setApiKey(e.target.value)}
            className="w-full px-3 py-2 rounded-md text-[13px] border outline-none mb-3 transition-colors"
            style={{ background: 'var(--bg-2)', borderColor: 'var(--border-default)', color: 'var(--text-0)' }}
            onFocus={e => e.currentTarget.style.borderColor = 'var(--border-strong)'}
            onBlur={e => e.currentTarget.style.borderColor = 'var(--border-default)'}
            autoFocus
          />

          {error && (
            <p className="text-[12px] mb-3" style={{ color: 'var(--red)' }}>{error}</p>
          )}

          <button
            type="submit"
            disabled={!apiKey.trim() || loading}
            className="w-full px-3 py-2 rounded-md text-[13px] font-medium transition-opacity"
            style={{
              background: 'var(--text-0)',
              color: 'var(--bg-0)',
              opacity: !apiKey.trim() || loading ? 0.5 : 1,
            }}
          >
            {loading ? "Verifying…" : "Sign in"}
          </button>
        </form>

        <p className="text-[11px] text-center mt-4" style={{ color: 'var(--text-3)' }}>
          API keys are configured via <code className="mono">AGENTCI_API_KEYS</code>
        </p>
      </div>
    </div>
  );
}
