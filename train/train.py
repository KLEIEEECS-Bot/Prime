#!/usr/bin/env python3
"""
Interactive meeting-action extractor (single-file).

- Deterministic handling for: "next Friday", "this Monday", "in 3 days", "tomorrow", etc.
- Safe span/indexing: uses local sentence indices (enumerate(sent)).
- Falls back to spaCy DATE entities then dateparser for fuzzy cases.
- Multi-line interactive input: paste meeting notes, finish by entering an empty line.
"""

import calendar
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import dateparser
import spacy

# Load model (ensure en_core_web_sm is installed)
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
    r"\b(?P<prefix>by\s+|on\s+|due\s+)?(?P<mod>next|this|coming)\s+(?P<wd>"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.IGNORECASE,
)
PAT_IN_N = re.compile(
    r"\b(?:in)\s+(?P<n>\d+)\s+(?P<unit>days?|weeks?|months?)\b", re.IGNORECASE
)
PAT_TODAY_TOM = re.compile(r"\b(?P<tok>today|tomorrow|yesterday)\b", re.IGNORECASE)


def compute_weekday_date(today: datetime, target_wd: int, modifier: str) -> datetime:
    d = today.weekday()  # 0=Mon .. 6=Sun
    base = (target_wd - d) % 7
    mod = modifier.lower()
    if mod == "this" or mod == "coming":
        days_ahead = base
    elif mod == "next":
        days_ahead = base if base > 0 else 7
    else:
        days_ahead = base
    return (today + timedelta(days=days_ahead)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def compute_in_n(today: datetime, n: int, unit: str) -> Optional[datetime]:
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


def deterministic_parse_date(sentence_text: str, today: datetime) -> Optional[datetime]:
    s = sentence_text

    m = PAT_NEXT_THIS.search(s)
    if m:
        mod = m.group("mod").lower()
        wd = m.group("wd").lower()
        if wd in WEEKDAYS:
            target = WEEKDAYS[wd]
            return compute_weekday_date(today, target, mod)

    m2 = PAT_IN_N.search(s)
    if m2:
        n = int(m2.group("n"))
        unit = m2.group("unit")
        return compute_in_n(today, n, unit)

    m3 = PAT_TODAY_TOM.search(s)
    if m3:
        tok = m3.group("tok").lower()
        if tok == "today":
            return today.replace(hour=0, minute=0, second=0, microsecond=0)
        if tok == "tomorrow":
            return (today + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        if tok == "yesterday":
            return (today - timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )

    return None


def extract_date_from_text(sentence_text: str, today: datetime) -> Optional[datetime]:
    # 1) deterministic patterns
    dt = deterministic_parse_date(sentence_text, today)
    if dt:
        return dt

    # 2) spaCy DATE entities
    doc = nlp(sentence_text)
    for ent in doc.ents:
        if ent.label_ == "DATE":
            parsed = dateparser.parse(
                ent.text,
                settings={"RELATIVE_BASE": today, "PREFER_DATES_FROM": "future"},
            )
            if parsed:
                return parsed

    # 3) fallback to parsing whole sentence
    parsed = dateparser.parse(
        sentence_text, settings={"RELATIVE_BASE": today, "PREFER_DATES_FROM": "future"}
    )
    return parsed


def find_assignee(sent_doc) -> Optional[str]:
    """
    Use safe, span-local indexing. Heuristics:
      1) spaCy PERSON entity (prefer multi-token)
      2) capitalized/proper-noun near first verb (local lookback)
      3) simple 'assign ...' regex
    """
    persons = [ent.text for ent in sent_doc.ents if ent.label_ == "PERSON"]
    if persons:
        persons.sort(key=lambda s: len(s.split()), reverse=True)
        return persons[0]

    # local enumeration avoids Span indexing errors
    for local_idx, token in enumerate(sent_doc):
        if token.pos_ == "VERB":
            start_scan = max(0, local_idx - 4)
            for j in range(local_idx - 1, start_scan - 1, -1):  # scan leftwards
                t = sent_doc[j]  # safe: j is local index in the span
                if t.ent_type_ == "PERSON":
                    return t.text
                if t.pos_ == "PROPN":
                    return t.text
                if t.text.istitle() and len(t.text) > 1:
                    return t.text
            break

    m = re.search(
        r"\bassign(?:ed|)\s+(?:to\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", sent_doc.text
    )
    if m:
        return m.group(1)

    return None


def extract_action_items(text: str, today: Optional[datetime] = None) -> List[Dict]:
    if today is None:
        today = datetime.now()
    doc = nlp(text)
    out = []
    for sent in doc.sents:
        st = sent.text.strip()
        if not any(tok.pos_ == "VERB" for tok in sent):
            continue
        assignee = find_assignee(sent) or "General"
        dt = extract_date_from_text(st, today)
        deadline = dt.date().isoformat() if dt else "No deadline"
        out.append({"action": st, "assignee": assignee, "deadline": deadline})
    return out


def interactive_input() -> str:
    """Read multi-line input from user; stop when an empty line is entered."""
    print(
        "Paste or type meeting notes. Finish input by entering an empty line (press Enter on blank line)."
    )
    lines = []
    try:
        while True:
            line = input()
            if line.strip() == "":
                break
            lines.append(line)
    except EOFError:
        # Support piping or Ctrl-D termination
        pass
    return "\n".join(lines).strip()


def main():
    notes = interactive_input()
    if not notes:
        print("No meeting notes provided. Exiting.")
        return

    today = datetime.now()
    items = extract_action_items(notes, today=today)

    if not items:
        print("No actionable sentences found.")
        return

    print("\nExtracted action items:")
    for idx, it in enumerate(items, 1):
        print(f"\nItem {idx}:")
        print(f"  Action  : {it['action']}")
        print(f"  Assignee: {it['assignee']}")
        print(f"  Deadline: {it['deadline']}")


if __name__ == "__main__":
    main()
