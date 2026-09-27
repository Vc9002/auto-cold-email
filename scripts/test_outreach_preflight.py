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
                (preflight.HANDOFFS / "2026-09-26-claude-research.json").write_text(json.dumps(self.data), encoding="utf-8")
                newer = {**self.data, "status": "BLOCKED", "research_completed_at_et": (self.now - timedelta(hours=1)).isoformat()}
                (preflight.HANDOFFS / "2026-09-27-claude-research.json").write_text(json.dumps(newer), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "BLOCKED"):
                    preflight.latest_handoff(self.now.date(), self.now)
            finally:
                preflight.HANDOFFS = old_handoffs

    def test_temporary_handoff_is_ignored(self):
        old_handoffs = preflight.HANDOFFS
        with tempfile.TemporaryDirectory() as folder:
            preflight.HANDOFFS = Path(folder)
            try:
                published = preflight.HANDOFFS / "2026-09-27-claude-research.json"
                published.write_text(json.dumps(self.data), encoding="utf-8")
                temporary = preflight.HANDOFFS / ".tmp-2026-09-28-claude-research.json"
                temporary.write_text("{incomplete", encoding="utf-8")
                path, _, _ = preflight.latest_handoff(self.now.date(), self.now)
                self.assertEqual(path, published)
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



class PoolTests(unittest.TestCase):
    def setUp(self):
        self.row = {
            "contact_id": "example-banker",
            "priority_rank": 1,
            "name": "Example Banker",
            "firm": "Example Bank",
            "parent_bank": "Example Bank",
            "city": "New York",
            "ib_group": "Technology",
            "group_status": "verified",
            "connection_type": "school",
            "connection_evidence": "Penn on profile",
            "specific_reason": "Verified Penn education and Technology group",
            "linkedin_url": "https://www.linkedin.com/in/example",
            "company_email": "banker@examplebank.com",
            "email_source": "Hunter",
            "email_verification_state": "verified",
            "profile_checked_at_et": "2026-09-27T06:00:00-04:00",
            "status": "READY",
        }
        self.pool = {
            "last_updated_et": "2026-09-27T06:30:00-04:00",
            "candidates": [self.row],
            "search_coverage_cumulative": {"searched": ["Example Bank"], "not_yet_searched": ["Other Bank"]},
        }

    def other(self, **changes):
        row = dict(self.row, contact_id="other", name="Other Banker", priority_rank=2,
                   linkedin_url="https://www.linkedin.com/in/other", company_email="other@examplebank.com")
        row.update(changes)
        return row

    def test_valid_pool(self):
        self.assertEqual(preflight.validate_pool(self.pool)["by_status"]["READY"], 1)

    def test_apollo_source_fails(self):
        self.row["email_source"] = "Apollo"
        with self.assertRaisesRegex(ValueError, "finder-script provider"):
            preflight.validate_pool(self.pool)

    def test_catchall_single_provider_not_sendable(self):
        self.row["email_verification_state"] = "accept_all_domain"
        with self.assertRaisesRegex(ValueError, "not sendable"):
            preflight.validate_pool(self.pool)

    def test_catchall_two_provider_agreement_is_sendable(self):
        self.row["email_verification_state"] = "accept_all_2plus_agree"
        preflight.validate_pool(self.pool)

    def test_duplicate_email_across_statuses_fails(self):
        self.pool["candidates"].append(self.other(status="PENDING_EMAIL", priority_rank=None, company_email="banker@examplebank.com"))
        with self.assertRaisesRegex(ValueError, "duplicate company_email"):
            preflight.validate_pool(self.pool)

    def test_repeated_ready_rank_fails(self):
        self.pool["candidates"].append(self.other(parent_bank="Other Bank", priority_rank=1))
        with self.assertRaisesRegex(ValueError, "priority_rank"):
            preflight.validate_pool(self.pool)

    def test_same_bank_group_cap_fails(self):
        self.pool["candidates"].append(self.other())
        with self.assertRaisesRegex(ValueError, "cap"):
            preflight.validate_pool(self.pool)

    def test_unverified_group_caps_whole_bank(self):
        self.pool["candidates"].append(self.other(ib_group=None, group_status="unverified"))
        with self.assertRaisesRegex(ValueError, "cap"):
            preflight.validate_pool(self.pool)

    def test_different_verified_groups_same_bank_pass(self):
        self.pool["candidates"].append(self.other(ib_group="Healthcare"))
        preflight.validate_pool(self.pool)

    def test_non_ready_row_with_rank_fails(self):
        self.pool["candidates"].append(self.other(status="PENDING_EMAIL", parent_bank="Other Bank"))
        with self.assertRaisesRegex(ValueError, "null unless READY"):
            preflight.validate_pool(self.pool)

    def test_sent_row_needs_message_id(self):
        self.row.update(status="SENT", priority_rank=None, sent_at_et="2026-09-28T10:05:00-04:00")
        with self.assertRaisesRegex(ValueError, "gmail_message_id"):
            preflight.validate_pool(self.pool)

    def test_firm_in_both_coverage_lists_fails(self):
        self.pool["search_coverage_cumulative"]["not_yet_searched"].append("Example Bank")
        with self.assertRaisesRegex(ValueError, "both searched"):
            preflight.validate_pool(self.pool)

if __name__ == "__main__":
    unittest.main()
