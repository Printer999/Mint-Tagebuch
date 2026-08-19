import asyncio
import functools
import logging
import os
from pathlib import Path

import bcrypt
import psycopg
from psycopg import sql
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

# Render sets DATABASE_URL for its managed PostgreSQL. Locally we fall back to
# the development database. The URL is normalized so psycopg3 accepts it.
_DEFAULT_DATABASE_URL = "postgresql://localhost/mint_tagebuch"

def _normalize_database_url(raw: str) -> str:
    """Render ships `postgres://` URLs which psycopg3 rejects; convert to
    `postgresql://`."""
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]
    return raw

DATABASE_URL = _normalize_database_url(
    os.getenv("DATABASE_URL", _DEFAULT_DATABASE_URL)
)

# A stable secret key is required for signed session cookies.
SECRET_KEY = os.getenv("SECRET_KEY", "mint-week-dev-secret-change-me")

# The default password assigned to every newly created account.
DEFAULT_PASSWORD = "1234"

app = Quart(
    __name__, 
    static_folder=str(BASE_DIR / "static"),
    template_folder=str(BASE_DIR / "templates")
)
app.secret_key = SECRET_KEY


def configure_logger() -> logging.Logger:
    logger = logging.getLogger("mint_tagebuch")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

        # Console logging always works on Render. File logging is optional, as
        # some deployment environments mount the application directory read-only.
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

        try:
            file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        except OSError:
            logger.warning("Log file %s is not writable; using console logging only.", LOG_PATH)
        else:
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

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
                    CHECK (role IN ('OWNER', 'ADMIN', 'EDITOR', 'VIEWER')),
                must_change_password BOOLEAN NOT NULL DEFAULT TRUE,
                locked BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # Migration fuer bereits bestehende Installationen.
        conn.execute(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS locked BOOLEAN NOT NULL DEFAULT FALSE"
        )

        # Aeltere Versionen koennen einen anders benannten CHECK-Constraint
        # besitzen, der OWNER noch nicht erlaubt. Deshalb werden nur die
        # CHECK-Constraints entfernt, die tatsaechlich die Spalte `role`
        # betreffen, und anschliessend ein eindeutiger Constraint angelegt.
        role_constraints = conn.execute(
            """
            SELECT DISTINCT c.conname
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            JOIN pg_attribute a
              ON a.attrelid = t.oid
             AND a.attnum = ANY(c.conkey)
            WHERE c.contype = 'c'
              AND t.relname = 'users'
              AND n.nspname = current_schema()
              AND a.attname = 'role'
            """
        ).fetchall()
        for row in role_constraints:
            conn.execute(
                sql.SQL("ALTER TABLE users DROP CONSTRAINT {}").format(
                    sql.Identifier(row["conname"])
                )
            )

        conn.execute(
            "ALTER TABLE users ADD CONSTRAINT users_role_check "
            "CHECK (role IN ('OWNER', 'ADMIN', 'EDITOR', 'VIEWER'))"
        )

        # OWNER darf nur TheHacker sein. Eventuelle alte/falsche OWNER-Rollen
        # werden beim Start sicher auf ADMIN zurueckgesetzt.
        conn.execute(
            "UPDATE users SET role = 'ADMIN' "
            "WHERE role = 'OWNER' AND name <> 'TheHacker'"
        )
        conn.commit()
    logger.info("PostgreSQL database initialized (entries + users)")

async def seed_admin() -> None:
    """Stellt sicher, dass der Admin-Account 'TheHacker' existiert.

    Wird NUR beim allerersten Start ausgefuehrt (wenn der Admin noch nicht in
    der Datenbank steht). Bei jedem spaeteren Neustart tut diese Funktion
    GAR NICHTS - sie ueberschreibt weder das Passwort noch das
    `must_change_password`-Flag. Ein einmal geaendertes Passwort und ein
    einmal auf FALSE gesetztes Flag bleiben also ueber Neustarts hinweg
    unveraendert erhalten.
    """
    existing = await run_db_query(
        "SELECT id FROM users WHERE name = %s",
        ("TheHacker",),
        fetchone=True,
    )
    if existing:
        # Admin existiert bereits -> nichts tun. Insbesondere wird
        # must_change_password NICHT zurueckgesetzt. Ein einmal geaendertes
        # Passwort bleibt ueber Neustarts hinweg erhalten.
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
        "SELECT * FROM entries WHERE id = %s",
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
        FROM users WHERE name = %s
        """,
        (name,),
        fetchone=True,
    )

async def get_user_by_id(user_id: int):
    return await run_db_query(
        """
        SELECT id, name, password_hash, role, must_change_password, locked, created_at
        FROM users WHERE id = %s
        """,
        (user_id,),
        fetchone=True,
    )

async def list_users():
    return await run_db_query(
        """
        SELECT id, name, role, must_change_password, locked, created_at
        FROM users ORDER BY created_at ASC
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

