"""Regression tests for the MySQL adapter and affected routes; no server needed."""

import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pymysql

import app as diary


class DatabaseConnectionTests(unittest.TestCase):
    def test_connection_supports_unicode_credentials_without_url_escaping(self):
        connect = pymysql.connect
        password = "päss🌱@:/%"
        with (
            patch.object(diary, "MYSQL_PASSWORD", password),
            patch.object(diary, "MYSQL_SSL_CA", ""),
            patch.object(
                pymysql, "connect",
                side_effect=lambda **kwargs: connect(defer_connect=True, **kwargs),
            ),
        ):
            connection = diary.get_connection()

        self.assertEqual(connection.password, password.encode("utf-8"))
        self.assertEqual(connection.charset, "utf8mb4")
        self.assertIs(connection.cursorclass, pymysql.cursors.DictCursor)
        self.assertFalse(connection.autocommit_mode)


class DatabaseQueryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.connection = MagicMock()
        self.cursor = self.connection.cursor.return_value.__enter__.return_value
        connection_patch = patch.object(
            diary, "get_connection", return_value=self.connection
        )
        connection_patch.start()
        self.addCleanup(connection_patch.stop)

    async def test_insert_keeps_special_characters_in_parameters_and_commits(self):
        self.cursor.lastrowid = 42
        query = "INSERT INTO entries (high_light) VALUES (%s)"
        params = ("Grüße 🌱, 100% Spaß, 'Zitat' und \\Pfad",)

        result = await diary.run_db_query(query, params, commit=True)

        self.assertEqual(result, 42)
        self.cursor.execute.assert_called_once_with(query, params)
        self.connection.commit.assert_called_once()
        self.connection.rollback.assert_not_called()
        self.connection.close.assert_called_once()

    async def test_select_returns_dictionary_rows_without_commit(self):
        rows = [{"id": 7, "name": "Jörg", "created_at": datetime(2026, 9, 20)}]
        self.cursor.fetchall.return_value = rows
        self.cursor.fetchone.return_value = rows[0]

        self.assertEqual(
            await diary.run_db_query("SELECT * FROM users", fetchall=True), rows
        )
        self.assertEqual(
            await diary.run_db_query("SELECT * FROM users", fetchone=True), rows[0]
        )
        self.connection.commit.assert_not_called()
        self.assertEqual(self.connection.close.call_count, 2)

    async def test_duplicate_rolls_back_closes_and_propagates(self):
        error = pymysql.IntegrityError(1062, "Duplicate entry")
        self.cursor.execute.side_effect = error

        with self.assertRaises(pymysql.IntegrityError) as raised:
            await diary.run_db_query("INSERT INTO entries ...", commit=True)

        self.assertIs(raised.exception, error)
        self.connection.commit.assert_not_called()
        self.connection.rollback.assert_called_once()
        self.connection.close.assert_called_once()
        self.connection.cursor.return_value.__exit__.assert_called_once()

    async def test_commit_failure_rolls_back_and_closes(self):
        self.connection.commit.side_effect = pymysql.OperationalError(
            2013, "Lost connection"
        )

        with self.assertRaises(pymysql.OperationalError):
            await diary.run_db_query("UPDATE users SET locked = TRUE", commit=True)

        self.connection.rollback.assert_called_once()
        self.connection.close.assert_called_once()


class MySQLRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        diary.app.config["TESTING"] = True
        self.client = diary.app.test_client()
        self.owner = {
            "id": 1,
            "name": diary.OWNER_NAME,
            "role": "OWNER",
            "must_change_password": 0,
            "locked": 0,
        }
        async with self.client.session_transaction() as session:
            session.update(
                user_id=1,
                user_name=diary.OWNER_NAME,
                user_role="OWNER",
                must_change_password=False,
            )
        for name, replacement in (
            ("get_user_by_id", AsyncMock(return_value=self.owner)),
            ("touch_user_session", AsyncMock()),
            ("REQUEST_RATE_LIMITER", diary.SlidingWindowRateLimiter(600, 60)),
        ):
            item = patch.object(diary, name, replacement)
            item.start()
            self.addCleanup(item.stop)

    async def assert_flash_contains(self, text):
        async with self.client.session_transaction() as session:
            messages = [message for _, message in session.get("_flashes", [])]
        self.assertTrue(any(text in message for message in messages), messages)

    async def test_duplicate_diary_date_shows_error(self):
        with patch.object(
            diary, "save_entry", side_effect=pymysql.IntegrityError(1062, "duplicate")
        ):
            response = await self.client.post(
                "/new", form={"entry_date": "2026-09-20", "rating": "4"}
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("bereits ein Eintrag", await response.get_data(as_text=True))

    async def test_edit_duplicate_date_shows_error(self):
        entry = {
            "id": 8,
            "entry_date": datetime(2026, 9, 20).date(),
            "rating": 4,
            "high_light": "Gut",
            "low_light": "-",
            "notes": "-",
        }
        with (
            patch.object(diary, "get_entry_by_id", return_value=entry),
            patch.object(
                diary, "update_entry",
                side_effect=pymysql.IntegrityError(1062, "duplicate"),
            ),
        ):
            response = await self.client.post(
                "/entries/8/edit", form={"entry_date": "2026-09-21", "rating": "4"}
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Datum ist bereits vergeben", await response.get_data(as_text=True))

    async def test_duplicate_username_shows_error(self):
        with patch.object(
            diary, "create_user", side_effect=pymysql.IntegrityError(1062, "duplicate")
        ):
            response = await self.client.post(
                "/users", form={"name": "Anna", "role": "EDITOR"}
            )
        self.assertEqual(response.status_code, 302)
        await self.assert_flash_contains("Nutzer mit diesem Namen existiert bereits")

    async def test_overlong_username_is_rejected_before_insert(self):
        with patch.object(diary, "create_user") as create_user:
            response = await self.client.post(
                "/users", form={"name": "x" * 192, "role": "VIEWER"}
            )
        self.assertEqual(response.status_code, 302)
        create_user.assert_not_awaited()
        await self.assert_flash_contains("höchstens 191 Zeichen")

    async def test_overlong_username_is_rejected_before_owner_update(self):
        target = dict(self.owner, id=2, name="Anna", role="VIEWER")
        diary.get_user_by_id.side_effect = [self.owner, target]
        with patch.object(diary, "run_db_query") as query:
            response = await self.client.post(
                "/owner/users/2/edit", form={"name": "x" * 192, "role": "VIEWER"}
            )
        self.assertEqual(response.status_code, 302)
        query.assert_not_awaited()
        await self.assert_flash_contains("höchstens 191 Zeichen")

    async def test_owner_rename_duplicate_shows_error(self):
        target = dict(self.owner, id=2, name="Anna", role="VIEWER")
        diary.get_user_by_id.side_effect = [self.owner, target]
        with patch.object(
            diary, "run_db_query",
            side_effect=pymysql.IntegrityError(1062, "duplicate"),
        ):
            response = await self.client.post(
                "/owner/users/2/edit", form={"name": "Ben", "role": "VIEWER"}
            )
        self.assertEqual(response.status_code, 302)
        await self.assert_flash_contains("Nutzername ist bereits vergeben")

    async def test_mysql_integer_presence_is_returned_as_json_boolean(self):
        with patch.object(
            diary, "list_users",
            return_value=[{"id": 1, "is_online": 1}, {"id": 2, "is_online": 0}],
        ):
            response = await self.client.get("/owner/presence")
        self.assertEqual(response.status_code, 200)
        data = await response.get_json()
        self.assertIs(data["users"][0]["is_online"], True)
        self.assertIs(data["users"][1]["is_online"], False)


if __name__ == "__main__":
    unittest.main()
