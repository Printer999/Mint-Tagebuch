import asyncio
import logging
import sqlite3
from pathlib import Path

from quart import Quart, flash, redirect, render_template, request, url_for

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "mint_diary.db"
LOG_PATH = BASE_DIR / "mint_tagebuch.log"

app = Quart(__name__)
app.secret_key = "mint-week-secret-key"


def configure_logger() -> logging.Logger:
    logger = logging.getLogger("mint_tagebuch")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        )
        logger.addHandler(file_handler)

    return logger


logger = configure_logger()


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_date TEXT NOT NULL UNIQUE,
                high_light TEXT NOT NULL,
                low_light TEXT NOT NULL,
                rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
    logger.info("SQLite database initialized")


async def run_db_query(query: str, params=(), *, fetchall: bool = False, fetchone: bool = False, commit: bool = False):
    def _execute() -> object:
        conn = get_connection()
        try:
            cursor = conn.execute(query, params)
            if commit:
                conn.commit()
            if fetchall:
                return cursor.fetchall()
            if fetchone:
                return cursor.fetchone()
            return cursor.lastrowid
        finally:
            conn.close()

    return await asyncio.to_thread(_execute)


async def get_dashboard_summary():
    summary = await run_db_query(
        """
        SELECT
            COUNT(*) AS total_entries,
            ROUND(AVG(rating), 1) AS avg_rating,
            MIN(entry_date) AS first_date,
            MAX(entry_date) AS last_date
        FROM entries
        """,
        fetchone=True,
    )

    best_day = await run_db_query(
        """
        SELECT entry_date, high_light, low_light, rating
        FROM entries
        ORDER BY rating DESC, entry_date DESC
        LIMIT 1
        """,
        fetchone=True,
    )

    latest = await run_db_query(
        """
        SELECT entry_date, high_light, rating
        FROM entries
        ORDER BY entry_date DESC
        LIMIT 1
        """,
        fetchone=True,
    )

    return {
        "total_entries": summary["total_entries"] if summary else 0,
        "avg_rating": float(summary["avg_rating"] or 0) if summary else 0.0,
        "first_date": summary["first_date"] if summary else None,
        "last_date": summary["last_date"] if summary else None,
        "best_day": best_day,
        "latest": latest,
    }


async def get_recent_entries():
    return await run_db_query(
        """
        SELECT *
        FROM entries
        ORDER BY entry_date DESC
        LIMIT 8
        """,
        fetchall=True,
    )


async def save_entry(entry_date: str, high_light: str, low_light: str, rating: int, notes: str):
    await run_db_query(
        """
        INSERT INTO entries (entry_date, high_light, low_light, rating, notes)
        VALUES (?, ?, ?, ?, ?)
        """,
        (entry_date, high_light, low_light, rating, notes),
        commit=True,
    )
    logger.info("New diary entry saved for %s", entry_date)


@app.before_serving
async def before_serving():
    init_db()
    logger.info("Mint week app started")


@app.route("/", methods=["GET", "POST"])
async def index():
    if request.method == "POST":
        form = await request.form
        entry_date = (form.get("entry_date") or "").strip()
        high_light = (form.get("high_light") or "").strip()
        low_light = (form.get("low_light") or "").strip()
        notes = (form.get("notes") or "").strip()
        rating = int(form.get("rating", 3) or 3)

        if not entry_date or not high_light or not low_light:
            flash("Bitte fülle das Datum, High und Low Light aus.", "error")
            return await render_template(
                "index.html",
                summary=await get_dashboard_summary(),
                entries=await get_recent_entries(),
            )

        try:
            await save_entry(entry_date, high_light, low_light, rating, notes)
            flash("Eintrag erfolgreich gespeichert.", "success")
        except sqlite3.IntegrityError:
            flash("Für dieses Datum existiert bereits ein Eintrag.", "error")

        return redirect(url_for("index"))

    summary = await get_dashboard_summary()
    entries = await get_recent_entries()
    return await render_template("index.html", summary=summary, entries=entries)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
