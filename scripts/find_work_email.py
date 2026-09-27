#!/usr/bin/env python3
"""
find_work_email.py

Cascading work-email finder for IB networking outreach.
Order: Prospeo -> Hunter -> GetProspect -> Tomba -> MineLead (first hit wins, stops immediately).
Every lookup is cached locally (email_cache.db) so the same person is never
queried twice against any provider, even across days/sessions.

NOT WIRED INTO THE SCHEDULED TASK OR ANY LIVE WORKFLOW.
This is a standalone tool. Nothing here sends email or touches the
recruiting trackers. Call find_work_email() or run this file directly
against a small test set before it's trusted with real candidates.

Usage as a library:
    from find_work_email import find_work_email
    result = find_work_email("Jane", "Doe", "Goldman Sachs", "gs.com")

Usage as a CLI (single lookup):
    python find_work_email.py "Jane" "Doe" --domain gs.com --company "Goldman Sachs"

Usage as a CLI (batch from a JSON file of candidates):
    python find_work_email.py --batch candidates.json --out results.json

Catch-all recheck (asks every provider, bypasses cache, reports agreement):
    python find_work_email.py "Jane" "Doe" --domain jpmorgan.com --all-providers
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _resolve_key_dir() -> Path:
    """
    EMAIL_FINDER_KEY_DIR always wins when set. Otherwise, try known
    locations in order and use the first that exists: this file's own
    "Api Key" subfolder (works if this script lives inside the campaign
    folder itself, e.g. on the candidate's own machine), then the path this
    session's cloud container uses when the folder is staged from a linked
    device. If none exist yet, fall back to the container path anyway so the
    error message on first use names a real, meaningful path instead of a
    silently wrong default.
    """
    env_override = os.environ.get("EMAIL_FINDER_KEY_DIR")
    if env_override:
        return Path(env_override)

    candidates = [
        Path(__file__).resolve().parent / "Api Key",
        Path("/mnt/user-data/uploads/Recruiting/Networking Workflow/Api Key"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


KEY_DIR = _resolve_key_dir()
DB_PATH = Path(os.environ.get("EMAIL_FINDER_DB", str(Path(__file__).parent / "email_cache.db")))

REQUEST_TIMEOUT = 20  # seconds
RETRY_ATTEMPTS = 2
RETRY_BACKOFF_SECONDS = 2

# Monthly free-tier ceilings, used only for local bookkeeping/warnings.
MONTHLY_LIMITS = {
    "prospeo": 100,
    "hunter": 50,
    "getprospect": 50,
    "tomba": 25,
    "minelead": 24,
}

CASCADE_ORDER = ["prospeo", "hunter", "getprospect", "tomba", "minelead"]

# Sentinel: a provider function returns this when it made NO network call at
# all (e.g. missing domain/company it requires), as distinct from making a
# call that came back empty. Only a real call should count against the
# provider's monthly quota — returning this must never increment usage.
NOT_ATTEMPTED = object()


# ---------------------------------------------------------------------------
# Key loading
# ---------------------------------------------------------------------------

def _read_key_file(filename: str) -> str:
    path = KEY_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Missing key file: {path}")
    return path.read_text().strip()


def _load_keys() -> dict:
    """
    Loads all provider credentials. Raises with a clear message if a key
    file is missing or malformed, rather than silently skipping a provider.
    """
    keys = {}

    keys["prospeo"] = _read_key_file(".prospeo_api_key.txt")
    keys["hunter"] = _read_key_file(".hunter_api_key.txt")
    keys["getprospect"] = _read_key_file(".getprospect_api_key.txt")
    keys["minelead"] = _read_key_file(".minelead_api_key.txt")

    tomba_raw = _read_key_file(".tomba_api_key.txt")
    # Tomba's key file format varies by how it was saved (raw two lines,
    # "label = value" pairs, extra whitespace, etc.) — pull the tokens out by
    # their fixed prefix wherever they appear rather than assuming a layout.
    key_match = re.search(r"\bta_[A-Za-z0-9]+\b", tomba_raw)
    secret_match = re.search(r"\bts_[A-Za-z0-9-]+\b", tomba_raw)
    tomba_key = key_match.group(0) if key_match else None
    tomba_secret = secret_match.group(0) if secret_match else None

    if not tomba_key or not tomba_secret:
        raise ValueError(
            "Tomba requires both a Key (ta_...) and a Secret (ts_...); "
            f"could not parse both from {KEY_DIR / '.tomba_api_key.txt'}"
        )
    keys["tomba_key"] = tomba_key
    keys["tomba_secret"] = tomba_secret

    return keys


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class EmailResult:
    name: str
    company: Optional[str]
    domain: Optional[str]
    email: Optional[str]
    status: str          # "verified" | "unverified" | "not_found" | "error"
    provider: Optional[str]
    confidence: Optional[str]   # provider's own score/label, kept as string
    raw_provider_response: Optional[dict] = None
    checked_at: float = 0.0

    def to_dict(self):
        d = asdict(self)
        return d


# ---------------------------------------------------------------------------
# Local cache (SQLite) — avoids re-querying providers for the same person
# ---------------------------------------------------------------------------

def _init_db(conn: sqlite3.Connection):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS email_cache (
            cache_key TEXT PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            company TEXT,
            domain TEXT,
            email TEXT,
            status TEXT,
            provider TEXT,
            confidence TEXT,
            checked_at REAL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS credit_usage (
            provider TEXT,
            month TEXT,
            used INTEGER,
            PRIMARY KEY (provider, month)
        )
        """
    )
    conn.commit()


