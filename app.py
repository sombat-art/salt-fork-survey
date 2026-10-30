"""
Post-use evaluation form for the Salt Fork field study, storing results in PostgreSQL.

- GET  /         -> serves form.html as-is
- POST /submit   -> validates the submission and inserts one row into `evaluations`
- GET  /export   -> downloads all responses as CSV (HTTP Basic Auth)
- GET  /healthz  -> checks that PostgreSQL is reachable

Database connection settings come from the standard PostgreSQL environment
variables (PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE). docker-compose.yml
sets them for you.

Run with Docker (app + PostgreSQL together):
    cp .env.example .env      # then set the passwords
    docker compose up -d --build
"""

import atexit
import csv
import hmac
import io
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from functools import wraps
from zoneinfo import ZoneInfo

from flask import Flask, Response, redirect, request, send_from_directory, url_for
from psycopg import Error as PgError
from psycopg_pool import ConnectionPool, PoolTimeout

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FORM_VERSION = "2.0 (19 ก.พ. 2569)"
LOCAL_TZ = ZoneInfo("Asia/Bangkok")

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "")

# Refuse to start with no admin password or the placeholder from .env.example:
# /export returns every participant's answers.
if not ADMIN_PASS or ADMIN_PASS == "change-me":
    sys.exit("ADMIN_PASS is not set (or is still 'change-me'). Set it in .env and restart.")

app = Flask(__name__)
app.logger.setLevel(logging.INFO)  # show start-up and error messages in `docker compose logs`

# One pool per worker process. conninfo="" means "use the PG* environment variables".
# open=True starts connecting in the background; it does not block if the DB is still starting.
# check= tests each connection before handing it out, so a connection broken by a
# database restart is replaced instead of failing a participant's submission.
pool = ConnectionPool(
    conninfo="", min_size=1, max_size=5, open=True, timeout=10,
    check=ConnectionPool.check_connection,
)
# Close the pool cleanly when the process exits (container stop, or a one-off
# command such as `flask routes`); otherwise exit waits ~20 s for its threads.
atexit.register(pool.close)

USAGE_FREQUENCY = ["ไม่ใช้เลย", "นานๆครั้ง", "บ่อยแต่ไม่ทุกวัน", "ทุกวัน แต่ไม่ทุกมื้อ", "ทุกวัน และทุกมื้อ"]
CALIBRATION_AWARENESS = ["ไม่ทราบเลย", "ทราบ แต่ไม่เคยทำ", "ทราบ และเคยทำแล้ว"]
PRICE_AGREEMENT = ["เห็นด้วย", "ไม่เห็นด้วย"]

SATISFACTION_KEYS = [
    "sat_shape", "sat_grip", "sat_weight", "sat_button", "sat_light_display",
    "sat_light_brightness", "sat_speed", "sat_accuracy", "sat_cleaning",
    "sat_coating_durability", "sat_battery_life", "sat_storage",
    "sat_portability", "sat_dipped_food", "sat_health_benefit",
    "sat_switch_likelihood",
]

# Columns written on insert (order matters: matches the VALUES placeholders).
INSERT_COLUMNS = (
    ["form_version", "usage_frequency"]
    + SATISFACTION_KEYS
    + ["calibration_awareness", "calibration_times", "price_agreement", "suggestions", "user_agent",
       "submission_id"]
)
# ON CONFLICT: a second POST with the same submission_id (Back + send again, or a
# double tap on the button) is ignored instead of creating a duplicate row.
INSERT_SQL = (
    f"INSERT INTO evaluations ({', '.join(INSERT_COLUMNS)}) "
    f"VALUES ({', '.join(['%s'] * len(INSERT_COLUMNS))}) "
    f"ON CONFLICT (submission_id) DO NOTHING"
)

# Column order for the CSV export.
EXPORT_FIELDS = (
    ["id", "submitted_at", "usage_frequency"]
    + SATISFACTION_KEYS
    + ["calibration_awareness", "calibration_times", "price_agreement", "suggestions"]
)
EXPORT_SQL = f"SELECT {', '.join(EXPORT_FIELDS)} FROM evaluations ORDER BY submitted_at, id"


