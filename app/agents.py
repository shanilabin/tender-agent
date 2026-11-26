"""The agents. Version 1: Scanner and Filter — plain code, no AI tokens.
Analyzer, Menu Checker and Writer arrive in version 2 (they will use Claude via PydanticAI).
"""

import json
import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import PROFILE_PATH
from .db import Tender, TenderScore, utcnow
from .sources import SOURCES, http_client

log = logging.getLogger(__name__)


# ---------- Agent 1: Scanner ----------
def run_scanner(s: Session) -> dict:
    """Fetches every source and stores tenders not seen before.

    The first time a source is scanned, everything it returns is stored as `baseline`
    (so we don't email years of old tenders); only later additions count as new.
    """
    report = {}
    with http_client() as client:
        for src in SOURCES:
            try:
                items, note = src.fetch(client)
            except Exception as e:  # one broken source must not stop the others
                log.exception("source %s failed", src.name)
                report[src.name] = {"label": src.label, "error": str(e)[:300]}
                continue
            first_run = s.scalar(select(Tender.id).where(Tender.source == src.name).limit(1)) is None
            known = set(s.scalars(select(Tender.external_id).where(Tender.source == src.name)))
            new = 0
            for t in items:
                if t.external_id in known:
                    continue
                known.add(t.external_id)
                s.add(
                    Tender(
                        source=src.name,
                        external_id=t.external_id,
                        title=t.title,
                        url=t.url,
                        publisher=t.publisher,
                        deadline=t.deadline,
                        raw=t.raw,
                        baseline=first_run,
                    )
                )
                new += 1
            s.commit()
            report[src.name] = {"label": src.label, "fetched": len(items), "new": new, "baseline": first_run}
            if note:
                report[src.name]["note"] = note
    return report


# ---------- Agent 2: Filter ----------
def load_profile() -> dict:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def score_title(text: str, profile: dict) -> tuple[int, list[str]]:
    """Keyword score 0-100 with the reasons that produced it.

    Longer keywords are matched first and their text is consumed, so "ארוחות חמות"
    is not counted again as "ארוחות".
    """
    remaining = f" {text} "
    score = 0
    reasons: list[str] = []
    groups = ["positive_keywords", "client_keywords", "kashrut_keywords", "negative_keywords"]
    for group in groups:
        for kw, pts in sorted(profile.get(group, {}).items(), key=lambda kv: -len(kv[0])):
            if kw in remaining:
                score += pts
                reasons.append(f"{kw} ({'+' if pts > 0 else ''}{pts})")
                remaining = remaining.replace(kw, " ")
    return max(0, min(100, score)), reasons


def run_filter(s: Session, today: date | None = None) -> dict:
    """Scores every tender that has no score yet."""
    profile = load_profile()
    threshold = int(profile.get("relevance_threshold", 40))
    today = today or date.today()
    pending = s.scalars(select(Tender).where(~Tender.score.has())).all()
    relevant = 0
    for t in pending:
        score, reasons = score_title(t.title, profile)
        expired = t.deadline is not None and t.deadline < today
        if expired:
            reasons.append("מועד ההגשה עבר")
        is_relevant = score >= threshold and not expired
        relevant += is_relevant
        s.add(TenderScore(tender_id=t.id, score=score, relevant=is_relevant, reasons=reasons, scored_at=utcnow()))
    s.commit()
    return {"scored": len(pending), "relevant": relevant, "threshold": threshold}
