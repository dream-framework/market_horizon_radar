#!/usr/bin/env python3
"""Live-only Corporate Horizon Radar updater.

No demo rows are created. If a feed fails, the failure is recorded in feed_status.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import math
import os
import re
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
PUBLIC_DATA_DIR = ROOT / "public" / "data"
DATA_DIR = ROOT / "data"
SNAPSHOT_PATH = PUBLIC_DATA_DIR / "snapshot.json"
EVIDENCE_PATH = PUBLIC_DATA_DIR / "evidence.json"
HISTORY_PATH = PUBLIC_DATA_DIR / "history.jsonl"
RAW_DIR = DATA_DIR / "raw"

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
FRED_OBS_URL = "https://api.stlouisfed.org/fred/series/observations"
APP_VERSION = "2026-07-02-livefix3-sec-user-agent-text"
DEFAULT_SEC_USER_AGENT = "MarketHorizonRadar/1.0 your_email@example.com"


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_z(x: dt.datetime) -> str:
    return x.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: Any) -> dt.datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    candidates = [text]
    if text.endswith("Z"):
        candidates.append(text[:-1] + "+00:00")
    if len(text) == 8 and text.isdigit():
        candidates.append(f"{text[:4]}-{text[4:6]}-{text[6:8]}")
    if re.fullmatch(r"\d{14}", text):
        candidates.append(f"{text[:4]}-{text[4:6]}-{text[6:8]}T{text[8:10]}:{text[10:12]}:{text[12:14]}+00:00")
    for cand in candidates:
        try:
            if cand.endswith("Z"):
                cand = cand[:-1] + "+00:00"
            parsed = dt.datetime.fromisoformat(cand)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
            return parsed.astimezone(dt.timezone.utc)
        except ValueError:
            pass
    return None


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(path)


def append_jsonl(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, sort_keys=True) + "\n")


def read_jsonl(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    if limit is not None:
        lines = lines[-limit:]
    out: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def http_get_json(url: str, headers: dict[str, str] | None = None, timeout: int = 30, retries: int = 3, sleep_s: float = 0.5) -> Any:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            return json.loads(data.decode("utf-8", errors="replace"))
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(sleep_s * (attempt + 1))
    raise RuntimeError(f"GET JSON failed for {url}: {last_error}")


def http_get_text(url: str, headers: dict[str, str] | None = None, timeout: int = 30, retries: int = 2, sleep_s: float = 0.5) -> str:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            return data.decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(sleep_s * (attempt + 1))
    raise RuntimeError(f"GET text failed for {url}: {last_error}")


def source_id(*parts: str) -> str:
    h = hashlib.sha256("|".join(parts).encode("utf-8", errors="ignore")).hexdigest()
    return h[:24]


def strip_html(text: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def classify_text(text: str, signals: dict[str, Any], hint: str | None = None) -> dict[str, float]:
    scores = {
        "dust_cloud": 0.0,
        "defensive_decay": 0.0,
        "ridge_reach": 0.0,
        "geo_vector": 0.0,
        "macro_vector": 0.0,
    }
    lower = text.lower()
    for cls, words in signals.get("keywords", {}).items():
        for kw in words:
            if kw.lower() in lower:
                scores[cls] = scores.get(cls, 0.0) + 1.0
    if hint in scores:
        scores[hint] += 0.8
    return scores


def nonzero_classes(scores: dict[str, float]) -> list[str]:
    return [k for k, v in scores.items() if v > 0]


def load_sec_ticker_map(sec_headers: dict[str, str], feed_status: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    cache_path = DATA_DIR / "company_tickers_cache.json"
    try:
        raw = http_get_json(SEC_TICKERS_URL, headers=sec_headers)
        write_json(cache_path, raw)
        feed_status.append({"source": "SEC company_tickers", "ok": True, "detail": "downloaded"})
    except Exception as exc:  # noqa: BLE001
        if cache_path.exists():
            raw = load_json(cache_path)
            feed_status.append({"source": "SEC company_tickers", "ok": False, "detail": f"using cache after error: {exc}"})
        else:
            raise
    out: dict[str, dict[str, Any]] = {}
    for item in raw.values():
        ticker = str(item.get("ticker", "")).upper().strip()
        if not ticker:
            continue
        out[ticker] = item
    return out


def sec_doc_url(cik: int, accession: str, primary_doc: str | None) -> str:
    cik_raw = str(int(cik))
    acc_no_dash = accession.replace("-", "")
    if primary_doc:
        return f"https://www.sec.gov/Archives/edgar/data/{cik_raw}/{acc_no_dash}/{primary_doc}"
    return f"https://www.sec.gov/Archives/edgar/data/{cik_raw}/{acc_no_dash}/{accession}.txt"


def parse_recent_columnar(recent: dict[str, Any]) -> list[dict[str, Any]]:
    keys = list(recent.keys())
    n = 0
    for value in recent.values():
        if isinstance(value, list):
            n = max(n, len(value))
    rows = []
    for i in range(n):
        row: dict[str, Any] = {}
        for key in keys:
            value = recent.get(key)
            if isinstance(value, list) and i < len(value):
                row[key] = value[i]
        rows.append(row)
    return rows


def fetch_sec_evidence(watchlist: dict[str, Any], signals: dict[str, Any], now: dt.datetime, feed_status: list[dict[str, Any]]) -> list[dict[str, Any]]:
    env_user_agent = os.getenv("SEC_USER_AGENT", "").strip()
    user_agent = env_user_agent or DEFAULT_SEC_USER_AGENT
    if not env_user_agent:
        feed_status.append({"source": "SEC EDGAR", "ok": True, "detail": "Using plain-text default SEC_USER_AGENT from repository; replace your_email@example.com with a real contact when possible."})

    sec_headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate", "Host": "data.sec.gov"}
    sec_file_headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
    ticker_map = load_sec_ticker_map(sec_file_headers, feed_status)
    lookback = dt.timedelta(hours=float(watchlist.get("lookback_hours", 72)))
    cutoff = now - lookback
    max_companies = int(watchlist.get("max_sec_companies_per_run", 60))
    doc_fetch_limit = int(watchlist.get("sec_document_fetch_limit_per_run", 35))
    doc_fetch_count = 0
    evidence: list[dict[str, Any]] = []
    form_weights = signals.get("sec_form_weights", {})
    item_weights = signals.get("sec_item_weights", {})

    for entry in watchlist.get("tickers", [])[:max_companies]:
        ticker = str(entry.get("ticker", "")).upper().strip()
        sector = str(entry.get("sector", "unknown"))
        info = ticker_map.get(ticker)
        if not info:
            feed_status.append({"source": "SEC EDGAR", "ok": False, "ticker": ticker, "detail": "ticker not found in SEC company_tickers"})
            continue
        cik = int(info["cik_str"])
        cik10 = f"{cik:010d}"
        company = str(info.get("title", ticker))
        url = SEC_SUBMISSIONS_URL.format(cik10=cik10)
        try:
            submissions = http_get_json(url, headers=sec_headers)
            feed_status.append({"source": "SEC submissions", "ok": True, "ticker": ticker})
            time.sleep(0.12)
        except Exception as exc:  # noqa: BLE001
            feed_status.append({"source": "SEC submissions", "ok": False, "ticker": ticker, "detail": str(exc)})
            continue
        recent = submissions.get("filings", {}).get("recent", {})
        for row in parse_recent_columnar(recent):
            form = str(row.get("form", "")).upper().strip()
            if form not in form_weights:
                continue
            event_dt = parse_time(row.get("acceptanceDateTime")) or parse_time(row.get("filingDate"))
            if not event_dt or event_dt < cutoff:
                continue
            accession = str(row.get("accessionNumber", "")).strip()
            primary_doc = str(row.get("primaryDocument", "")).strip() or None
            url_doc = sec_doc_url(cik, accession, primary_doc)
            items = str(row.get("items", "") or "")
            title = f"{ticker} {form} filed {row.get('filingDate', '')}".strip()
            base_text = " ".join([title, items, str(row.get("primaryDocDescription", ""))])
            doc_text = ""
            if doc_fetch_count < doc_fetch_limit and form in {"8-K", "10-Q", "10-K", "6-K", "20-F"}:
                try:
                    raw_text = http_get_text(url_doc, headers=sec_file_headers, timeout=25)
                    doc_text = strip_html(raw_text)[:25000]
                    doc_fetch_count += 1
                    time.sleep(0.12)
                except Exception as exc:  # noqa: BLE001
                    feed_status.append({"source": "SEC document", "ok": False, "ticker": ticker, "url": url_doc, "detail": str(exc)})
            scores = classify_text(base_text + " " + doc_text, signals)
            scores["dust_cloud"] += float(form_weights.get(form, 0.0)) * 0.15
            for item in re.findall(r"\d+\.\d+", items):
                for cls, val in item_weights.get(item, {}).items():
                    scores[cls] = scores.get(cls, 0.0) + float(val)
            if not nonzero_classes(scores):
                continue
            excerpt = doc_text[:360] if doc_text else base_text[:360]
            evidence.append({
                "id": source_id("sec", ticker, accession, form),
                "source_type": "sec_filing",
                "source": "SEC EDGAR submissions",
                "url": url_doc,
                "observed_at_utc": iso_z(now),
                "event_time_utc": iso_z(event_dt),
                "entity": ticker,
                "entity_name": company,
                "sector": sector,
                "title": title,
                "summary": excerpt,
                "classification": scores,
                "classes": nonzero_classes(scores),
                "metadata": {"form": form, "items": items, "accession": accession}
            })
    return evidence


def gdelt_query_from_config(signals: dict[str, Any]) -> dict[str, Any]:
    """Return one GDELT query for the whole run.

    The first repo version made one DOC API request per signal bucket. On
    GitHub-hosted runners that can quickly produce HTTP 429 responses. One
    broad request is less brittle; classification is then done locally from the
    returned article titles/domains.
    """
    combined = signals.get("gdelt_combined_query")
    if isinstance(combined, dict) and str(combined.get("query", "")).strip():
        return combined

    # Backward-compatible fallback if an older config only has gdelt_queries.
    terms: list[str] = []
    for q in signals.get("gdelt_queries", []):
        query = str(q.get("query", "")).strip()
        if query:
            terms.append(f"({query})")
    return {
        "name": "combined_live_news",
        "query": " OR ".join(terms) if terms else "(bankruptcy OR restructuring OR layoffs OR sanctions OR recession) company",
        "timespan": "24h",
        "maxrecords": 100,
    }


def dominant_class(scores: dict[str, float]) -> str:
    nonzero = [(k, float(v)) for k, v in scores.items() if float(v) > 0.0]
    if not nonzero:
        return "news"
    return max(nonzero, key=lambda kv: kv[1])[0]


def fetch_gdelt_evidence(signals: dict[str, Any], now: dt.datetime, feed_status: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fetch GDELT news with one request and classify locally.

    This is live-only. If GDELT returns 429 or another failure, no synthetic rows
    are emitted; the feed failure is recorded and the scoring gate remains closed
    unless SEC or another live corporate source provides enough evidence.
    """
    q = gdelt_query_from_config(signals)
    params = {
        "query": q["query"],
        "mode": "artlist",
        "format": "json",
        "maxrecords": str(int(q.get("maxrecords", 100))),
        "timespan": str(q.get("timespan", "24h")),
        "sort": "datedesc",
    }
    url = GDELT_DOC_URL + "?" + urllib.parse.urlencode(params)
    headers = {"User-Agent": os.getenv("GDELT_USER_AGENT", os.getenv("SEC_USER_AGENT", DEFAULT_SEC_USER_AGENT)).strip() or DEFAULT_SEC_USER_AGENT}
    try:
        data = http_get_json(url, headers=headers, timeout=45, retries=4, sleep_s=5.0)
        articles = data.get("articles", []) if isinstance(data, dict) else []
        feed_status.append({
            "source": "GDELT DOC",
            "ok": True,
            "query": q.get("name", "combined_live_news"),
            "articles": len(articles),
            "detail": "single combined request; local classification",
        })
    except Exception as exc:  # noqa: BLE001
        feed_status.append({"source": "GDELT DOC", "ok": False, "query": q.get("name", "combined_live_news"), "detail": str(exc)})
        return []

    evidence: list[dict[str, Any]] = []
    for a in articles:
        title = str(a.get("title", "") or "").strip()
        article_url = str(a.get("url", "") or "").strip()
        if not title or not article_url:
            continue
        seen = parse_time(a.get("seendate")) or now
        domain = str(a.get("domain", "") or "")
        source_country = str(a.get("sourceCountry", "") or "")
        lang = str(a.get("language", "") or "")
        text = " ".join([title, domain, source_country, lang])
        scores = classify_text(text, signals)
        classes = nonzero_classes(scores)
        if not classes:
            continue
        dom_class = dominant_class(scores)
        evidence.append({
            "id": source_id("gdelt", title, article_url),
            "source_type": "news",
            "source": "GDELT DOC 2.0",
            "url": article_url,
            "observed_at_utc": iso_z(now),
            "event_time_utc": iso_z(seen),
            "entity": domain or "GLOBAL_NEWS",
            "entity_name": domain or "GDELT article",
            "sector": dom_class,
            "title": title,
            "summary": title,
            "classification": scores,
            "classes": classes,
            "metadata": {"query": q.get("name", "combined_live_news"), "domain": domain, "sourceCountry": source_country, "language": lang}
        })

    # Deduplicate repeated articles.
    dedup: dict[str, dict[str, Any]] = {}
    for ev in evidence:
        key = ev["url"]
        if key not in dedup:
            dedup[key] = ev
        else:
            for cls, val in ev["classification"].items():
                dedup[key]["classification"][cls] = max(float(dedup[key]["classification"].get(cls, 0)), float(val))
            dedup[key]["classes"] = nonzero_classes(dedup[key]["classification"])
            dedup[key]["sector"] = dominant_class(dedup[key]["classification"])
    return list(dedup.values())

