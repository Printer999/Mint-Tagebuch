"""Opt-in integration test against the configured MySQL server.

Initializes the application's tables and initial admin as a normal start would.
All subsequent test records are isolated in a transaction and rolled back.
"""

import asyncio
import os
import unittest
import uuid
from datetime import date, timedelta
from unittest.mock import patch

import pymysql

import app as diary


@unittest.skipUnless(os.getenv("MINT_TEST_MYSQL") == "1", "MySQL live test is opt-in")
class MySQLLiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_and_database_operations(self):
        async with diary.app.test_app() as test_app:
            response = await test_app.test_client().get("/login")
            self.assertEqual(response.status_code, 200)
            await diary.init_db()  # Starting again must preserve the schema.

        connection = await asyncio.to_thread(diary.get_connection)

        async def transaction_query(query, params=(), *, fetchall=False,
                                    fetchone=False, commit=False):
            # Use one real connection but defer commits to allow full cleanup.
            def execute():
                with connection.cursor() as cursor:
                    cursor.execute(query, params)
                    if fetchall:
                        return cursor.fetchall()
                    if fetchone:
                        return cursor.fetchone()
                    return cursor.lastrowid
            return await asyncio.to_thread(execute)

        try:
            with patch.object(diary, "run_db_query", transaction_query):
                name = "Test_" + uuid.uuid4().hex
                await diary.create_user(name, "EDITOR")
                user = await diary.get_user_by_name(name)
                self.assertIsNotNone(user["created_at"])
                self.assertIsNone(await diary.get_user_by_name(name.lower()))

                with self.assertRaises(pymysql.IntegrityError):
                    await diary.create_user(name.lower(), "VIEWER")

                long_name = "N" + uuid.uuid4().hex + "🌱" * 158
                self.assertEqual(len(long_name), diary.MAX_USERNAME_LENGTH)
                await diary.create_user(long_name, "VIEWER")
                self.assertIsNotNone(await diary.get_user_by_name(long_name))

                entry_date = date(2090, 1, 1)
                while await transaction_query(
                    "SELECT id FROM entries WHERE entry_date = %s",
                    (entry_date,), fetchone=True,
                ):
                    entry_date += timedelta(days=1)
                await diary.save_entry(str(entry_date), "Grüße 🌱", "-", 4, "100% Spaß")
                entry = await transaction_query(
                    "SELECT * FROM entries WHERE entry_date = %s",
                    (entry_date,), fetchone=True,
                )
                self.assertEqual(entry["high_light"], "Grüße 🌱")
                self.assertIsNotNone(entry["created_at"])
                with self.assertRaises(pymysql.IntegrityError):
                    await diary.save_entry(str(entry_date), "duplicate", "-", 2, "-")

                await transaction_query(
                    "UPDATE entries SET created_at = %s WHERE id = %s",
                    ("2020-01-01 12:00:00", entry["id"]),
                )
                await diary.update_entry(entry["id"], str(entry_date), "Änderung", "-", 5, "-")
                updated = await diary.get_entry_by_id(entry["id"])
                self.assertEqual(updated["rating"], 5)
                self.assertEqual(updated["created_at"].year, 2020)
                self.assertGreaterEqual((await diary.get_dashboard_summary())["total_entries"], 1)

                async with diary.app.test_request_context("/heartbeat"):
                    await diary.touch_user_session(user["id"])
                    token = diary.session["presence_token"]
                    await diary.touch_user_session(user["id"])
                    count = await transaction_query(
                        "SELECT COUNT(*) AS count FROM user_sessions WHERE session_token = %s",
                        (token,), fetchone=True,
                    )
                    self.assertEqual(count["count"], 1)
                    online = next(u for u in await diary.list_users() if u["id"] == user["id"])
                    self.assertTrue(online["is_online"])

                    await transaction_query(
                        "UPDATE user_sessions SET last_seen_at = CURRENT_TIMESTAMP "
                        "- INTERVAL %s SECOND WHERE session_token = %s",
                        (diary.PRESENCE_TIMEOUT_SECONDS + 10, token),
                    )
                    offline = next(u for u in await diary.list_users() if u["id"] == user["id"])
                    self.assertFalse(offline["is_online"])
                    await diary.end_user_session()
                    await diary.touch_user_session(user["id"])

                await diary.delete_user(user["id"])
                self.assertIsNone(await transaction_query(
                    "SELECT session_token FROM user_sessions WHERE session_token = %s",
                    (token,), fetchone=True,
                ))
                await diary.delete_entry(entry["id"])
                self.assertIsNone(await diary.get_entry_by_id(entry["id"]))
        finally:
            try:
                await asyncio.to_thread(connection.rollback)
            finally:
                await asyncio.to_thread(connection.close)
