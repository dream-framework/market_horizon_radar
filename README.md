# Corporate Horizon Radar

Live-only DREAM/S2 playground for corporate horizon compression.

This repo builds an hourly dashboard from real public feeds only. It does not ship demo data. If live feeds are unavailable, the dashboard reports insufficient evidence instead of filling fake values.

## What it does

- Pulls SEC EDGAR company submissions for a configurable watchlist.
- Pulls GDELT live news for corporate stress, corporate reach, macro pressure, and geopolitics vectors.
- Optionally pulls FRED macro series when `FRED_API_KEY` is configured.
- Scores the interplay between:
  - `ridge_reach`: durable expansion / forward optionality evidence.
  - `defensive_decay`: weakening continuation strength.
  - `dust_cloud`: reactive, short-horizon, stability-eroding evidence.
  - `geo_vector`: exogenous geopolitical pressure.
  - `macro_vector`: exogenous macro / credit pressure.
  - `sync`: cross-source / cross-entity clustering.
- Writes static JSON outputs under `public/data/` and serves a GitHub Pages dashboard.

## Hard no-fake-data rule

The updater writes only rows that came from a live source. Every evidence row has:

- `source_type`
- `source`
- `url`
- `observed_at_utc`
- `event_time_utc` when the source provides one
- `title`
- `classification`

If a source fails, the snapshot includes the failure in `feed_status`. It does not create substitute rows.

## Required setup

1. Create a new GitHub repository.
2. Copy these files into it.
3. Add repository secret:
   - `SEC_USER_AGENT`: a real identifying user agent, for example `YourOrgName your.email@example.com`.
4. Optional repository secret:
   - `FRED_API_KEY`: needed only for FRED macro series.
5. Enable GitHub Pages using GitHub Actions.
6. Run the workflow manually once: **Actions -> hourly-live-update -> Run workflow**.

## Main files

```text
.github/workflows/hourly.yml       hourly updater and Pages deployment
config/watchlist.json              companies and sectors to monitor
config/signals.json                source queries, weights, thresholds
scripts/update_live.py             live ingestion + scoring + narrative
scripts/backfill_sec.py            historical SEC backfill for calibration
public/index.html                  dashboard
public/app.js                      dashboard logic
public/styles.css                  dashboard style
public/data/snapshot.json          generated live snapshot, not committed initially
public/data/history.jsonl          generated rolling history, not committed initially
```

## Model interpretation

The probability in the dashboard is a model score, not a guaranteed financial forecast. It becomes more meaningful after historical calibration. Before enough history exists, the model marks `baseline_status` as `warming_up` and lowers confidence.

Recommended use:

1. Let the hourly action run for several weeks.
2. Run `scripts/backfill_sec.py` to build a longer SEC-only event spine.
3. Compare phase spikes to known sector events.
4. Adjust `config/signals.json` weights only after out-of-sample checks.

## Local run

```bash
export SEC_USER_AGENT="YourOrgName your.email@example.com"
python scripts/update_live.py
python -m http.server 8000 -d public
```

Then open `http://localhost:8000`.

## Notes on source coverage

- SEC EDGAR submissions are strongest for formal corporate actions and filings.
- GDELT is strongest for live narrative pressure and geopolitical vectors.
- FRED is optional because it requires an API key.
- This repo does not include paid news, paid market data, SEDAR+, or exchange-primary feeds.

## Strict scoring gate

If SEC is skipped, GDELT returns no corporate rows, or the only live data is FRED/macro context, the app now displays `WARMUP / insufficient_live_corporate_evidence`. In that state:

- `gated p` is `not scored`;
- `raw pressure` is still shown for transparency;
- no S1/S2/S3/S4 phase is emitted.

This prevents the false phase shown by older builds where FRED rows inflated `sync`.

## Live-feed reliability note

The updater uses one combined GDELT DOC request per run and classifies returned articles locally. This avoids the earlier pattern of five separate GDELT calls per hour, which was vulnerable to HTTP 429 rate limiting on GitHub-hosted runners. If GDELT still returns 429, the run records the failure and emits no synthetic news rows. The phase gate remains closed unless SEC/news corporate evidence is actually present.

Required for SEC corporate filings:

```text
SEC_USER_AGENT=CorporateHorizonRadar/1.0 your_email@example.com
```

Optional for macro context:

```text
FRED_API_KEY=your_fred_key
```

## Deployment verification

This build stamps every generated `public/data/snapshot.json` with:

```json
"app_version": "2026-07-02-livefix2-combined-gdelt"
```

After pushing, run the workflow once and open `public/data/snapshot.json` on GitHub Pages. If this version is missing, the deployed page is still serving an older generated snapshot.

The GDELT feed status in this version should show a single query named `corporate_geo_macro_combined`. If you still see separate `corporate_dust`, `defensive_decay`, or `ridge_reach` GDELT feed rows, the old updater is still deployed or the workflow has not rerun after the new commit.


## SEC user-agent plain-text fallback

This build includes a plain-text fallback value:

```text
MarketHorizonRadar/1.0 your_email@example.com
```

It is **not** an API key. It is only the HTTP `User-Agent` string sent to SEC EDGAR. The workflow uses this value if the `SEC_USER_AGENT` GitHub secret is missing. For cleaner SEC compliance, replace `your_email@example.com` in `.github/workflows/hourly.yml` and `config/app_identity.json`, or create a repository secret named `SEC_USER_AGENT` with your real contact email.
