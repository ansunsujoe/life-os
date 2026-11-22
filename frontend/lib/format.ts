import type { Category, Confidence } from "./types";

export function fmtDuration(seconds: number): string {
  const m = Math.round(seconds / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  const r = m % 60;
  return r ? `${h}h ${r}m` : `${h}h`;
}

export function fmtMinutes(min: number): string {
  return fmtDuration(min * 60);
}

export function fmtTime(iso: string, tz?: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", timeZone: tz });
}

export function fmtDateTime(iso: string | null | undefined, tz?: string): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: tz });
}

export function fmtDay(day: string): string {
  // day is YYYY-MM-DD (a local calendar date); avoid timezone shifts.
  const [y, m, d] = day.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
}

export function relMinutes(min: number | null | undefined): string {
  if (min === null || min === undefined) return "";
  if (min < 1) return "just now";
  if (min < 60) return `${Math.round(min)} min`;
  const h = min / 60;
  if (h < 24) return `${h.toFixed(h < 10 ? 1 : 0)} h`;
  return `${Math.round(h / 24)} d`;
}

export function todayLocal(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function shiftDay(day: string, delta: number): string {
  const [y, m, d] = day.split("-").map(Number);
  const dt = new Date(y, m - 1, d + delta);
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
}

export const CONFIDENCE_LABEL: Record<Confidence, string> = {
  high: "Confirmed / recorded",
  medium: "Strong signal",
  low: "Inferred",
};

export const CONFIDENCE_COLOR: Record<Confidence, string> = { high: "teal", medium: "blue", low: "gray" };

export const SOURCE_LABEL: Record<string, string> = {
  activitywatch: "ActivityWatch",
  apple_health: "Apple Health",
  robinhood_csv: "Robinhood CSV",
  manual: "Manual",
  manual_summary: "Summary",
  activity_json: "Import",
  filesystem: "Files",
  claude_hook: "Claude Code",
};

export const DOMAIN_OPTIONS = [
  { value: "software", label: "Software" },
  { value: "trading", label: "Trading" },
  { value: "music", label: "Music" },
  { value: "learning", label: "Learning" },
  { value: "faith", label: "Faith" },
  { value: "health", label: "Health" },
  { value: "recovery", label: "Recovery" },
];

export function catMap(cats: Category[] | undefined): Record<string, Category> {
  return Object.fromEntries((cats ?? []).map((c) => [c.key, c]));
}

export function catColor(cats: Record<string, Category>, key: string): string {
  return cats[key]?.color ?? "gray";
}

export function cssColor(name: string, shade = 6): string {
  return `var(--mantine-color-${name}-${shade})`;
}