def force_password_change(func):
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


@app.before_request
async def refresh_logged_in_user():
    """Keep the signed session synchronized with the current database row.

    This is especially important after changing ADMIN to OWNER: navigation and
    role checks update immediately. Deleted or locked accounts also lose access
    without waiting for a fresh login. Database outages are logged but do not
    destroy an otherwise valid session.
    """
    if request.endpoint == "static":
        return None

    user_id = session.get("user_id")
    if not user_id:
        return None

    try:
        db_user = await get_user_by_id(user_id)
    except Exception as exc:
        logger.exception("Could not refresh session user %s: %s", user_id, exc)
        return None

    if not db_user:
        session.clear()
        await flash("Dein Konto existiert nicht mehr. Bitte melde dich erneut an.", "error")
        if request.endpoint != "login":
            return redirect(url_for("login"))
        return None

    if bool(db_user.get("locked")):
        session.clear()
        await flash("Dieser Account ist gesperrt. Bitte wende dich an den Owner.", "error")
        if request.endpoint != "login":
            return redirect(url_for("login"))
        return None

    session["user_name"] = db_user["name"]
    session["user_role"] = db_user["role"]
    session["must_change_password"] = bool(db_user["must_change_password"])
    return None

@app.context_processor
def inject_user():
    user = current_user()
    role = user["role"] if user else None
    return {
        "current_user": user,
        "is_owner": role == "OWNER",
        "is_admin": role in ("OWNER", "ADMIN"),
        "is_editor": role in ("OWNER", "ADMIN", "EDITOR"),
        "is_viewer": role == "VIEWER",
        "can_edit": role in ("OWNER", "ADMIN", "EDITOR"),
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
            user["password_hash"].encode("utf-8") if user else b"$2b$12$" + b"0" * 53
        )
        ok = bcrypt.checkpw(password.encode("utf-8"), stored_hash)

        if not user or not ok:
            await flash("Name oder Passwort ist falsch.", "error")
            return await render_template("login.html", name=name)
        
        if user.get("locked"):
            await flash("Dieser Account ist gesperrt. Bitte wende dich an den Owner.", "error")
            return await render_template("login.html", name=name)

        # Passwort-Wechsel NUR erzwingen, wenn das eingegebene Passwort
        # tatsächlich das Standard-Passwort "1234" ist. Es wird bewusst NICHT
        # auf das `must_change_password`-Flag in der Datenbank vertraut, da
        # dieses (z. B. nach Render-Neustarts, DB-Pausen oder abgebrochenen
        # Passwort-Wechseln) aus der Sync geraten kann. So wird ein bereits
        # geändertes Passwort nie fälschlicherweise erneut zum Ändern
        # aufgefordert.
        is_default_password = (password == DEFAULT_PASSWORD)

        # Das DB-Flag mit der Realität synchronisieren, damit die
        # Nutzerverwaltungs-Anzeige korrekt bleibt (Passwort offen / Aktiv).
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

        logger.info(
            "User %s logged in (default password: %s)",
            user["name"],
            is_default_password,
        )

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

    # Render context: `current_user` wird bewusst auf None gesetzt, damit die
    # base.html das nackte Auth-Layout (ohne Topbar/Navigation) rendert. Der
    # User ist weiterhin in der Session eingeloggt; nur die Template-Variable
    # wird überschrieben. `user_name` wird separat für die Begrüßung übergeben.
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
@role_required("OWNER", "ADMIN", "EDITOR")
async def create_entry():
    if request.method == "POST":
        form = await request.form
        entry_date = (form.get("entry_date") or "").strip()
        high_light = (form.get("high_light") or "").strip() or "-"
        low_light = (form.get("low_light") or "").strip() or "-"
        notes = (form.get("notes") or "").strip() or "-"
        rating = int(form.get("rating", 3) or 3)

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
@role_required("OWNER", "ADMIN", "EDITOR")
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
        rating = int(form.get("rating", entry["rating"]) or entry["rating"])

        if not entry_date:
            await flash("Bitte wähle ein Datum aus.", "error")
            return await render_template("edit_entry.html", entry=entry)

        try:
            await update_entry(entry_id, entry_date, high_light, low_light, rating, notes)
            await flash("Eintrag erfolgreich bearbeitet.", "success")
        except psycopg.IntegrityError:
            await flash("Dieses Datum ist bereits vergeben. Bitte wähle ein anderes Datum.", "error")
            return await render_template("edit_entry.html", entry=entry)

        return redirect(url_for("index"))

    return await render_template("edit_entry.html", entry=entry)

