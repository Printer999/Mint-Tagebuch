import asyncio
import logging
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from quart import Quart, flash, redirect, render_template, request, url_for

BASE_DIR = Path(__file__).resolve().parent
LOG_PATH = BASE_DIR / "mint_tagebuch.log"
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://user1:nUxzeWSB11nWUe2Lx2fCc6wTV1BbXcDr@dpg-da1g13c9v7es73bbai50-a:5432/mint_tagebuch?sslmode=require",
)

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


def get_connection():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS entries (
                id SERIAL PRIMARY KEY,
                entry_date DATE NOT NULL UNIQUE,
                high_light TEXT NOT NULL,
                low_light TEXT NOT NULL,
                rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
                notes TEXT,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
    logger.info("PostgreSQL database initialized")


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
            return getattr(cursor, "lastrowid", None)
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


async def get_entry_by_id(entry_id: int):
    return await run_db_query(
        """
        SELECT *
        FROM entries
        WHERE id = %s
        """,
        (entry_id,),
        fetchone=True,
    )


async def save_entry(entry_date: str, high_light: str, low_light: str, rating: int, notes: str):
    await run_db_query(
        """
        INSERT INTO entries (entry_date, high_light, low_light, rating, notes)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (entry_date, high_light, low_light, rating, notes),
        commit=True,
    )
    logger.info("New diary entry saved for %s", entry_date)


async def update_entry(entry_id: int, entry_date: str, high_light: str, low_light: str, rating: int, notes: str):
    await run_db_query(
        """
        UPDATE entries
        SET entry_date = %s, high_light = %s, low_light = %s, rating = %s, notes = %s
        WHERE id = %s
        """,
        (entry_date, high_light, low_light, rating, notes, entry_id),
        commit=True,
    )
    logger.info("Diary entry %s updated", entry_id)


async def delete_entry(entry_id: int):
    await run_db_query(
        """
        DELETE FROM entries
        WHERE id = %s
        """,
        (entry_id,),
        commit=True,
    )
    logger.info("Diary entry %s deleted", entry_id)


@app.before_serving
async def before_serving():
    init_db()
    logger.info("Mint week app started")


@app.route("/", methods=["GET", "POST"])
async def index():
    summary = await get_dashboard_summary()
    entries = await get_recent_entries()
    return await render_template("index.html", summary=summary, entries=entries)


@app.route("/new", methods=["GET", "POST"])
async def create_entry():
    if request.method == "POST":
        form = await request.form
        entry_date = (form.get("entry_date") or "").strip()
        high_light = (form.get("high_light") or "").strip()
        low_light = (form.get("low_light") or "").strip()
        notes = (form.get("notes") or "").strip()
        rating = int(form.get("rating", 3) or 3)

        if not entry_date or not high_light or not low_light:
            flash("Bitte fülle das Datum, High und Low Light aus.", "error")
            return await render_template("create_entry.html")

        try:
            await save_entry(entry_date, high_light, low_light, rating, notes)
            flash("Eintrag erfolgreich gespeichert.", "success")
        except psycopg.IntegrityError:
            flash("Für dieses Datum existiert bereits ein Eintrag.", "error")
            return await render_template("create_entry.html")

        return redirect(url_for("index"))

    return await render_template("create_entry.html")


@app.route("/entries/<int:entry_id>/edit", methods=["GET", "POST"])
async def edit_entry(entry_id: int):
    entry = await get_entry_by_id(entry_id)
    if entry is None:
        flash("Eintrag nicht gefunden.", "error")
        return redirect(url_for("index"))

    if request.method == "POST":
        form = await request.form
        entry_date = (form.get("entry_date") or "").strip()
        high_light = (form.get("high_light") or "").strip()
        low_light = (form.get("low_light") or "").strip()
        notes = (form.get("notes") or "").strip()
        rating = int(form.get("rating", entry["rating"]) or entry["rating"])

        if not entry_date or not high_light or not low_light:
            flash("Bitte fülle das Datum, High und Low Light aus.", "error")
            return await render_template("edit_entry.html", entry=entry)

        try:
            await update_entry(entry_id, entry_date, high_light, low_light, rating, notes)
            flash("Eintrag erfolgreich bearbeitet.", "success")
        except psycopg.IntegrityError:
            flash("Dieses Datum ist bereits vergeben. Bitte wähle ein anderes Datum.", "error")
            return await render_template("edit_entry.html", entry=entry)

        return redirect(url_for("index"))

    return await render_template("edit_entry.html", entry=entry)


@app.route("/entries/<int:entry_id>/delete", methods=["POST"])
async def delete_entry_route(entry_id: int):
    entry = await get_entry_by_id(entry_id)
    if entry is None:
        flash("Eintrag nicht gefunden.", "error")
        return redirect(url_for("index"))

    await delete_entry(entry_id)
    flash("Eintrag gelöscht.", "success")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