def fetch_fred(signals: dict[str, Any], now: dt.datetime, feed_status: list[dict[str, Any]]) -> list[dict[str, Any]]:
    api_key = os.getenv("FRED_API_KEY", "").strip()
    if not api_key:
        feed_status.append({"source": "FRED", "ok": False, "detail": "FRED_API_KEY missing; macro feed skipped"})
        return []
    evidence: list[dict[str, Any]] = []
    obs_start = (now - dt.timedelta(days=400)).date().isoformat()
    for s in signals.get("fred_series", []):
        params = {
            "series_id": s["id"],
            "api_key": api_key,
            "file_type": "json",
            "observation_start": obs_start,
            "sort_order": "asc",
        }
        url = FRED_OBS_URL + "?" + urllib.parse.urlencode(params)
        try:
            data = http_get_json(url, timeout=40)
            obs = data.get("observations", []) if isinstance(data, dict) else []
            feed_status.append({"source": "FRED", "ok": True, "series": s["id"], "observations": len(obs)})
        except Exception as exc:  # noqa: BLE001
            feed_status.append({"source": "FRED", "ok": False, "series": s["id"], "detail": str(exc)})
            continue
        values: list[tuple[dt.datetime, float]] = []
        for row in obs:
            try:
                val = float(row.get("value"))
            except (TypeError, ValueError):
                continue
            d = parse_time(row.get("date"))
            if d:
                values.append((d, val))
        if len(values) < 2:
            continue
        latest_d, latest_v = values[-1]
        prev_v = values[-2][1]
        delta = latest_v - prev_v
        abs_delta = abs(delta)
        scores = {"dust_cloud": 0.0, "defensive_decay": 0.0, "ridge_reach": 0.0, "geo_vector": 0.0, "macro_vector": min(3.0, abs_delta * 4.0)}
        title = f"{s['id']} {s['name']} latest {latest_v:g}, change {delta:+g}"
        evidence.append({
            "id": source_id("fred", s["id"], iso_z(latest_d), str(latest_v)),
            "source_type": "macro_series",
            "source": "FRED",
            "url": f"https://fred.stlouisfed.org/series/{urllib.parse.quote(s['id'])}",
            "observed_at_utc": iso_z(now),
            "event_time_utc": iso_z(latest_d),
            "entity": s["id"],
            "entity_name": s["name"],
            "sector": "macro",
            "title": title,
            "summary": title,
            "classification": scores,
            "classes": nonzero_classes(scores),
            "metadata": {"series_id": s["id"], "latest": latest_v, "delta": delta}
        })
    return evidence


