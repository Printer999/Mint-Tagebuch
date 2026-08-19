import asyncio
import functools
import logging
import os
from pathlib import Path
from urllib.parse import quote_plus

import bcrypt
import psycopg
from psycopg.rows import dict_row
from quart import (
    Quart,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

BASE_DIR = Path(__file__).resolve().parent
LOG_PATH = BASE_DIR / "mint_tagebuch.log"
DEFAULT_PASSWORD = "1234"
OWNER_NAME = "TheHacker"
VALID_ROLES = ("OWNER", "ADMIN", "EDITOR", "VIEWER")
EDIT_ROLES = ("OWNER", "ADMIN", "EDITOR")
ADMIN_ROLES = ("OWNER", "ADMIN")


def _normalize_database_url(raw: str) -> str:
    raw = (raw or "").strip().strip('"').strip("'")

    # Tolerate a common Render setup mistake where the value itself is pasted as
    # "DATABASE_URL=postgresql://...".
    if raw.upper().startswith("DATABASE_URL="):
        raw = raw.split("=", 1)[1].strip().strip('"').strip("'")

    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]

    return raw


def _build_database_url() -> str:
    raw = _normalize_database_url(os.getenv("DATABASE_URL", ""))
    if raw:
        return raw

    host = (os.getenv("PGHOST") or "").strip()
    port = (os.getenv("PGPORT") or "5432").strip()
    database = (os.getenv("PGDATABASE") or "").strip()
    user = (os.getenv("PGUSER") or "").strip()
    password = os.getenv("PGPASSWORD") or ""

    if host and database and user:
        return (
            f"postgresql://{quote_plus(user)}:{quote_plus(password)}"
            f"@{host}:{port}/{quote_plus(database)}"
        )

    raise RuntimeError(
        "Keine PostgreSQL-Verbindung konfiguriert. Setze auf Render DATABASE_URL "
        "oder PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD."
    )


DATABASE_URL = _build_database_url()
SECRET_KEY = os.getenv("SECRET_KEY", "mint-week-dev-secret-change-me")

app = Quart(
    __name__,
    static_folder=str(BASE_DIR / "static"),
    template_folder=str(BASE_DIR / "templates"),
)
app.secret_key = SECRET_KEY


def configure_logger() -> logging.Logger:
    logger = logging.getLogger("mint_tagebuch")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        try:
            file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
            file_handler.setFormatter(
                logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            )
            logger.addHandler(file_handler)
        except OSError:
            # A read-only filesystem must not prevent the web service from starting.
            pass

        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        )
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
            result = None
            if fetchall:
                result = cursor.fetchall()
            elif fetchone:
                result = cursor.fetchone()
            else:
                result = getattr(cursor, "lastrowid", None)

            if commit:
                conn.commit()
            return result
        finally:
            conn.close()

    return await asyncio.to_thread(_execute)


async def init_db() -> None:
    def _init():
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
                        CHECK (role IN ('OWNER', 'ADMIN', 'EDITOR', 'VIEWER')),
                    must_change_password BOOLEAN NOT NULL DEFAULT TRUE,
                    locked BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # Migrate databases created by older app versions.
            conn.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS locked "
                "BOOLEAN NOT NULL DEFAULT FALSE"
            )

            # Older versions only allowed ADMIN/EDITOR/VIEWER. Remove the old
            # role CHECK constraint without relying on its automatically chosen name.
            conn.execute(
                """
                DO $$
                DECLARE item record;
                BEGIN
                    FOR item IN
                        SELECT conname
                        FROM pg_constraint
                        WHERE conrelid = 'users'::regclass
                          AND contype = 'c'
                          AND pg_get_constraintdef(oid) ILIKE '%role%'
                    LOOP
                        EXECUTE format(
                            'ALTER TABLE users DROP CONSTRAINT %I', item.conname
                        );
                    END LOOP;
                END $$;
                """
            )

            # OWNER is reserved for exactly one account.
            conn.execute(
                "UPDATE users SET role = 'ADMIN' "
                "WHERE role = 'OWNER' AND name <> %s",
                (OWNER_NAME,),
            )
            conn.execute(
                "UPDATE users SET locked = FALSE WHERE name = %s",
                (OWNER_NAME,),
            )

            conn.execute(
                """
                ALTER TABLE users
                ADD CONSTRAINT users_role_check
                CHECK (role IN ('OWNER', 'ADMIN', 'EDITOR', 'VIEWER'))
                """
            )
            conn.commit()

    await asyncio.to_thread(_init)
    logger.info("PostgreSQL database initialized (entries + users + owner migration)")