def _cache_key(first_name: str, last_name: str, domain: Optional[str], company: Optional[str]) -> str:
    d = (domain or "").strip().lower()
    c = (company or "").strip().lower()
    return f"{first_name.strip().lower()}|{last_name.strip().lower()}|{d}|{c}"


def _get_cached(conn: sqlite3.Connection, key: str) -> Optional[EmailResult]:
    row = conn.execute(
        "SELECT first_name, last_name, company, domain, email, status, provider, confidence, checked_at "
        "FROM email_cache WHERE cache_key = ?",
        (key,),
    ).fetchone()
    if row is None:
        return None
    first_name, last_name, company, domain, email, status, provider, confidence, checked_at = row
    return EmailResult(
        name=f"{first_name} {last_name}".strip(),
        company=company,
        domain=domain,
        email=email,
        status=status,
        provider=provider,
        confidence=confidence,
        checked_at=checked_at,
    )


def _store_cache(conn: sqlite3.Connection, key: str, first_name: str, last_name: str, result: EmailResult):
    conn.execute(
        """
        INSERT INTO email_cache (cache_key, first_name, last_name, company, domain, email, status, provider, confidence, checked_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(cache_key) DO UPDATE SET
            email=excluded.email, status=excluded.status, provider=excluded.provider,
            confidence=excluded.confidence, checked_at=excluded.checked_at
        """,
        (
            key, first_name, last_name, result.company, result.domain,
            result.email, result.status, result.provider, result.confidence, result.checked_at,
        ),
    )
    conn.commit()


def _month_key() -> str:
    return time.strftime("%Y-%m")


def _get_credit_usage(conn: sqlite3.Connection, provider: str) -> int:
    row = conn.execute(
        "SELECT used FROM credit_usage WHERE provider = ? AND month = ?",
        (provider, _month_key()),
    ).fetchone()
    return row[0] if row else 0


def _increment_credit_usage(conn: sqlite3.Connection, provider: str, n: int = 1):
    month = _month_key()
    conn.execute(
        """
        INSERT INTO credit_usage (provider, month, used) VALUES (?, ?, ?)
        ON CONFLICT(provider, month) DO UPDATE SET used = used + ?
        """,
        (provider, month, n, n),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Provider calls
#
# Each function returns EmailResult or None (None = "not found by this
# provider, try the next one"). Errors are caught and logged rather than
# raised, so one flaky provider never breaks the cascade.
# ---------------------------------------------------------------------------

def _request_with_retry(method: str, url: str, **kwargs) -> Optional[requests.Response]:
    last_exc = None
    for attempt in range(RETRY_ATTEMPTS + 1):
        try:
            resp = requests.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SECONDS)
    print(f"  [warn] request to {url} failed after retries: {last_exc}", file=sys.stderr)
    return None


