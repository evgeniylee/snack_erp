import os
import unittest
from unittest.mock import patch


os.environ["DATABASE_URL"] = "sqlite://"
os.environ["BOT_TOKEN"] = "123456:test-token"

import main
from services import google_sheets


class StartupTest(unittest.TestCase):
    def test_health_check_does_not_initialize_google_sheets(self):
        response = main.web.test_client().get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"ERP BOT OK")
        self.assertIsNone(google_sheets.spreadsheet)

    def test_status_reports_webhook_mode(self):
        response = main.web.test_client().get("/status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["telegram_mode"], "webhook")
        self.assertFalse(response.json["bot_ready"])

    def test_webhook_rejects_missing_secret(self):
        response = main.web.test_client().post("/telegram", json={})

        self.assertEqual(response.status_code, 403)

    def test_application_is_created_without_polling_updater(self):
        application = main.build_application()

        self.assertIsNone(application.updater)
        self.assertEqual(len(application.handlers[0]), 2)


if __name__ == "__main__":
    unittest.main()
