// Resolve the shared view settings from the URL (?days=, ?start=&end=, ?fully_loaded, ?attribution).

export type SearchParams = Record<string, string | string[] | undefined>;

export function param(sp: SearchParams, key: string): string | undefined {
  const v = sp[key];
  return Array.isArray(v) ? v[0] : v;
}

export interface View {
  start?: string;
  end?: string;
  days: number;
  fullyLoaded: boolean;
  attribution: string;
  query: string;
}

function iso(d: Date): string {
  return d.toISOString().slice(0, 10);
}

/** `dataThrough` anchors relative ranges to the latest data, not today's date. */
export function resolveView(sp: SearchParams, dataThrough?: string | null): View {
  const fullyLoaded = param(sp, "fully_loaded") === "true";
  const attribution = param(sp, "attribution") ?? "position_based";
  const days = Number(param(sp, "days") ?? 90) || 90;
  let start = param(sp, "start");
  let end = param(sp, "end");
  if (!start && dataThrough) {
    const last = new Date(`${dataThrough}T00:00:00Z`);
    const first = new Date(last);
    first.setUTCDate(first.getUTCDate() - (days - 1));
    start = iso(first);
    end = iso(last);
  }
  const q = new URLSearchParams();
  if (param(sp, "days")) q.set("days", String(days));
  if (param(sp, "start")) q.set("start", param(sp, "start")!);
  if (param(sp, "end")) q.set("end", param(sp, "end")!);
  if (fullyLoaded) q.set("fully_loaded", "true");
  if (attribution !== "position_based") q.set("attribution", attribution);
  return { start, end, days, fullyLoaded, attribution, query: q.toString() };
}
