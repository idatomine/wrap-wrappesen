"""Lager falsk Spotify-lyttehistorikk, så du kan bygge og teste før dine egne data kommer.

Filene får samme navn og felt som Spotify-eksporten:
    testdata/Spotify Extended Streaming History/Streaming_History_Audio_<år>_<n>.json   (utvidet)
    testdata/Spotify Account Data/StreamingHistory_music_0.json                        (kontodata, siste år)

Alle artister, låter og podkaster er oppdiktet.

Bruk:
    python scripts/make_fake_data.py
    python scripts/make_fake_data.py --seed 7 --end 2026-11-15
"""
from __future__ import annotations

import argparse
import json
import string
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
START = date(2024, 1, 1)
TRIP = (date(2025, 8, 4), date(2025, 8, 10))  # en uke i London, for å teste tidssoner
TZ = {"NO": "Europe/Oslo", "GB": "Europe/London"}
CHUNK = 10_000  # avspillinger per fil

ARTIST_FIRST = ["Nordlys", "Fjell", "Midnatt", "Glass", "Bølge", "Sølv", "Neon", "Skygge",
                "Vinter", "Papir", "Kobber", "Salt", "Torden", "Sommer", "Måne", "Is"]
ARTIST_LAST = ["klubben", "kollektivet", "bandet", "maskinen", "orkesteret",
               "duoen", "radio", "hjertet", "byen", "gjengen"]
WORDS = ["natt", "lys", "regn", "vei", "hjem", "tog", "brev", "himmel", "vind", "sol",
         "tid", "dans", "hav", "stjerne", "drøm", "storm", "gate", "gull", "kyst", "feber"]
SHOWS = ["Pratepodden", "Morgenkaffe med data", "Historier fra fjellet"]
N_ARTISTS = 45
PLATFORMS, PLATFORM_P = ["ios", "osx", "web_player"], [0.6, 0.3, 0.1]

# Hvor sannsynlig det er å starte en lytteøkt hver time (topp morgen, ettermiddag og kveld)
HOUR_W = np.array([0.3, 0.15, 0.1, 0.05, 0.05, 0.1, 0.4, 1.2, 1.5, 1.0, 0.8, 0.8,
                   1.0, 0.9, 0.9, 1.3, 1.6, 1.4, 1.1, 1.0, 1.2, 1.4, 1.1, 0.6])

FIELDS = [
    "ts", "platform", "ms_played", "conn_country", "ip_addr",
    "master_metadata_track_name", "master_metadata_album_artist_name",
    "master_metadata_album_album_name", "spotify_track_uri",
    "episode_name", "episode_show_name", "spotify_episode_uri",
    "audiobook_title", "audiobook_uri", "audiobook_chapter_uri", "audiobook_chapter_title",
    "reason_start", "reason_end", "shuffle", "skipped", "offline",
    "offline_timestamp", "incognito_mode",
]


def title(rng, k_min=1, k_max=3):
    words = rng.choice(WORDS, size=int(rng.integers(k_min, k_max + 1)), replace=False)
    return " ".join(words).capitalize()


def uri(rng, kind):
    alphabet = np.array(list(string.ascii_letters + string.digits))
    return f"spotify:{kind}:" + "".join(rng.choice(alphabet, 22))


def utc_str(t):
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_catalog(rng, n_days):
    """Artister med album og låter. Noen artister «debuterer» underveis, og hver
    artist har en periode der du hører ekstra mye på dem, så toppen endrer seg over tid."""
    combos = [a + b for a in ARTIST_FIRST for b in ARTIST_LAST]
    artists = []
    for rank, i in enumerate(rng.choice(len(combos), size=N_ARTISTS, replace=False)):
        tracks = []
        for _ in range(int(rng.integers(1, 4))):
            album = title(rng, 1, 2)
            for _ in range(int(rng.integers(3, 9))):
                tracks.append({"name": title(rng), "album": album, "uri": uri(rng, "track"),
                               "dur_ms": int(rng.integers(120_000, 300_000))})
        w = 1 / np.arange(1, len(tracks) + 1) ** 1.2
        artists.append({
            "name": combos[i],
            "base": 1 / (rank + 1) ** 1.1,
            "debut": 0 if rng.random() < 0.7 else int(rng.integers(0, n_days)),
            "peak": rng.uniform(0, n_days),
            "width": rng.uniform(30, 200),
            "tracks": tracks,
            "track_p": w / w.sum(),
        })
    return artists


def artist_probs(artists, day_i):
    w = np.array([
        0.0 if day_i < a["debut"]
        else a["base"] * (0.3 + 1.5 * np.exp(-((day_i - a["peak"]) / a["width"]) ** 2))
        for a in artists
    ])
    return w / w.sum()