def require_admin(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        auth = request.authorization
        ok = (
            auth is not None
            and hmac.compare_digest((auth.username or "").encode(), ADMIN_USER.encode())
            and hmac.compare_digest((auth.password or "").encode(), ADMIN_PASS.encode())
        )
        if not ok:
            return Response(
                "Authentication required", 401,
                {"WWW-Authenticate": 'Basic realm="Evaluation form admin"'},
            )
        return view(*args, **kwargs)
    return wrapped


@app.get("/")
def index():
    return send_from_directory(BASE_DIR, "form.html")


@app.post("/submit")
def submit():
    form = request.form
    errors = []

    usage_frequency = form.get("usage_frequency", "")
    if usage_frequency not in USAGE_FREQUENCY:
        errors.append("missing/invalid usage_frequency")

    satisfaction = {}
    for key in SATISFACTION_KEYS:
        val = form.get(key, "")
        if val not in ("1", "2", "3", "4", "5"):
            errors.append(f"missing/invalid {key}")
        else:
            satisfaction[key] = int(val)

    calibration = form.get("calibration", "")
    if calibration not in CALIBRATION_AWARENESS:
        errors.append("missing/invalid calibration")

    calibration_times = None
    if calibration == "ทราบ และเคยทำแล้ว":
        raw = form.get("calibration_times", "").strip()
        if raw:
            try:
                calibration_times = int(raw)
                if not 0 <= calibration_times <= 100000:
                    errors.append("invalid calibration_times")
            except ValueError:
                errors.append("invalid calibration_times")

    price_agreement = form.get("price_agreement", "")
    if price_agreement not in PRICE_AGREEMENT:
        errors.append("missing/invalid price_agreement")

    # Random ID the form page creates once per filled-in form (see form.html).
    # Missing or malformed (e.g. JavaScript off): store NULL, which never conflicts.
    try:
        submission_id = str(uuid.UUID(form.get("submission_id", "")))
    except ValueError:
        submission_id = None

    if errors:
        return (
            "กรุณากลับไปตอบคำถามให้ครบทุกข้อ แล้วส่งแบบฟอร์มใหม่อีกครั้ง "
            "(" + "; ".join(errors) + ")",
            400,
        )

    values = (
        [FORM_VERSION, usage_frequency]
        + [satisfaction[k] for k in SATISFACTION_KEYS]
        + [
            calibration,
            calibration_times,
            price_agreement,
            form.get("suggestions", "").strip()[:5000],
            request.headers.get("User-Agent", "")[:300],
            submission_id,
        ]
    )

    try:
        # The `with` block commits on success and rolls back on any error.
        with pool.connection() as conn:
            cur = conn.execute(INSERT_SQL, values)
            if cur.rowcount == 0:
                app.logger.info("Repeated submission %s ignored (already saved)", submission_id)
    except (PgError, PoolTimeout):
        app.logger.exception("Failed to save evaluation")
        return (
            "ขออภัย ระบบไม่สามารถบันทึกข้อมูลได้ในขณะนี้ กรุณาลองส่งใหม่อีกครั้งภายหลัง",
            503,
        )

    # Post/Redirect/Get: send the browser to /thanks instead of answering the POST
    # with the page, so refreshing the thank-you page can't resubmit the form.
    return redirect(url_for("thanks"), code=303)


@app.get("/thanks")
def thanks():
    return send_from_directory(BASE_DIR, "thanks.html")


@app.get("/export")
@require_admin
def export():
    """All rows as CSV, UTF-8 with BOM so Thai opens correctly in Excel. Times in Bangkok time."""
    buf = io.StringIO()
    buf.write("﻿")
    writer = csv.writer(buf)
    writer.writerow(EXPORT_FIELDS)

    try:
        with pool.connection() as conn:
            for row in conn.execute(EXPORT_SQL):
                row = list(row)
                row[1] = row[1].astimezone(LOCAL_TZ).isoformat(timespec="seconds")
                writer.writerow(["" if v is None else v for v in row])
    except (PgError, PoolTimeout):
        app.logger.exception("Export failed")
        return "Database unavailable, try again later", 503

    filename = f"evaluations-{datetime.now(LOCAL_TZ).strftime('%Y%m%d-%H%M')}.csv"
    return Response(
        buf.getvalue(),
        content_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/healthz")
def healthz():
    try:
        with pool.connection(timeout=3) as conn:
            n = conn.execute("SELECT count(*) FROM evaluations").fetchone()[0]
        return {"status": "ok", "db": "ok", "responses": n}
    except (PgError, PoolTimeout):
        return {"status": "degraded", "db": "unreachable"}, 503


def ensure_schema(attempts=30, delay=2):
    """Create the table if it doesn't exist. Retries while PostgreSQL is still starting.

    An advisory lock makes sure only one gunicorn worker runs the DDL at a time.
    """
    with open(os.path.join(BASE_DIR, "schema.sql"), encoding="utf-8") as f:
        ddl = f.read()
    for attempt in range(1, attempts + 1):
        try:
            with pool.connection() as conn:
                conn.execute("SELECT pg_advisory_lock(424201)")
                try:
                    conn.execute(ddl)
                    conn.commit()
                finally:
                    conn.execute("SELECT pg_advisory_unlock(424201)")
            app.logger.info("Database schema ready")
            return
        except (PgError, PoolTimeout) as exc:
            app.logger.warning("Database not ready (attempt %d/%d): %s", attempt, attempts, exc)
            time.sleep(delay)
    sys.exit("Could not reach PostgreSQL to create the schema; giving up.")


ensure_schema()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=False)
