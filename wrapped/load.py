"""Leser Spotify-eksporten din inn i én pandas-tabell.

Spotify har to pakker med lyttehistorikk:
  - «Utvidet strømmehistorikk»: Streaming_History_Audio_*.json
    Hele kontoens levetid, med track-URI, skips, shuffle, land osv.
  - «Kontodata»: StreamingHistory_music_*.json
    Bare siste år, og bare fire felt (tid, artist, låt, millisekunder).

Du kan peke på en mappe med utpakkede filer, på ZIP-filen rett fra Spotify,
eller på en mappe som inneholder ZIP-filer. Har du begge pakkene, brukes bare
den utvidede, siden den inneholder alt kontodataen har.

Tabellen har én rad per avspilling og disse kolonnene:
  ts          når avspillingen SLUTTET, i UTC (slik Spotify lagrer det)
  local       samme tidspunkt i lokal tid – all statistikk bruker denne
  ms_played   hvor lenge du faktisk hørte, i millisekunder
  kind        "music", "podcast", "audiobook" eller "unknown"
  track, artist, album, track_uri, episode, show, audiobook
  skipped     True hvis du hoppet videre (bare i utvidet historikk, ellers tom)
  shuffle, platform, country, reason_start, reason_end, incognito
  source      "extended" eller "account"
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

# Tidssone per landkode (conn_country). Spotify oppgir bare land, ikke by, så for
# land med flere tidssoner (USA, Canada, Australia ...) er dette en tilnærming.
COUNTRY_TZ = {
    "NO": "Europe/Oslo", "SE": "Europe/Stockholm", "DK": "Europe/Copenhagen",
    "FI": "Europe/Helsinki", "IS": "Atlantic/Reykjavik", "GB": "Europe/London",
    "IE": "Europe/Dublin", "DE": "Europe/Berlin", "NL": "Europe/Amsterdam",
    "BE": "Europe/Brussels", "FR": "Europe/Paris", "ES": "Europe/Madrid",
    "PT": "Europe/Lisbon", "IT": "Europe/Rome", "AT": "Europe/Vienna",
    "CH": "Europe/Zurich", "PL": "Europe/Warsaw", "CZ": "Europe/Prague",
    "HR": "Europe/Zagreb", "GR": "Europe/Athens", "EE": "Europe/Tallinn",
    "LV": "Europe/Riga", "LT": "Europe/Vilnius", "TR": "Europe/Istanbul",
    "ZA": "Africa/Johannesburg", "EG": "Africa/Cairo", "AE": "Asia/Dubai",
    "TH": "Asia/Bangkok", "JP": "Asia/Tokyo", "SG": "Asia/Singapore",
    "KR": "Asia/Seoul", "CN": "Asia/Shanghai", "PH": "Asia/Manila",
    "MY": "Asia/Kuala_Lumpur", "VN": "Asia/Ho_Chi_Minh", "MN": "Asia/Ulaanbaatar",
    "IN": "Asia/Kolkata", "ID": "Asia/Jakarta",
    "US": "America/New_York", "CA": "America/Toronto", "MX": "America/Mexico_City",
    "BR": "America/Sao_Paulo", "AU": "Australia/Sydney", "NZ": "Pacific/Auckland",
}
DEFAULT_TZ = "Europe/Oslo"  # brukes når landet mangler, er "ZZ" (Spotify sin kode for ukjent) eller ikke står i lista

EXTENDED_PREFIX = "Streaming_History_Audio_"
ACCOUNT_PREFIX = "StreamingHistory_music_"

COLUMNS = [
    "ts", "local", "ms_played", "kind", "track", "artist", "album", "track_uri",
    "episode", "show", "audiobook", "skipped", "shuffle", "platform", "country",
    "reason_start", "reason_end", "incognito", "source",
]


def load_history(path: str | Path = "data", force_tz: str | None = None) -> pd.DataFrame:
    """Les all lyttehistorikk under `path`.

    force_tz: bruk én tidssone for alt (f.eks. "Europe/Oslo") i stedet for å gå ut fra landet.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Finner ikke {path}")

    extended, account = [], []
    for name, records in _read_history_files(path):
        (extended if name.startswith(EXTENDED_PREFIX) else account).extend(records)

    if extended:
        df = _from_extended(extended)
    elif account:
        df = _from_account(account)
    else:
        raise FileNotFoundError(
            f"Fant ingen lyttehistorikk i {path}. Ventet filer som "
            f"{EXTENDED_PREFIX}*.json eller {ACCOUNT_PREFIX}*.json (gjerne inni en ZIP)."
        )

    # Samme avspilling kan dukke opp flere ganger hvis både ZIP-en og den
    # utpakkede mappa ligger i data/, eller hvis du har lastet ned flere ganger.
    df = df.drop_duplicates(subset=["ts", "ms_played", "track", "artist", "episode", "audiobook"])

    if force_tz:
        zones = pd.Series(force_tz, index=df.index)
    else:
        zones = df["country"].map(COUNTRY_TZ).fillna(DEFAULT_TZ)
    df["local"] = _to_local(df["ts"], zones)
    return df.sort_values("ts").reset_index(drop=True)[COLUMNS]


