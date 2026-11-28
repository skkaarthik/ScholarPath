"""Chatbot context: choose the relevant records and describe them compactly. Pure functions only.

The chatbot never sees the whole database. For each question the server picks:

* the scholarship open on the Review page, if any (the "current" scholarship);
* up to ``MAX_RECORDS`` other scholarships that fit the question (and the Check my fit
  profile, when the student has filled it in);
* the student's application entries, only when the question is about their progress.

Each scholarship is tagged S1, S2, ... so the answer can point at records we really hold.
After the answer comes back, ``clean_answer`` keeps only those tags and only links that
belong to those records; anything else is removed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .dates import GROUPS, describe_deadline
from .matching import FAILED, SATISFIED, InternshipProfile, StudentProfile, evaluate, evaluate_internship
from .models import (DEGREES, DISCIPLINES, FUNDING_CATEGORIES, INTERN_DEGREES, STIPEND_KINDS, STUDY_YEARS, SUBJECTS,
                     TRACKER_OUTCOMES, TRACKER_STATUSES, WORK_ARRANGEMENTS, InternshipRecord)

MAX_RECORDS = 4                 # other scholarships per question (keeps the prompt small)
MAX_TEXT = 400                  # characters of source wording per scholarship
MAX_CURRENT_TEXT = 900          # more for the scholarship being reviewed

STOPWORDS = set("""a an the and or of for to in on at by with from is are be am i me my we our you your it this that
these those what which who how when where why can could should would do does did any some about tell show give list
want need please scholarship scholarships internship internships intern interns there their them as if so than then
into more most best good""".split())
PROGRESS_WORDS = {"application", "applications", "applied", "status", "progress", "track", "tracking", "result",
                  "results", "submitted", "outcome", "awarded", "waiting", "heard"}
COMPARE_WORDS = {"other", "others", "similar", "alternative", "alternatives", "else", "instead", "compare"}
RECOMMEND_WORDS = {"recommend", "recommendation", "suggest", "which", "options", "find", "eligible", "fit",
                   "match", "matches", "qualify", "apply"}


@dataclass
class ContextRecord:
    tag: str                    # "S1"
    view: object                # services.ScholarshipView
    verdict: str = ""           # from matching.evaluate, when a profile exists
    met: list[str] = field(default_factory=list)
    not_met: list[str] = field(default_factory=list)
    to_verify: list[str] = field(default_factory=list)
    why: list[str] = field(default_factory=list)   # why it was picked (also used by demo answers)


@dataclass
class ChatContext:
    records: list[ContextRecord]
    current_tag: str | None
    applications: list[dict] | None          # None: progress was not asked about
    profile_used: bool
    intent: str                              # "progress" | "recommend" | "current" | "general"


def clean(text: str, limit: int) -> str:
    """Untrusted text (user input or scraped wording): drop control characters, squeeze, cut."""
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z'&-]+", (text or "").lower()) if w not in STOPWORDS and len(w) > 2}


GENERIC_NAME_WORDS = {"master's", "masters", "global", "international", "award", "awards", "programme", "program",
                      "university", "phd", "fund", "fellowship", "fellowships", "great", "excellence", "graduate",
                      "intern", "internship", "trainee"}


def name_words(name: str) -> set[str]:
    """The distinctive words of a scholarship name (falls back to all words for very generic names)."""
    w = words(name)
    return (w - GENERIC_NAME_WORDS) or w


def _labels(restriction, labels: dict) -> list[str]:
    return [labels.get(v, v) for v in restriction.values] if restriction.kind == "list" else []


def _record_words(rec) -> set[str]:
    if isinstance(rec, InternshipRecord):
        return words(" ".join([rec.title, rec.employer, " ".join(rec.cities), " ".join(rec.states),
                               WORK_ARRANGEMENTS.get(rec.work_arrangement, ""),
                               " ".join(_labels(rec.disciplines, DISCIPLINES)),
                               "paid stipend" if rec.stipend_kind.startswith("paid") else ""]))
    parts = [rec.name, rec.provider, " ".join(rec.host_countries), " ".join(_labels(rec.degrees, DEGREES)),
             " ".join(_labels(rec.subjects, SUBJECTS)), " ".join(rec.nationalities.values),
             FUNDING_CATEGORIES.get(rec.funding_category, "")]
    return words(" ".join(parts))


def detect_intent(question: str, has_current: bool) -> str:
    w = set(re.findall(r"[a-z]+", question.lower()))
    if w & PROGRESS_WORDS and ({"my", "i", "me"} & w or "applications" in w):
        return "progress"
    if w & RECOMMEND_WORDS and not has_current:
        return "recommend"
    return "current" if has_current else ("recommend" if w & RECOMMEND_WORDS else "general")


def _evaluate(profile, rec, ctx: ContextRecord) -> None:
    result = evaluate_internship(profile, rec) if isinstance(profile, InternshipProfile) else evaluate(profile, rec)
    ctx.verdict = result.overall
    for r in result.rules:
        line = f"{r.rule}: {r.reason}"
        (ctx.met if r.status == SATISFIED else ctx.not_met if r.status == FAILED else ctx.to_verify).append(line)


def select(views: list, question: str, history: list[tuple[str, str]], current_id: str | None,
           profile: StudentProfile | None, applications: list | None) -> ChatContext:
    """Pick the records for one question. ``views`` are all ScholarshipViews in the dataset."""
    by_id = {v.record.id: v for v in views}
    current = by_id.get(current_id) if current_id else None
    recent_user = " ".join(q for q, _ in history[-2:])
    intent = detect_intent(question, current is not None)
    asked = words(question) | (words(recent_user) if intent != "current" else set())
    wants_closed = bool({"closed", "expired", "past"} & set(question.lower().split()))

    scored = []
    for v in views:
        if current is not None and v.record.id == current.record.id:
            continue
        if v.group == "expired" and not wants_closed:
            continue
        hits = sorted(asked & _record_words(v.record))
        ctx = ContextRecord("", v, why=[f"mentions {', '.join(hits)}"] if hits else [])
        score = 3 * len(hits)
        if profile is not None:
            _evaluate(profile, v.record, ctx)
            score += {"Matches recorded requirements": 3, "Needs manual verification": 1}.get(ctx.verdict, -4)
            ctx.why.append(ctx.verdict.lower())
        if score > 0 or (intent == "recommend" and not hits):
            scored.append((score, v.days_left if v.days_left is not None else 10_000, v.record.name, ctx))
    scored.sort(key=lambda t: (-t[0], t[1], t[2]))

    if intent == "progress":
        picked = []
    elif intent == "current" and not set(question.lower().split()) & COMPARE_WORDS:
        picked = []                       # a question about the open scholarship only
    else:
        picked = [t[3] for t in scored[:MAX_RECORDS]]

    records: list[ContextRecord] = []
    if current is not None:
        ctx = ContextRecord("", current, why=["the scholarship being reviewed"])
        if profile is not None:
            _evaluate(profile, current.record, ctx)
        records.append(ctx)
    records += picked
    if intent == "progress" and applications:
        records += [ContextRecord("", by_id[sid], why=["in your Applications"])
                    for sid in list(dict.fromkeys(a.scholarship_id for a in applications))
                    if sid in by_id and sid != current_id][:MAX_RECORDS]
    for i, ctx in enumerate(records, start=1):
        ctx.tag = f"S{i}"

    apps = None
    if intent == "progress":
        apps = [{"tag": next((c.tag for c in records if c.view.record.id == a.scholarship_id), None),
                 "name": by_id[a.scholarship_id].record.name if a.scholarship_id in by_id else "(not in this dataset)",
                 "status": TRACKER_STATUSES.get(a.status, a.status),
                 "submitted": a.submitted_date.isoformat() if a.submitted_date else None,
                 "target": a.target_date.isoformat() if a.target_date else None,
                 "outcome": TRACKER_OUTCOMES.get(a.outcome, a.outcome) if a.outcome else None}
                for a in (applications or [])]
    return ChatContext(records, records[0].tag if current is not None else None, apps,
                       profile is not None and intent in ("recommend", "current"), intent)


def _restriction(r, labels: dict | None = None) -> str:
    if r.kind == "unrestricted":
        return "open to all (stated)"
    if r.kind == "list" and r.values:
        return ", ".join((labels or {}).get(v, v) for v in r.values)
    return "NOT STATED"


def _stipend_line(rec) -> str:
    if rec.stipend_kind == "paid":
        low, high = rec.stipend_min, rec.stipend_max
        amount = f"Rs {low:,}" if high in (None, low) else (f"up to Rs {high:,}" if low is None else f"Rs {low:,}-{high:,}")
        return f"{amount} per month"
    return STIPEND_KINDS.get(rec.stipend_kind, "NOT STATED")


def describe_internship(ctx: ContextRecord, today: date, current: bool) -> str:
    """One internship as compact text for the model (facts only, no employer description text)."""
    rec, view = ctx.view.record, ctx.view
    lines = [
        f"[{ctx.tag}] {clean(rec.title, 160)} - {clean(rec.employer, 120)}" + ("  (BEING REVIEWED)" if current else ""),
        f"  Status: {GROUPS.get(view.group, view.group)}; deadline: {describe_deadline(rec.deadline_kind, rec.deadline_date, today)}",
        f"  Where: {', '.join(rec.cities) or ', '.join(rec.states) or 'NOT STATED'}; arrangement: "
        f"{WORK_ARRANGEMENTS.get(rec.work_arrangement, 'NOT STATED')}",
        f"  Discipline: {_restriction(rec.disciplines, DISCIPLINES)}; degree: {_restriction(rec.degrees, INTERN_DEGREES)}; "
        f"year of study: {_restriction(rec.study_years, STUDY_YEARS)}",
        f"  Stipend: {_stipend_line(rec)}; duration: {clean(rec.duration_text, 80) or 'NOT STATED'}",
    ]
    if rec.experience_text:
        lines.append(f"  Experience: {clean(rec.experience_text, 160)}")
    if rec.eligibility_text:
        lines.append(f"  Recorded facts: {clean(rec.eligibility_text, MAX_CURRENT_TEXT if current else MAX_TEXT)}")
    lines.append(f"  Employer's page: {rec.application_url or rec.source_url or 'NOT RECORDED'}")
    if rec.fetch_method == "fictional":
        lines.append("  NOTE: fictional practice record, not a real internship.")
    if ctx.verdict:
        lines.append(f"  Check against the student's profile: {ctx.verdict}")
        for label, items in (("meets", ctx.met), ("does not meet", ctx.not_met), ("needs verification", ctx.to_verify)):
            if items:
                lines.append(f"    {label}: " + " | ".join(clean(i, 140) for i in items[:4]))
    return "\n".join(lines)


def describe(ctx: ContextRecord, today: date, current: bool) -> str:
    """One scholarship as compact text for the model."""
    rec, view = ctx.view.record, ctx.view
    if isinstance(rec, InternshipRecord):
        return describe_internship(ctx, today, current)
    lines = [
        f"[{ctx.tag}] {clean(rec.name, 160)} - {clean(rec.provider, 120)}" + ("  (BEING REVIEWED)" if current else ""),
        f"  Status: {GROUPS.get(view.group, view.group)}; deadline: {describe_deadline(rec.deadline_kind, rec.deadline_date, today)}",
        f"  Where: {', '.join(rec.host_countries) or 'NOT STATED'}; degree: {_restriction(rec.degrees, DEGREES)}; "
        f"subjects: {_restriction(rec.subjects, SUBJECTS)}",
        f"  Nationalities: {_restriction(rec.nationalities)}"
        + (f"; excluded: {', '.join(rec.nationality_exclusions.values)}" if rec.nationality_exclusions.values else ""),
        f"  Funding: {FUNDING_CATEGORIES.get(rec.funding_category, 'NOT STATED')}"
        + (f" - {clean(rec.funding_description, 200)}" if rec.funding_description else ""),
    ]
    if rec.min_score is not None:
        lines.append(f"  Minimum score: {rec.min_score:g} {rec.score_scale or ''}".rstrip())
    if rec.requirements:
        reqs = "; ".join(clean(r.text, 160) for r in rec.requirements[: 8 if current else 3])
        lines.append(f"  Documents/requirements recorded: {reqs}")
    if rec.eligibility_text:
        lines.append(f"  Source wording: \"{clean(rec.eligibility_text, MAX_CURRENT_TEXT if current else MAX_TEXT)}\"")
    lines.append(f"  Official page: {rec.application_url or rec.source_url or 'NOT RECORDED'}")
    if rec.fetch_method == "fictional":
        lines.append("  NOTE: fictional practice record, not a real scholarship.")
    if ctx.verdict:
        lines.append(f"  Check against the student's profile: {ctx.verdict}")
        for label, items in (("meets", ctx.met), ("does not meet", ctx.not_met), ("needs verification", ctx.to_verify)):
            if items:
                lines.append(f"    {label}: " + " | ".join(clean(i, 140) for i in items[:4]))
    return "\n".join(lines)


def profile_text(profile: StudentProfile | None) -> str:
    if profile is None:
        return "Not provided (the student has not filled in Check my fit)."
    if isinstance(profile, InternshipProfile):
        parts = [f"degree {INTERN_DEGREES.get(profile.degree, profile.degree)}" if profile.degree else "",
                 f"year of study {STUDY_YEARS.get(profile.year, profile.year)}" if profile.year else "",
                 "in the final year" if profile.final_year else "",
                 f"discipline {DISCIPLINES.get(profile.discipline, profile.discipline)}" if profile.discipline else "",
                 f"prefers {profile.preferred_place}" if profile.preferred_place else ""]
        return ", ".join(p for p in parts if p) or "Provided, but every field is blank."
    parts = [f"nationality {profile.nationality}" if profile.nationality else "",
             f"degree {DEGREES.get(profile.degree, profile.degree)}" if profile.degree else "",
             f"subject {SUBJECTS.get(profile.subject, profile.subject)}" if profile.subject else "",
             f"score {profile.score:g} {profile.score_scale or ''}".strip() if profile.score is not None else "",
             f"prefers {profile.preferred_destination}" if profile.preferred_destination else ""]
    return ", ".join(p for p in parts if p) or "Provided, but every field is blank."


def context_block(chat: ChatContext, today: date, profile: StudentProfile | None, dataset_label: str,
                  kind: str = "scholarship") -> str:
    noun = "INTERNSHIP" if kind == "internship" else "SCHOLARSHIP"
    out = [f"Dataset: {dataset_label}. Today: {today.isoformat()}."]
    if chat.profile_used:
        out.append(f"Student profile (from Check my fit): {profile_text(profile)}")
    elif chat.intent == "recommend":
        needed = ("degree, year of study and discipline" if kind == "internship"
                  else "nationality, degree level and subject")
        out.append(f"Student profile: not provided. Ask for {needed} if they are "
                   "needed and not already in the conversation.")
    if chat.records:
        out.append(f"{noun} RECORDS (the only {noun.lower()}s you may mention):")
        out += [describe(c, today, c.tag == chat.current_tag) for c in chat.records]
    else:
        out.append(f"{noun} RECORDS: none matched this question.")
    if chat.applications is not None:
        if chat.applications:
            out.append("THE STUDENT'S APPLICATION ENTRIES (from ScholarPath's tracker):")
            out += [f"- {a['name']}" + (f" [{a['tag']}]" if a["tag"] else "") + f": {a['status']}"
                    + (f", submitted {a['submitted']}" if a["submitted"] else "")
                    + (f", own target date {a['target']}" if a["target"] else "")
                    + (f", outcome {a['outcome']}" if a["outcome"] else "") for a in chat.applications]
        else:
            out.append("THE STUDENT'S APPLICATION ENTRIES: none recorded.")
    return "\n".join(out)


# --- after the answer ---------------------------------------------------------------------

URL = re.compile(r"https?://[^\s)\]>\"']+")
MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
TAG = re.compile(r"[ \t]*[\[(](S\d{1,3})[\])]")
UNKNOWN_NOTE = "(not in ScholarPath's records)"


def allowed_urls(chat: ChatContext) -> set[str]:
    urls = set()
    for c in chat.records:
        urls |= {u.rstrip("/") for u in (c.view.record.application_url, c.view.record.source_url) if u}
    return urls


def clean_answer(answer: str, chat: ChatContext) -> tuple[str, list[ContextRecord], bool]:
    """Keep only links to the records we supplied; turn S-tags into a validated reference list.

    Returns (text, referenced records, invented): ``invented`` is True when the answer used a tag
    we never supplied, i.e. it talked about a scholarship that is not in ScholarPath's records.
    Such a tag is replaced by a visible warning rather than silently dropped."""
    ok = allowed_urls(chat)
    answer = MD_LINK.sub(lambda m: m.group(0) if m.group(2).rstrip("/.") in ok else m.group(1), answer)

    def bare(m):
        url = m.group(0).rstrip(".,;:")
        return m.group(0) if url.rstrip("/") in ok else "(link removed: not in ScholarPath's records)"

    answer = re.sub(r"(?<!\()" + URL.pattern, bare, answer)
    tags = {c.tag: c for c in chat.records}
    used: list[ContextRecord] = []
    for m in TAG.finditer(answer):
        c = tags.get(m.group(1))
        # A tag counts only if the scholarship's own name is written just before it, so a
        # mixed-up tag can never put a link to the wrong scholarship under the answer.
        if c is not None and c not in used and name_words(c.view.record.name) & words(answer[max(0, m.start() - 120):m.start()]):
            used.append(c)
    invented = any(t not in tags for t in TAG.findall(answer))
    answer = TAG.sub(lambda m: "" if m.group(1) in tags else f" {UNKNOWN_NOTE}", answer)
    for c in chat.records:                       # a record named in full but not tagged
        if c not in used and c.view.record.name.lower() in answer.lower():
            used.append(c)
    return answer.strip(), used, invented
