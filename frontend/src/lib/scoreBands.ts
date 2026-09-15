/** Analytical label presentation (docs/08 §2, §5): text + icon, never colour alone. */
import type { SignalLabel } from "@/api/generated/schema";

export const LABELS: SignalLabel[] = [
  "STRONG_BEARISH",
  "BEARISH",
  "NEUTRAL",
  "BULLISH",
  "STRONG_BULLISH",
];

interface LabelStyle {
  text: string;
  icon: string; // unicode glyph, not an image
  className: string; // tailwind bg/text
}

const STYLES: Record<SignalLabel, LabelStyle> = {
  STRONG_BEARISH: { text: "Strong bearish", icon: "▼▼", className: "bg-band-strong-bearish/10 text-band-strong-bearish ring-1 ring-band-strong-bearish/30" },
  BEARISH: { text: "Bearish", icon: "▼", className: "bg-band-bearish/10 text-band-bearish ring-1 ring-band-bearish/30" },
  NEUTRAL: { text: "Neutral", icon: "▬", className: "bg-band-neutral/10 text-band-neutral ring-1 ring-band-neutral/30" },
  BULLISH: { text: "Bullish", icon: "▲", className: "bg-band-bullish/10 text-band-bullish ring-1 ring-band-bullish/30" },
  STRONG_BULLISH: { text: "Strong bullish", icon: "▲▲", className: "bg-band-strong-bullish/10 text-band-strong-bullish ring-1 ring-band-strong-bullish/30" },
};

export function labelStyle(l: SignalLabel): LabelStyle {
  return STYLES[l];
}

export function compositeClass(v: number): string {
  if (v >= 60) return "text-band-strong-bullish";
  if (v >= 20) return "text-band-bullish";
  if (v > -20) return "text-band-neutral";
  if (v > -60) return "text-band-bearish";
  return "text-band-strong-bearish";
}
