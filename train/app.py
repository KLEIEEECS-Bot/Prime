#!/usr/bin/env python3
"""
Meeting-note -> Action-item extractor Flask app
- Correctly handles "before <month>" and "end of <month>"
- Normalizes dates to midnight
- Robust assignee detection using spaCy + regex + heuristics
- Tracks unassigned tasks as 'general_tasks'
- JSON API at POST /api/extract
"""

import calendar
import logging
import os
import re
from datetime import datetime, timedelta

import dateparser
from dateparser import parse as dp_parse
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_cors import CORS

# --------------------
# Configuration
# --------------------
LOG_LEVEL = os.environ.get("APP_LOG_LEVEL", "INFO")
logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)

SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*")
HOST = os.environ.get("FLASK_HOST", "0.0.0.0")
PORT = int(os.environ.get("FLASK_PORT", "5000"))
DEBUG = os.environ.get("FLASK_DEBUG", "True").lower() in ("1", "true", "yes")

app = Flask(__name__)
app.secret_key = SECRET_KEY

if CORS_ORIGINS == "*":
    CORS(app)
else:
    origins = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]
    CORS(app, resources={r"/*": {"origins": origins}})

# --------------------
# NLP setup
# --------------------
try:
    import spacy

    nlp = spacy.load("en_core_web_sm")
    logger.info("Loaded spaCy model en_core_web_sm")
except Exception:
    logger.warning("spaCy model not available, using blank pipeline")
    nlp = spacy.blank("en")

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

# --------------------
# Regex patterns
# --------------------
PAT_NEXT_THIS = re.compile(
    r"\b(?P<mod>next|this|coming)\s+(?P<wd>monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.IGNORECASE,
)
PAT_IN_N = re.compile(
    r"\b(?:in)\s+(?P<n>\d+)\s+(?P<unit>days?|weeks?|months?)\b", re.IGNORECASE
)
PAT_TODAY_TOM = re.compile(r"\b(?P<tok>today|tomorrow|yesterday)\b", re.IGNORECASE)
PAT_BEFORE = re.compile(r"\b(before|by)\s+(?P<time>[\w\s,.-]+)", re.IGNORECASE)
PAT_END_OF_MONTH = re.compile(r"\bend of (?P<month>[\w]+)\b", re.IGNORECASE)
PAT_BEFORE_MONTH = re.compile(r"\b(before|by)\s+(?P<month>[\w]+)\b", re.IGNORECASE)
ASSIGNEE_REGEX = re.compile(
    r"\b(?:assigned|assign|to)\s+(?:to\s+)?(?P<name>[A-Z][\w\.'-]+(?:\s+[A-Z][\w\.'-]+)*)",
    re.IGNORECASE,
)


# --------------------
# Helpers: dates
# --------------------
def now_midnight():
    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)


