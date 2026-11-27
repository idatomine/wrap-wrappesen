# wrap-wrappesen

Min egen Spotify Wrapped (fordi jeg klarer ikke å vente til desember hvert år). Laget fra lyttehistorikken man kan laste ned fra Spotify.
Velg en måned, et helt år eller all time.

## Kom i gang

```bash
pip install -r requirements.txt                  # bare hvis du mangler pandas
python scripts/make_fake_data.py                 # lager testdata i testdata/
python run.py --data testdata --list             # hvilke perioder finnes?
python run.py --data testdata --period 2025      # hele 2025
python run.py --data testdata --period 2025-03   # mars 2025
python run.py --data testdata                    # all time
```

## Egne data

1. Spotify → Konto → Personvern → «Last ned dataene dine» → huk av «Utvidet strømmehistorikk».
2. Legg ZIP-filen du får i `data/` (den trenger ikke pakkes ut).
3. Lag nettsiden: `python run.py --html`, og åpne `output/wrapped.html` i nettleseren.
   Der velger du år og måned (eller All time). Piltastene ← → blar til forrige/neste periode.
4. Vil du heller ha tallene i terminalen: `python run.py --period 2025`.

`data/` står i `.gitignore` fordi eksporten inneholder brukernavn og IP-adresser.

## Struktur

| Fil | Hva den gjør |
|---|---|
| `wrapped/load.py` | Leser eksporten (utvidet historikk eller kontodata, også rett fra ZIP) til én tabell i lokal tid |
| `wrapped/stats.py` | Regner ut alle tallene for en periode (`"all"`, `"2025"`, `"2025-03"`) |
| `wrapped/ui.py` + `wrapped/template.html` | Lager nettsiden. Fargene står øverst i `template.html` |
| `run.py` | Lager nettsiden (`--html`), skriver ut en periode i terminalen, eller lagrer alle perioder som JSON (`--json`) |
| `scripts/make_fake_data.py` | Lager falske data i samme format som Spotify |

## Valg som påvirker tallene

- En avspilling teller først etter 30 sekunder, som hos Spotify. Minutter teller alt.
- Låter rangeres etter antall avspillinger, artister og album etter minutter.
- Tidspunkt er lokal tid, ut fra landet hver avspilling skjedde i.
