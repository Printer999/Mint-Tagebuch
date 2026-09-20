import asyncio
import functools
import logging
import os
import secrets
import time
from collections import deque
from pathlib import Path

import bcrypt
import pymysql
from pymysql.cursors import DictCursor
from quart import (
    Quart,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

# MySQL-Zugangsdaten: Die Standardwerte rechts kannst du direkt hier ändern.
# Gleichnamige Umgebungsvariablen haben Vorrang (z. B. beim Deployment).
MYSQL_HOST = os.getenv("MYSQL_HOST", "sql7.freesqldatabase.com")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "sql7837418")
MYSQL_USER = os.getenv("MYSQL_USER", "sql7837418")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "GhGFlF2E4n")
# Optional: Pfad zum CA-Zertifikat für eine geprüfte TLS-Verbindung.
MYSQL_SSL_CA = os.getenv("MYSQL_SSL_CA", "")

BASE_DIR = Path(__file__).resolve().parent
LOG_PATH = BASE_DIR / "mint_tagebuch.log"
DEFAULT_PASSWORD = "1234"
OWNER_NAME = "TheHacker"
VALID_ROLES = ("OWNER", "ADMIN", "EDITOR", "VIEWER")
EDIT_ROLES = ("OWNER", "ADMIN", "EDITOR")
ADMIN_ROLES = ("OWNER", "ADMIN")
# Older InnoDB versions allow at most 767 bytes per indexed column.
MAX_USERNAME_LENGTH = 191
# A browser sends a small heartbeat once a minute.  After two missed
# heartbeats, the account is shown as offline in the owner administration.
PRESENCE_TIMEOUT_SECONDS = 120
TRUST_PROXY_HEADERS = os.getenv("TRUST_PROXY_HEADERS", "").lower() in {
    "1",
    "true",
    "yes",
}
# Used when a name is unknown so failed logins take the same bcrypt path as
# known accounts. Generating it here guarantees that it is a valid bcrypt hash.
DUMMY_PASSWORD_HASH = bcrypt.hashpw(
    b"invalid-login-password", bcrypt.gensalt()
)


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
# Request rate limiting
# --------------------------------------------------------------------------- #

class SlidingWindowRateLimiter:
    """Small in-memory limiter for one Hypercorn worker.

    The key cap keeps a flood of unique client addresses from growing memory
    without bound. The deployed service uses one worker, so this covers every
    request handled by the app instance.
    """

    def __init__(
        self, maximum_requests: int, window_seconds: int, *, max_keys: int = 10_000
    ):
        self.maximum_requests = maximum_requests
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._requests: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()
        self._last_cleanup = time.monotonic()

    def _remove_expired(self, requests: deque[float], now: float) -> None:
        cutoff = now - self.window_seconds
        while requests and requests[0] <= cutoff:
            requests.popleft()

    def _cleanup(self, now: float) -> None:
        for key, requests in list(self._requests.items()):
            self._remove_expired(requests, now)
            if not requests:
                del self._requests[key]
        self._last_cleanup = now

    async def check(self, key: str) -> int | None:
        """Record a request and return retry seconds when its limit is hit."""
        now = time.monotonic()

        async with self._lock:
            if now - self._last_cleanup >= self.window_seconds:
                self._cleanup(now)

            requests = self._requests.get(key)
            if requests is None:
                if len(self._requests) >= self.max_keys:
                    return self.window_seconds
                requests = deque()
                self._requests[key] = requests

            self._remove_expired(requests, now)
            if len(requests) >= self.maximum_requests:
                retry_after = requests[0] + self.window_seconds - now
                return max(1, int(retry_after) + 1)

            requests.append(now)
            return None


# Normal browsing remains generous for classrooms and shared networks. Login
# limits are narrower because every attempt performs an expensive bcrypt check.
REQUEST_RATE_LIMITER = SlidingWindowRateLimiter(600, 60)
LOGIN_IP_RATE_LIMITER = SlidingWindowRateLimiter(40, 5 * 60)
LOGIN_ACCOUNT_RATE_LIMITER = SlidingWindowRateLimiter(8, 15 * 60)


def client_address() -> str:
    """Return the real client IP when a trusted reverse proxy provides it."""
    if TRUST_PROXY_HEADERS:
        forwarded_for = request.headers.get("X-Forwarded-For", "")
        forwarded_address = forwarded_for.split(",", 1)[0].strip()
        if forwarded_address:
            return forwarded_address[:64]

    return (request.remote_addr or "unknown")[:64]


