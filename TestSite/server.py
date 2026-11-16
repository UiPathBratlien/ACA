"""CoverWell demo backend: serves the site and stores enrollments in SQLite.

Run:  python server.py [port]      (default port 8080, binds to 127.0.0.1 only)

API
  POST   /api/enrollments                 create an enrollment (JSON body) -> 201 + record
  GET    /api/enrollments                 list all (filters: ?email= &last_name= &confirmation=)
  GET    /api/enrollments/<confirmation>  one record, 404 if missing
  DELETE /api/enrollments/<confirmation>  delete one record
  DELETE /api/enrollments                 delete ALL records (reset between test runs)

Database file: data/enrollments.db (table `enrollments`).
"""
import json
import os
import random
import sqlite3
import sys
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "data", "enrollments.db")

FIELDS = [
    "first_name", "last_name", "dob", "email", "zip", "household_size", "age",
    "income", "tobacco", "monthly_credit", "plan_id", "plan_name", "plan_tier",
    "carrier", "monthly_premium", "full_premium", "deductible",
]
REQUIRED = ["first_name", "last_name", "dob", "email", "zip", "plan_name", "monthly_premium"]


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with db() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS enrollments (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                confirmation     TEXT UNIQUE NOT NULL,
                created_at       TEXT NOT NULL,
                status           TEXT NOT NULL DEFAULT 'Submitted',
                first_name       TEXT NOT NULL,
                last_name        TEXT NOT NULL,
                dob              TEXT NOT NULL,
                email            TEXT NOT NULL,
                zip              TEXT NOT NULL,
                household_size   INTEGER,
                age              INTEGER,
                income           REAL,
                tobacco          INTEGER,
                monthly_credit   REAL,
                plan_id          TEXT,
                plan_name        TEXT NOT NULL,
                plan_tier        TEXT,
                carrier          TEXT,
                monthly_premium  REAL NOT NULL,
                full_premium     REAL,
                deductible       REAL
            )""")


def new_confirmation(conn):
    while True:
        num = "CW-" + "".join(random.choices("0123456789", k=8))
        if not conn.execute("SELECT 1 FROM enrollments WHERE confirmation=?", (num,)).fetchone():
            return num


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def end_headers(self):
        # Always serve fresh pages so browsers pick up site edits immediately.
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    # ---- helpers -------------------------------------------------------
    def send_json(self, status, payload):
        body = json.dumps(payload, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def route(self):
        path = urlparse(self.path).path.rstrip("/")
        if not path.startswith("/api/enrollments"):
            return None, None
        rest = path[len("/api/enrollments"):].lstrip("/")
        return "enrollments", unquote(rest) or None

    # Block direct download of the database / server source
    def do_GET(self):
        res, key = self.route()
        if res is None:
            p = urlparse(self.path).path.lower()
            if p.startswith("/data") or p.endswith(".py"):
                return self.send_json(404, {"error": "Not found"})
            return super().do_GET()
        with db() as c:
            if key:
                row = c.execute("SELECT * FROM enrollments WHERE confirmation=?", (key,)).fetchone()
                return self.send_json(200, dict(row)) if row else self.send_json(404, {"error": "Not found"})
            q = parse_qs(urlparse(self.path).query)
            sql, args = "SELECT * FROM enrollments WHERE 1=1", []
            for col in ("email", "last_name", "confirmation"):
                if col in q:
                    sql += f" AND lower({col}) = lower(?)"
                    args.append(q[col][0])
            rows = c.execute(sql + " ORDER BY id DESC", args).fetchall()
            self.send_json(200, {"count": len(rows), "enrollments": [dict(r) for r in rows]})

    def do_POST(self):
        res, key = self.route()
        if res is None or key:
            return self.send_json(404, {"error": "Not found"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self.send_json(400, {"error": "Invalid JSON"})
        missing = [f for f in REQUIRED if data.get(f) in (None, "")]
        if missing:
            return self.send_json(400, {"error": "Missing fields: " + ", ".join(missing)})
        with db() as c:
            conf = new_confirmation(c)
            created = datetime.now(timezone.utc).isoformat(timespec="seconds")
            vals = [data.get(f) for f in FIELDS]
            if vals[FIELDS.index("tobacco")] is not None:
                vals[FIELDS.index("tobacco")] = 1 if data["tobacco"] else 0
            c.execute(
                f"INSERT INTO enrollments (confirmation, created_at, {', '.join(FIELDS)}) "
                f"VALUES (?, ?, {', '.join('?' * len(FIELDS))})",
                [conf, created, *vals])
            row = c.execute("SELECT * FROM enrollments WHERE confirmation=?", (conf,)).fetchone()
        self.send_json(201, dict(row))

    def do_DELETE(self):
        res, key = self.route()
        if res is None:
            return self.send_json(404, {"error": "Not found"})
        with db() as c:
            if key:
                n = c.execute("DELETE FROM enrollments WHERE confirmation=?", (key,)).rowcount
                return self.send_json(200 if n else 404, {"deleted": n})
            n = c.execute("DELETE FROM enrollments").rowcount
        self.send_json(200, {"deleted": n})

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    init_db()
    print(f"CoverWell running at http://localhost:{port}/   (admin: /admin.html)")
    print(f"Database: {DB_PATH}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
