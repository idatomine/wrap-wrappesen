"""Skriv ut Wrapped for en periode i terminalen, eller lagre alle perioder som JSON.

Eksempler:
    python run.py --data testdata                        # all time
    python run.py --data testdata --period 2025          # hele 2025
    python run.py --data testdata --period 2025-03       # mars 2025
    python run.py --data testdata --list                 # vis hvilke perioder som finnes
    python run.py --data testdata --json output/wrapped.json   # alle perioder til én fil
    python run.py --html                                 # lag nettsiden output/wrapped.html fra data/
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from wrapped.load import load_history
from wrapped.stats import MONTHS, available_periods, build_all, build_period, label
from wrapped.ui import write_html

WEEKDAYS = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]
SOURCE = {"extended": "utvidet strømmehistorikk", "account": "kontodata"}


def num(x) -> str:
    return f"{x:,}".replace(",", " ")


def nice_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day}. {MONTHS[d.month - 1]} {d.year}"


def section(title, lines):
    if not lines:
        return
    print(title)
    for i, line in enumerate(lines, 1):
        print(f"  {i:>2}. {line}")
    print()


def bars(rows, width=30):
    top = max((v for _, v in rows), default=0) or 1
    for name, v in rows:
        print(f"  {name:<8} {'█' * round(width * v / top):<{width}} {num(v)}")
    print()


def print_period(w: dict):
    o = w["overview"]
    print(f"\n═══ {w['label']} ═══   ({nice_date(w['first_date'])} – {nice_date(w['last_date'])})\n")
    print(f"{num(o['minutes'])} minutter musikk (≈ {o['minutes'] / 60:.0f} timer, {o['minutes_per_day']} min per dag)")
    print(f"{num(o['plays'])} avspillinger · {num(o['unique_tracks'])} ulike låter · {num(o['unique_artists'])} artister")
    print(f"Lyttet {o['days_listened']} av {o['days_in_period']} dager · {num(o['podcast_minutes'])} min podkast\n")

    section("Topplåter", [f"{r['track']} – {r['artist']}  ({r['plays']} avspillinger)" for r in w["top_tracks"][:5]])
    section("Toppartister", [f"{r['artist']}  ({num(r['minutes'])} min)" for r in w["top_artists"][:5]])
    section("Toppalbum", [f"{r['album']} – {r['artist']}  ({num(r['minutes'])} min)" for r in w["top_albums"][:5]])

    print("Minutter over tid")
    tl = w["timeline"]
    fmt = (lambda s: s[8:]) if len(w["key"]) == 7 else (lambda s: f"{MONTHS[int(s[5:]) - 1][:3]} {s[2:4]}")
    bars([(fmt(r["label"]), r["minutes"]) for r in tl if r["minutes"] or len(tl) <= 12])

    print("Tid på døgnet (minutter per time)")
    bars([(f"kl. {h:02d}", v) for h, v in enumerate(w["minutes_per_hour"])], width=24)

    for p in w["dayparts"]:
        top = p["top_artists"][0]["artist"] if p["top_artists"] else "–"
        print(f"  {p['name']:<12} ({p['from']:02d}–{p['to']:02d})  {num(p['minutes']):>7} min   mest: {top}")
    print()

    if w["daypart_trend"]:
        print("Andel av lyttingen per del av døgnet")
        print(f"  {'':<8} {'natt':>6} {'morgen':>7} {'etterm.':>8} {'kveld':>6}")
        for r in w["daypart_trend"]:
            print(f"  {r['label']:<8} {r['natt']:>6.0%} {r['morgen']:>7.0%} {r['ettermiddag']:>8.0%} {r['kveld']:>6.0%}")
        print()

    if w["top_track_per_bucket"]:
        section("Månedens/årets låt", [f"{r['label']}: {r['track']} – {r['artist']} ({r['plays']})"
                                        for r in w["top_track_per_bucket"]])

    h = w["favorite_hour"]
    print(f"Favoritt-tidspunkt: kl. {h:02d}–{(h + 1) % 24:02d} · favorittdag: {WEEKDAYS[w['favorite_weekday']]}")
    bd = w["biggest_day"]
    print(f"Største lyttedag: {nice_date(bd['date'])} ({num(bd['minutes'])} min)")
    if w["longest_streak"]:
        st = w["longest_streak"]
        print(f"Lengste streak: {st['days']} dager på rad ({nice_date(st['from'])} – {nice_date(st['to'])})")
    if w["first_song"]:
        fs = w["first_song"]
        print(f"Første låt: {fs['track']} – {fs['artist']} ({fs['time']})")
    if w["skips"]:
        s = w["skips"]
        ms = s["most_skipped"]
        print(f"Hoppet over {s['skip_rate']:.0%} av låtene · mest skippet: {ms['track']} – {ms['artist']} ({ms['skips']} ganger)")
    print()
    if w["new_artists"]:
        section("Nye artister i perioden", [f"{r['artist']}  ({num(r['minutes'])} min)" for r in w["new_artists"][:5]])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=Path("data"), help="mappe eller ZIP med Spotify-eksporten (standard: data/)")
    ap.add_argument("--period", default="all", help='"all", et år ("2025") eller en måned ("2025-03")')
    ap.add_argument("--list", action="store_true", help="vis hvilke perioder som finnes")
    ap.add_argument("--tz", help="bruk én tidssone for alt, f.eks. Europe/Oslo (standard: ut fra landet)")
    ap.add_argument("--json", type=Path, help="lagre alle perioder som JSON her")
    ap.add_argument("--html", type=Path, nargs="?", const=Path("output/wrapped.html"),
                    help="lag nettsiden med periodevelger (standard: output/wrapped.html)")
    ap.add_argument("--title", default="Idas Wrapped", help="navnet øverst på nettsiden")
    args = ap.parse_args()

    df = load_history(args.data, force_tz=args.tz)
    print(f"Leste {num(len(df))} avspillinger fra {SOURCE[df['source'].iloc[0]]}")

    if args.list:
        print("\n".join(f"  {k:<8} {label(k)}" for k in available_periods(df)))
    elif args.html:
        path = write_html(build_all(df), args.html, title=args.title, rows=len(df))
        print(f"Lagret nettsiden i {path}. Åpne den i nettleseren.")
    elif args.json:
        everything = build_all(df)
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(everything, ensure_ascii=False), encoding="utf-8")
        print(f"Lagret {len(everything['periods'])} perioder i {args.json}")
    else:
        print_period(build_period(df, args.period))


if __name__ == "__main__":
    main()
