import asyncio
import functools
import logging
import os
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import bcrypt
import psycopg
from psycopg.rows import dict_row
from quart import (
    Quart,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

BASE_DIR = Path(__file__).resolve().parent
LOG_PATH = BASE_DIR / "mint_tagebuch.log"

# Render sets DATABASE_URL for its managed PostgreSQL. Locally we fall back to
# the development database. The URL is normalized so psycopg3 accepts it
# (Render sometimes ships a `postgres://` scheme which psycopg3 rejects).
_DEFAULT_DATABASE_URL = (
    "postgresql://user1:nUxzeWSB11nWUe2Lx2fCc6wTV1BbXcDr"
    "@dpg-da1g13c9v7es73bbai50-a:5432/mint_tagebuch?sslmode=require"
)


def _normalize_database_url(raw: str) -> str:
    """Render ships `postgres://` URLs which psycopg3 rejects; convert to
    `postgresql://`. Everything else is left untouched so the local dev URL
    (with its sslmode param) keeps working."""
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]
    return raw


DATABASE_URL = _normalize_database_url(
    os.getenv("DATABASE_URL", _DEFAULT_DATABASE_URL)
)

# A stable secret key is required for signed session cookies. On Render set
# the SECRET_KEY environment variable to a long random string.
SECRET_KEY = os.getenv("SECRET_KEY", "mint-week-dev-secret-change-me")

# The default password assigned to every newly created account and used when
# an admin resets a password. Users must change it on first login.
DEFAULT_PASSWORD = "1234"

app = Quart(__name__)
app.secret_key = SECRET_KEY


def configure_logger() -> logging.Logger:
    logger = logging.getLogger("mint_tagebuch")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        )
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        )
        logger.addHandler(file_handler)
        logger.addHandler(stream_handler)

    return logger


logger = configure_logger()


# --------------------------------------------------------------------------- #
# Database helpers
# --------------------------------------------------------------------------- #

def get_connection():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


async def run_db_query(
    query: str,
    params=(),
    *,
    fetchall: bool = False,
    fetchone: bool = False,
    commit: bool = False,
):
    def _execute():
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


async def init_db() -> None:
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'VIEWER'
                    CHECK (role IN ('ADMIN', 'EDITOR', 'VIEWER')),
                must_change_password BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
    logger.info("PostgreSQL database initialized (entries + users)")


