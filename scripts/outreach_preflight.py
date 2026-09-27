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
RESUME_BASENAME = os.environ.get("RESUME_BASENAME", "Resume")  # set per campaign, e.g. "Jane_Doe_Resume_2026-07-15"
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
PUBLISHED_HANDOFF_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}-claude-research\.json$")


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
    files = [path for path in HANDOFFS.glob("*.json") if PUBLISHED_HANDOFF_NAME.fullmatch(path.name)]
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
    resume = ROOT / "Resumes" / f"{RESUME_BASENAME}.pdf"
    if not resume.is_file() or resume.read_bytes()[:4] != b"%PDF":
        fail("canonical résumé PDF is missing or unreadable")
    source = ROOT / "Resumes" / f"{RESUME_BASENAME}.docx"
    if source.stat().st_mtime > resume.stat().st_mtime:
        fail("canonical Word résumé is newer than its PDF export")
    path, data, digest = latest_handoff(today, now)
    return selection(today, path, data, digest, reserve)


POOL = HANDOFFS / "research_pool.json"
POOL_STATUSES = {"READY", "PENDING_EMAIL", "PENDING_CATCHALL_RECHECK", "EXCLUDED", "SENT"}
SENDABLE_EMAIL_STATES = {"verified", "accept_all_2plus_agree"}


def validate_pool(data: dict) -> dict:
    """Validate research_pool.json against the rolling-pool contract.

    Claude runs this on its working copy before writing the pool back; Codex
    runs it before selecting READY rows. It never reads Gmail or trackers and
    a PASS is not permission to send.
    """
    if not isinstance(data, dict) or not isinstance(data.get("candidates"), list):
        fail("pool has no candidates list")
    parse_et(data.get("last_updated_et"), "last_updated_et")
    coverage = data.get("search_coverage_cumulative")
    if not isinstance(coverage, dict) or not isinstance(coverage.get("searched"), list) or not isinstance(coverage.get("not_yet_searched"), list):
        fail("search_coverage_cumulative must have searched and not_yet_searched lists")
    if set(coverage["searched"]) & set(coverage["not_yet_searched"]):
        fail("a firm is listed as both searched and not_yet_searched")
    ids, urls, emails, ranks = set(), set(), set(), set()
    ready_caps: dict = {}
    counts = {status: 0 for status in POOL_STATUSES}
    for item in data["candidates"]:
        if not isinstance(item, dict):
            fail("pool row is not an object")
        cid, status, name = item.get("contact_id"), item.get("status"), item.get("name")
        label = cid or name or "<unnamed row>"
        if not cid or not name or not item.get("firm") or not item.get("parent_bank"):
            fail(f"{label}: missing contact_id, name, firm, or parent_bank")
        if cid in ids:
            fail(f"{label}: duplicate contact_id")
        ids.add(cid)
        if status not in POOL_STATUSES:
            fail(f"{label}: invalid status {status!r}")
        counts[status] += 1
        url = item.get("linkedin_url")
        if url:
            key = url.strip().lower().rstrip("/")
            if not key.startswith("https://www.linkedin.com/in/"):
                fail(f"{label}: LinkedIn URL is invalid")
            if key in urls:
                fail(f"{label}: duplicate LinkedIn URL")
            urls.add(key)
        email = item.get("company_email")
        if email:
            if not isinstance(email, str) or not COMPANY_EMAIL_PATTERN.fullmatch(email):
                fail(f"{label}: company_email is malformed")
            if email.lower().split("@")[1] in PERSONAL_EMAIL_DOMAINS:
                fail(f"{label}: company_email is a personal address")
            if email.lower() in emails:
                fail(f"{label}: duplicate company_email")
            emails.add(email.lower())
        rank = item.get("priority_rank")
        if status != "READY":
            if rank is not None:
                fail(f"{label}: priority_rank must be null unless READY")
            if status == "SENT" and (not item.get("sent_at_et") or not item.get("gmail_message_id")):
                fail(f"{label}: SENT row needs sent_at_et and gmail_message_id")
            continue
        # READY rows: everything Codex needs to send must already be here.
        if not isinstance(rank, int) or rank < 1 or rank in ranks:
            fail(f"{label}: READY priority_rank is missing, invalid, or repeated")
        ranks.add(rank)
        if not url or not email:
            fail(f"{label}: READY row needs linkedin_url and company_email")
        if item.get("email_source") not in VALID_EMAIL_SOURCES:
            fail(f"{label}: email_source {item.get('email_source')!r} is not a finder-script provider")
        if item.get("email_verification_state") not in SENDABLE_EMAIL_STATES:
            fail(f"{label}: email_verification_state is not sendable")
        if item.get("city") not in WINDOWS:
            fail(f"{label}: city is outside the five target cities")
        if not item.get("specific_reason") or item.get("connection_type") not in {"school", "fraternity", "hometown", "interest", "none"}:
            fail(f"{label}: READY row needs specific_reason and a valid connection_type")
        parse_et(item.get("profile_checked_at_et"), f"{label} profile_checked_at_et")
        group_status = item.get("group_status")
        if group_status == "verified":
            if not item.get("ib_group"):
                fail(f"{label}: verified group is blank")
            cap_key = (item["parent_bank"].lower(), item["ib_group"].lower())
        elif group_status == "unverified":
            if item.get("ib_group") is not None:
                fail(f"{label}: unverified group must have null ib_group")
            cap_key = (item["parent_bank"].lower(), None)
        else:
            fail(f"{label}: group_status is invalid")
        # One READY prospect per parent bank + group; an unverified group caps the
        # whole parent bank, so it also conflicts with any verified group there.
        bank = item["parent_bank"].lower()
        for other in ready_caps.get(bank, []):
            if other == cap_key or other[1] is None or cap_key[1] is None:
                fail(f"{label}: violates the one-READY-per-parent-bank-and-group cap")
        ready_caps.setdefault(bank, []).append(cap_key)
    return {"rows": len(data["candidates"]), "by_status": counts, "ready_ranks": sorted(ranks)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate outreach prerequisites without sending")
    parser.add_argument("--reserve", action="store_true", help="persist today's provisional selection after validation")
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument("--acquire-lock", action="store_true", help="hold the exclusive campaign lock beyond this process")
    commands.add_argument("--release-lock", metavar="TOKEN", help="release a previously acquired lock with its exact token")
    commands.add_argument("--lock-status", action="store_true", help="show the existing campaign lock without changing it")
    commands.add_argument("--under-lock", metavar="TOKEN", help="run preflight while the caller holds the persistent lock")
    commands.add_argument("--validate-pool", nargs="?", const=str(POOL), metavar="PATH", help="validate research_pool.json (or a working copy) against the pool contract; no lock, no send checks")
    args = parser.parse_args()
    try:
        if args.validate_pool:
            with open(args.validate_pool, encoding="utf-8") as handle:
                result = validate_pool(json.load(handle))
            print(json.dumps({"status": "PASS", "pool": args.validate_pool, **result}, indent=2))
            return 0
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
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "BLOCKED", "reason": str(error)}, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())