def aggregate_current(evidence: list[dict[str, Any]]) -> dict[str, float]:
    """Aggregate live evidence into raw model indices.

    Important guardrail: macro series are pressure context, not corporate
    synchronization. Sync is therefore calculated only from SEC/news evidence
    that carries corporate deformation/reach/geopolitical classes. This avoids
    false S2 phases when FRED is the only live source.
    """
    totals = {
        "dust_cloud": 0.0,
        "defensive_decay": 0.0,
        "ridge_reach": 0.0,
        "geo_vector": 0.0,
        "macro_vector": 0.0,
    }
    for ev in evidence:
        for cls in totals:
            totals[cls] += float(ev.get("classification", {}).get(cls, 0.0) or 0.0)

    sync_classes = {"dust_cloud", "defensive_decay", "ridge_reach", "geo_vector"}
    sync_evidence: list[dict[str, Any]] = []
    corporate_deformation_count = 0
    macro_count = 0

    for ev in evidence:
        source_type = str(ev.get("source_type", ""))
        classes = set(ev.get("classes", []))
        if source_type == "macro_series":
            macro_count += 1
            continue
        if classes & sync_classes:
            sync_evidence.append(ev)
            if classes & {"dust_cloud", "defensive_decay", "ridge_reach"}:
                corporate_deformation_count += 1

    entities = {ev.get("entity") for ev in sync_evidence if ev.get("entity")}
    sectors = {ev.get("sector") for ev in sync_evidence if ev.get("sector")}
    domains = {ev.get("metadata", {}).get("domain") for ev in sync_evidence if ev.get("metadata", {}).get("domain")}
    source_types = {ev.get("source_type") for ev in sync_evidence if ev.get("source_type")}

    if sync_evidence:
        totals["sync"] = (
            math.log1p(len(entities))
            + math.log1p(len(sectors))
            + math.log1p(len(domains))
            + math.log1p(len(source_types))
        )
    else:
        totals["sync"] = 0.0

    totals["evidence_count"] = float(len(evidence))
    totals["sync_evidence_count"] = float(len(sync_evidence))
    totals["corporate_deformation_count"] = float(corporate_deformation_count)
    totals["macro_evidence_count"] = float(macro_count)
    return totals


