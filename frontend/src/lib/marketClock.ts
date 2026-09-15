/** Is the NSE cash/F&O session live *right now* (client clock, IST)?
 *
 *  09:15 → 15:40 IST, Mon–Fri (15:40 = 15:30 close + a 10-min tail for the
 *  closing-session prints, matching the OI-pulse trace cutoff). Holidays aren't
 *  known here — pair this with `/calendar/status.is_open`: poll fast only when
 *  BOTH agree, so an early-close or holiday still stops the polling.
 *
 *  Used to switch periodic refetches off after the bell — once the session ends
 *  the board / health data is static, so one fetch on load is enough. */
export function istSessionWindow(now: Date = new Date()): boolean {
  const ist = new Date(now.toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
  const dow = ist.getDay(); // 0 Sun … 6 Sat
  if (dow === 0 || dow === 6) return false;
  const mins = ist.getHours() * 60 + ist.getMinutes();
  return mins >= 9 * 60 + 15 && mins <= 15 * 60 + 40;
}
