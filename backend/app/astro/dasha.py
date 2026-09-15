"""Vimshottari dasha — the 120-year lord cycle, drilled down to a session.

Pure and deterministic, no IO. The nine lords rule in fixed proportion
(Ketu 7 · Venus 20 · Sun 6 · Moon 10 · Mars 7 · Rahu 18 · Jupiter 16 ·
Saturn 19 · Mercury 17 = 120 years). An antardasha (sub-period) of lord *b*
inside the mahadasha of lord *a* lasts ``years[a] · years[b] / 120``.

Two views, both driven off the same ratio:

* :func:`vimshottari_grid` — the abstract 9×9 table with a *chosen* start lord.
  Scale the whole 120 to any window (default **390-minute trading session**)
  and every cell reads as both "years" and "H:MM:SS of the session".

* :func:`moon_dasha` — the **Moon-anchored** timeline for one real day. The
  cycle is started from the Moon's actual nakshatra lord, and the first
  (mahadasha) period is cut to its *balance* — the un-elapsed fraction of the
  nakshatra the Moon still has to cross — exactly as a birth-chart dasha
  balance is computed, only with **``cycle_minutes`` (390 or 400) standing in
  for 120 years**. This is *not* a different dasha system; it is the standard
  balance-of-dasha calculation compressed onto a session. ``cycle_minutes`` is
  configurable and never silently chosen.
"""

from __future__ import annotations

#: one nakshatra spans 360/27° = 13°20'.
NAK_SPAN_DEG = 360.0 / 27.0

VIM_ORDER: tuple[str, ...] = (
    "Ketu",
    "Venus",
    "Sun",
    "Moon",
    "Mars",
    "Rahu",
    "Jupiter",
    "Saturn",
    "Mercury",
)
VIM_YEARS: dict[str, int] = {
    "Ketu": 7,
    "Venus": 20,
    "Sun": 6,
    "Moon": 10,
    "Mars": 7,
    "Rahu": 18,
    "Jupiter": 16,
    "Saturn": 19,
    "Mercury": 17,
}
VIM_TOTAL_YEARS = 120  # == sum(VIM_YEARS.values())

#: short codes as they appear on panchang dasha tables
VIM_ABBR: dict[str, str] = {
    "Ketu": "Ke",
    "Venus": "Ve",
    "Sun": "Su",
    "Moon": "Ch",
    "Mars": "Se",
    "Rahu": "Ra",
    "Jupiter": "Gu",
    "Saturn": "Sa",
    "Mercury": "Bu",
}


def _rotated(seq: tuple[str, ...], start: str) -> tuple[str, ...]:
    i = seq.index(start)
    return seq[i:] + seq[:i]


#: rashi (sign) lords, index 0 = Mesha, in VIM_ORDER title-case spelling.
_RASHI_LORDS: tuple[str, ...] = (
    "Mars", "Venus", "Mercury", "Moon", "Sun", "Mercury",
    "Venus", "Mars", "Jupiter", "Saturn", "Saturn", "Jupiter",
)


def _sub_of(pos: float, span: float, start_lord: str) -> tuple[str, float, float]:
    """Walk :data:`VIM_ORDER` from ``start_lord``, cutting ``span`` into the nine
    Vimshottari proportions; return the lord whose slice contains ``pos`` plus
    that slice's ``(start, length)`` within ``span``."""
    acc = 0.0
    seq = _rotated(VIM_ORDER, start_lord)
    for ld in seq:
        seg = span * VIM_YEARS[ld] / VIM_TOTAL_YEARS
        if pos < acc + seg - 1e-12:
            return ld, acc, seg
        acc += seg
    return seq[-1], acc - seg, seg  # numeric edge at the very end