def zscore(value: float, previous: list[float]) -> float:
    if len(previous) < 2:
        return math.log1p(max(value, 0.0))
    mean = statistics.mean(previous)
    sd = statistics.pstdev(previous)
    if sd < 1e-6:
        sd = max(1.0, abs(mean) * 0.25)
    return (value - mean) / sd


def sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1 / (1 + z)
    z = math.exp(x)
    return z / (1 + z)


def phase_for_probability(p: float, signals: dict[str, Any]) -> dict[str, str]:
    for row in signals.get("phase_thresholds", []):
        if p <= float(row["max_probability"]):
            return {"phase": row["phase"], "label": row["label"]}
    return {"phase": "S4", "label": "forced_repricing_risk"}


def build_score(current: dict[str, float], history: list[dict[str, Any]], signals: dict[str, Any]) -> dict[str, Any]:
    min_hist = int(signals.get("min_history_points_for_baseline", 24))
    min_sync_evidence = int(signals.get("min_sync_evidence_for_phase", 3))
    min_corp_deformation = int(signals.get("min_corporate_deformation_evidence_for_phase", 2))
    require_nonzero_deformation = bool(signals.get("require_nonzero_dust_or_decay_for_phase", True))

    keys = ["dust_cloud", "defensive_decay", "ridge_reach", "geo_vector", "macro_vector", "sync"]
    previous_by_key: dict[str, list[float]] = {k: [] for k in keys}
    for h in history:
        raw = h.get("raw_indices", {})
        for k in keys:
            try:
                previous_by_key[k].append(float(raw.get(k, 0.0)))
            except (TypeError, ValueError):
                pass

    z = {k: zscore(float(current.get(k, 0.0)), previous_by_key[k]) for k in keys}
    coeff = signals.get("probability", {})
    linear = float(coeff.get("intercept", 0.0))
    for k in keys:
        linear += float(coeff.get(f"{k}_z", 0.0)) * z[k]
    p = sigmoid(linear)

    hist_points = len(history)
    baseline_status = "calibrated" if hist_points >= min_hist else "warming_up"
    sync_count = int(current.get("sync_evidence_count", 0.0))
    corp_count = int(current.get("corporate_deformation_count", 0.0))
    has_deformation = (float(current.get("dust_cloud", 0.0)) > 0.0 or float(current.get("defensive_decay", 0.0)) > 0.0)

    gate_reasons: list[str] = []
    if sync_count < min_sync_evidence:
        gate_reasons.append(f"sync evidence {sync_count} < required {min_sync_evidence}")
    if corp_count < min_corp_deformation:
        gate_reasons.append(f"corporate deformation evidence {corp_count} < required {min_corp_deformation}")
    if require_nonzero_deformation and not has_deformation:
        gate_reasons.append("dust and defensive decay are both zero")

    diversity = min(1.0, math.log1p(current.get("evidence_count", 0.0)) / math.log(60.0))
    history_factor = min(1.0, hist_points / max(1, min_hist))
    confidence = max(0.05, min(1.0, 0.25 + 0.50 * history_factor + 0.25 * diversity))

    if gate_reasons:
        # Macro-only pressure can be displayed, but it is not allowed to mint a
        # corporate phase. This keeps the dashboard honest during warm-up and
        # source outages.
        return {
            "probability": None,
            "raw_probability": round(p, 4),
            "phase": "WARMUP",
            "phase_label": "insufficient_live_corporate_evidence",
            "confidence": round(min(confidence, 0.20), 4),
            "baseline_status": "insufficient_live_evidence",
            "history_points": hist_points,
            "linear_score": round(linear, 4),
            "gate_reasons": gate_reasons,
            "z_indices": {k: round(v, 4) for k, v in z.items()},
            "raw_indices": {k: round(float(current.get(k, 0.0)), 4) for k in current},
        }

    phase = phase_for_probability(p, signals)
    return {
        "probability": round(p, 4),
        "raw_probability": round(p, 4),
        "phase": phase["phase"],
        "phase_label": phase["label"],
        "confidence": round(confidence, 4),
        "baseline_status": baseline_status,
        "history_points": hist_points,
        "linear_score": round(linear, 4),
        "gate_reasons": [],
        "z_indices": {k: round(v, 4) for k, v in z.items()},
        "raw_indices": {k: round(float(current.get(k, 0.0)), 4) for k in current},
    }


