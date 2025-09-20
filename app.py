#!/usr/bin/env python3
import calendar
import csv
import io
import re
from datetime import datetime, timedelta

import dateparser
import spacy
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from flask_cors import CORS

# --------------------
# Flask app
# --------------------
app = Flask(__name__)
app.secret_key = "dev-secret"
CORS(app)

# --------------------
# NLP setup
# --------------------
nlp = spacy.load("en_core_web_sm")

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

PAT_NEXT_THIS = re.compile(
    r"\b(?P<mod>next|this|coming)\s+(?P<wd>monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.IGNORECASE,
)
PAT_IN_N = re.compile(
    r"\b(?:in)\s+(?P<n>\d+)\s+(?P<unit>days?|weeks?|months?)\b", re.IGNORECASE
)
PAT_TODAY_TOM = re.compile(r"\b(?P<tok>today|tomorrow|yesterday)\b", re.IGNORECASE)
PAT_BEFORE = re.compile(r"\b(before|by)\s+(?P<time>[\w\s,.-]+)", re.IGNORECASE)
ASSIGNEE_REGEX = re.compile(
    r"\b(?:assigned|assign|to)\s+(?:to\s+)?(?P<name>[A-Z][\w\.'-]+(?:\s+[A-Z][\w\.'-]+)*)",
    re.IGNORECASE,
)

# --------------------
# Dummy Database
# --------------------
all_tasks = [
    {
        "task": "Finalize Q3 marketing report",
        "person": "Alice",
        "deadline": "2025-09-25",
        "status": "In Progress",
        "team": "Marketing",
    },
    {
        "task": "Develop new user auth feature",
        "person": "Bob",
        "deadline": "2025-10-05",
        "status": "Pending",
        "team": "Engineering",
    },
    {
        "task": "Deploy server updates",
        "person": "Charlie",
        "deadline": "2025-09-22",
        "status": "Completed",
        "team": "DevOps",
    },
    {
        "task": "Create new ad creatives",
        "person": "Alice",
        "deadline": "2025-09-30",
        "status": "Pending",
        "team": "Marketing",
    },
]

# --------------------
# Users
# --------------------
USER_CREDENTIALS = {"admin": "password"}


# --------------------
# NLP / Date Helpers
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
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


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
    m_before = PAT_BEFORE.search(text)
    if m_before:
        parsed = dateparser.parse(
            m_before.group("time"), settings={"RELATIVE_BASE": today}
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
            parsed = dateparser.parse(ent.text, settings={"RELATIVE_BASE": today})
            if parsed:
                return normalize_parsed(parsed)
    parsed = dateparser.parse(text, settings={"RELATIVE_BASE": today})
    return normalize_parsed(parsed)


def find_assignee(sent_doc):
    persons = [ent.text for ent in sent_doc.ents if ent.label_ == "PERSON"]
    if persons:
        return persons[0]
    m = ASSIGNEE_REGEX.search(sent_doc.text)
    if m:
        return m.group("name").strip()
    return "General"


def extract_action_items(text):
    today = now_midnight()
    doc = nlp(text)
    items = []
    for sent in doc.sents:
        if not any(tok.pos_ == "VERB" for tok in sent):
            continue
        action = sent.text.strip()
        assignee = find_assignee(sent)
        dt = extract_date(action, today)
        deadline = dt.date().isoformat() if dt else "No deadline"
        items.append({"action": action, "assignee": assignee, "deadline": deadline})
    return items


# --------------------
# Routes
# --------------------
@app.route("/")
def home():
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username in USER_CREDENTIALS and USER_CREDENTIALS[username] == password:
            session["user"] = username
            return redirect(url_for("dashboard"))
        error = "Invalid Credentials"
    return render_template("login.html", error=error)


@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    extracted = None
    if request.method == "POST":
        notes = request.form.get("notes", "")
        extracted = extract_action_items(notes)
    return render_template(
        "dashboard.html", user=session["user"], extracted=extracted, tasks=all_tasks
    )


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))


# --------------------
# Add Task (manual form)
# --------------------
@app.route("/add")
def add_task_page():
    return render_template("add_data.html")


@app.route("/add-task", methods=["POST"])
def add_task():
    new_task = {
        "task": request.form["task"].strip(),
        "person": request.form["person"].strip(),
        "deadline": request.form["deadline"].strip(),
        "status": request.form["status"].strip(),
        "team": request.form["team"].strip(),
    }
    all_tasks.append(new_task)
    return redirect(url_for("dashboard"))


# --------------------
# Add Task via File Upload
# --------------------
@app.route("/upload-tasks", methods=["POST"])
def upload_tasks():
    if "file" not in request.files:
        return redirect(url_for("add_task_page"))
    file = request.files["file"]
    if file.filename == "" or not file.filename.endswith(".txt"):
        return redirect(url_for("add_task_page"))
    stream = io.StringIO(file.stream.read().decode("utf-8"))
    reader = csv.reader(stream)
    for row in reader:
        if not row or len(row) != 5:
            continue
        task, person, team, deadline, status = [r.strip() for r in row]
        # Optional: normalize deadline using extract_date
        dt = extract_date(deadline, now_midnight())
        deadline_norm = dt.date().isoformat() if dt else deadline
        all_tasks.append(
            {
                "task": task,
                "person": person,
                "team": team,
                "deadline": deadline_norm,
                "status": status,
            }
        )
    return redirect(url_for("dashboard"))


# --------------------
# API Endpoint
# --------------------
@app.route("/api/extract", methods=["POST"])
def api_extract():
    data = request.get_json(force=True)
    notes = data.get("notes", "")
    return jsonify(extract_action_items(notes))


# --------------------
# Run App
# --------------------
if __name__ == "__main__":
    app.run(debug=True)