async def seed_admin() -> None:
    """Create the default admin account if it does not yet exist. The admin is
    seeded only once; re-running this never overwrites an existing password so
    a deployed instance keeps its changed password across restarts."""
    existing = await run_db_query(
        "SELECT id FROM users WHERE name = %s",
        ("TheHacker",),
        fetchone=True,
    )
    if existing:
        return

    password_hash = bcrypt.hashpw(
        DEFAULT_PASSWORD.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")
    await run_db_query(
        """
        INSERT INTO users (name, password_hash, role, must_change_password)
        VALUES (%s, %s, %s, %s)
        """,
        ("TheHacker", password_hash, "ADMIN", True),
        commit=True,
    )
    logger.info("Seeded admin user 'TheHacker' with default password")


# --------------------------------------------------------------------------- #
# Domain queries: entries
# --------------------------------------------------------------------------- #

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


# --------------------------------------------------------------------------- #
# Domain queries: users
# --------------------------------------------------------------------------- #

async def get_user_by_name(name: str):
    return await run_db_query(
        """
        SELECT id, name, password_hash, role, must_change_password, created_at
        FROM users
        WHERE name = %s
        """,
        (name,),
        fetchone=True,
    )


async def get_user_by_id(user_id: int):
    return await run_db_query(
        """
        SELECT id, name, password_hash, role, must_change_password, created_at
        FROM users
        WHERE id = %s
        """,
        (user_id,),
        fetchone=True,
    )


async def list_users():
    return await run_db_query(
        """
        SELECT id, name, role, must_change_password, created_at
        FROM users
        ORDER BY created_at ASC
        """,
        fetchall=True,
    )


async def create_user(name: str, role: str) -> None:
    password_hash = bcrypt.hashpw(
        DEFAULT_PASSWORD.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")
    await run_db_query(
        """
        INSERT INTO users (name, password_hash, role, must_change_password)
        VALUES (%s, %s, %s, %s)
        """,
        (name, password_hash, role, True),
        commit=True,
    )
    logger.info("User %s created with role %s", name, role)


async def update_user_role(user_id: int, role: str) -> None:
    await run_db_query(
        "UPDATE users SET role = %s WHERE id = %s",
        (role, user_id),
        commit=True,
    )


async def reset_user_password(user_id: int) -> None:
    password_hash = bcrypt.hashpw(
        DEFAULT_PASSWORD.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")
    await run_db_query(
        """
        UPDATE users
        SET password_hash = %s, must_change_password = TRUE
        WHERE id = %s
        """,
        (password_hash, user_id),
        commit=True,
    )
    logger.info("Password for user %s reset to default", user_id)


async def delete_user(user_id: int) -> None:
    await run_db_query(
        "DELETE FROM users WHERE id = %s",
        (user_id,),
        commit=True,
    )
    logger.info("User %s deleted", user_id)


async def set_user_password(user_id: int, new_password: str) -> None:
    password_hash = bcrypt.hashpw(
        new_password.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")
    await run_db_query(
        """
        UPDATE users
        SET password_hash = %s, must_change_password = FALSE
        WHERE id = %s
        """,
        (password_hash, user_id),
        commit=True,
    )


# --------------------------------------------------------------------------- #
# Auth helpers + decorators
# --------------------------------------------------------------------------- #

def current_user():
    """Returns the logged-in user dict from the session, or None."""
    user_id = session.get("user_id")
    if not user_id:
        return None
    return {
        "id": user_id,
        "name": session.get("user_name"),
        "role": session.get("user_role"),
        "must_change_password": session.get("must_change_password", False),
    }


def login_required(func):
    """Redirects anonymous users to the login page."""

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        if not current_user():
            flash("Bitte melde dich an, um diese Seite zu sehen.", "error")
            return redirect(url_for("login"))
        return await func(*args, **kwargs)

    return wrapper


def role_required(*roles):
    """Allows access only for the given roles. Must be used together with
    `login_required` (applied first)."""

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                flash("Bitte melde dich an.", "error")
                return redirect(url_for("login"))
            if user["role"] not in roles:
                flash("Du hast keine Berechtigung für diese Aktion.", "error")
                return redirect(url_for("index"))
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def force_password_change(func):
    """Redirects users who still have the default password to the change
    password page. Applied after login_required on every authenticated route
    except the change-password page itself."""

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        user = current_user()
        if user and user.get("must_change_password"):
            return redirect(url_for("change_password"))
        return await func(*args, **kwargs)

    return wrapper


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #

@app.before_serving
async def before_serving():
    await init_db()
    await seed_admin()
    logger.info("Mint week app started")


# --------------------------------------------------------------------------- #
# Context processor: expose current_user + role flags to every template
# --------------------------------------------------------------------------- #

@app.context_processor
def inject_user():
    user = current_user()
    role = user["role"] if user else None
    return {
        "current_user": user,
        "is_admin": role == "ADMIN",
        "is_editor": role in ("ADMIN", "EDITOR"),
        "is_viewer": role == "VIEWER",
        "can_edit": role in ("ADMIN", "EDITOR"),
    }


# --------------------------------------------------------------------------- #
# Auth routes
# --------------------------------------------------------------------------- #

@app.route("/login", methods=["GET", "POST"])
async def login():
    if current_user():
        return redirect(url_for("index"))

    if request.method == "POST":
        form = await request.form
        name = (form.get("name") or "").strip()
        password = form.get("password") or ""

        if not name or not password:
            flash("Bitte Name und Passwort eingeben.", "error")
            return await render_template("login.html", name=name)

        user = await get_user_by_name(name)

        # Always run a hash comparison to keep timing roughly constant even
        # when the user does not exist.
        stored_hash = (
            user["password_hash"].encode("utf-8") if user else b"$2b$12$" + b"0" * 53
        )
        ok = bcrypt.checkpw(password.encode("utf-8"), stored_hash)

        if not user or not ok:
            flash("Name oder Passwort ist falsch.", "error")
            return await render_template("login.html", name=name)

        session.clear()
        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        session["user_role"] = user["role"]
        session["must_change_password"] = user["must_change_password"]

        logger.info("User %s logged in", user["name"])

        if user["must_change_password"]:
            return redirect(url_for("change_password"))
        return redirect(url_for("index"))

    return await render_template("login.html", name="")


@app.route("/logout", methods=["POST"])
async def logout():
    session.clear()
    flash("Du wurdest abgemeldet.", "success")
    return redirect(url_for("login"))


@app.route("/change-password", methods=["GET", "POST"])
@login_required
async def change_password():
    user = current_user()

    if request.method == "POST":
        form = await request.form
        current_password = form.get("current_password") or ""
        new_password = form.get("new_password") or ""
        confirm_password = form.get("confirm_password") or ""

        if not current_password or not new_password or not confirm_password:
            flash("Bitte alle Felder ausfüllen.", "error")
            return await render_template("change_password.html")

        if new_password != confirm_password:
            flash("Die neuen Passwörter stimmen nicht überein.", "error")
            return await render_template("change_password.html")

        if len(new_password) < 4:
            flash("Das neue Passwort muss mindestens 4 Zeichen lang sein.", "error")
            return await render_template("change_password.html")

        if new_password == DEFAULT_PASSWORD:
            flash("Das neue Passwort darf nicht 1234 sein.", "error")
            return await render_template("change_password.html")

        full_user = await get_user_by_id(user["id"])
        if not full_user:
            session.clear()
            return redirect(url_for("login"))

        if not bcrypt.checkpw(
            current_password.encode("utf-8"),
            full_user["password_hash"].encode("utf-8"),
        ):
            flash("Das aktuelle Passwort ist falsch.", "error")
            return await render_template("change_password.html")

        await set_user_password(user["id"], new_password)
        session["must_change_password"] = False
        logger.info("User %s changed their password", user["name"])
        flash("Passwort erfolgreich geändert.", "success")

        return redirect(url_for("index"))

    return await render_template("change_password.html")


# --------------------------------------------------------------------------- #
# Diary routes (protected)
# --------------------------------------------------------------------------- #

@app.route("/", methods=["GET"])
@login_required
@force_password_change
async def index():
    summary = await get_dashboard_summary()
    entries = await get_recent_entries()
    return await render_template("index.html", summary=summary, entries=entries)


@app.route("/new", methods=["GET", "POST"])
@login_required
@force_password_change
@role_required("ADMIN", "EDITOR")
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
@login_required
@force_password_change
@role_required("ADMIN", "EDITOR")
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
@login_required
@force_password_change
@role_required("ADMIN", "EDITOR")
async def delete_entry_route(entry_id: int):
    entry = await get_entry_by_id(entry_id)
    if entry is None:
        flash("Eintrag nicht gefunden.", "error")
        return redirect(url_for("index"))

    await delete_entry(entry_id)
    flash("Eintrag gelöscht.", "success")
    return redirect(url_for("index"))


# --------------------------------------------------------------------------- #
# User management routes (admin only)
# --------------------------------------------------------------------------- #

@app.route("/users", methods=["GET"])
@login_required
@force_password_change
@role_required("ADMIN")
async def users():
    users_list = await list_users()
    return await render_template("users.html", users=users_list)


@app.route("/users", methods=["POST"])
@login_required
@force_password_change
@role_required("ADMIN")
async def create_user_route():
    form = await request.form
    name = (form.get("name") or "").strip()
    role = (form.get("role") or "VIEWER").upper()

    if not name:
        flash("Bitte einen Namen eingeben.", "error")
        return redirect(url_for("users"))

    if role not in ("ADMIN", "EDITOR", "VIEWER"):
        flash("Ungültige Rolle.", "error")
        return redirect(url_for("users"))

    try:
        await create_user(name, role)
        flash(
            f"Nutzer '{name}' angelegt. Standard-Passwort: {DEFAULT_PASSWORD}. "
            f"Beim ersten Login muss es geändert werden.",
            "success",
        )
    except psycopg.IntegrityError:
        flash("Ein Nutzer mit diesem Namen existiert bereits.", "error")

    return redirect(url_for("users"))


@app.route("/users/<int:user_id>/role", methods=["POST"])
@login_required
@force_password_change
@role_required("ADMIN")
async def update_user_role_route(user_id: int):
    form = await request.form
    role = (form.get("role") or "VIEWER").upper()

    if role not in ("ADMIN", "EDITOR", "VIEWER"):
        flash("Ungültige Rolle.", "error")
        return redirect(url_for("users"))

    target = await get_user_by_id(user_id)
    if target is None:
        flash("Nutzer nicht gefunden.", "error")
        return redirect(url_for("users"))

    # Prevent the admin from stripping their own admin rights.
    user = current_user()
    if target["id"] == user["id"] and role != "ADMIN":
        flash("Du kannst dir nicht selbst die Admin-Rechte entziehen.", "error")
        return redirect(url_for("users"))

    await update_user_role(user_id, role)
    flash(f"Rolle von '{target['name']}' auf {role} geändert.", "success")
    return redirect(url_for("users"))


@app.route("/users/<int:user_id>/reset-password", methods=["POST"])
@login_required
@force_password_change
@role_required("ADMIN")
async def reset_user_password_route(user_id: int):
    target = await get_user_by_id(user_id)
    if target is None:
        flash("Nutzer nicht gefunden.", "error")
        return redirect(url_for("users"))

    await reset_user_password(user_id)
    flash(
        f"Passwort von '{target['name']}' auf {DEFAULT_PASSWORD} zurückgesetzt. "
        f"Es muss beim nächsten Login geändert werden.",
        "success",
    )
    return redirect(url_for("users"))


@app.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
@force_password_change
@role_required("ADMIN")
async def delete_user_route(user_id: int):
    target = await get_user_by_id(user_id)
    if target is None:
        flash("Nutzer nicht gefunden.", "error")
        return redirect(url_for("users"))

    user = current_user()
    if target["id"] == user["id"]:
        flash("Du kannst dich nicht selbst löschen.", "error")
        return redirect(url_for("users"))

    await delete_user(user_id)
    flash(f"Nutzer '{target['name']}' gelöscht.", "success")
    return redirect(url_for("users"))


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