def top_evidence(evidence: list[dict[str, Any]], cls: str, n: int = 5) -> list[dict[str, Any]]:
    ranked = sorted(evidence, key=lambda ev: float(ev.get("classification", {}).get(cls, 0.0) or 0.0), reverse=True)
    return [ev for ev in ranked if float(ev.get("classification", {}).get(cls, 0.0) or 0.0) > 0][:n]


def build_narrative(snapshot: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    score = snapshot["score"]
    z = score["z_indices"]
    raw = score["raw_indices"]
    dust = top_evidence(evidence, "dust_cloud", 3)
    decay = top_evidence(evidence, "defensive_decay", 3)
    reach = top_evidence(evidence, "ridge_reach", 3)
    geo = top_evidence(evidence, "geo_vector", 3)
    math_line = (
        "p = sigmoid(b0 + 0.90*dust_z + 0.70*decay_z + 0.55*sync_z "
        "+ 0.35*geo_z + 0.30*macro_z - 0.50*reach_z)"
    )
    english = []
    probability = score.get("probability")
    probability_text = "n/a" if probability is None else f"{probability:.1%}"
    raw_probability = score.get("raw_probability")
    raw_probability_text = "n/a" if raw_probability is None else f"{raw_probability:.1%}"
    english.append(
        f"Current phase is {score['phase']} ({score['phase_label']}) with gated probability {probability_text} "
        f"and raw ungated pressure {raw_probability_text}. Confidence: {score['confidence']:.1%}. "
        f"Baseline status: {score['baseline_status']}."
    )
    if score.get("gate_reasons"):
        english.append("Gate active: " + "; ".join(score["gate_reasons"]) + ".")
    english.append(
        f"Raw ridge/dust balance: dust={raw.get('dust_cloud', 0):.2f}, decay={raw.get('defensive_decay', 0):.2f}, "
        f"reach={raw.get('ridge_reach', 0):.2f}, geo={raw.get('geo_vector', 0):.2f}, macro={raw.get('macro_vector', 0):.2f}, sync={raw.get('sync', 0):.2f}."
    )
    if dust or decay:
        english.append("Top deformation evidence: " + "; ".join(ev["title"] for ev in (dust + decay)[:4]))
    if geo:
        english.append("Geopolitical vector evidence: " + "; ".join(ev["title"] for ev in geo[:3]))
    if reach:
        english.append("Reach counter-evidence: " + "; ".join(ev["title"] for ev in reach[:3]))
    if not evidence:
        english.append("No live evidence rows were collected. The model did not fabricate substitute data.")
    return {
        "english": english,
        "math": {
            "formula": math_line,
            "z_indices": z,
            "raw_indices": raw,
            "interpretation": "Positive dust/decay/sync/geo/macro raises phase-transition pressure. Positive reach lowers it."
        }
    }


def trim_history(path: Path, max_lines: int) -> None:
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) <= max_lines:
        return
    path.write_text("\n".join(lines[-max_lines:]) + "\n", encoding="utf-8")