async def seed_admin() -> None:
    existing = await run_db_query(
        "SELECT id FROM users WHERE name = %s",
        (OWNER_NAME,),
        fetchone=True,
    )
    if existing:
        return

    password_hash = bcrypt.hashpw(
        DEFAULT_PASSWORD.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")
    await run_db_query(
        """
        INSERT INTO users
            (name, password_hash, role, must_change_password, locked)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (OWNER_NAME, password_hash, "ADMIN", True, False),
        commit=True,
    )
    logger.info("Seeded protected account %s with default password", OWNER_NAME)


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
        "SELECT * FROM entries WHERE id = %s",
        (entry_id,),
        fetchone=True,
    )


async def save_entry(
    entry_date: str,
    high_light: str,
    low_light: str,
    rating: int,
    notes: str,
):
    await run_db_query(
        """
        INSERT INTO entries (entry_date, high_light, low_light, rating, notes)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (entry_date, high_light, low_light, rating, notes),
        commit=True,
    )
    logger.info("New diary entry saved for %s", entry_date)


async def update_entry(
    entry_id: int,
    entry_date: str,
    high_light: str,
    low_light: str,
    rating: int,
    notes: str,
):
    await run_db_query(
        """
        UPDATE entries
        SET entry_date = %s,
            high_light = %s,
            low_light = %s,
            rating = %s,
            notes = %s
        WHERE id = %s
        """,
        (entry_date, high_light, low_light, rating, notes, entry_id),
        commit=True,
    )
    logger.info("Diary entry %s updated", entry_id)


async def delete_entry(entry_id: int):
    await run_db_query(
        "DELETE FROM entries WHERE id = %s",
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
        SELECT id, name, password_hash, role, must_change_password, locked, created_at
        FROM users
        WHERE name = %s
        """,
        (name,),
        fetchone=True,
    )


async def get_user_by_id(user_id: int):
    return await run_db_query(
        """
        SELECT id, name, password_hash, role, must_change_password, locked, created_at
        FROM users
        WHERE id = %s
        """,
        (user_id,),
        fetchone=True,
    )


async def list_users():
    return await run_db_query(
        """
        SELECT id, name, role, must_change_password, locked, created_at
        FROM users
        ORDER BY
            CASE role
                WHEN 'OWNER' THEN 0
                WHEN 'ADMIN' THEN 1
                WHEN 'EDITOR' THEN 2
                ELSE 3
            END,
            created_at ASC
        """,
        fetchall=True,
    )


async def create_user(name: str, role: str) -> None:
    password_hash = bcrypt.hashpw(
        DEFAULT_PASSWORD.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")
    await run_db_query(
        """
        INSERT INTO users
            (name, password_hash, role, must_change_password, locked)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (name, password_hash, role, True, False),
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
    user_id = session.get("user_id")
    if not user_id:
        return None
    return {
        "id": user_id,
        "name": session.get("user_name"),
        "role": session.get("user_role"),
        "must_change_password": session.get("must_change_password", False),
        "locked": session.get("locked", False),
    }


def login_required(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        if not current_user():
            await flash("Bitte melde dich an, um diese Seite zu sehen.", "error")
            return redirect(url_for("login"))
        return await func(*args, **kwargs)

    return wrapper


def role_required(*roles):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                await flash("Bitte melde dich an.", "error")
                return redirect(url_for("login"))
            if user["role"] not in roles:
                await flash("Du hast keine Berechtigung für diese Aktion.", "error")
                return redirect(url_for("index"))
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def owner_required(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            await flash("Bitte melde dich an.", "error")
            return redirect(url_for("login"))
        if user["role"] != "OWNER" or user["name"] != OWNER_NAME:
            await flash("Dieser Bereich ist ausschließlich für den Owner.", "error")
            return redirect(url_for("index"))
        return await func(*args, **kwargs)

    return wrapper


def force_password_change(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        user = current_user()
        if user and user.get("must_change_password"):
            return redirect(url_for("change_password"))
        return await func(*args, **kwargs)

    return wrapper


# --------------------------------------------------------------------------- #
# Lifecycle + session synchronization
# --------------------------------------------------------------------------- #

@app.before_serving
async def before_serving():
    await init_db()
    await seed_admin()
    logger.info("Mint week app started")


@app.before_request
async def sync_logged_in_user():
    if request.endpoint == "static":
        return None

    user_id = session.get("user_id")
    if not user_id:
        return None

    db_user = await get_user_by_id(user_id)
    if not db_user:
        session.clear()
        if request.endpoint not in ("login", "logout"):
            await flash("Dein Nutzerkonto existiert nicht mehr.", "error")
            return redirect(url_for("login"))
        return None

    # OWNER may only ever be TheHacker. Repair impossible/stale states safely.
    if db_user["role"] == "OWNER" and db_user["name"] != OWNER_NAME:
        await update_user_role(db_user["id"], "ADMIN")
        db_user = await get_user_by_id(user_id)

    if db_user["locked"] and db_user["name"] != OWNER_NAME:
        session.clear()
        if request.endpoint != "login":
            await flash("Dein Konto ist gesperrt.", "error")
            return redirect(url_for("login"))
        return None

    session["user_name"] = db_user["name"]
    session["user_role"] = db_user["role"]
    session["must_change_password"] = bool(db_user["must_change_password"])
    session["locked"] = bool(db_user["locked"])
    return None


@app.context_processor
def inject_user():
    user = current_user()
    role = user["role"] if user else None
    return {
        "current_user": user,
        "is_owner": role == "OWNER",
        "is_admin": role in ADMIN_ROLES,
        "is_editor": role in EDIT_ROLES,
        "is_viewer": role == "VIEWER",
        "can_edit": role in EDIT_ROLES,
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
            await flash("Bitte Name und Passwort eingeben.", "error")
            return await render_template("login.html", name=name)

        user = await get_user_by_name(name)
        stored_hash = (
            user["password_hash"].encode("utf-8")
            if user
            else b"$2b$12$" + b"0" * 53
        )
        ok = bcrypt.checkpw(password.encode("utf-8"), stored_hash)

        if not user or not ok:
            await flash("Name oder Passwort ist falsch.", "error")
            return await render_template("login.html", name=name)

        if user["locked"] and user["name"] != OWNER_NAME:
            await flash("Dieses Konto ist gesperrt.", "error")
            return await render_template("login.html", name=name)

        is_default_password = password == DEFAULT_PASSWORD
        if bool(user["must_change_password"]) != is_default_password:
            await run_db_query(
                "UPDATE users SET must_change_password = %s WHERE id = %s",
                (is_default_password, user["id"]),
                commit=True,
            )

        session.clear()
        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        session["user_role"] = user["role"]
        session["must_change_password"] = is_default_password
        session["locked"] = bool(user["locked"])

        logger.info("User %s logged in with role %s", user["name"], user["role"])

        if is_default_password:
            return redirect(url_for("change_password"))
        return redirect(url_for("index"))

    return await render_template("login.html", name="")


@app.route("/logout", methods=["POST"])
async def logout():
    session.clear()
    await flash("Du wurdest abgemeldet.", "success")
    return redirect(url_for("login"))


@app.route("/change-password", methods=["GET", "POST"])
@login_required
async def change_password():
    user = current_user()
    ctx = {"current_user": None, "user_name": user["name"]}

    if request.method == "POST":
        form = await request.form
        current_password = form.get("current_password") or ""
        new_password = form.get("new_password") or ""
        confirm_password = form.get("confirm_password") or ""

        if not current_password or not new_password or not confirm_password:
            await flash("Bitte alle Felder ausfüllen.", "error")
            return await render_template("change_password.html", **ctx)

        if new_password != confirm_password:
            await flash("Die neuen Passwörter stimmen nicht überein.", "error")
            return await render_template("change_password.html", **ctx)

        if len(new_password) < 4:
            await flash("Das neue Passwort muss mindestens 4 Zeichen lang sein.", "error")
            return await render_template("change_password.html", **ctx)

        if new_password == DEFAULT_PASSWORD:
            await flash("Das neue Passwort darf nicht 1234 sein.", "error")
            return await render_template("change_password.html", **ctx)

        full_user = await get_user_by_id(user["id"])
        if not full_user:
            session.clear()
            return redirect(url_for("login"))

        if not bcrypt.checkpw(
            current_password.encode("utf-8"),
            full_user["password_hash"].encode("utf-8"),
        ):
            await flash("Das aktuelle Passwort ist falsch.", "error")
            return await render_template("change_password.html", **ctx)

        await set_user_password(user["id"], new_password)
        session["must_change_password"] = False
        logger.info("User %s changed their password", user["name"])
        await flash("Passwort erfolgreich geändert.", "success")
        return redirect(url_for("index"))

    return await render_template("change_password.html", **ctx)


# --------------------------------------------------------------------------- #
# Diary routes
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
@role_required(*EDIT_ROLES)
async def create_entry():
    if request.method == "POST":
        form = await request.form
        entry_date = (form.get("entry_date") or "").strip()
        high_light = (form.get("high_light") or "").strip() or "-"
        low_light = (form.get("low_light") or "").strip() or "-"
        notes = (form.get("notes") or "").strip() or "-"

        try:
            rating = int(form.get("rating", 3) or 3)
        except (TypeError, ValueError):
            rating = 3
        rating = min(5, max(1, rating))

        if not entry_date:
            await flash("Bitte wähle ein Datum aus.", "error")
            return await render_template("create_entry.html")

        try:
            await save_entry(entry_date, high_light, low_light, rating, notes)
            await flash("Eintrag erfolgreich gespeichert.", "success")
        except psycopg.IntegrityError:
            await flash("Für dieses Datum existiert bereits ein Eintrag.", "error")
            return await render_template("create_entry.html")

        return redirect(url_for("index"))

    return await render_template("create_entry.html")


@app.route("/entries/<int:entry_id>/edit", methods=["GET", "POST"])
@login_required
@force_password_change
@role_required(*EDIT_ROLES)
async def edit_entry(entry_id: int):
    entry = await get_entry_by_id(entry_id)
    if entry is None:
        await flash("Eintrag nicht gefunden.", "error")
        return redirect(url_for("index"))

    if request.method == "POST":
        form = await request.form
        entry_date = (form.get("entry_date") or "").strip()
        high_light = (form.get("high_light") or "").strip() or "-"
        low_light = (form.get("low_light") or "").strip() or "-"
        notes = (form.get("notes") or "").strip() or "-"

        try:
            rating = int(form.get("rating", entry["rating"]) or entry["rating"])
        except (TypeError, ValueError):
            rating = int(entry["rating"])
        rating = min(5, max(1, rating))

        if not entry_date:
            await flash("Bitte wähle ein Datum aus.", "error")
            return await render_template("edit_entry.html", entry=entry)

        try:
            await update_entry(
                entry_id, entry_date, high_light, low_light, rating, notes
            )
            await flash("Eintrag erfolgreich bearbeitet.", "success")
        except psycopg.IntegrityError:
            await flash(
                "Dieses Datum ist bereits vergeben. Bitte wähle ein anderes Datum.",
                "error",
            )
            return await render_template("edit_entry.html", entry=entry)

        return redirect(url_for("index"))

    return await render_template("edit_entry.html", entry=entry)


@app.route("/entries/<int:entry_id>/delete", methods=["POST"])
@login_required
@force_password_change
@role_required(*EDIT_ROLES)
async def delete_entry_route(entry_id: int):
    entry = await get_entry_by_id(entry_id)
    if entry is None:
        await flash("Eintrag nicht gefunden.", "error")
        return redirect(url_for("index"))

    await delete_entry(entry_id)
    await flash("Eintrag gelöscht.", "success")
    return redirect(url_for("index"))


# --------------------------------------------------------------------------- #
# User management routes: ADMIN + OWNER
# --------------------------------------------------------------------------- #

@app.route("/users", methods=["GET"])
@login_required
@force_password_change
@role_required(*ADMIN_ROLES)
async def users():
    try:
        users_list = await list_users()
    except Exception as exc:
        logger.exception("list_users failed: %s", exc)
        await flash(
            "Die Nutzerliste konnte nicht geladen werden. Details: " + str(exc),
            "error",
        )
        return redirect(url_for("index"))

    return await render_template("users.html", users=users_list)


@app.route("/users", methods=["POST"])
@login_required
@force_password_change
@role_required(*ADMIN_ROLES)
async def create_user_route():
    form = await request.form
    name = (form.get("name") or "").strip()
    role = (form.get("role") or "VIEWER").upper()

    if not name:
        await flash("Bitte einen Namen eingeben.", "error")
        return redirect(url_for("users"))

    if role not in ("ADMIN", "EDITOR", "VIEWER"):
        await flash("Ungültige Rolle.", "error")
        return redirect(url_for("users"))

    if name == OWNER_NAME:
        await flash(f"Der Name '{OWNER_NAME}' ist für den Owner reserviert.", "error")
        return redirect(url_for("users"))

    try:
        await create_user(name, role)
        await flash(
            f"Nutzer '{name}' angelegt. Standard-Passwort: {DEFAULT_PASSWORD}. "
            "Beim ersten Login muss es geändert werden.",
            "success",
        )
    except psycopg.IntegrityError:
        await flash("Ein Nutzer mit diesem Namen existiert bereits.", "error")

    return redirect(url_for("users"))


@app.route("/users/<int:user_id>/role", methods=["POST"])
@login_required
@force_password_change
@role_required(*ADMIN_ROLES)
async def update_user_role_route(user_id: int):
    form = await request.form
    role = (form.get("role") or "VIEWER").upper()

    if role not in ("ADMIN", "EDITOR", "VIEWER"):
        await flash("Ungültige Rolle.", "error")
        return redirect(url_for("users"))

    target = await get_user_by_id(user_id)
    if target is None:
        await flash("Nutzer nicht gefunden.", "error")
        return redirect(url_for("users"))

    if target["name"] == OWNER_NAME or target["role"] == "OWNER":
        await flash("Der Owner-Rang kann hier nicht verändert werden.", "error")
        return redirect(url_for("users"))

    user = current_user()
    if target["id"] == user["id"] and role not in ADMIN_ROLES:
        await flash("Du kannst dir nicht selbst die Admin-Rechte entziehen.", "error")
        return redirect(url_for("users"))

    await update_user_role(user_id, role)
    await flash(f"Rolle von '{target['name']}' auf {role} geändert.", "success")
    return redirect(url_for("users"))


@app.route("/users/<int:user_id>/reset-password", methods=["POST"])
@login_required
@force_password_change
@role_required(*ADMIN_ROLES)
async def reset_user_password_route(user_id: int):
    target = await get_user_by_id(user_id)
    if target is None:
        await flash("Nutzer nicht gefunden.", "error")
        return redirect(url_for("users"))

    if target["name"] == OWNER_NAME or target["role"] == "OWNER":
        await flash("Das Owner-Passwort kann hier nicht zurückgesetzt werden.", "error")
        return redirect(url_for("users"))

    await reset_user_password(user_id)
    await flash(
        f"Passwort von '{target['name']}' auf {DEFAULT_PASSWORD} zurückgesetzt. "
        "Es muss beim nächsten Login geändert werden.",
        "success",
    )
    return redirect(url_for("users"))


@app.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
@force_password_change
@role_required(*ADMIN_ROLES)
async def delete_user_route(user_id: int):
    target = await get_user_by_id(user_id)
    if target is None:
        await flash("Nutzer nicht gefunden.", "error")
        return redirect(url_for("users"))

    if target["name"] == OWNER_NAME or target["role"] == "OWNER":
        await flash("Der Owner kann nicht gelöscht werden.", "error")
        return redirect(url_for("users"))

    user = current_user()
    if target["id"] == user["id"]:
        await flash("Du kannst dich nicht selbst löschen.", "error")
        return redirect(url_for("users"))

    await delete_user(user_id)
    await flash(f"Nutzer '{target['name']}' gelöscht.", "success")
    return redirect(url_for("users"))


@app.route("/users/become-owner", methods=["POST"])
@login_required
@force_password_change
@role_required("ADMIN")
async def become_owner():
    user = current_user()

    if user["name"] != OWNER_NAME:
        await flash("Nur TheHacker kann Owner werden.", "error")
        return redirect(url_for("users"))

    try:
        # Defense in depth: ensure there can never be a second OWNER.
        await run_db_query(
            "UPDATE users SET role = 'ADMIN' WHERE role = 'OWNER' AND name <> %s",
            (OWNER_NAME,),
            commit=True,
        )
        await run_db_query(
            "UPDATE users SET role = 'OWNER', locked = FALSE WHERE id = %s AND name = %s",
            (user["id"], OWNER_NAME),
            commit=True,
        )
    except Exception as exc:
        logger.exception("Owner promotion failed: %s", exc)
        await flash("Owner-Rang konnte nicht gesetzt werden: " + str(exc), "error")
        return redirect(url_for("users"))

    session["user_role"] = "OWNER"
    session["locked"] = False
    await flash("Du hast jetzt den Rang OWNER.", "success")
    return redirect(url_for("owner_page"))


# --------------------------------------------------------------------------- #
# Owner routes
# --------------------------------------------------------------------------- #

@app.route("/owner", methods=["GET"])
@login_required
@force_password_change
@owner_required
async def owner_page():
    users_list = await list_users()
    return await render_template("owner.html", users=users_list)


@app.route("/owner/users/<int:user_id>/edit", methods=["POST"])
@login_required
@force_password_change
@owner_required
async def owner_edit_user(user_id: int):
    target = await get_user_by_id(user_id)
    if target is None:
        await flash("Nutzer nicht gefunden.", "error")
        return redirect(url_for("owner_page"))

    if target["name"] == OWNER_NAME or target["role"] == "OWNER":
        await flash("Der Owner-Account ist geschützt.", "error")
        return redirect(url_for("owner_page"))

    form = await request.form
    name = (form.get("name") or "").strip()
    role = (form.get("role") or target["role"]).upper()
    new_password = form.get("new_password") or ""
    locked = "locked" in form

    if not name:
        await flash("Der Nutzername darf nicht leer sein.", "error")
        return redirect(url_for("owner_page"))

    if name == OWNER_NAME:
        await flash(f"Der Name '{OWNER_NAME}' ist für den Owner reserviert.", "error")
        return redirect(url_for("owner_page"))

    if role not in ("ADMIN", "EDITOR", "VIEWER"):
        await flash("Ungültige Rolle.", "error")
        return redirect(url_for("owner_page"))

    if new_password and len(new_password) < 4:
        await flash("Das neue Passwort muss mindestens 4 Zeichen lang sein.", "error")
        return redirect(url_for("owner_page"))

    try:
        await run_db_query(
            "UPDATE users SET name = %s, role = %s, locked = %s WHERE id = %s",
            (name, role, locked, user_id),
            commit=True,
        )
        if new_password:
            await set_user_password(user_id, new_password)
    except psycopg.IntegrityError:
        await flash("Dieser Nutzername ist bereits vergeben.", "error")
        return redirect(url_for("owner_page"))

    await flash(f"Nutzer '{name}' wurde aktualisiert.", "success")
    return redirect(url_for("owner_page"))


@app.route("/owner/password", methods=["POST"])
@login_required
@force_password_change
@owner_required
async def owner_change_owner_password():
    form = await request.form
    new_password = form.get("new_password") or ""
    confirm_password = form.get("confirm_password") or ""

    if len(new_password) < 4:
        await flash("Das neue Owner-Passwort muss mindestens 4 Zeichen lang sein.", "error")
        return redirect(url_for("owner_page"))

    if new_password != confirm_password:
        await flash("Die Passwörter stimmen nicht überein.", "error")
        return redirect(url_for("owner_page"))

    if new_password == DEFAULT_PASSWORD:
        await flash("Das Owner-Passwort darf nicht 1234 sein.", "error")
        return redirect(url_for("owner_page"))

    await set_user_password(current_user()["id"], new_password)
    session["must_change_password"] = False
    await flash("Owner-Passwort wurde geändert.", "success")
    return redirect(url_for("owner_page"))


@app.route("/owner/delete-entries", methods=["POST"])
@login_required
@force_password_change
@owner_required
async def owner_delete_entries():
    await run_db_query("DELETE FROM entries", commit=True)
    logger.warning("Owner deleted all diary entries")
    await flash("Alle Tagebucheinträge wurden gelöscht.", "success")
    return redirect(url_for("owner_page"))


@app.route("/owner/delete-other-users", methods=["POST"])
@login_required
@force_password_change
@owner_required
async def owner_delete_other_users():
    await run_db_query(
        "DELETE FROM users WHERE name <> %s",
        (OWNER_NAME,),
        commit=True,
    )
    logger.warning("Owner deleted all other users")
    await flash("Alle anderen Nutzer wurden gelöscht.", "success")
    return redirect(url_for("owner_page"))


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