@app.route("/entries/<int:entry_id>/delete", methods=["POST"])
@login_required
@force_password_change
@role_required("OWNER", "ADMIN", "EDITOR")
async def delete_entry_route(entry_id: int):
    entry = await get_entry_by_id(entry_id)
    if entry is None:
        await flash("Eintrag nicht gefunden.", "error")
        return redirect(url_for("index"))

    await delete_entry(entry_id)
    await flash("Eintrag gelöscht.", "success")
    return redirect(url_for("index"))

# --------------------------------------------------------------------------- #
# User management routes (admin only)
# --------------------------------------------------------------------------- #

@app.route("/users", methods=["GET"])
@login_required
@force_password_change
@role_required("OWNER", "ADMIN")
async def users():
    try:
        users_list = await list_users()
    except Exception as exc:
        # DB-Fehler (z. B. Tabelle nicht erreichbar nach Render-Neustart).
        # Statt eines kryptischen 500ers eine lesbare Meldung anzeigen.
        logger.exception("list_users failed: %s", exc)
        await flash(
            "Die Nutzerliste konnte nicht geladen werden (Datenbank-Fehler). "
            "Falls Render gerade neu gestartet wurde, versuche es in wenigen "
            "Sekunden noch einmal. Details: " + str(exc),
            "error",
        )
        return redirect(url_for("index"))
    return await render_template("users.html", users=users_list)

@app.route("/users", methods=["POST"])
@login_required
@force_password_change
@role_required("OWNER", "ADMIN")
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

    try:
        await create_user(name, role)
        await flash(
            f"Nutzer '{name}' angelegt. Standard-Passwort: {DEFAULT_PASSWORD}. "
            f"Beim ersten Login muss es geändert werden.",
            "success",
        )
    except psycopg.IntegrityError:
        await flash("Ein Nutzer mit diesem Namen existiert bereits.", "error")

    return redirect(url_for("users"))

@app.route("/users/<int:user_id>/role", methods=["POST"])
@login_required
@force_password_change
@role_required("OWNER", "ADMIN")
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

    if target["name"] == "TheHacker" or target["role"] == "OWNER":
        await flash("Der Owner-Account kann hier nicht im Rang geändert werden.", "error")
        return redirect(url_for("users"))

    user = current_user()
    if target["id"] == user["id"] and role != "ADMIN":
        await flash("Du kannst dir nicht selbst die Admin-Rechte entziehen.", "error")
        return redirect(url_for("users"))

    await update_user_role(user_id, role)
    await flash(f"Rolle von '{target['name']}' auf {role} geändert.", "success")
    return redirect(url_for("users"))

@app.route("/users/<int:user_id>/reset-password", methods=["POST"])
@login_required
@force_password_change
@role_required("OWNER", "ADMIN")
async def reset_user_password_route(user_id: int):
    target = await get_user_by_id(user_id)
    if target is None:
        await flash("Nutzer nicht gefunden.", "error")
        return redirect(url_for("users"))

    if target["name"] == "TheHacker" or target["role"] == "OWNER":
        await flash("Das Owner-Passwort kann nicht durch die Adminverwaltung zurückgesetzt werden.", "error")
        return redirect(url_for("users"))

    await reset_user_password(user_id)
    await flash(
        f"Passwort von '{target['name']}' auf {DEFAULT_PASSWORD} zurückgesetzt. "
        f"Es muss beim nächsten Login geändert werden.",
        "success",
    )
    return redirect(url_for("users"))

@app.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
@force_password_change
@role_required("OWNER", "ADMIN")
async def delete_user_route(user_id: int):
    target = await get_user_by_id(user_id)
    if target is None:
        await flash("Nutzer nicht gefunden.", "error")
        return redirect(url_for("users"))

    if target["name"] == "TheHacker" or target["role"] == "OWNER":
        await flash("Der Owner-Account kann nicht gelöscht werden.", "error")
        return redirect(url_for("users"))

    user = current_user()
    if target["id"] == user["id"]:
        await flash("Du kannst dich nicht selbst löschen.", "error")
        return redirect(url_for("users"))

    await delete_user(user_id)
    await flash(f"Nutzer '{target['name']}' gelöscht.", "success")
    return redirect(url_for("users"))


# --------------------------------------------------------------------------- #
# Owner management (TheHacker only)
# --------------------------------------------------------------------------- #