def _try_prospeo(keys: dict, first_name: str, last_name: str, company: Optional[str], domain: Optional[str]):
    if not domain and not company:
        return NOT_ATTEMPTED
    body = {"data": {"first_name": first_name, "last_name": last_name}}
    if domain:
        body["data"]["company_website"] = domain
    if company:
        body["data"]["company_name"] = company

    resp = _request_with_retry(
        "POST", "https://api.prospeo.io/enrich-person",
        headers={"Content-Type": "application/json", "X-KEY": keys["prospeo"]},
        json=body,
    )
    if resp is None or resp.status_code != 200:
        return None
    data = resp.json()
    email_block = (data.get("person") or {}).get("email") or {}
    email = email_block.get("email")
    if not email:
        return None
    status = "verified" if email_block.get("status") == "VERIFIED" else "unverified"
    return EmailResult(
        name=f"{first_name} {last_name}", company=company, domain=domain,
        email=email, status=status, provider="prospeo",
        confidence=email_block.get("verification_method"),
        raw_provider_response=data, checked_at=time.time(),
    )


def _try_hunter(keys: dict, first_name: str, last_name: str, company: Optional[str], domain: Optional[str]):
    if not domain:
        return NOT_ATTEMPTED  # Hunter's finder needs a domain
    params = {
        "domain": domain,
        "first_name": first_name,
        "last_name": last_name,
        "api_key": keys["hunter"],
    }
    resp = _request_with_retry("GET", "https://api.hunter.io/v2/email-finder", params=params)
    if resp is None or resp.status_code != 200:
        return None
    data = resp.json()
    email_data = data.get("data") or {}
    email = email_data.get("email")
    if not email:
        return None
    verification = (email_data.get("verification") or {}).get("status")
    status = "verified" if verification == "valid" else "unverified"
    return EmailResult(
        name=f"{first_name} {last_name}", company=company, domain=domain,
        email=email, status=status, provider="hunter",
        confidence=str(email_data.get("score")),
        raw_provider_response=data, checked_at=time.time(),
    )


def _try_getprospect(keys: dict, first_name: str, last_name: str, company: Optional[str], domain: Optional[str]):
    if not domain and not company:
        return NOT_ATTEMPTED
    body = {"data": {"first_name": first_name, "last_name": last_name}}
    if domain:
        body["data"]["domain"] = domain
    if company:
        body["data"]["company"] = company

    resp = _request_with_retry(
        "POST", "https://api.getprospect.com/v2/email/find",
        headers={"Content-Type": "application/json", "x-api-key": keys["getprospect"]},
        json=body,
    )
    if resp is None or resp.status_code != 200:
        return None
    data = resp.json()
    inner = data.get("data") or {}
    email = inner.get("email")
    if not email or inner.get("status") != "valid":
        return None
    return EmailResult(
        name=f"{first_name} {last_name}", company=company, domain=domain,
        email=email, status="verified", provider="getprospect",
        confidence=inner.get("status"),
        raw_provider_response=data, checked_at=time.time(),
    )


def _try_tomba(keys: dict, first_name: str, last_name: str, company: Optional[str], domain: Optional[str]):
    if not domain:
        return NOT_ATTEMPTED
    params = {"domain": domain, "first_name": first_name, "last_name": last_name}
    resp = _request_with_retry(
        "GET", "https://api.tomba.io/v1/email-finder",
        headers={"X-Tomba-Key": keys["tomba_key"], "X-Tomba-Secret": keys["tomba_secret"]},
        params=params,
    )
    if resp is None or resp.status_code != 200:
        return None
    data = resp.json()
    inner = data.get("data") or {}
    email = inner.get("email")
    if not email:
        return None
    verification_status = (inner.get("verification") or {}).get("status")
    status = "verified" if verification_status == "valid" else "unverified"
    return EmailResult(
        name=f"{first_name} {last_name}", company=company, domain=domain,
        email=email, status=status, provider="tomba",
        confidence=str(inner.get("score")),
        raw_provider_response=data, checked_at=time.time(),
    )


def _try_minelead(keys: dict, first_name: str, last_name: str, company: Optional[str], domain: Optional[str]):
    if not domain:
        return NOT_ATTEMPTED  # MineLead's /find needs a domain, no company-name fallback
    params = {
        "key": keys["minelead"],
        "domain": domain,
        "firstname": first_name,
        "lastname": last_name,
    }
    resp = _request_with_retry("GET", "https://api.minelead.io/v1/find/", params=params)
    if resp is None or resp.status_code != 200:
        return None
    data = resp.json()
    if data.get("status") != "success":
        return None
    email = data.get("email")
    if not email:
        return None
    quality = data.get("quality")
    # MineLead has no separate SMTP-verification flag on /find, just a 0-100
    # confidence score — treat a high score as "unverified" (not confirmed by
    # mailbox check) rather than claiming "verified" it never asserted.
    return EmailResult(
        name=f"{first_name} {last_name}", company=company, domain=domain,
        email=email, status="unverified", provider="minelead",
        confidence=str(quality),
        raw_provider_response=data, checked_at=time.time(),
    )


