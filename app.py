"""Kharcha: Personal Expense Tracker - CS50x 2026 Final Project.
A Flask + SQLite web app. One account sees only its own entries.
The SQLite schema is created automatically at startup (init_db),
so no database file needs to be committed or shipped.
"""
import os
import sqlite3
from datetime import date, datetime
from functools import wraps
from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
app = Flask(__name__)


@app.template_filter("money")
def money_filter(value):
    """Format an amount with thousands separators, e.g. 62,000.00."""
    return f"{float(value):,.2f}"


@app.template_filter("humandate")
def humandate_filter(value):
    """Render an ISO date (2026-11-12) as '12 Nov 2026'."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d %b %Y")
    except (TypeError, ValueError):
        return value


@app.template_filter("monthname")
def monthname_filter(value):
    """Render a year-month (2026-11) as 'Nov 2026'."""
    try:
        return datetime.strptime(value, "%Y-%m").strftime("%b %Y")
    except (TypeError, ValueError):
        return value


app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.config["SESSION_COOKIE_HTTPONLY"] = True
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "kharcha.db")
CATEGORIES = ["Food", "Transport", "Rent", "Utilities", "Shopping", "Entertainment", "Health", "Education", "Salary", "Freelance", "Other"]
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db
@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()
def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK (kind IN ('income', 'expense')),
            amount REAL NOT NULL CHECK (amount > 0),
            category TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            date TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_entries_user_date ON entries(user_id, date DESC);
    """)
    db.commit()
    db.close()
init_db()
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped
def parse_amount(raw):
    try:
        value = round(float(raw), 2)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None
def parse_entry_date(raw):
    raw = (raw or "").strip()
    if not raw:
        return date.today().isoformat()
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None
    return parsed.isoformat() if parsed <= date.today() else None
@app.route("/")
@login_required
def index():
    db = get_db()
    totals = db.execute("SELECT COALESCE(SUM(CASE WHEN kind='income' THEN amount ELSE 0 END), 0) AS income, COALESCE(SUM(CASE WHEN kind='expense' THEN amount ELSE 0 END), 0) AS expense FROM entries WHERE user_id = ?", (session["user_id"],)).fetchone()
    income = totals["income"]
    expense = totals["expense"]
    entries = db.execute("SELECT * FROM entries WHERE user_id = ? ORDER BY date DESC, id DESC", (session["user_id"],)).fetchall()
    by_category = db.execute("SELECT category, kind, SUM(amount) AS total, COUNT(*) AS n FROM entries WHERE user_id = ? GROUP BY category, kind ORDER BY total DESC", (session["user_id"],)).fetchall()
    monthly = db.execute("SELECT strftime('%Y-%m', date) AS month, COALESCE(SUM(CASE WHEN kind='income' THEN amount ELSE 0 END), 0) AS income, COALESCE(SUM(CASE WHEN kind='expense' THEN amount ELSE 0 END), 0) AS expense FROM entries WHERE user_id = ? GROUP BY month ORDER BY month DESC LIMIT 6", (session["user_id"],)).fetchall()
    # Presentation data for the dashboard charts (kept out of the templates).
    expense_cats = []
    total_expense = float(expense) or 0.0
    top_expense = max((float(r["total"]) for r in by_category if r["kind"] == "expense"), default=0.0)
    for r in by_category:
        if r["kind"] != "expense":
            continue
        expense_cats.append({
            "category": r["category"],
            "total": float(r["total"]),
            "n": r["n"],
            "bar": round(float(r["total"]) / top_expense * 100) if top_expense else 0,
            "share": round(float(r["total"]) / total_expense * 100) if total_expense else 0,
        })
    monthly_rows = [dict(m) for m in monthly]
    peak = max((max(float(m["income"]), float(m["expense"])) for m in monthly_rows), default=0.0)
    for m in monthly_rows:
        m["income_h"] = round(float(m["income"]) / peak * 100) if peak else 0
        m["expense_h"] = round(float(m["expense"]) / peak * 100) if peak else 0
        m["net"] = float(m["income"]) - float(m["expense"])
    monthly_rows.reverse()
    return render_template("index.html", entries=entries, income=income, expense=expense, balance=income - expense, by_category=by_category, monthly=monthly, expense_cats=expense_cats, monthly_chart=monthly_rows)
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirmation = request.form.get("confirmation", "")
        if not username or not password:
            flash("Username and password are required.", "danger")
        elif password != confirmation:
            flash("Passwords do not match.", "danger")
        elif len(password) < 4:
            flash("Password must be at least 4 characters.", "danger")
        else:
            db = get_db()
            try:
                cur = db.execute("INSERT INTO users (username, hash) VALUES (?, ?)", (username, generate_password_hash(password)))
                db.commit()
            except sqlite3.IntegrityError:
                flash("That username is already taken.", "danger")
                return render_template("register.html")
            session.clear()
            session["user_id"] = cur.lastrowid
            session["username"] = username
            flash("Welcome to Kharcha, " + username + "!", "success")
            return redirect(url_for("index"))
    return render_template("register.html")
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not password:
            flash("Enter your username and password.", "danger")
        else:
            user = get_db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            if user is None or not check_password_hash(user["hash"], password):
                flash("Invalid username or password.", "danger")
            else:
                session.clear()
                session["user_id"] = user["id"]
                session["username"] = user["username"]
                flash("Logged in as " + user["username"] + ".", "success")
                return redirect(url_for("index"))
    return render_template("login.html")
@app.route("/logout")
def logout():
    session.clear()
    flash("You have logged out.", "info")
    return redirect(url_for("login"))
@app.route("/add", methods=["GET", "POST"])
@login_required
def add():
    if request.method == "POST":
        kind = request.form.get("kind", "expense")
        if kind not in ("income", "expense"):
            flash("Choose income or expense.", "danger")
            return render_template("add.html", categories=CATEGORIES, today=date.today().isoformat())
        amount = parse_amount(request.form.get("amount"))
        entry_date = parse_entry_date(request.form.get("date"))
        category = request.form.get("category", "Other").strip() or "Other"
        note = request.form.get("note", "").strip()
        if amount is None:
            flash("Enter an amount greater than 0.", "danger")
        elif entry_date is None:
            flash("Enter a valid date, not in the future.", "danger")
        else:
            db = get_db()
            db.execute("INSERT INTO entries (user_id, kind, amount, category, note, date) VALUES (?, ?, ?, ?, ?, ?)", (session["user_id"], kind, amount, category, note, entry_date))
            db.commit()
            flash("Entry added.", "success")
            return redirect(url_for("index"))
    return render_template("add.html", categories=CATEGORIES, today=date.today().isoformat())
@app.route("/delete/<int:entry_id>", methods=["POST"])
@login_required
def delete(entry_id):
    db = get_db()
    cur = db.execute("DELETE FROM entries WHERE id = ? AND user_id = ?", (entry_id, session["user_id"]))
    db.commit()
    if cur.rowcount:
        flash("Entry deleted.", "success")
    else:
        flash("Entry not found.", "warning")
    return redirect(url_for("index"))
@app.route("/summary")
@login_required
def summary():
    return redirect(url_for("index"))
if __name__ == "__main__":
    app.run(debug=True)
