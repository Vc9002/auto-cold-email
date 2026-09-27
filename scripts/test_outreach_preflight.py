"""No-send checks for the local campaign gate."""

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

MODULE = Path(__file__).with_name("outreach_preflight.py")
spec = importlib.util.spec_from_file_location("outreach_preflight", MODULE)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)
ET = ZoneInfo("America/New_York")


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 28, 10, 0, tzinfo=ET)
        self.candidate = {
            "priority_rank": 1,
            "name": "Example Banker",
            "linkedin_url": "https://www.linkedin.com/in/example",
            "firm": "Example Bank",
            "parent_bank": "Example Bank",
            "title": "Investment Banking Analyst",
            "ib_group": "Technology",
            "group_status": "verified",
            "city": "New York",
            "connection_type": "school",
            "specific_reason": "Verified Penn education and Technology group",
            "profile_checked_at_et": (self.now - timedelta(hours=2)).isoformat(),
            "company_email": "banker@examplebank.com",
            "email_source": "Prospeo",
            "email_verification_state": "verified",
            "email_verified_at_et": (self.now - timedelta(hours=4)).isoformat(),
        }
        self.data = {
            "schema_version": 2,
            "campaign": "Summer 2028 IB Summer Analyst networking",
            "send_date_et": "2026-09-28",
            "research_completed_at_et": (self.now - timedelta(hours=3)).isoformat(),
            "status": "READY",
            "candidate_count": 1,
            "search_coverage": [{"firm": "Example Bank", "cities": ["New York"], "qualified_count": 1}],
            "candidates": [self.candidate],
        }

    def test_valid_handoff(self):
        preflight.validate_handoff(self.data, self.now.date(), self.now)

    def test_stale_handoff_fails(self):
        self.data["research_completed_at_et"] = (self.now - timedelta(hours=37)).isoformat()
        with self.assertRaisesRegex(ValueError, "36 hours"):
            preflight.validate_handoff(self.data, self.now.date(), self.now)

    def test_wrong_daylight_saving_offset_fails(self):
        self.data["research_completed_at_et"] = "2026-09-28T07:00:00-05:00"
        with self.assertRaisesRegex(ValueError, "daylight-saving"):
            preflight.validate_handoff(self.data, self.now.date(), self.now)

    def test_duplicate_profile_fails(self):
        self.data["candidates"].append({**self.candidate, "priority_rank": 2})
        self.data["candidate_count"] = 2
        with self.assertRaisesRegex(ValueError, "repeated"):
            preflight.validate_handoff(self.data, self.now.date(), self.now)

    def test_missing_company_email_fails(self):
        del self.candidate["company_email"]
        with self.assertRaisesRegex(ValueError, "company_email"):
            preflight.validate_handoff(self.data, self.now.date(), self.now)

    def test_unverified_email_fails(self):
        self.candidate["email_verification_state"] = "catch-all"
        with self.assertRaisesRegex(ValueError, "finder-script-verified"):
            preflight.validate_handoff(self.data, self.now.date(), self.now)

    def test_invalid_source_fails(self):
        self.candidate["email_source"] = "guessed pattern"
        with self.assertRaisesRegex(ValueError, "finder-script-verified"):
            preflight.validate_handoff(self.data, self.now.date(), self.now)

    def test_apollo_source_fails(self):
        self.candidate["email_source"] = "Apollo"
        with self.assertRaisesRegex(ValueError, "finder-script-verified"):
            preflight.validate_handoff(self.data, self.now.date(), self.now)

    def test_personal_address_fails(self):
        self.candidate["company_email"] = "banker@gmail.com"
        with self.assertRaisesRegex(ValueError, "company address"):
            preflight.validate_handoff(self.data, self.now.date(), self.now)

    def test_duplicate_company_email_fails(self):
        self.data["candidates"].append({**self.candidate, "priority_rank": 2, "linkedin_url": "https://www.linkedin.com/in/another", "company_email": "BANKER@examplebank.com"})
        self.data["candidate_count"] = 2
        with self.assertRaisesRegex(ValueError, "company emails are repeated"):
            preflight.validate_handoff(self.data, self.now.date(), self.now)

    def test_stale_email_verification_fails(self):
        self.candidate["email_verified_at_et"] = (self.now - timedelta(hours=37)).isoformat()
        with self.assertRaisesRegex(ValueError, "email verification"):
            preflight.validate_handoff(self.data, self.now.date(), self.now)

    def test_wrong_email_verification_offset_fails(self):
        self.candidate["email_verified_at_et"] = "2026-09-28T07:00:00-05:00"
        with self.assertRaisesRegex(ValueError, "daylight-saving"):
            preflight.validate_handoff(self.data, self.now.date(), self.now)

    def test_newer_blocked_handoff_wins(self):
        old_handoffs = preflight.HANDOFFS
        with tempfile.TemporaryDirectory() as folder:
            preflight.HANDOFFS = Path(folder)
            try:
                (preflight.HANDOFFS / "older.json").write_text(json.dumps(self.data), encoding="utf-8")
                newer = {**self.data, "status": "BLOCKED", "research_completed_at_et": (self.now - timedelta(hours=1)).isoformat()}
                (preflight.HANDOFFS / "newer.json").write_text(json.dumps(newer), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "BLOCKED"):
                    preflight.latest_handoff(self.now.date(), self.now)
            finally:
                preflight.HANDOFFS = old_handoffs

    def test_exclusive_lock_releases_after_failure(self):
        old_lock = preflight.LOCK
        with tempfile.TemporaryDirectory() as folder:
            preflight.LOCK = Path(folder) / "lock.json"
            try:
                with self.assertRaisesRegex(ValueError, "already exists"):
                    with preflight.writer_lock():
                        with preflight.writer_lock():
                            pass
                self.assertFalse(preflight.LOCK.exists())
            finally:
                preflight.LOCK = old_lock

    def test_daily_selection_is_idempotent_and_immutable(self):
        old_state_dir = preflight.STATE_DIR
        with tempfile.TemporaryDirectory() as folder:
            preflight.STATE_DIR = Path(folder)
            try:
                first = preflight.selection(self.now.date(), Path("handoff.json"), self.data, "first-hash", True)
                self.assertEqual(first["provisional_selected"][0]["company_email"], "banker@examplebank.com")
                second = preflight.selection(self.now.date(), Path("handoff.json"), self.data, "first-hash", True)
                self.assertEqual(first, second)
                self.assertEqual(len(list(Path(folder).glob("*.json"))), 1)
                with self.assertRaisesRegex(ValueError, "different handoff"):
                    preflight.selection(self.now.date(), Path("handoff.json"), self.data, "changed-hash", True)
            finally:
                preflight.STATE_DIR = old_state_dir

    def test_persistent_lock_requires_owner_token(self):
        old_lock = preflight.LOCK
        with tempfile.TemporaryDirectory() as folder:
            preflight.LOCK = Path(folder) / "lock.json"
            try:
                held = preflight.acquire_persistent_lock()
                preflight.require_lock_owner(held["token"])
                with self.assertRaisesRegex(ValueError, "already exists"):
                    preflight.acquire_persistent_lock()
                with self.assertRaisesRegex(ValueError, "does not match"):
                    preflight.require_lock_owner("wrong-token")
                with self.assertRaisesRegex(ValueError, "does not match"):
                    preflight.release_persistent_lock("wrong-token")
                self.assertTrue(preflight.LOCK.exists())
                preflight.release_persistent_lock(held["token"])
                self.assertFalse(preflight.LOCK.exists())
            finally:
                preflight.LOCK = old_lock


if __name__ == "__main__":
    unittest.main()