PROVIDER_FUNCS = {
    "prospeo": _try_prospeo,
    "hunter": _try_hunter,
    "getprospect": _try_getprospect,
    "tomba": _try_tomba,
    "minelead": _try_minelead,
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def find_work_email(
    first_name: str,
    last_name: str,
    company: Optional[str] = None,
    domain: Optional[str] = None,
    force_refresh: bool = False,
    conn: Optional[sqlite3.Connection] = None,
    keys: Optional[dict] = None,
) -> EmailResult:
    """
    Cascades Prospeo -> Hunter -> GetProspect -> Tomba -> MineLead, stopping
    at the first provider that returns an email. Caches every outcome
    (including not-found) so a repeat lookup costs zero API credits.

    domain is strongly preferred over company (most providers need it for
    the highest-accuracy match); pass both when you have them.
    """
    owns_conn = conn is None
    if conn is None:
        conn = sqlite3.connect(DB_PATH)
        _init_db(conn)
    if keys is None:
        keys = _load_keys()

    key = _cache_key(first_name, last_name, domain, company)

    if not force_refresh:
        cached = _get_cached(conn, key)
        if cached is not None:
            if owns_conn:
                conn.close()
            return cached

    result: Optional[EmailResult] = None
    for provider in CASCADE_ORDER:
        used = _get_credit_usage(conn, provider)
        limit = MONTHLY_LIMITS[provider]
        if used >= limit:
            print(f"  [skip] {provider}: monthly free quota exhausted ({used}/{limit})", file=sys.stderr)
            continue

        func = PROVIDER_FUNCS[provider]
        try:
            candidate = func(keys, first_name, last_name, company, domain)
        except Exception as exc:  # noqa: BLE001 - one bad provider must not kill the cascade
            print(f"  [error] {provider} raised {exc!r}", file=sys.stderr)
            candidate = None

        if candidate is NOT_ATTEMPTED:
            # No network call was made (e.g. this provider needs a domain we
            # don't have) — never counts against the monthly quota.
            continue

        _increment_credit_usage(conn, provider, 1)

        if candidate is not None:
            result = candidate
            break

    if result is None:
        result = EmailResult(
            name=f"{first_name} {last_name}", company=company, domain=domain,
            email=None, status="not_found", provider=None, confidence=None,
            checked_at=time.time(),
        )

    _store_cache(conn, key, first_name, last_name, result)

    if owns_conn:
        conn.close()
    return result


PROVIDER_DISPLAY = {
    "prospeo": "Prospeo", "hunter": "Hunter", "getprospect": "GetProspect",
    "tomba": "Tomba", "minelead": "MineLead",
}


def find_work_email_all_providers(
    first_name: str,
    last_name: str,
    company: Optional[str] = None,
    domain: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    keys: Optional[dict] = None,
) -> dict:
    """
    Catch-all recheck mode. Unlike find_work_email(), this does NOT stop at the
    first hit and does NOT read the cache: it asks every provider that still
    has monthly quota, so the pool's "2+ providers independently agree" rule
    can actually be evaluated. Costs up to one credit per provider, so use it
    only for PENDING_CATCHALL_RECHECK rows, never as the default lookup.

    Returns per-provider answers plus a suggested email_verification_state:
      verified               - at least one provider mailbox-verified an address
                               (the most-agreed verified address is suggested)
      accept_all_2plus_agree - 2+ providers returned the identical address
      accept_all_domain      - one provider, or providers disagree
      not_found              - no provider returned anything
    """
    owns_conn = conn is None
    if conn is None:
        conn = sqlite3.connect(DB_PATH)
        _init_db(conn)
    if keys is None:
        keys = _load_keys()

    answers = []
    for provider in CASCADE_ORDER:
        used = _get_credit_usage(conn, provider)
        if used >= MONTHLY_LIMITS[provider]:
            answers.append({"provider": PROVIDER_DISPLAY[provider], "skipped": "monthly quota exhausted"})
            continue
        try:
            candidate = PROVIDER_FUNCS[provider](keys, first_name, last_name, company, domain)
        except Exception as exc:  # noqa: BLE001
            print(f"  [error] {provider} raised {exc!r}", file=sys.stderr)
            candidate = None
        if candidate is NOT_ATTEMPTED:
            answers.append({"provider": PROVIDER_DISPLAY[provider], "skipped": "needs a domain"})
            continue
        _increment_credit_usage(conn, provider, 1)
        if candidate is None:
            answers.append({"provider": PROVIDER_DISPLAY[provider], "email": None, "status": "not_found"})
        else:
            answers.append({
                "provider": PROVIDER_DISPLAY[provider],
                "email": candidate.email.lower(),
                "status": candidate.status,
                "confidence": candidate.confidence,
            })

    if owns_conn:
        conn.close()

    by_address: dict = {}
    for a in answers:
        if a.get("email"):
            by_address.setdefault(a["email"], []).append(a)
    verified = {e: v for e, v in by_address.items() if any(x["status"] == "verified" for x in v)}

    if verified:
        email = max(verified, key=lambda e: len(verified[e]))
        state = "verified"
    elif by_address:
        email = max(by_address, key=lambda e: len(by_address[e]))
        # Any split between providers counts as disagreement, per the
        # catch-all rule in NETWORKING_CONTEXT.md.
        agree = len(by_address[email]) >= 2 and len(by_address) == 1
        state = "accept_all_2plus_agree" if agree else "accept_all_domain"
    else:
        email, state = None, "not_found"

    agreeing = [x["provider"] for x in by_address.get(email, [])] if email else []
    return {
        "name": f"{first_name} {last_name}",
        "company": company,
        "domain": domain,
        "suggested_email": email,
        "suggested_email_verification_state": state,
        "suggested_email_source": agreeing[0] if agreeing else None,
        "agreeing_providers": agreeing,
        "distinct_addresses_returned": sorted(by_address),
        "provider_answers": answers,
        "checked_at": time.time(),
    }


def find_work_emails_batch(candidates: list, force_refresh: bool = False) -> list:
    """
    candidates: list of dicts with at least first_name/last_name and one of
    company/domain, e.g. from a networking-handoff JSON's `candidates` array
    (which uses full `name` + `firm` — split the name before calling this,
    or adapt the field mapping to match the handoff schema in use).
    """
    keys = _load_keys()
    conn = sqlite3.connect(DB_PATH)
    _init_db(conn)

    results = []
    for c in candidates:
        r = find_work_email(
            first_name=c["first_name"],
            last_name=c["last_name"],
            company=c.get("company"),
            domain=c.get("domain"),
            force_refresh=force_refresh,
            conn=conn,
            keys=keys,
        )
        results.append(r.to_dict())

    conn.close()
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Cascading work-email finder (Prospeo -> Hunter -> GetProspect -> Tomba -> MineLead)")
    parser.add_argument("first_name", nargs="?")
    parser.add_argument("last_name", nargs="?")
    parser.add_argument("--company", default=None)
    parser.add_argument("--domain", default=None)
    parser.add_argument("--batch", default=None, help="Path to JSON file: a list of {first_name,last_name,company,domain}")
    parser.add_argument("--out", default=None, help="Path to write JSON results (batch mode)")
    parser.add_argument("--force-refresh", action="store_true", help="Bypass cache and re-query providers")
    parser.add_argument("--all-providers", action="store_true",
                        help="Catch-all recheck: query EVERY provider (no cache, no early stop) and report whether 2+ agree. Single lookup only.")
    args = parser.parse_args()

    if args.all_providers:
        if args.batch or not args.first_name or not args.last_name:
            parser.error("--all-providers takes one first_name last_name (with --domain), not --batch")
        result = find_work_email_all_providers(args.first_name, args.last_name, args.company, args.domain)
        print(json.dumps(result, indent=2, default=str))
        return

    if args.batch:
        with open(args.batch) as f:
            candidates = json.load(f)
        results = find_work_emails_batch(candidates, force_refresh=args.force_refresh)
        output = json.dumps(results, indent=2, default=str)
        if args.out:
            with open(args.out, "w") as f:
                f.write(output)
            print(f"Wrote {len(results)} results to {args.out}")
        else:
            print(output)
        return

    if not args.first_name or not args.last_name:
        parser.error("Provide first_name and last_name, or use --batch")

    result = find_work_email(args.first_name, args.last_name, args.company, args.domain, force_refresh=args.force_refresh)
    print(json.dumps(result.to_dict(), indent=2, default=str))


if __name__ == "__main__":
    main()
