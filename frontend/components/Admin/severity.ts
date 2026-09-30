import type { AlertSeverity } from "./types";

/**
 * Status colors are reserved for severity and always paired with the label
 * text below (never color alone) — the dot hex mirrors the fixed
 * good/warning/serious/critical status palette, while badge backgrounds stay
 * on Tailwind's built-in scale to match this app's existing error styling.
 */
export const SEVERITY_STYLES: Record<
  AlertSeverity,
  { label: string; dot: string; badgeBg: string; badgeText: string; border: string }
> = {
  critical: {
    label: "Critical",
    dot: "#d03b3b",
    badgeBg: "bg-red-50",
    badgeText: "text-red-700",
    border: "border-red-200",
  },
  serious: {
    label: "Serious",
    dot: "#ec835a",
    badgeBg: "bg-orange-50",
    badgeText: "text-orange-700",
    border: "border-orange-200",
  },
  warning: {
    label: "Warning",
    dot: "#fab219",
    badgeBg: "bg-amber-50",
    badgeText: "text-amber-700",
    border: "border-amber-200",
  },
};

/** Severest first, which is also the order counts are listed in. */
export const SEVERITY_ORDER: AlertSeverity[] = ["critical", "serious", "warning"];

/** The "good" end of the same status palette: a run that found nothing. */
export const CLEAN_DOT = "#3c9c6a";

/**
 * A tool that raised nothing keeps the neutral bubble it has always had, so
 * color in the "Tools used" row means a finding and nothing else.
 */
export const NEUTRAL_BUBBLE = "border-violet-200 bg-violet-50 text-violet-900";

/** Bubble and badge colors for a severity, or the neutral pair for none. */
export function severityClasses(severity: AlertSeverity | null | undefined): string {
  if (!severity) return NEUTRAL_BUBBLE;
  const style = SEVERITY_STYLES[severity];
  return `${style.border} ${style.badgeBg} ${style.badgeText}`;
}

/**
 * The severest of several severities — what a tool called more than once, and
 * a run as a whole, are colored by. Null when none of them raised anything.
 */
export function highestSeverity(
  severities: ReadonlyArray<AlertSeverity | null | undefined>,
): AlertSeverity | null {
  return SEVERITY_ORDER.find((severity) => severities.includes(severity)) ?? null;
}
