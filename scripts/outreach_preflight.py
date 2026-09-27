"""No-send campaign gate. Run with the bundled Python runtime on this PC.

This script never accesses Gmail, email-finder provider APIs, or email send APIs. A PASS here is
necessary but never sufficient authorization to send. Its lock protects only
this preflight operation; a later sender must hold the same lock continuously
through Gmail reconciliation, each send, workbook writes, and final checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import sys
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
HANDOFFS = ROOT / "Networking Handoffs"
TRACKERS = ROOT / "Trackers"
STATE_DIR = ROOT / "Networking Workflow" / "daily-state"
LOCK = ROOT / "Networking Workflow" / "outreach_writer.lock"
ET = ZoneInfo("America/New_York")
WINDOWS = {
    "New York": "10:00 ET",
    "Philadelphia": "10:00 ET",
    "Chicago": "11:00 ET",
    "Houston": "11:00 ET",
    "San Francisco": "13:00 ET",
}
PERSONAL_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "live.com",
    "icloud.com", "aol.com", "proton.me", "protonmail.com",
}
COMPANY_EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")
# Providers cascaded by find_work_email.py, in cascade order. Apollo is not
# part of this workflow and must never appear here.
VALID_EMAIL_SOURCES = {"Prospeo", "Hunter", "GetProspect", "Tomba", "MineLead"}


def fail(message: str) -> None:
    raise ValueError(message)


def parse_et(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        fail(f"{label} is not a parseable timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        fail(f"{label} has no timezone offset")
    if parsed.utcoffset() != parsed.astimezone(ET).utcoffset():
        fail(f"{label} has the wrong Eastern daylight-saving offset")
    return parsed.astimezone(ET)


def validate_handoff(data: dict, today: date, now: datetime) -> None:
    if data.get("schema_version") != 2:
        fail("handoff schema_version is not 2")
    if data.get("campaign") != "Summer 2028 IB Summer Analyst networking":
        fail("handoff campaign does not match")
    if data.get("send_date_et") != today.isoformat():
        fail("handoff send_date_et does not match today")
    if data.get("status") != "READY":
        fail(f"handoff status is {data.get('status')!r}")
    finished = parse_et(data.get("research_completed_at_et"), "research_completed_at_et")
    if finished > now or now - finished > timedelta(hours=36):
        fail("handoff is future dated or more than 36 hours old")
    candidates = data.get("candidates")
    coverage = data.get("search_coverage")
    if not isinstance(candidates, list) or not candidates:
        fail("handoff has no candidates")
    if data.get("candidate_count") != len(candidates):
        fail("candidate_count does not match candidates")
    if not isinstance(coverage, list) or not coverage:
        fail("search_coverage is empty")
    for item in coverage:
        if not isinstance(item, dict) or not item.get("firm") or not item.get("cities") or not isinstance(item.get("qualified_count"), int):
            fail("search_coverage has an incomplete entry")
    ranks, urls, emails = set(), set(), set()
    required = ("name", "linkedin_url", "firm", "parent_bank", "title", "city", "connection_type", "specific_reason")
    for item in candidates:
        if not isinstance(item, dict) or any(not item.get(k) for k in required):
            fail("candidate has missing required fields")
        rank = item.get("priority_rank")
        if not isinstance(item["linkedin_url"], str):
            fail("candidate LinkedIn URL is invalid")
        url = item["linkedin_url"].strip().lower().rstrip("/")
        if not isinstance(rank, int) or rank < 1 or rank in ranks:
            fail("candidate priority ranks are invalid or repeated")
        if not url.startswith("https://www.linkedin.com/in/") or url in urls:
            fail("candidate LinkedIn URLs are invalid or repeated")
        if item["city"] not in WINDOWS:
            fail("candidate city is outside the five target cities")
        if item.get("group_status") not in ("verified", "unverified"):
            fail("candidate group_status is invalid")
        if item["group_status"] == "verified" and not item.get("ib_group"):
            fail("verified group is blank")
        if item["group_status"] == "unverified" and (item.get("ib_group") is not None or not item.get("uncertainty_note")):
            fail("unverified group needs null ib_group and an uncertainty note")
        parse_et(item.get("profile_checked_at_et"), "profile_checked_at_et")
        email = item.get("company_email")
        if not isinstance(email, str) or not COMPANY_EMAIL_PATTERN.fullmatch(email):
            fail("candidate company_email is missing or malformed")
        local, domain = email.lower().split("@")
        if not local or "." not in domain or domain.startswith(".") or domain.endswith(".") or domain in PERSONAL_EMAIL_DOMAINS:
            fail("candidate company_email is not a valid company address")
        if email.lower() in emails:
            fail("candidate company emails are repeated")
        if item.get("email_source") not in VALID_EMAIL_SOURCES or item.get("email_verification_state") != "verified":
            fail("candidate email is not finder-script-verified")
        email_verified = parse_et(item.get("email_verified_at_et"), "email_verified_at_et")
        if email_verified > finished or now - email_verified > timedelta(hours=36):
            fail("candidate email verification is future dated or more than 36 hours old")
        ranks.add(rank)
        urls.add(url)
        emails.add(email.lower())
    if ranks != set(range(1, len(candidates) + 1)):
        fail("candidate ranks must start at 1 without gaps")


def latest_handoff(today: date, now: datetime) -> tuple[Path, dict, str]:
    files = list(HANDOFFS.glob("*.json"))
    eligible = []
    for path in files:
        try:
            raw = path.read_bytes()
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            fail(f"unreadable or malformed published JSON: {path.name}")
        if data.get("send_date_et") == today.isoformat():
            timestamp = parse_et(data.get("research_completed_at_et"), "research_completed_at_et")
            eligible.append((timestamp, path, data, hashlib.sha256(raw).hexdigest()))
    if not eligible:
        fail("no published handoff for today's Eastern date")
    eligible.sort(key=lambda entry: entry[0], reverse=True)
    _, path, data, digest = eligible[0]
    validate_handoff(data, today, now)
    return path, data, digest


@contextmanager
def writer_lock():
    token = str(uuid.uuid4())
    payload = {"token": token, "pid": os.getpid(), "host": socket.gethostname(), "started_at_et": datetime.now(ET).isoformat()}
    try:
        fd = os.open(LOCK, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        fail(f"campaign writer lock already exists: {LOCK}; inspect the prior run and Gmail Sent before clearing it")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(payload, out)
        yield
    finally:
        try:
            current = json.loads(LOCK.read_text(encoding="utf-8"))
            if current.get("token") == token:
                LOCK.unlink()
        except (OSError, json.JSONDecodeError):
            pass


def acquire_persistent_lock() -> dict:
    payload = {"token": str(uuid.uuid4()), "pid": os.getpid(), "host": socket.gethostname(), "started_at_et": datetime.now(ET).isoformat()}
    try:
        fd = os.open(LOCK, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        fail(f"campaign writer lock already exists: {LOCK}; inspect the prior run and Gmail Sent before clearing it")
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump(payload, out)
    return payload


def release_persistent_lock(token: str) -> None:
    current = json.loads(LOCK.read_text(encoding="utf-8"))
    if current.get("token") != token:
        fail("lock token does not match; the lock was not released")
    LOCK.unlink()


def require_lock_owner(token: str) -> None:
    current = json.loads(LOCK.read_text(encoding="utf-8"))
    if current.get("token") != token:
        fail("lock token does not match; preflight was not run")


def selection(today: date, path: Path, data: dict, digest: str, reserve: bool) -> dict:
    selected = sorted(data["candidates"], key=lambda item: item["priority_rank"])[:10]
    result = {
        "send_date_et": today.isoformat(), "handoff": str(path), "handoff_sha256": digest,
        "provisional_selected": [{"rank": x["priority_rank"], "linkedin_url": x["linkedin_url"], "company_email": x["company_email"], "email_verified_at_et": x["email_verified_at_et"], "city": x["city"], "window": WINDOWS[x["city"]]} for x in selected],
        "confirmed_message_ids": [],
        "remaining_validation": "Gmail reconciliation, both-workbook duplicates, Claude's finder-script evidence review, role/group verification, actual draft and attachment review",
    }
    if reserve:
        STATE_DIR.mkdir(exist_ok=True)
        state = STATE_DIR / f"{today.isoformat()}.json"
        if state.exists():
            previous = json.loads(state.read_text(encoding="utf-8"))
            if previous.get("send_date_et") == today.isoformat():
                if previous.get("handoff_sha256") != digest:
                    fail("daily selection already exists for a different handoff; review before replacing")
                return previous
        temporary = state.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(result, indent=2), encoding="utf-8")
        os.replace(temporary, state)
    return result


def preflight(reserve: bool = False, now: datetime | None = None) -> dict:
    now = now or datetime.now(ET)
    today = now.date()
    if today.weekday() >= 4:
        fail("no initial outreach Friday through Sunday")
    for name in ("Outreach Tracker.xlsx", "Recruiting Tracker.xlsx"):
        path = TRACKERS / name
        if not path.is_file():
            fail(f"missing tracker: {path}")
        with path.open("rb") as handle:
            if handle.read(2) != b"PK":
                fail(f"tracker is unreadable or not an XLSX: {path}")
    resume = ROOT / "Resumes" / "Vincent_Chen_Resume_2026-07-15.pdf"
    if not resume.is_file() or resume.read_bytes()[:4] != b"%PDF":
        fail("canonical résumé PDF is missing or unreadable")
    source = ROOT / "Resumes" / "Vincent_Chen_Resume_2026-07-15.docx"
    if source.stat().st_mtime > resume.stat().st_mtime:
        fail("canonical Word résumé is newer than its PDF export")
    path, data, digest = latest_handoff(today, now)
    return selection(today, path, data, digest, reserve)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate outreach prerequisites without sending")
    parser.add_argument("--reserve", action="store_true", help="persist today's provisional selection after validation")
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument("--acquire-lock", action="store_true", help="hold the exclusive campaign lock beyond this process")
    commands.add_argument("--release-lock", metavar="TOKEN", help="release a previously acquired lock with its exact token")
    commands.add_argument("--lock-status", action="store_true", help="show the existing campaign lock without changing it")
    commands.add_argument("--under-lock", metavar="TOKEN", help="run preflight while the caller holds the persistent lock")
    args = parser.parse_args()
    try:
        if args.acquire_lock:
            print(json.dumps({"status": "LOCKED", **acquire_persistent_lock()}, indent=2))
            return 0
        if args.release_lock:
            release_persistent_lock(args.release_lock)
            print(json.dumps({"status": "RELEASED"}))
            return 0
        if args.lock_status:
            print(json.dumps({"status": "LOCKED", **json.loads(LOCK.read_text(encoding="utf-8"))} if LOCK.exists() else {"status": "FREE"}, indent=2))
            return 0
        if args.under_lock:
            require_lock_owner(args.under_lock)
            print(json.dumps({"status": "PASS", **preflight(args.reserve)}, indent=2))
            return 0
        with writer_lock():
            print(json.dumps({"status": "PASS", **preflight(args.reserve)}, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "BLOCKED", "reason": str(error)}, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())
