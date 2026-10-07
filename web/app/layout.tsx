import type { Metadata } from "next";
import Link from "next/link";
import Script from "next/script";
import { Inter, JetBrains_Mono } from "next/font/google";
import { Suspense } from "react";

import { Nav } from "@/components/Nav";
import { Shortcuts } from "@/components/Shortcuts";
import { ThemeToggle, themeScript } from "@/components/ThemeToggle";
import { api, type Alert, type Health } from "@/lib/api";
import { dayLabel } from "@/lib/format";

import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jetbrains", display: "swap" });

export const metadata: Metadata = {
  title: { default: "CACLens", template: "%s · CACLens" },
  description: "Channel-level CAC, LTV:CAC and payback analytics with plain-English Q&A.",
};

async function status(): Promise<{ health: Health | null; openAlerts: number }> {
  try {
    const health = await api<Health>("/v1/health");
    const alerts = health.status === "ok" ? await api<{ alerts: Alert[] }>("/v1/alerts", { status: "open" }) : { alerts: [] };
    return { health, openAlerts: alerts.alerts.length };
  } catch {
    return { health: null, openAlerts: 0 };
  }
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const { health, openAlerts } = await status();
  return (
    <html lang="en" className={`${inter.variable} ${mono.variable}`} suppressHydrationWarning>
      <head>
        <Script id="caclens-theme" strategy="beforeInteractive">
          {themeScript}
        </Script>
      </head>
      <body>
        <a href="#main" className="sr-only">
          Skip to content
        </a>
        <div className="shell">
          <aside className="sidebar">
            <Link href="/" className="brand" aria-label="CACLens home">
              <span className="brand-mark" aria-hidden>
                ◎
              </span>
              CACLens
            </Link>
            <Suspense fallback={null}>
              <Nav openAlerts={openAlerts} />
            </Suspense>
            <div className="sidebar-foot">
              <span className="muted">
                {health?.data_through ? `Data through ${dayLabel(health.data_through)}` : "API offline"}
              </span>
              {health?.qa_planner && (
                <span className="muted">Q&A: {health.qa_planner === "claude" ? "Claude" : "offline planner"}</span>
              )}
              <ThemeToggle />
              <span className="muted">
                Press <kbd>?</kbd> for shortcuts
              </span>
            </div>
          </aside>
          <main id="main" className="main">
            {children}
          </main>
        </div>
        <Shortcuts />
      </body>
    </html>
  );
}
