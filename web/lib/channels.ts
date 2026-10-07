// Colour follows the entity, never its rank: each channel owns one categorical slot
// everywhere in the app, so filtering never repaints the survivors.

export const CHANNELS: Record<string, { label: string; color: string; paid: boolean }> = {
  google_search: { label: "Google Search", color: "var(--series-1)", paid: true },
  meta_ads: { label: "Meta Ads", color: "var(--series-2)", paid: true },
  linkedin_ads: { label: "LinkedIn Ads", color: "var(--series-3)", paid: true },
  organic_search: { label: "Organic Search", color: "var(--series-4)", paid: false },
  referral: { label: "Referral", color: "var(--series-5)", paid: false },
  email: { label: "Email", color: "var(--series-6)", paid: false },
  direct: { label: "Direct", color: "var(--series-7)", paid: false },
  other: { label: "Other", color: "var(--series-neutral)", paid: false },
  unattributed: { label: "Unattributed", color: "var(--series-neutral)", paid: false },
  unallocated: { label: "Unallocated costs", color: "var(--series-neutral)", paid: false },
};

export function channelLabel(channel: string): string {
  return CHANNELS[channel]?.label ?? channel;
}

export function channelColor(channel: string): string {
  return CHANNELS[channel]?.color ?? "var(--series-neutral)";
}

export const ATTRIBUTION_MODELS = [
  "position_based",
  "first_touch",
  "last_touch",
  "linear",
  "time_decay",
] as const;