def main() -> int:
    now = utc_now()
    PUBLIC_DATA_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    watchlist = load_json(CONFIG_DIR / "watchlist.json")
    signals = load_json(CONFIG_DIR / "signals.json")
    feed_status: list[dict[str, Any]] = []

    evidence: list[dict[str, Any]] = []
    evidence.extend(fetch_sec_evidence(watchlist, signals, now, feed_status))
    evidence.extend(fetch_gdelt_evidence(signals, now, feed_status))
    evidence.extend(fetch_fred(signals, now, feed_status))

    # Deduplicate by id after all sources.
    dedup: dict[str, dict[str, Any]] = {}
    for ev in evidence:
        dedup[ev["id"]] = ev
    evidence = sorted(dedup.values(), key=lambda ev: ev.get("event_time_utc", ""), reverse=True)

    hist_window = int(signals.get("history_window_points", 720))
    history = read_jsonl(HISTORY_PATH, limit=hist_window)
    current = aggregate_current(evidence)
    score = build_score(current, history, signals)
    snapshot = {
        "generated_at_utc": iso_z(now),
        "model_name": "market_horizon_radar_live_only_v2",
        "app_version": APP_VERSION,
        "feed_status": feed_status,
        "score": score,
        "source_counts": {
            "evidence_total": len(evidence),
            "by_source_type": {},
            "by_class": {},
        },
        "top_evidence": evidence[:40],
    }
    for ev in evidence:
        st = ev.get("source_type", "unknown")
        snapshot["source_counts"]["by_source_type"][st] = snapshot["source_counts"]["by_source_type"].get(st, 0) + 1
        for cls in ev.get("classes", []):
            snapshot["source_counts"]["by_class"][cls] = snapshot["source_counts"]["by_class"].get(cls, 0) + 1
    snapshot["narrative"] = build_narrative(snapshot, evidence)

    write_json(SNAPSHOT_PATH, snapshot)
    write_json(EVIDENCE_PATH, evidence[:500])
    hist_row = {
        "generated_at_utc": snapshot["generated_at_utc"],
        "probability": score["probability"],
        "raw_probability": score.get("raw_probability"),
        "phase": score["phase"],
        "phase_label": score["phase_label"],
        "confidence": score["confidence"],
        "baseline_status": score["baseline_status"],
        "raw_indices": score["raw_indices"],
        "z_indices": score["z_indices"],
        "evidence_count": len(evidence),
    }
    append_jsonl(HISTORY_PATH, hist_row)
    trim_history(HISTORY_PATH, hist_window)
    write_json(RAW_DIR / f"snapshot_{now.strftime('%Y%m%dT%H%M%SZ')}.json", snapshot)
    print(json.dumps({"generated_at_utc": snapshot["generated_at_utc"], "app_version": APP_VERSION, "evidence_total": len(evidence), "probability": score["probability"], "phase": score["phase"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
