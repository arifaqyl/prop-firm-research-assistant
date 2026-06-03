from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any

import requests


SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
DEFAULT_SEC_FORMS = ("8-K", "10-Q", "10-K", "6-K", "20-F")


def sec_recent_filings(symbol: str, forms: list[str] | None = None, limit: int = 8) -> dict[str, Any]:
    normalized_symbol = symbol.strip().upper() or "AAPL"
    allowed_forms = [item.strip().upper() for item in (forms or list(DEFAULT_SEC_FORMS)) if item.strip()]
    try:
        mapping = _fetch_sec_ticker_mapping()
        company = _lookup_company_by_symbol(mapping, normalized_symbol)
        if not company:
            return {
                "status": "symbol_not_found",
                "symbol": normalized_symbol,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "filings": [],
                "warnings": [f"SEC ticker mapping did not contain {normalized_symbol}"],
                "source": SEC_TICKERS_URL,
            }
        filings_payload = _fetch_sec_submissions(company["cik"])
        filings = _extract_recent_filings(filings_payload, allowed_forms, limit=min(max(limit, 1), 20))
        return {
            "status": "active",
            "symbol": normalized_symbol,
            "company_name": company["name"],
            "cik": company["cik"],
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "forms_requested": allowed_forms,
            "filings": filings,
            "filing_signal": _filing_signal(filings),
            "warnings": [],
            "sources": [
                {"name": "SEC ticker mapping", "url": SEC_TICKERS_URL},
                {"name": "SEC submissions", "url": SEC_SUBMISSIONS_URL.format(cik=company["cik"])},
            ],
            "rule": "SEC filing feed is informational. It adds event awareness and timing context; it does not authorize a trade by itself.",
        }
    except Exception as exc:  # pragma: no cover - network/provider state varies
        return {
            "status": "provider_error",
            "symbol": normalized_symbol,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "filings": [],
            "warnings": [str(exc)],
            "source": SEC_TICKERS_URL,
        }


def _sec_headers() -> dict[str, str]:
    user_agent = os.getenv("SEC_USER_AGENT", "prop-firm-ai/0.1 research-bot")
    return {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}


def _fetch_sec_ticker_mapping() -> dict[str, Any]:
    response = requests.get(SEC_TICKERS_URL, headers=_sec_headers(), timeout=15)
    response.raise_for_status()
    return response.json()


def _fetch_sec_submissions(cik: str) -> dict[str, Any]:
    response = requests.get(SEC_SUBMISSIONS_URL.format(cik=cik), headers=_sec_headers(), timeout=15)
    response.raise_for_status()
    return response.json()


def _lookup_company_by_symbol(mapping: dict[str, Any], symbol: str) -> dict[str, str] | None:
    for item in mapping.values():
        if str(item.get("ticker", "")).upper() == symbol:
            cik_str = str(item.get("cik_str", "")).strip()
            return {
                "ticker": symbol,
                "name": str(item.get("title", symbol)),
                "cik": cik_str.zfill(10),
            }
    return None


def _extract_recent_filings(payload: dict[str, Any], allowed_forms: list[str], limit: int) -> list[dict[str, Any]]:
    recent = (payload.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accession_numbers = recent.get("accessionNumber") or []
    primary_documents = recent.get("primaryDocument") or []
    primary_descriptions = recent.get("primaryDocDescription") or []

    rows = []
    for index, form in enumerate(forms):
        form_text = str(form or "").upper()
        if allowed_forms and form_text not in allowed_forms:
            continue
        accession = str(accession_numbers[index]) if index < len(accession_numbers) else ""
        accession_nodashes = accession.replace("-", "")
        document = str(primary_documents[index]) if index < len(primary_documents) else ""
        cik = str(payload.get("cik", "")).lstrip("0")
        filing_url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodashes}/{document}"
            if cik and accession_nodashes and document
            else None
        )
        rows.append(
            {
                "form": form_text,
                "filing_date": str(dates[index]) if index < len(dates) else None,
                "accession_number": accession,
                "primary_document": document,
                "description": str(primary_descriptions[index]) if index < len(primary_descriptions) else "",
                "filing_url": filing_url,
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _filing_signal(filings: list[dict[str, Any]]) -> dict[str, Any]:
    if not filings:
        return {
            "event_risk": "none_detected",
            "headline": "No recent requested SEC forms were found in the current SEC feed.",
        }
    latest = filings[0]
    form = latest.get("form", "")
    if form == "8-K":
        return {
            "event_risk": "high",
            "headline": "Recent 8-K detected. Treat this as an active event window and reduce confidence.",
        }
    if form in {"10-Q", "10-K", "20-F", "6-K"}:
        return {
            "event_risk": "medium",
            "headline": f"Recent {form} filing detected. Fundamentals context changed and should be reviewed.",
        }
    return {
        "event_risk": "low",
        "headline": f"Recent filing activity detected: {form}.",
    }
