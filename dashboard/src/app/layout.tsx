import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "AgentCI",
  description: "CI/CD Quality Gate for LLM Agents",
};

function Nav() {
  return (
    <header className="fixed top-0 left-0 right-0 h-12 border-b z-50 flex items-center px-5 gap-6"
            style={{ background: 'var(--bg-1)', borderColor: 'var(--border-subtle)' }}>
      <Link href="/" className="flex items-center gap-2 mr-4">
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
          <rect width="18" height="18" rx="4" fill="url(#g)" />
          <path d="M5 12.5V9l4-4.5 4 4.5v3.5" stroke="#fff" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
          <defs><linearGradient id="g" x1="0" y1="0" x2="18" y2="18"><stop stopColor="#60a5fa"/><stop offset="1" stopColor="#a78bfa"/></linearGradient></defs>
        </svg>
        <span className="text-[13px] font-semibold" style={{ color: 'var(--text-0)' }}>AgentCI</span>
      </Link>
      <nav className="flex items-center gap-1">
        <NavItem href="/" label="Runs" />
        <NavItem href="/trends" label="Trends" />
      </nav>
      <div className="ml-auto flex items-center gap-3">
        <span className="flex items-center gap-1.5 text-[11px]" style={{ color: 'var(--text-2)' }}>
          <span className="w-1.5 h-1.5 rounded-full bg-[var(--green)]" />
          Healthy
        </span>
      </div>
    </header>
  );
}

function NavItem({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      className="nav-item px-2.5 py-1 rounded text-[13px] transition-colors"
    >
      {label}
    </Link>
  );
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
      </head>
      <body>
        <Nav />
        <main className="pt-12">
          {children}
        </main>
      </body>
    </html>
  );
}
