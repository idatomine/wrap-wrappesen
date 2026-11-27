"""Regner ut Wrapped-tallene for en valgfri periode.

En periode er en nøkkel:
    "all"       all time
    "2025"      hele 2025
    "2025-03"   mars 2025

Valg som påvirker tallene (endre dem gjerne):
  - En «avspilling» teller først etter 30 sekunder (MIN_MS), slik som hos Spotify.
    Minutter teller alt du har hørt, også låter du hoppet over.
  - Låter rangeres etter antall avspillinger, artister og album etter minutter.
  - Tidspunkt er lokal tid for når låta sluttet.
"""
from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

MIN_MS = 30_000
DAYPARTS = [("natt", 0, 6), ("morgen", 6, 12), ("ettermiddag", 12, 18), ("kveld", 18, 24)]
MONTHS = ["januar", "februar", "mars", "april", "mai", "juni", "juli",
          "august", "september", "oktober", "november", "desember"]


# ---------- perioder ----------

def music(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["kind"] == "music"]


def available_periods(df: pd.DataFrame) -> list[str]:
    """Alle perioder det finnes musikk i: "all", så årene, så månedene."""
    months = sorted(music(df)["local"].dt.strftime("%Y-%m").unique())
    years = sorted({m[:4] for m in months})
    return ["all", *years, *months]


def label(key: str) -> str:
    """"all" -> "All time", "2025" -> "Hele 2025", "2025-03" -> "Mars 2025"."""
    if key == "all":
        return "All time"
    if len(key) == 4:
        return f"Hele {key}"
    return f"{MONTHS[int(key[5:]) - 1].capitalize()} {key[:4]}"


def select(df: pd.DataFrame, key: str) -> pd.DataFrame:
    if key == "all":
        return df
    year = df["local"].dt.year
    if len(key) == 4:
        return df[year == int(key)]
    return df[(year == int(key[:4])) & (df["local"].dt.month == int(key[5:]))]


