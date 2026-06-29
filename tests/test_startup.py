import asyncio
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

    def test_run_creates_event_loop_before_polling(self):
        try:
            with patch.object(main, "main") as start_polling:
                with patch.object(main.threading, "Thread") as thread:
                    main.run()

            start_polling.assert_called_once_with()
            thread.assert_called_once_with(target=main.run_web)
            thread.return_value.start.assert_called_once_with()
            self.assertIsInstance(
                asyncio.get_event_loop(),
                asyncio.AbstractEventLoop,
            )
        finally:
            asyncio.get_event_loop().close()
            asyncio.set_event_loop(None)


if __name__ == "__main__":
    unittest.main()
