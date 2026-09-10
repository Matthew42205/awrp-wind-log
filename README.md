# AWRP Wind Log

Hourly modelled wind direction and speed at the Allerton Waste Recovery Park
stack, logged automatically so it can be cross-referenced against the
[emissions log](https://github.com/Matthew42205/awrp-emissions-log) to see
whether high-emission events coincided with wind likely to carry the plume
towards surrounding villages.

## What this is (and isn't)

- **Modelled, not measured.** Data comes from the UK Met Office's UKV 2km
  model (`ukmo_uk_deterministic_2km`), accessed via the free
  [Open-Meteo](https://open-meteo.com) API, for the stack's coordinates.
  It is not a physical anemometer reading at the site.
- **Direction is unreliable at low wind speed.** Hours below 2 m/s at 10m
  are flagged `calm_flag=True` and are not assigned a downwind receptor.
- **"Downwind" is a screening flag, not an exposure claim.** It tells you
  the plume was likely travelling in that general direction, not what
  ground-level concentration resulted — that depends on plume rise,
  atmospheric stability, and dilution, none of which this script models.
  Use it to prioritise which emissions events are worth closer scrutiny,
  not as a standalone claim of harm.

## Files

- `wind_logger.py` — fetches the last few days of hourly wind data each
  run, appends any hours not already logged to `wind_log.csv`, and flags
  which receptors/villages fall within the plume's likely path.
- `receptors.json` — the stack coordinate and the list of receptors/
  villages checked each run. See the `_readme` field inside it for the
  provenance of each coordinate — the villages list uses approximate,
  unverified coordinates and should be checked against a map before you
  rely on any single village's flag.
- `wind_log.csv` — created on first run; one row per hour.
- `.github/workflows/wind-log.yml` — runs the logger once per hour via
  GitHub Actions and commits any new rows.

## Setup

1. Create a new **public** GitHub repo (public keeps the data verifiable
   the same way the emissions log is).
2. Push these files to it.
3. In the repo's Settings → Actions → General, make sure "Read and write
   permissions" is enabled for the `GITHUB_TOKEN` (needed for the workflow
   to commit `wind_log.csv` back to the repo).
4. The workflow runs automatically at 5 minutes past every hour. You can
   also trigger it manually from the Actions tab ("Run workflow") to check
   it works before waiting for the schedule.

## Joining with the emissions log

Both logs should be compared in the same timezone. This script requests
data with `timezone=UTC` explicitly, so `wind_log.csv` timestamps are UTC.
Confirm the emissions logger's timestamps are also UTC (or convert one to
match) before joining rows by hour — a mismatch here would silently shift
every comparison by an hour for half the year (BST).

To match a specific emissions reading to a wind row: truncate the
emissions timestamp down to the hour and look up that hour in
`wind_log.csv`.

## Receptor list

`receptors.json` tracks 18 points. Two kinds of entry:

- **`latlon_receptors`** — verified coordinates (Google Maps satellite
  imagery, cross-checked against the stack in the same way). Covers the
  ten settlements you'd care most about: Coneythorpe, Arkendale, Marton
  cum Grafton, Great Ouseburn, Little Ouseburn, Whixley, Flaxby,
  Knaresborough, Allerton Mauleverer, and Hopperton. The script computes
  exact bearing AND straight-line distance from the stack for these
  automatically — no manual bearing/distance entry needed.
- **`bearing_receptors`** — the remaining ES Ch.10 Table 10.19 points
  (South Farm, Walls Close House, Thornbar Farm, Clareton Village, Marton
  Cottage Farm, Allerton Castle, Mickledale Farm, Marton Moor Farm) where
  no verified coordinate has been added yet, so bearing/distance are
  taken directly from the ES text instead.

**Known discrepancies between the ES's rounded compass directions and the
verified coordinates** (see `_discrepancy_notes` in `receptors.json`):
- Arkendale: ES table says 270°/1750m ("west"); the verified coordinate
  (outside the church) is 304°/2073m — closer to Ch.12's looser text
  description ("north-west").
- Flaxby: ES text says "south-west"; the verified coordinate (Bay Horse
  Inn, village centre) is 120°/6125m — south-east, nearly the opposite
  side of the compass. Worth checking before citing the ES's own
  receptor list if this ever matters to correspondence.

Each hour's row now lists downwind receptors with their distance, nearest
first, e.g. `Allerton Castle (1.9km);Whixley (4.1km)`. Distance is a rough
proxy for dilution (further = more diluted, all else equal) — it is not a
substitute for actual dispersion modelling, but it's useful for
prioritising which flagged events are worth a closer look.

`SECTOR_TOLERANCE_DEG` in `wind_logger.py` (default 22.5°, i.e. a 45° cone)
controls how narrowly "downwind" is defined. Narrower = fewer false
positives but more hours where nothing is flagged.

To add another settlement (e.g. if you verify a coordinate for somewhere
not currently listed), add it to `latlon_receptors` with `lat`/`lon` — no
code changes needed.
