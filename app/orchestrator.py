"""Runs the enabled agents in order and prepares the daily email (sent by n8n)."""

from datetime import date
from html import escape

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from .agents import run_filter, run_scanner
from .config import EMAIL_FROM, PUBLIC_BASE_URL
from .db import Run, Tender, TenderScore, enabled_agents, get_setting, utcnow

V2_AGENTS = {"analyzer", "menu_checker", "writer"}


def run_pipeline(s: Session) -> dict:
    enabled = enabled_agents(s)
    run = Run()
    s.add(run)
    s.commit()

    summary: dict = {"enabled_agents": sorted(enabled)}
    if not enabled:
        summary["status"] = "paused"
    else:
        if "scanner" in enabled:
            summary["scanner"] = run_scanner(s)
        if "filter" in enabled:
            summary["filter"] = run_filter(s)
        skipped = sorted(enabled & V2_AGENTS)
        if skipped:
            summary["not_implemented_yet"] = skipped
        summary["status"] = "ok"

    to_notify = pending_notifications(s) if "filter" in enabled else []
    run.finished_at = utcnow()
    run.summary = summary | {"to_notify": len(to_notify)}
    s.commit()

    return {
        "run_id": run.id,
        "summary": summary,
        "count": len(to_notify),
        "tender_ids": [t.id for t in to_notify],
        "email": build_email(s, to_notify) if to_notify else None,
    }


def pending_notifications(s: Session) -> list[Tender]:
    today = date.today()
    q = (
        select(Tender)
        .join(TenderScore)
        .options(selectinload(Tender.score))
        .where(
            TenderScore.relevant.is_(True),
            Tender.baseline.is_(False),
            Tender.notified.is_(False),
            or_(Tender.deadline.is_(None), Tender.deadline >= today),
        )
        .order_by(TenderScore.score.desc())
    )
    return list(s.scalars(q))


def build_email(s: Session, tenders: list[Tender]) -> dict:
    rows = []
    for t in tenders:
        deadline = t.deadline.strftime("%d/%m/%Y") if t.deadline else "לא צוין"
        link = f'<a href="{escape(t.url)}">למכרז</a>' if t.url else ""
        rows.append(
            "<tr>"
            f'<td style="padding:8px;border-bottom:1px solid #eee"><b>{escape(t.title)}</b><br>'
            f'<span style="color:#666;font-size:13px">{escape(t.publisher or "")} · הגשה עד {deadline} · '
            f'{escape(", ".join(t.score.reasons))}</span></td>'
            f'<td style="padding:8px;border-bottom:1px solid #eee;text-align:center"><b>{t.score.score}</b></td>'
            f'<td style="padding:8px;border-bottom:1px solid #eee">{link}</td>'
            "</tr>"
        )
    html = (
        '<div dir="rtl" style="font-family:Arial,sans-serif;max-width:720px">'
        f"<h2>נמצאו {len(tenders)} מכרזים חדשים שעשויים להתאים</h2>"
        '<table style="border-collapse:collapse;width:100%">'
        '<tr style="background:#f4f1ea"><th style="padding:8px;text-align:right">מכרז</th>'
        '<th style="padding:8px">ציון</th><th></th></tr>'
        + "".join(rows)
        + "</table>"
        f'<p><a href="{escape(PUBLIC_BASE_URL)}">לאישור או דחייה בדף הניהול</a></p>'
        '<p style="color:#888;font-size:12px">המערכת רק ממליצה. שום דבר לא מוגש בלי אישור שלכם.</p>'
        "</div>"
    )
    return {
        "from": EMAIL_FROM,
        "to": get_setting(s, "recipient"),
        "subject": f"מכרזי הזנה: {len(tenders)} חדשים שעשויים להתאים",
        "html": html,
    }


def mark_notified(s: Session, ids: list[int]) -> int:
    tenders = s.scalars(select(Tender).where(Tender.id.in_(ids))).all()
    for t in tenders:
        t.notified = True
    s.commit()
    return len(tenders)