def _bounds(key: str, ctx: dict) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Første og siste dag i perioden, men aldri utenfor der dataene dine finnes."""
    first, last = ctx["first"].normalize(), ctx["last"].normalize()
    if key == "all":
        start, end = first, last
    elif len(key) == 4:
        start, end = pd.Timestamp(f"{key}-01-01"), pd.Timestamp(f"{key}-12-31")
    else:
        p = pd.Period(key, "M")
        start, end = p.start_time, p.end_time.normalize()
    return max(start, first), min(end, last)


# ---------- byggeklosser ----------

def _records(df: pd.DataFrame) -> list[dict]:
    """DataFrame -> liste med dicts med vanlige Python-typer (klar for JSON)."""
    return json.loads(df.to_json(orient="records", force_ascii=False))


def _minutes(ms) -> int:
    return int(round(ms / 60_000))


def _rank(df: pd.DataFrame, keys: list[str], by: str, n: int) -> list[dict]:
    """Topp n etter "plays" (antall avspillinger) eller "minutes"."""
    if df.empty:
        return []
    aggs = {"plays": ("is_play", "sum"), "ms": ("ms_played", "sum")}
    if "track" in keys:
        aggs["uri"] = ("track_uri", "first")  # nyttig senere, f.eks. for albumbilder
    t = df.assign(is_play=df["ms_played"] >= MIN_MS).groupby(keys).agg(**aggs)
    t["minutes"] = (t.pop("ms") / 60_000).round().astype(int)
    t["plays"] = t["plays"].astype(int)
    order = ["plays", "minutes"] if by == "plays" else ["minutes", "plays"]
    return _records(t.sort_values(order, ascending=False).head(n).reset_index())


def _daypart(hours: pd.Series) -> pd.Series:
    return pd.cut(hours, bins=[0, 6, 12, 18, 24], right=False, labels=[d[0] for d in DAYPARTS])


# ---------- tallene ----------

def overview(m, full, key, ctx) -> dict:
    plays = m[m["ms_played"] >= MIN_MS]
    start, end = _bounds(key, ctx)
    days = (end - start).days + 1
    minutes = _minutes(m["ms_played"].sum())
    return {
        "minutes": minutes,
        "plays": len(plays),
        "unique_tracks": len(plays[["track", "artist"]].drop_duplicates()),
        "unique_artists": int(plays["artist"].nunique()),
        "days_listened": int(m.loc[m["ms_played"] > 0, "local"].dt.date.nunique()),
        "days_in_period": days,
        "minutes_per_day": round(minutes / days, 1),
        "podcast_minutes": _minutes(full.loc[full["kind"] == "podcast", "ms_played"].sum()),
    }


def timeline(m, key) -> list[dict]:
    """Minutter over tid: per måned for all time og år, per dag for en måned."""
    if len(key) == 7:
        s = m.groupby(m["local"].dt.strftime("%Y-%m-%d"))["ms_played"].sum()
        idx = [f"{key}-{d:02d}" for d in range(1, pd.Period(key, "M").days_in_month + 1)]
    else:
        s = m.groupby(m["local"].dt.strftime("%Y-%m"))["ms_played"].sum()
        if key == "all":
            idx = list(pd.period_range(s.index.min(), s.index.max(), freq="M").strftime("%Y-%m"))
        else:
            idx = [f"{key}-{i:02d}" for i in range(1, 13)]
    s = (s / 60_000).reindex(idx, fill_value=0).round().astype(int)
    return [{"label": k, "minutes": int(v)} for k, v in s.items()]


def minutes_per_hour(m) -> list[int]:
    s = m.groupby(m["local"].dt.hour)["ms_played"].sum().reindex(range(24), fill_value=0)
    return [_minutes(v) for v in s]


def minutes_per_weekday(m) -> list[int]:
    s = m.groupby(m["local"].dt.dayofweek)["ms_played"].sum().reindex(range(7), fill_value=0)
    return [_minutes(v) for v in s]


def week_heatmap(m) -> list[list[int]]:
    """7 x 24 minutter: rad = ukedag (0 = mandag), kolonne = time."""
    t = (m.groupby([m["local"].dt.dayofweek.rename("d"), m["local"].dt.hour.rename("h")])["ms_played"]
          .sum().unstack(fill_value=0)
          .reindex(index=range(7), columns=range(24), fill_value=0))
    return (t / 60_000).round().astype(int).values.tolist()


def dayparts(m, n=3) -> list[dict]:
    """Hva du hører på om natta, morgenen, ettermiddagen og kvelden."""
    part = _daypart(m["local"].dt.hour)
    out = []
    for name, start, end in DAYPARTS:
        sub = m[part == name]
        out.append({
            "name": name, "from": start, "to": end,
            "minutes": _minutes(sub["ms_played"].sum()),
            "top_artists": _rank(sub, ["artist"], "minutes", n),
            "top_tracks": _rank(sub, ["track", "artist"], "plays", n),
        })
    return out


def daypart_trend(m, key) -> list[dict] | None:
    """Andel av lyttingen i hver del av døgnet, per år (all time) eller per måned (et år)."""
    if len(key) == 7:
        return None
    bucket = (m["local"].dt.year.astype(str) if key == "all" else m["local"].dt.strftime("%Y-%m")).rename("bucket")
    part = _daypart(m["local"].dt.hour).rename("part")
    t = m.groupby([bucket, part], observed=False)["ms_played"].sum().unstack(fill_value=0)
    share = t.div(t.sum(axis=1), axis=0).fillna(0)
    return [{"label": k, **{p: round(float(share.loc[k, p]), 3) for p in share.columns}} for k in share.index]


def top_track_per_bucket(m, key) -> list[dict] | None:
    """Årets låt for hvert år (all time) eller månedens låt for hver måned (et år)."""
    if len(key) == 7:
        return None
    plays = m[m["ms_played"] >= MIN_MS]
    bucket = (plays["local"].dt.year.astype(str) if key == "all" else plays["local"].dt.strftime("%Y-%m")).rename("label")
    counts = plays.groupby([bucket, "track", "artist"]).size().rename("plays").reset_index()
    best = counts.sort_values(["label", "plays"], ascending=[True, False]).drop_duplicates("label")
    return _records(best)


def biggest_day(m) -> dict:
    per_day = m.groupby(m["local"].dt.date)["ms_played"].sum()
    return {"date": str(per_day.idxmax()), "minutes": _minutes(per_day.max())}


def longest_streak(m) -> dict | None:
    """Flest dager på rad med lytting."""
    days = pd.Series(sorted(m.loc[m["ms_played"] > 0, "local"].dt.normalize().unique()))
    if days.empty:
        return None
    run_id = (days.diff() != pd.Timedelta(days=1)).cumsum()
    runs = days.groupby(run_id).agg(["size", "first", "last"])
    best = runs.loc[runs["size"].idxmax()]
    return {"days": int(best["size"]), "from": str(best["first"].date()), "to": str(best["last"].date())}


def first_song(m) -> dict | None:
    plays = m[m["ms_played"] >= MIN_MS]
    if plays.empty:
        return None
    row = plays.sort_values("local").iloc[0]
    return {"track": row["track"], "artist": row["artist"], "time": row["local"].strftime("%Y-%m-%d %H:%M")}


def skip_stats(m) -> dict | None:
    """Andel låter du hoppet over, og låta du hoppet over flest ganger. Krever utvidet historikk."""
    if (m["source"] != "extended").any():
        return None
    skipped = m["skipped"].astype(bool)
    per_track = skipped.groupby([m["track"], m["artist"]]).sum().sort_values(ascending=False)
    (track, artist), n = per_track.index[0], int(per_track.iloc[0])
    return {"skip_rate": round(float(skipped.mean()), 3),
            "most_skipped": {"track": track, "artist": artist, "skips": n}}


def new_artists(m, key, ctx, n) -> list[dict] | None:
    """Artister du hørte for første gang i perioden, rangert etter minutter.
    Krever utvidet historikk, og at dataene dine starter før perioden."""
    if key == "all" or ctx["source"] != "extended":
        return None
    start = pd.Timestamp(f"{key}-01-01" if len(key) == 4 else f"{key}-01")
    if ctx["first"] >= start:
        return None  # vi vet ikke hva du hørte før dataene starter
    first_heard = ctx["first_heard"]
    new = first_heard[first_heard >= start].index
    return _rank(m[m["artist"].isin(new)], ["artist"], "minutes", n)


# ---------- alt samlet ----------

def _context(df: pd.DataFrame) -> dict:
    """Ting som gjelder hele historikken, og som vi bare vil regne ut én gang."""
    m = music(df)
    plays = m[m["ms_played"] >= MIN_MS]
    return {
        "first": m["local"].min(),
        "last": m["local"].max(),
        "source": m["source"].iloc[0],
        "first_heard": plays.groupby("artist")["local"].min(),
    }


def build_period(df: pd.DataFrame, key: str, n: int = 10, ctx: dict | None = None) -> dict:
    """Alle tallene for én periode, som en dict med vanlige Python-typer."""
    ctx = ctx or _context(df)
    full = select(df, key)
    m = music(full)
    if m.empty:
        raise ValueError(f"Ingen musikk i perioden {label(key)}")
    start, end = _bounds(key, ctx)
    by_hour = minutes_per_hour(m)
    by_weekday = minutes_per_weekday(m)
    return {
        "key": key,
        "label": label(key),
        "first_date": str(start.date()),
        "last_date": str(end.date()),
        "overview": overview(m, full, key, ctx),
        "top_tracks": _rank(m, ["track", "artist"], "plays", n),
        "top_artists": _rank(m, ["artist"], "minutes", n),
        "top_albums": _rank(m, ["album", "artist"], "minutes", n),
        "timeline": timeline(m, key),
        "minutes_per_hour": by_hour,
        "minutes_per_weekday": by_weekday,
        "favorite_hour": by_hour.index(max(by_hour)),
        "favorite_weekday": by_weekday.index(max(by_weekday)),
        "week_heatmap": week_heatmap(m),
        "dayparts": dayparts(m),
        "daypart_trend": daypart_trend(m, key),
        "top_track_per_bucket": top_track_per_bucket(m, key),
        "biggest_day": biggest_day(m),
        "longest_streak": longest_streak(m),
        "first_song": first_song(m),
        "skips": skip_stats(m),
        "new_artists": new_artists(m, key, ctx, n),
    }


def build_all(df: pd.DataFrame, n: int = 10) -> dict:
    """Tallene for alle perioder – det grensesnittet trenger."""
    ctx = _context(df)
    keys = available_periods(df)
    return {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "source": ctx["source"],
        "periods": [{"key": k, "label": label(k)} for k in keys],
        "data": {k: build_period(df, k, n, ctx) for k in keys},
    }
