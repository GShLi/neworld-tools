import unittest
from unittest.mock import patch
from pathlib import Path
import neworld_checkin
from datetime import datetime, timezone

from neworld_checkin import AutomationError, choose_reward, load_credentials, response_state


class CredentialTests(unittest.TestCase):
    def test_environment_credentials(self):
        with patch.dict("os.environ", {"NEWORLD_USERNAME":"example@example.com",
                                      "NEWORLD_PASSWORD":" secret with spaces "}, clear=True):
            self.assertEqual(load_credentials(), {"username":"example@example.com",
                                                  "password":" secret with spaces ", "totp_code":""})

    def test_missing_credentials_fail_before_browser_launch(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(AutomationError):
                load_credentials()

    def test_different_accounts_use_separate_profiles(self):
        state = Path(".state")
        first = neworld_checkin.profile_path(state, "first@example.com")
        second = neworld_checkin.profile_path(state, "second@example.com")
        self.assertNotEqual(first, second)
        self.assertEqual(first, neworld_checkin.profile_path(state, "first@example.com"))
        self.assertEqual(first.parent, state)
        self.assertNotIn("first@example.com", str(first))


class PolicyTests(unittest.TestCase):
    def test_entire_week(self):
        # 2026-11-02 is Monday. Local timezone must not affect the policy.
        for day, expected in [(2, "traffic"), (3, "time"), (4, "time"),
                              (5, "time"), (6, "time"), (7, "time"), (8, "time")]:
            with self.subTest(day=day):
                self.assertEqual(choose_reward(datetime(2026, 11, day, 4,
                                                       tzinfo=timezone.utc)), expected)

    def test_beijing_midnight(self):
        self.assertEqual(choose_reward(datetime(2026, 11, 1, 15, 59,
                                               tzinfo=timezone.utc)), "time")
        self.assertEqual(choose_reward(datetime(2026, 11, 1, 16,
                                               tzinfo=timezone.utc)), "traffic")
        self.assertEqual(choose_reward(datetime(2026, 11, 2, 16,
                                               tzinfo=timezone.utc)), "time")

    def test_reject_naive_date(self):
        with self.assertRaises(ValueError):
            choose_reward(datetime(2026, 11, 2))


class ResponseTests(unittest.TestCase):
    def test_success_and_challenge(self):
        self.assertEqual(response_state({"ret": 1, "msg": "成功"}), "success")
        self.assertEqual(response_state({"ret": 2}), "captcha")

    def test_fail_closed(self):
        for data in [{"ret": 0}, {"ret": -1}, {}, [], None,
                     {"ret": "1"}, {"ret": True}]:
            with self.subTest(data=data), self.assertRaises(AutomationError):
                response_state(data)


if __name__ == "__main__":
    unittest.main()
