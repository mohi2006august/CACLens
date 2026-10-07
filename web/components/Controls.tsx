"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTransition } from "react";

import { ATTRIBUTION_MODELS } from "@/lib/channels";
import { modelLabel } from "@/lib/format";

const PRESETS = [
  { days: "30", label: "30d" },
  { days: "90", label: "90d" },
  { days: "180", label: "6m" },
  { days: "365", label: "12m" },
];

/** One row of filters above the content they scope (date range first). */
export function Controls({
  showRange = true,
  showFullyLoaded = true,
  showAttribution = true,
}: {
  showRange?: boolean;
  showFullyLoaded?: boolean;
  showAttribution?: boolean;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [pending, startTransition] = useTransition();

  function update(changes: Record<string, string | null>) {
    const next = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(changes)) {
      if (v === null || v === "") next.delete(k);
      else next.set(k, v);
    }
    startTransition(() => router.replace(`${pathname}?${next.toString()}`, { scroll: false }));
  }

  const days = params.get("days") ?? (params.get("start") ? "" : "90");

  return (
    <div className="controls" role="group" aria-label="View settings" aria-busy={pending}>
      {showRange && (
        <span className="segmented" role="group" aria-label="Date range">
          {PRESETS.map((p) => (
            <a
              key={p.days}
              href={`?days=${p.days}`}
              aria-current={days === p.days ? "true" : undefined}
              onClick={(e) => {
                e.preventDefault();
                update({ days: p.days, start: null, end: null });
              }}
            >
              {p.label}
            </a>
          ))}
        </span>
      )}
      {showFullyLoaded && (
        <label className="control">
          <input
            type="checkbox"
            checked={params.get("fully_loaded") === "true"}
            onChange={(e) => update({ fully_loaded: e.target.checked ? "true" : null })}
          />
          Fully loaded
        </label>
      )}
      {showAttribution && (
        <label className="control">
          Attribution
          <select
            value={params.get("attribution") ?? "position_based"}
            onChange={(e) => update({ attribution: e.target.value === "position_based" ? null : e.target.value })}
          >
            {ATTRIBUTION_MODELS.map((m) => (
              <option key={m} value={m}>
                {modelLabel(m)}
              </option>
            ))}
          </select>
        </label>
      )}
      {pending && <span className="muted">Updating…</span>}
    </div>
  );
}
