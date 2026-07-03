#!/usr/bin/env python3
"""Historical SEC-only backfill for calibration.

This script collects historical SEC filing metadata for the configured watchlist. It does
not create fake labels. It produces an event spine that can be compared to later outcomes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
OUT = ROOT / "data" / "backfill_sec_events.jsonl"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def get_json(url: str, headers: dict[str, str]):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def parse_recent(recent: dict):
    n = max((len(v) for v in recent.values() if isinstance(v, list)), default=0)
    for i in range(n):
        row = {}
        for k, v in recent.items():
            if isinstance(v, list) and i < len(v):
                row[k] = v[i]
        yield row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=float, default=5.0)
    args = ap.parse_args()
    user_agent = os.getenv("SEC_USER_AGENT", "").strip()
    if not user_agent:
        print("SEC_USER_AGENT is required", file=sys.stderr)
        return 2
    headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
    watchlist = load_json(CONFIG_DIR / "watchlist.json")
    signals = load_json(CONFIG_DIR / "signals.json")
    form_weights = signals.get("sec_form_weights", {})
    tickers = get_json(SEC_TICKERS_URL, headers)
    by_ticker = {str(v.get("ticker", "")).upper(): v for v in tickers.values()}
    cutoff = dt.date.today() - dt.timedelta(days=int(args.years * 365.25))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with OUT.open("w", encoding="utf-8") as f:
        for entry in watchlist.get("tickers", []):
            ticker = str(entry.get("ticker", "")).upper().strip()
            sector = str(entry.get("sector", "unknown"))
            info = by_ticker.get(ticker)
            if not info:
                continue
            cik = int(info["cik_str"])
            data = get_json(SEC_SUBMISSIONS_URL.format(cik10=f"{cik:010d}"), headers)
            time.sleep(0.12)
            for row in parse_recent(data.get("filings", {}).get("recent", {})):
                form = str(row.get("form", "")).upper()
                if form not in form_weights:
                    continue
                filing_date = str(row.get("filingDate", ""))
                try:
                    d = dt.date.fromisoformat(filing_date)
                except ValueError:
                    continue
                if d < cutoff:
                    continue
                event = {
                    "ticker": ticker,
                    "company": info.get("title"),
                    "sector": sector,
                    "filingDate": filing_date,
                    "form": form,
                    "items": row.get("items"),
                    "accessionNumber": row.get("accessionNumber"),
                    "primaryDocument": row.get("primaryDocument"),
                    "source": "SEC EDGAR submissions",
                }
                f.write(json.dumps(event, sort_keys=True) + "\n")
                count += 1
    print(json.dumps({"output": str(OUT), "events": count}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