def owner_only(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        user = current_user()
        if not user or user.get("name") != "TheHacker" or user.get("role") != "OWNER":
            await flash("Diese Seite ist ausschließlich für den Owner verfügbar.", "error")
            return redirect(url_for("index"))
        return await func(*args, **kwargs)
    return wrapper


async def promote_thehacker_to_owner(user_id: int) -> None:
    """Promotes TheHacker robustly, even when an older DB role CHECK still exists."""
    def _promote():
        with get_connection() as conn:
            # Older deployments may still have a CHECK constraint that only allows
            # ADMIN/EDITOR/VIEWER. Remove every CHECK constraint that touches the
            # role column, then install the canonical constraint including OWNER.
            constraints = conn.execute(
                """
                SELECT DISTINCT c.conname
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                JOIN pg_attribute a
                  ON a.attrelid = t.oid
                 AND a.attnum = ANY(c.conkey)
                WHERE c.contype = 'c'
                  AND t.relname = 'users'
                  AND n.nspname = current_schema()
                  AND a.attname = 'role'
                """
            ).fetchall()

            for row in constraints:
                constraint_name = row["conname"]
                safe_name = constraint_name.replace('"', '""')
                conn.execute(f'ALTER TABLE users DROP CONSTRAINT "{safe_name}"')

            conn.execute(
                "ALTER TABLE users ADD CONSTRAINT users_role_check "
                "CHECK (role IN ('OWNER', 'ADMIN', 'EDITOR', 'VIEWER'))"
            )

            existing_owner = conn.execute(
                "SELECT id FROM users WHERE role = 'OWNER' AND id <> %s LIMIT 1",
                (user_id,),
            ).fetchone()
            if existing_owner:
                raise ValueError("Es existiert bereits ein anderer Owner.")

            result = conn.execute(
                "UPDATE users SET role = 'OWNER', locked = FALSE WHERE id = %s AND name = %s",
                (user_id, "TheHacker"),
            )
            if result.rowcount != 1:
                raise ValueError("TheHacker wurde in der Datenbank nicht gefunden.")

            conn.commit()

    await asyncio.to_thread(_promote)


@app.route("/become-owner", methods=["POST"])
@login_required
@force_password_change
@role_required("ADMIN")
async def become_owner():
    user = current_user()
    if not user or user.get("name") != "TheHacker":
        await flash("Nur TheHacker kann Owner werden.", "error")
        return redirect(url_for("users"))

    try:
        await promote_thehacker_to_owner(user["id"])
    except Exception as exc:
        logger.exception("Owner promotion failed for user %s: %s", user.get("id"), exc)
        await flash(
            "Owner-Rang konnte nicht gesetzt werden. Datenbankfehler: " + str(exc),
            "error",
        )
        return redirect(url_for("users"))

    session["user_role"] = "OWNER"
    await flash("Dein Rang wurde auf OWNER erhöht.", "success")

    # Deliberately return to the already-working user management page first.
    # This separates promotion errors from possible owner-page template errors.
    return redirect(url_for("users"))


@app.route("/owner", methods=["GET"])
@login_required
@force_password_change
@owner_only
async def owner_page():
    users_list = await list_users()
    return await render_template("owner.html", users=users_list)


@app.route("/owner/users/<int:user_id>/edit", methods=["POST"])
@login_required
@force_password_change
@owner_only
async def owner_edit_user(user_id: int):
    target = await get_user_by_id(user_id)
    if target is None:
        await flash("Nutzer nicht gefunden.", "error")
        return redirect(url_for("owner_page"))
    if target["name"] == "TheHacker" or target["role"] == "OWNER":
        await flash("Der Owner-Account wird auf dieser Seite separat verwaltet.", "error")
        return redirect(url_for("owner_page"))

    form = await request.form
    name = (form.get("name") or "").strip()
    role = (form.get("role") or "VIEWER").upper()
    new_password = form.get("new_password") or ""
    locked = form.get("locked") == "on"

    if not name:
        await flash("Der Nutzername darf nicht leer sein.", "error")
        return redirect(url_for("owner_page"))
    if name == "TheHacker":
        await flash("Der Name TheHacker ist für den Owner reserviert.", "error")
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
@owner_only
async def owner_change_owner_password():
    form = await request.form
    new_password = form.get("new_password") or ""
    confirm_password = form.get("confirm_password") or ""
    if len(new_password) < 4:
        await flash("Das neue Passwort muss mindestens 4 Zeichen lang sein.", "error")
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
@owner_only
async def owner_delete_entries():
    await run_db_query("DELETE FROM entries", commit=True)
    await flash("Alle Tagebucheinträge wurden gelöscht. Nutzerkonten bleiben erhalten.", "success")
    return redirect(url_for("owner_page"))


@app.route("/owner/delete-other-users", methods=["POST"])
@login_required
@force_password_change
@owner_only
async def owner_delete_other_users():
    user = current_user()
    await run_db_query("DELETE FROM users WHERE id <> %s", (user["id"],), commit=True)
    await flash("Alle anderen Nutzer wurden gelöscht.", "success")
    return redirect(url_for("owner_page"))

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)