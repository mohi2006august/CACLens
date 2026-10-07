"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";

const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/cohorts", label: "Cohorts" },
  { href: "/attribution", label: "Attribution" },
  { href: "/alerts", label: "Alerts" },
  { href: "/optimiser", label: "Budget optimiser" },
  { href: "/ask", label: "Ask" },
  { href: "/definitions", label: "Definitions" },
  { href: "/data-quality", label: "Data quality" },
];

// The view settings (fully loaded, attribution, period) follow you between screens.
const CARRY = ["fully_loaded", "attribution", "start", "end", "days"];

export function Nav({ openAlerts }: { openAlerts: number }) {
  const pathname = usePathname();
  const params = useSearchParams();
  const carried = new URLSearchParams();
  for (const key of CARRY) {
    const value = params.get(key);
    if (value) carried.set(key, value);
  }
  const suffix = carried.toString() ? `?${carried.toString()}` : "";
  return (
    <nav className="nav" aria-label="Main">
      {LINKS.map((link) => {
        const active = link.href === "/" ? pathname === "/" || pathname.startsWith("/channels") : pathname.startsWith(link.href);
        return (
          <Link key={link.href} href={`${link.href}${suffix}`} aria-current={active ? "page" : undefined}>
            <span>{link.label}</span>
            {link.href === "/alerts" && openAlerts > 0 && (
              <span className="pill pill-critical" aria-label={`${openAlerts} open alerts`}>
                {openAlerts}
              </span>
            )}
          </Link>
        );
      })}
    </nav>
  );
}