def kp_chain(longitude: float) -> dict:
    """The KP lord chain for one sidereal longitude — **sign lord → star
    (nakshatra) lord → sub lord → sub-sub lord** — each level subdividing the
    one above by the Vimshottari 7·20·6·10·7·18·16·19·17 proportions. Pure."""
    lon = longitude % 360.0
    sign_lord = _RASHI_LORDS[int(lon // 30.0) % 12]
    nak_idx = int(lon // NAK_SPAN_DEG) % 27
    star_lord = VIM_ORDER[nak_idx % 9]
    pos_in_nak = lon - nak_idx * NAK_SPAN_DEG
    sub_lord, sub_start, sub_span = _sub_of(pos_in_nak, NAK_SPAN_DEG, star_lord)
    sub_sub_lord, _, _ = _sub_of(pos_in_nak - sub_start, sub_span, sub_lord)
    return {
        "sign_lord": sign_lord,
        "sign_lord_abbr": VIM_ABBR[sign_lord],
        "star_lord": star_lord,
        "star_lord_abbr": VIM_ABBR[star_lord],
        "sub_lord": sub_lord,
        "sub_lord_abbr": VIM_ABBR[sub_lord],
        "sub_sub_lord": sub_sub_lord,
        "sub_sub_lord_abbr": VIM_ABBR[sub_sub_lord],
    }


def _hms(minutes: float) -> str:
    total = round(minutes * 60)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def _years_label(years: float) -> str:
    y = int(years)
    months_f = (years - y) * 12.0
    mo = int(round(months_f * 100) / 100)
    days = round((months_f - mo) * 30.0)
    if days >= 30:
        mo, days = mo + 1, 0
    if mo >= 12:
        y, mo = y + 1, mo - 12
    parts = []
    if y:
        parts.append(f"{y}y")
    if mo:
        parts.append(f"{mo}m")
    if days:
        parts.append(f"{days}d")
    return " ".join(parts) or "0d"


def vimshottari_grid(total_minutes: float | None = 390.0, *, start_lord: str = "Ketu") -> dict:
    """The full mahadasha × antardasha table.

    ``total_minutes`` scales the 120-year cycle onto a session (``None`` ⇒
    years only). ``start_lord`` rotates the mahadasha sequence (pass the Moon's
    nakshatra lord to anchor a real chart). Antardasha columns are always the
    fixed :data:`VIM_ORDER` so the grid lines up with a printed panchang table;
    within a period the sub-lords actually *begin* with the period lord —
    ``row.antardasha_sequence`` gives that chronological order.
    """
    if start_lord not in VIM_YEARS:
        raise ValueError(f"unknown lord {start_lord!r}; expected one of {sorted(VIM_YEARS)}")

    md_seq = _rotated(VIM_ORDER, start_lord)
    per_year_min = (total_minutes / VIM_TOTAL_YEARS) if total_minutes is not None else None

    rows = []
    for md in md_seq:
        md_years = VIM_YEARS[md]
        md_min = md_years * per_year_min if per_year_min is not None else None
        antar = []
        for ad in VIM_ORDER:
            ad_years = md_years * VIM_YEARS[ad] / VIM_TOTAL_YEARS
            ad_min = md_min * VIM_YEARS[ad] / VIM_TOTAL_YEARS if md_min is not None else None
            antar.append(
                {
                    "lord": ad,
                    "abbr": VIM_ABBR[ad],
                    "years": round(ad_years, 6),
                    "years_label": _years_label(ad_years),
                    "minutes": round(ad_min, 6) if ad_min is not None else None,
                    "hms": _hms(ad_min) if ad_min is not None else None,
                }
            )
        rows.append(
            {
                "lord": md,
                "abbr": VIM_ABBR[md],
                "years": md_years,
                "years_label": _years_label(md_years),
                "minutes": round(md_min, 6) if md_min is not None else None,
                "hms": _hms(md_min) if md_min is not None else None,
                "antardashas": antar,
                "antardasha_sequence": list(_rotated(VIM_ORDER, md)),
            }
        )

    return {
        "total_years": VIM_TOTAL_YEARS,
        "total_minutes": total_minutes,
        "total_hms": _hms(total_minutes) if total_minutes is not None else None,
        "start_lord": start_lord,
        "order": list(md_seq),
        "abbr": VIM_ABBR,
        "years": VIM_YEARS,
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# Moon-anchored dasha — the balance-of-dasha timeline for one real day
# ---------------------------------------------------------------------------

_NAKSHATRAS: tuple[str, ...] = (
    "Ashwini",
    "Bharani",
    "Krittika",
    "Rohini",
    "Mrigashira",
    "Ardra",
    "Punarvasu",
    "Pushya",
    "Ashlesha",
    "Magha",
    "Purva Phalguni",
    "Uttara Phalguni",
    "Hasta",
    "Chitra",
    "Swati",
    "Vishakha",
    "Anuradha",
    "Jyeshtha",
    "Mula",
    "Purva Ashadha",
    "Uttara Ashadha",
    "Shravana",
    "Dhanishta",
    "Shatabhisha",
    "Purva Bhadrapada",
    "Uttara Bhadrapada",
    "Revati",
)  # nakshatra i is ruled by VIM_ORDER[i % 9] (Ashwini → Ketu)


def _parse_hm(hm: str) -> tuple[int, int]:
    try:
        h_s, m_s = hm.split(":")
        h, m = int(h_s), int(m_s)
    except ValueError:
        raise ValueError(f"session_open must be 'HH:MM', got {hm!r}") from None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"session_open out of range: {hm!r}")
    return h, m


def _clock(minutes_from_open: float, oh: int, om: int) -> str:
    total = (oh * 60 + om + minutes_from_open) % 1440.0
    h, m = divmod(int(round(total)), 60)
    return f"{h % 24:02d}:{m:02d}"


def _moon_balance(moon_longitude: float, cycle_minutes: float) -> dict:
    """Nakshatra placement of the Moon and the balance (un-elapsed part) of its
    ruling mahadasha, in ``cycle_minutes`` terms. Pure trig, no periods built."""
    if cycle_minutes <= 0:
        raise ValueError("cycle_minutes must be > 0")
    lon = moon_longitude % 360.0
    nak_idx = int(lon // NAK_SPAN_DEG) % 27
    pos_in_nak = lon - nak_idx * NAK_SPAN_DEG
    elapsed_frac = pos_in_nak / NAK_SPAN_DEG
    if elapsed_frac >= 1.0 - 1e-9:  # exact boundary lands at the next nakshatra's start
        nak_idx = (nak_idx + 1) % 27
        pos_in_nak = 0.0
        elapsed_frac = 0.0
    lord = VIM_ORDER[nak_idx % 9]
    md_full = cycle_minutes * VIM_YEARS[lord] / VIM_TOTAL_YEARS
    return {
        "moon_longitude": lon,
        "nakshatra": _NAKSHATRAS[nak_idx],
        "nakshatra_index": nak_idx,
        "pada": int(pos_in_nak // (NAK_SPAN_DEG / 4.0)) + 1,
        "position_in_nakshatra_deg": pos_in_nak,
        "elapsed_fraction": elapsed_frac,
        "remaining_fraction": 1.0 - elapsed_frac,
        "dasha_lord": lord,
        "dasha_lord_abbr": VIM_ABBR[lord],
        "md_full_minutes": md_full,
        "entry_offset": elapsed_frac * md_full,  # minutes of `lord`'s MD already gone
        "balance_minutes": md_full - elapsed_frac * md_full,
    }


def _subdivide(
    win_start: float,
    win_len: float,
    parent_lord: str,
    parent_nat_len: float,
    entry_offset: float,
    depth: int,
    max_depth: int,
    oh: int,
    om: int,
    per_min_years: float,
) -> list[dict]:
    """Vimshottari sub-periods that tile ``[win_start, win_start + win_len)``.

    Sub-lords cycle from ``parent_lord`` in :data:`VIM_ORDER`; each sub-period's
    *natural* length is ``parent_nat_len · years[sub] / 120``. ``entry_offset``
    is how many minutes of the parent's natural span have already elapsed at
    ``win_start`` (0 unless this window is itself a balance period), so the
    first emitted sub-period may start mid-stream. Recurses ``max_depth`` deep.
    """
    seq = _rotated(VIM_ORDER, parent_lord)
    nat = [parent_nat_len * VIM_YEARS[ld] / VIM_TOTAL_YEARS for ld in seq]
    out: list[dict] = []
    t = win_start
    placed = 0.0
    consumed = 0.0  # natural minutes of the parent walked past
    idx = 0
    guard = 0
    while placed < win_len - 1e-9 and guard < 400:
        guard += 1
        lord = seq[idx % 9]
        seg_nat = nat[idx % 9]
        if consumed + seg_nat <= entry_offset + 1e-9:
            consumed += seg_nat
            idx += 1
            continue
        sub_entry = max(0.0, entry_offset - consumed)  # into THIS sub's natural span
        visible_nat = seg_nat - sub_entry
        visible = min(visible_nat, win_len - placed)
        node = {
            "lord": lord,
            "abbr": VIM_ABBR[lord],
            "level": depth,
            "start_min": round(t, 6),
            "end_min": round(t + visible, 6),
            "minutes": round(visible, 6),
            "hms": _hms(visible),
            "start_clock": _clock(t, oh, om),
            "end_clock": _clock(t + visible, oh, om),
            "years": round(visible * per_min_years, 6),
            "years_label": _years_label(visible * per_min_years),
            "partial": visible < seg_nat - 1e-9,
            "children": (
                _subdivide(
                    t,
                    visible,
                    lord,
                    seg_nat,
                    sub_entry,
                    depth + 1,
                    max_depth,
                    oh,
                    om,
                    per_min_years,
                )
                if depth < max_depth
                else []
            ),
        }
        out.append(node)
        t += visible
        placed += visible
        consumed += seg_nat
        entry_offset = consumed  # first (possibly partial) period done — no more skipping
        idx += 1
    return out


def moon_dasha(
    moon_longitude: float,
    *,
    cycle_minutes: float = 390.0,
    levels: int = 2,
    session_open: str = "09:15",
) -> dict:
    """The Moon-anchored dasha timeline for one day.

    ``moon_longitude`` — the Moon's **sidereal** ecliptic longitude (degrees,
    ayanamsha already applied). ``cycle_minutes`` replaces the 120-year cycle
    (pass 390 or 400 explicitly). ``levels`` — 1 mahadasha only, 2 adds
    antardasha, 3 adds pratyantar. ``session_open`` anchors the wall clock.

    The first period is the **balance** of the Moon's nakshatra-lord mahadasha
    (its un-elapsed fraction); full periods follow in :data:`VIM_ORDER`,
    wrapping so the whole ``[0, cycle_minutes)`` session is tiled. The elapsed
    portion is simply not shown — it fell before the session opened.
    """
    if cycle_minutes <= 0:
        raise ValueError("cycle_minutes must be > 0")
    if not 1 <= levels <= 3:
        raise ValueError("levels must be 1, 2 or 3")
    oh, om = _parse_hm(session_open)
    b = _moon_balance(moon_longitude, cycle_minutes)
    per_min_years = VIM_TOTAL_YEARS / cycle_minutes

    periods = _subdivide(
        0.0,
        cycle_minutes,
        b["dasha_lord"],
        cycle_minutes,
        b["entry_offset"],
        1,
        levels,
        oh,
        om,
        per_min_years,
    )
    lord = b["dasha_lord"]
    return {
        "calculation_method": "MOON_BASED",
        "subdivision_minutes": cycle_minutes,
        "cycle_years": VIM_TOTAL_YEARS,
        "levels": levels,
        "session_open": f"{oh % 24:02d}:{om:02d}",
        "moon_longitude": round(b["moon_longitude"], 6),
        "nakshatra": b["nakshatra"],
        "nakshatra_index": b["nakshatra_index"],
        "pada": b["pada"],
        "position_in_nakshatra_deg": round(b["position_in_nakshatra_deg"], 6),
        "elapsed_fraction": round(b["elapsed_fraction"], 6),
        "remaining_fraction": round(b["remaining_fraction"], 6),
        "dasha_lord": lord,
        "dasha_lord_abbr": VIM_ABBR[lord],
        "balance_minutes": round(b["balance_minutes"], 6),
        "balance_hms": _hms(b["balance_minutes"]),
        "balance_years": round(VIM_YEARS[lord] * b["remaining_fraction"], 6),
        "balance_years_label": _years_label(VIM_YEARS[lord] * b["remaining_fraction"]),
        "order": list(_rotated(VIM_ORDER, lord)),
        "abbr": VIM_ABBR,
        "years": VIM_YEARS,
        "kp_chain": kp_chain(b["moon_longitude"]),
        "periods": periods,
    }


def moon_dasha_head(moon_longitude: float, cycle_minutes: float = 390.0) -> dict:
    """Just the lords running at session open — mahadasha + antardasha + their
    balances — without building the whole tree. For the day-log column."""
    b = _moon_balance(moon_longitude, cycle_minutes)
    md_lord = b["dasha_lord"]
    md_full = b["md_full_minutes"]
    entry = b["entry_offset"]
    # walk the antardasha sequence of the running mahadasha to the current sub
    seq = _rotated(VIM_ORDER, md_lord)
    consumed = 0.0
    ad_lord, ad_balance = md_lord, 0.0
    for i in range(400):
        lord = seq[i % 9]
        seg = md_full * VIM_YEARS[lord] / VIM_TOTAL_YEARS
        if consumed + seg > entry + 1e-9:
            ad_lord = lord
            ad_balance = consumed + seg - entry
            break
        consumed += seg
    return {
        "nakshatra": b["nakshatra"],
        "pada": b["pada"],
        "dasha_lord": md_lord,
        "dasha_lord_abbr": VIM_ABBR[md_lord],
        "dasha_balance_minutes": round(b["balance_minutes"], 6),
        "dasha_balance_hms": _hms(b["balance_minutes"]),
        "sub_lord": ad_lord,
        "sub_lord_abbr": VIM_ABBR[ad_lord],
        "sub_balance_hms": _hms(ad_balance),
    }