def music_session(rng, t, base, artists, p):
    rows = []
    shuffle = bool(rng.random() < 0.5)
    reason_start = str(rng.choice(["clickrow", "playbtn"]))
    artist = None
    for _ in range(1 + int(rng.poisson(7))):
        if artist is None or rng.random() > 0.3:  # 30 % sjanse for å bli hos samme artist
            artist = artists[rng.choice(len(artists), p=p)]
        track = artist["tracks"][rng.choice(len(artist["tracks"]), p=artist["track_p"])]
        dur = track["dur_ms"]
        r = rng.random()
        if r < 0.01:
            ms, reason_end, skipped = 0, "trackerror", False
        elif r < 0.17:  # hoppet over før 30 s
            ms, reason_end, skipped = int(rng.integers(500, 30_000)), "fwdbtn", True
        elif r < 0.22:  # hoppet over etter 30 s
            ms, reason_end, skipped = int(rng.integers(30_000, dur)), "fwdbtn", True
        elif r < 0.25:  # stoppet midt i
            ms, reason_end, skipped = int(rng.integers(30_000, dur)), "endplay", False
        else:
            ms, reason_end, skipped = dur, "trackdone", False
        t = t + timedelta(milliseconds=ms)
        rows.append({**base, "ts": utc_str(t), "ms_played": ms,
                     "master_metadata_track_name": track["name"],
                     "master_metadata_album_artist_name": artist["name"],
                     "master_metadata_album_album_name": track["album"],
                     "spotify_track_uri": track["uri"],
                     "reason_start": reason_start, "reason_end": reason_end,
                     "shuffle": shuffle, "skipped": skipped})
        if reason_end == "endplay":
            break
        reason_start = "trackdone" if reason_end == "trackerror" else reason_end
    return rows


def podcast_session(rng, t, base, episodes):
    show = str(rng.choice(SHOWS))
    name, ep_uri = episodes[show][int(rng.integers(len(episodes[show])))]
    ms = int(rng.integers(5, 60)) * 60_000
    t = t + timedelta(milliseconds=ms)
    return [{**base, "ts": utc_str(t), "ms_played": ms,
             "episode_name": name, "episode_show_name": show, "spotify_episode_uri": ep_uri,
             "reason_start": "clickrow", "reason_end": str(rng.choice(["endplay", "trackdone"])),
             "shuffle": False, "skipped": False}]


def generate(seed, end):
    rng = np.random.default_rng(seed)
    n_days = (end - START).days + 1
    artists = make_catalog(rng, n_days)
    episodes = {s: [(f"#{i}: {title(rng)}", uri(rng, "episode")) for i in range(1, 60)] for s in SHOWS}
    hour_p = HOUR_W / HOUR_W.sum()
    rows = []
    for day_i in range(n_days):
        day = START + timedelta(days=day_i)
        country = "GB" if TRIP[0] <= day <= TRIP[1] else "NO"
        tz = ZoneInfo(TZ[country])
        p = artist_probs(artists, day_i)
        for _ in range(int(rng.poisson(2.8 if day.weekday() >= 5 else 2.2))):
            t = datetime(day.year, day.month, day.day, int(rng.choice(24, p=hour_p)),
                         int(rng.integers(60)), int(rng.integers(60)), tzinfo=tz)
            base = {**dict.fromkeys(FIELDS), "conn_country": country,
                    "platform": str(rng.choice(PLATFORMS, p=PLATFORM_P)),
                    "ip_addr": f"192.0.2.{int(rng.integers(1, 255))}",
                    "offline": False, "incognito_mode": False}
            if rng.random() < 0.08:
                rows += podcast_session(rng, t, base, episodes)
            else:
                rows += music_session(rng, t, base, artists, p)
    rows.sort(key=lambda r: r["ts"])
    return rows


def write_extended(rows, out):
    folder = out / "Spotify Extended Streaming History"
    folder.mkdir(parents=True, exist_ok=True)
    by_year = {}
    for r in rows:
        by_year.setdefault(r["ts"][:4], []).append(r)
    i = 0
    for year, year_rows in sorted(by_year.items()):
        for s in range(0, len(year_rows), CHUNK):
            path = folder / f"Streaming_History_Audio_{year}_{i}.json"
            path.write_text(json.dumps(year_rows[s:s + CHUNK], ensure_ascii=False, indent=2), encoding="utf-8")
            i += 1


def write_account(rows, out, end):
    """Kontodata-formatet: bare musikk, bare siste år, bare fire felt."""
    cutoff = (end - timedelta(days=365)).isoformat()
    records = [{"endTime": r["ts"][:16].replace("T", " "),
                "artistName": r["master_metadata_album_artist_name"],
                "trackName": r["master_metadata_track_name"],
                "msPlayed": r["ms_played"]}
               for r in rows if r["ts"] >= cutoff and r["master_metadata_track_name"]]
    folder = out / "Spotify Account Data"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "StreamingHistory_music_0.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "testdata")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--end", type=date.fromisoformat, default=date.today(), help="siste dag, f.eks. 2026-11-15")
    args = ap.parse_args()

    rows = generate(args.seed, args.end)
    write_extended(rows, args.out)
    write_account(rows, args.out, args.end)
    print(f"Skrev {len(rows):,} avspillinger ({START} – {args.end}) til {args.out}".replace(",", " "))


if __name__ == "__main__":
    main()
