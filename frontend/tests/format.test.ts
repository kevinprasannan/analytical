import { bool, num, pct, price, relTime, DASH } from "@/lib/format";
import { compositeClass } from "@/lib/scoreBands";

test("null-ish values render as an em dash", () => {
  expect(price(null)).toBe(DASH);
  expect(num(undefined, 2)).toBe(DASH);
  expect(bool(null)).toBe(DASH);
  expect(pct(null)).toBe(DASH);
});

test("fixed decimals per field type", () => {
  expect(price(1234.5)).toBe("1,234.50");
  expect(num(0.123456, 2)).toBe("0.12");
  expect(pct(0.0123, 2)).toBe("1.23%");
});

test("relTime buckets", () => {
  const now = Date.parse("2026-08-29T12:00:00Z");
  expect(relTime("2026-08-29T11:59:30Z", now)).toBe("30s ago");
  expect(relTime("2026-08-29T11:30:00Z", now)).toBe("30m ago");
  expect(relTime("2026-08-29T09:00:00Z", now)).toBe("3h ago");
});

test("composite colour bands are symmetric at the boundaries", () => {
  expect(compositeClass(60)).toContain("strong-bullish");
  expect(compositeClass(20)).toContain("bullish");
  expect(compositeClass(0)).toContain("neutral");
  expect(compositeClass(-60)).toContain("strong-bearish");
});