def compute_weekday_date(today, target_wd, modifier):
    d = today.weekday()
    base = (target_wd - d) % 7
    days_ahead = (
        base if modifier.lower() in ["this", "coming"] else (base if base > 0 else 7)
    )
    return (today + timedelta(days=days_ahead)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def compute_in_n(today, n, unit):
    unit = unit.lower()
    if unit.startswith("day"):
        return (today + timedelta(days=n)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    if unit.startswith("week"):
        return (today + timedelta(weeks=n)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    if unit.startswith("month"):
        month = today.month - 1 + n
        year = today.year + month // 12
        month = month % 12 + 1
        day = min(today.day, calendar.monthrange(year, month)[1])
        return datetime(year, month, day)
    return None


def normalize_parsed(dt):
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        return datetime(dt.year, dt.month, dt.day)
    except:
        return None


def deterministic_parse_date(text, today):
    m = PAT_NEXT_THIS.search(text)
    if m:
        return compute_weekday_date(
            today, WEEKDAYS[m.group("wd").lower()], m.group("mod")
        )

    m2 = PAT_IN_N.search(text)
    if m2:
        return compute_in_n(today, int(m2.group("n")), m2.group("unit"))

    m3 = PAT_TODAY_TOM.search(text)
    if m3:
        tok = m3.group("tok").lower()
        if tok == "today":
            return today
        if tok == "tomorrow":
            return today + timedelta(days=1)
        if tok == "yesterday":
            return today - timedelta(days=1)

    m_before_month = PAT_BEFORE_MONTH.search(text)
    if m_before_month:
        month_name = m_before_month.group("month").strip().lower()
        parsed_month = dp_parse(month_name, settings={"RELATIVE_BASE": today})
        if parsed_month:
            year = today.year if parsed_month.month >= today.month else today.year
            month_num = parsed_month.month
            day = calendar.monthrange(year, month_num)[1]
            return datetime(year, month_num, day)

    m_eom = PAT_END_OF_MONTH.search(text)
    if m_eom:
        month_name = m_eom.group("month").strip().lower()
        parsed_month = dp_parse(month_name, settings={"RELATIVE_BASE": today})
        if parsed_month:
            year = today.year if parsed_month.month >= today.month else today.year + 1
            month_num = parsed_month.month
            day = calendar.monthrange(year, month_num)[1]
            return datetime(year, month_num, day)

    m_before = PAT_BEFORE.search(text)
    if m_before:
        parsed = dp_parse(
            m_before.group("time").strip(" ,.;"), settings={"RELATIVE_BASE": today}
        )
        if parsed:
            return normalize_parsed(parsed)

    return None


def extract_date(text, today):
    dt = deterministic_parse_date(text, today)
    if dt:
        return normalize_parsed(dt)
    doc = nlp(text)
    for ent in doc.ents:
        if ent.label_ == "DATE":
            parsed = dp_parse(ent.text, settings={"RELATIVE_BASE": today})
            if parsed:
                return normalize_parsed(parsed)
    parsed = dp_parse(text, settings={"RELATIVE_BASE": today})
    return normalize_parsed(parsed)


# --------------------
# Assignee
# --------------------
def find_assignee(sent_doc):
    persons = [ent.text for ent in sent_doc.ents if ent.label_ == "PERSON"]
    if persons:
        persons.sort(key=lambda s: len(s.split()), reverse=True)
        return persons[0]
    m = ASSIGNEE_REGEX.search(sent_doc.text)
    if m:
        return m.group("name").strip()
    for tok in sent_doc:
        if tok.pos_ == "VERB":
            for j in range(max(0, tok.i - 6), tok.i):
                t = sent_doc[j]
                if t.ent_type_ == "PERSON" or t.pos_ == "PROPN" or t.text.istitle():
                    return t.text
            break
    return "General"


# --------------------
# Extraction core
# --------------------
def extract_action_items(text):
    today = now_midnight()
    doc = nlp(text)
    items = []
    general_tasks = []
    for sent in doc.sents:
        sentence_text = sent.text.strip()
        if not any(tok.pos_ == "VERB" for tok in sent):
            continue
        if re.search(r"\bno deadline\b", sentence_text, re.IGNORECASE):
            continue
        action = sentence_text
        assignee = find_assignee(sent)
        if not assignee or assignee.lower() in ("no", "none"):
            assignee = "General"
        dt = extract_date(action, today)
        deadline = dt.date().isoformat() if dt else "No deadline"
        task = {"action": action, "assignee": assignee, "deadline": deadline}
        items.append(task)
        if assignee == "General":
            general_tasks.append(task)
    return {"items": items, "general_tasks": general_tasks}


# --------------------
# Routes
# --------------------
USER_CREDENTIALS = {"admin": os.environ.get("ADMIN_PASSWORD", "password")}


@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username in USER_CREDENTIALS and USER_CREDENTIALS[username] == password:
            session["user"] = username
            return redirect(url_for("dashboard"))
        flash("Invalid username/password", "danger")
    try:
        return render_template("login.html")
    except:
        return "<form method='post'>Username: <input name='username'><br>Password: <input name='password' type='password'><br><button type='submit'>Login</button></form>"


@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    extracted = None
    if request.method == "POST":
        notes = request.form.get("notes", "")
        extracted = extract_action_items(notes)
    try:
        return render_template(
            "dashboard.html", extracted=extracted, user=session["user"]
        )
    except:
        return jsonify({"user": session.get("user"), "extracted": extracted})


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))


# --------------------
# API
# --------------------
@app.route("/api/extract", methods=["POST"])
def api_extract():
    try:
        data = request.get_json(force=True)
        notes = data.get("notes", "")
        if not isinstance(notes, str):
            return jsonify({"error": "invalid 'notes' field, must be string"}), 400
        return jsonify(extract_action_items(notes)), 200
    except Exception as e:
        logger.exception("api_extract failed")
        return jsonify({"error": str(e)}), 400


@app.route("/health")
def health():
    return jsonify(
        {"status": "ok", "nlp_model": getattr(nlp, "meta", {}).get("name", "blank")}
    )


# --------------------
# Run
# --------------------
if __name__ == "__main__":
    logger.info("Starting app on %s:%d", HOST, PORT)
    app.run(host=HOST, port=PORT, debug=DEBUG, threaded=True)