def _is_history_file(name: str) -> bool:
    return name.endswith(".json") and name.startswith((EXTENDED_PREFIX, ACCOUNT_PREFIX))


def _read_history_files(path: Path):
    """Gir (filnavn, liste med avspillinger) for hver historikkfil, også dem inni ZIP-filer."""
    candidates = [path] if path.is_file() else sorted(path.rglob("*"))
    for p in candidates:
        if p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as zf:
                for member in sorted(zf.namelist()):
                    name = member.rsplit("/", 1)[-1]
                    if _is_history_file(name):
                        yield name, json.loads(zf.read(member).decode("utf-8"))
        elif _is_history_file(p.name):
            yield p.name, json.loads(p.read_text(encoding="utf-8"))


def _from_extended(records: list[dict]) -> pd.DataFrame:
    raw = pd.DataFrame.from_records(records)

    def col(name):
        # Eldre eksporter mangler noen felt; da fyller vi inn tomme verdier.
        return raw[name] if name in raw.columns else pd.Series(None, index=raw.index, dtype=object)

    df = pd.DataFrame({
        "ts": pd.to_datetime(col("ts"), utc=True),
        "ms_played": col("ms_played").fillna(0).astype("int64"),
        "track": col("master_metadata_track_name"),
        "artist": col("master_metadata_album_artist_name"),
        "album": col("master_metadata_album_album_name"),
        "track_uri": col("spotify_track_uri"),
        "episode": col("episode_name"),
        "show": col("episode_show_name"),
        "audiobook": col("audiobook_title"),
        "shuffle": col("shuffle"),
        "platform": col("platform"),
        "country": col("conn_country"),
        "reason_start": col("reason_start"),
        "reason_end": col("reason_end"),
        "incognito": col("incognito_mode"),
    })
    df["kind"] = np.select(
        [df["track"].notna(), df["episode"].notna(), df["audiobook"].notna()],
        ["music", "podcast", "audiobook"],
        default="unknown",
    )
    # «skipped» er ofte tomt i eldre data, så vi teller også
    # «avsluttet med neste-knappen» (reason_end == "fwdbtn") som et skip.
    df["skipped"] = col("skipped").eq(True) | df["reason_end"].eq("fwdbtn")
    df["source"] = "extended"
    return df


def _from_account(records: list[dict]) -> pd.DataFrame:
    raw = pd.DataFrame.from_records(records)
    df = pd.DataFrame({
        "ts": pd.to_datetime(raw["endTime"], utc=True),  # Spotify oppgir endTime i UTC
        "ms_played": raw["msPlayed"].astype("int64"),
        "track": raw["trackName"],
        "artist": raw["artistName"],
    })
    for c in ["album", "track_uri", "episode", "show", "audiobook", "skipped", "shuffle",
              "platform", "country", "reason_start", "reason_end", "incognito"]:
        df[c] = None
    df["kind"] = "music"
    df["source"] = "account"
    return df


def _to_local(ts_utc: pd.Series, zones: pd.Series) -> pd.Series:
    """Gjør UTC om til lokal tid, med riktig tidssone for hver rad."""
    parts = [ts_utc[zones == z].dt.tz_convert(z).dt.tz_localize(None) for z in zones.unique()]
    return pd.concat(parts).reindex(ts_utc.index)