async def rate_limited_response(retry_after: int):
    response = await make_response(
        await render_template("rate_limited.html", retry_after=retry_after), 429
    )
    response.headers["Retry-After"] = str(retry_after)
    response.headers["Cache-Control"] = "no-store"
    return response


# --------------------------------------------------------------------------- #
# Database helpers
# --------------------------------------------------------------------------- #

def get_connection():
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        database=MYSQL_DATABASE,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD.encode("utf-8"),
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
        init_command="SET time_zone = '+00:00'",
        ssl_ca=MYSQL_SSL_CA or None,
        ssl_verify_cert=bool(MYSQL_SSL_CA),
        ssl_verify_identity=bool(MYSQL_SSL_CA),
    )


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
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                if fetchall:
                    result = cursor.fetchall()
                elif fetchone:
                    result = cursor.fetchone()
                else:
                    result = cursor.lastrowid

            if commit:
                conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    return await asyncio.to_thread(_execute)


async def init_db() -> None:
    def _init():
        with get_connection() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS entries (
                    id INTEGER NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    entry_date DATE NOT NULL UNIQUE,
                    high_light LONGTEXT NOT NULL,
                    low_light LONGTEXT NOT NULL,
                    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
                    notes LONGTEXT,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(191) COLLATE utf8mb4_unicode_ci NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    role VARCHAR(6) NOT NULL DEFAULT 'VIEWER'
                        CHECK (role IN ('OWNER', 'ADMIN', 'EDITOR', 'VIEWER')),
                    must_change_password BOOLEAN NOT NULL DEFAULT TRUE,
                    locked BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY users_name_case_insensitive_unique (name)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_sessions (
                    session_token VARCHAR(64) CHARACTER SET ascii
                        COLLATE ascii_bin PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    INDEX user_sessions_presence_idx (user_id, last_seen_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
                """
            )
            # OWNER is reserved for exactly one account.
            cursor.execute(
                "UPDATE users SET role = 'ADMIN' "
                "WHERE role = 'OWNER' AND name COLLATE utf8mb4_bin <> %s",
                (OWNER_NAME,),
            )
            cursor.execute(
                "UPDATE users SET locked = FALSE WHERE name COLLATE utf8mb4_bin = %s",
                (OWNER_NAME,),
            )
            conn.commit()

    await asyncio.to_thread(_init)
    logger.info("MySQL database initialized (entries + users + sessions)")


async def seed_admin() -> None:
    existing = await run_db_query(
        "SELECT id FROM users WHERE name COLLATE utf8mb4_bin = %s",
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
        WHERE name COLLATE utf8mb4_bin = %s
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
        SELECT
            u.id,
            u.name,
            u.role,
            u.must_change_password,
            u.locked,
            u.created_at,
            EXISTS (
                SELECT 1
                FROM user_sessions AS active_session
                WHERE active_session.user_id = u.id
                  AND active_session.last_seen_at >= CURRENT_TIMESTAMP
                      - INTERVAL %s SECOND
            ) AS is_online
        FROM users AS u
        ORDER BY
            CASE u.role
                WHEN 'OWNER' THEN 0
                WHEN 'ADMIN' THEN 1
                WHEN 'EDITOR' THEN 2
                ELSE 3
            END,
            u.created_at ASC
        """,
        (PRESENCE_TIMEOUT_SECONDS,),
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


async def touch_user_session(user_id: int) -> None:
    """Create or refresh the current browser's presence record."""
    session_token = session.get("presence_token")
    if not session_token:
        session_token = secrets.token_urlsafe(32)
        session["presence_token"] = session_token

    await run_db_query(
        """
        INSERT INTO user_sessions (session_token, user_id, last_seen_at)
        VALUES (%s, %s, CURRENT_TIMESTAMP)
        ON DUPLICATE KEY UPDATE
            user_id = %s, last_seen_at = CURRENT_TIMESTAMP
        """,
        (session_token, user_id, user_id),
        commit=True,
    )


async def end_user_session() -> None:
    """Remove only this browser's presence record on logout or invalidation."""
    session_token = session.get("presence_token")
    if session_token:
        await run_db_query(
            "DELETE FROM user_sessions WHERE session_token = %s",
            (session_token,),
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
async def limit_request_rate():
    # Assets are cacheable and do not reach the database, so they do not need
    # to consume a visitor's application request budget.
    if request.endpoint in (None, "static"):
        return None

    retry_after = await REQUEST_RATE_LIMITER.check(client_address())
    if retry_after is not None:
        logger.warning("Request rate limit reached for %s", client_address())
        return await rate_limited_response(retry_after)

    return None


@app.before_request
async def sync_logged_in_user():
    if request.endpoint == "static":
        return None

    user_id = session.get("user_id")
    if not user_id:
        return None

    db_user = await get_user_by_id(user_id)
    if not db_user:
        await end_user_session()
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
        await end_user_session()
        session.clear()
        if request.endpoint != "login":
            await flash("Dein Konto ist gesperrt.", "error")
            return redirect(url_for("login"))
        return None

    session["user_name"] = db_user["name"]
    session["user_role"] = db_user["role"]
    session["must_change_password"] = bool(db_user["must_change_password"])
    session["locked"] = bool(db_user["locked"])
    await touch_user_session(db_user["id"])
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

        address = client_address()
        ip_retry_after = await LOGIN_IP_RATE_LIMITER.check(address)
        account_retry_after = await LOGIN_ACCOUNT_RATE_LIMITER.check(
            name.casefold()[:128]
        )
        retry_after = max(ip_retry_after or 0, account_retry_after or 0)
        if retry_after:
            logger.warning("Login rate limit reached for %s", address)
            return await rate_limited_response(retry_after)

        user = await get_user_by_name(name)
        stored_hash = (
            user["password_hash"].encode("utf-8")
            if user
            else DUMMY_PASSWORD_HASH
        )
        try:
            ok = bcrypt.checkpw(password.encode("utf-8"), stored_hash)
        except ValueError:
            # A corrupt stored hash must behave like a failed login, not an
            # unhandled server error.
            logger.warning("Invalid password hash for login name %s", name)
            ok = False

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
        await touch_user_session(user["id"])

        logger.info("User %s logged in with role %s", user["name"], user["role"])

        if is_default_password:
            return redirect(url_for("change_password"))
        return redirect(url_for("index"))

    return await render_template("login.html", name="")


@app.route("/logout", methods=["POST"])
async def logout():
    await end_user_session()
    session.clear()
    await flash("Du wurdest abgemeldet.", "success")
    return redirect(url_for("login"))


@app.route("/presence", methods=["POST"])
@login_required
async def presence():
    """Heartbeat endpoint used by the open application page."""
    return "", 204


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
        except pymysql.IntegrityError:
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
        except pymysql.IntegrityError:
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

def management_endpoint() -> str:
    """OWNER uses the combined owner page; ADMIN keeps the normal users page."""
    user = current_user()
    if user and user.get("role") == "OWNER":
        return "owner_page"
    return "users"


def redirect_to_management():
    return redirect(url_for(management_endpoint()))


@app.route("/users", methods=["GET"])
@login_required
@force_password_change
@role_required(*ADMIN_ROLES)
async def users():
    if current_user() and current_user().get("role") == "OWNER":
        return redirect(url_for("owner_page"))

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
        return redirect_to_management()

    if len(name) > MAX_USERNAME_LENGTH:
        await flash(
            f"Der Name darf höchstens {MAX_USERNAME_LENGTH} Zeichen lang sein.", "error"
        )
        return redirect_to_management()

    if role not in ("ADMIN", "EDITOR", "VIEWER"):
        await flash("Ungültige Rolle.", "error")
        return redirect_to_management()

    if name.casefold() == OWNER_NAME.casefold():
        await flash(f"Der Name '{OWNER_NAME}' ist für den Owner reserviert.", "error")
        return redirect_to_management()

    try:
        await create_user(name, role)
        await flash(
            f"Nutzer '{name}' angelegt. Standard-Passwort: {DEFAULT_PASSWORD}. "
            "Beim ersten Login muss es geändert werden.",
            "success",
        )
    except pymysql.IntegrityError:
        await flash("Ein Nutzer mit diesem Namen existiert bereits.", "error")

    return redirect_to_management()


@app.route("/users/<int:user_id>/role", methods=["POST"])
@login_required
@force_password_change
@role_required(*ADMIN_ROLES)
async def update_user_role_route(user_id: int):
    form = await request.form
    role = (form.get("role") or "VIEWER").upper()

    if role not in ("ADMIN", "EDITOR", "VIEWER"):
        await flash("Ungültige Rolle.", "error")
        return redirect_to_management()

    target = await get_user_by_id(user_id)
    if target is None:
        await flash("Nutzer nicht gefunden.", "error")
        return redirect_to_management()

    if target["name"] == OWNER_NAME or target["role"] == "OWNER":
        await flash("Der Owner-Rang kann hier nicht verändert werden.", "error")
        return redirect_to_management()

    user = current_user()
    if target["id"] == user["id"] and role not in ADMIN_ROLES:
        await flash("Du kannst dir nicht selbst die Admin-Rechte entziehen.", "error")
        return redirect_to_management()

    await update_user_role(user_id, role)
    await flash(f"Rolle von '{target['name']}' auf {role} geändert.", "success")
    return redirect_to_management()


@app.route("/users/<int:user_id>/reset-password", methods=["POST"])
@login_required
@force_password_change
@role_required(*ADMIN_ROLES)
async def reset_user_password_route(user_id: int):
    target = await get_user_by_id(user_id)
    if target is None:
        await flash("Nutzer nicht gefunden.", "error")
        return redirect_to_management()

    if target["name"] == OWNER_NAME or target["role"] == "OWNER":
        await flash("Das Owner-Passwort kann hier nicht zurückgesetzt werden.", "error")
        return redirect_to_management()

    await reset_user_password(user_id)
    await flash(
        f"Passwort von '{target['name']}' auf {DEFAULT_PASSWORD} zurückgesetzt. "
        "Es muss beim nächsten Login geändert werden.",
        "success",
    )
    return redirect_to_management()


@app.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
@force_password_change
@role_required(*ADMIN_ROLES)
async def delete_user_route(user_id: int):
    target = await get_user_by_id(user_id)
    if target is None:
        await flash("Nutzer nicht gefunden.", "error")
        return redirect_to_management()

    if target["name"] == OWNER_NAME or target["role"] == "OWNER":
        await flash("Der Owner kann nicht gelöscht werden.", "error")
        return redirect_to_management()

    user = current_user()
    if target["id"] == user["id"]:
        await flash("Du kannst dich nicht selbst löschen.", "error")
        return redirect_to_management()

    await delete_user(user_id)
    await flash(f"Nutzer '{target['name']}' gelöscht.", "success")
    return redirect_to_management()


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
            "UPDATE users SET role = 'ADMIN' "
            "WHERE role = 'OWNER' AND name COLLATE utf8mb4_bin <> %s",
            (OWNER_NAME,),
            commit=True,
        )
        await run_db_query(
            "UPDATE users SET role = 'OWNER', locked = FALSE "
            "WHERE id = %s AND name COLLATE utf8mb4_bin = %s",
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


@app.route("/owner/presence", methods=["GET"])
@login_required
@force_password_change
@owner_required
async def owner_presence():
    users_list = await list_users()
    return jsonify(
        users=[
            {"id": user["id"], "is_online": bool(user["is_online"])}
            for user in users_list
        ]
    )


@app.route("/owner/users/<int:user_id>/login-as", methods=["POST"])
@login_required
@force_password_change
@owner_required
async def owner_login_as_user(user_id: int):
    """Let the owner start a fresh session as an unlocked non-owner account."""
    target = await get_user_by_id(user_id)
    if target is None:
        await flash("Nutzer nicht gefunden.", "error")
        return redirect(url_for("owner_page"))

    if target["name"] == OWNER_NAME or target["role"] == "OWNER":
        await flash("Der Owner-Account kann nicht über diesen Weg gewechselt werden.", "error")
        return redirect(url_for("owner_page"))

    if target["locked"]:
        await flash("In einen gesperrten Account kann nicht gewechselt werden.", "error")
        return redirect(url_for("owner_page"))

    await end_user_session()
    session.clear()
    session["user_id"] = target["id"]
    session["user_name"] = target["name"]
    session["user_role"] = target["role"]
    session["must_change_password"] = bool(target["must_change_password"])
    session["locked"] = False
    await touch_user_session(target["id"])

    logger.info("Owner switched into user account %s", target["name"])
    await flash(f"Du bist jetzt als '{target['name']}' angemeldet.", "success")
    return redirect(url_for("index"))


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

    if len(name) > MAX_USERNAME_LENGTH:
        await flash(
            f"Der Name darf höchstens {MAX_USERNAME_LENGTH} Zeichen lang sein.", "error"
        )
        return redirect(url_for("owner_page"))

    if name.casefold() == OWNER_NAME.casefold():
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
    except pymysql.IntegrityError:
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
        "DELETE FROM users WHERE name COLLATE utf8mb4_bin <> %s",
        (OWNER_NAME,),
        commit=True,
    )
    logger.warning("Owner deleted all other users")
    await flash("Alle anderen Nutzer wurden gelöscht.", "success")
    return redirect(url_for("owner_page"))


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
