import hmac
import re
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .config import ADMIN_TOKEN
from .db import AGENTS, AgentSetting, Decision, Run, SessionLocal, Tender, TenderScore, get_setting, init_db, set_setting, utcnow
from .orchestrator import mark_notified, run_pipeline

app = FastAPI(title="Tender Agents")
UI_HTML = (Path(__file__).parent / "ui.html").read_text(encoding="utf-8")


@app.on_event("startup")
def _startup() -> None:
    init_db()


def session():
    with SessionLocal() as s:
        yield s


def require_admin(authorization: str = Header(default="")) -> None:
    if len(ADMIN_TOKEN) < 12:
        raise HTTPException(503, "ADMIN_TOKEN לא הוגדר בשרת")
    given = authorization.removeprefix("Bearer ")
    if not hmac.compare_digest(given.encode(), ADMIN_TOKEN.encode()):
        raise HTTPException(401, "סיסמת מנהל שגויה")


@app.middleware("http")
async def security_headers(request, call_next):
    res = await call_next(request)
    res.headers["X-Content-Type-Options"] = "nosniff"
    res.headers["X-Frame-Options"] = "DENY"
    res.headers["Referrer-Policy"] = "no-referrer"
    return res


@app.get("/", response_class=HTMLResponse)
def ui():
    return UI_HTML


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/state")
def state(s: Session = Depends(session)):
    settings = {a.name: a for a in s.scalars(select(AgentSetting))}
    agents = [
        {"name": n, "label": label, "description": d, "available": avail, "enabled": settings[n].enabled if n in settings else False}
        for n, label, d, avail in AGENTS
    ]
    tenders = s.scalars(
        select(Tender)
        .join(TenderScore)
        .options(selectinload(Tender.score), selectinload(Tender.decision))
        .where(TenderScore.score > 0)
        .order_by(TenderScore.relevant.desc(), TenderScore.score.desc(), Tender.found_at.desc())
        .limit(100)
    ).all()
    runs = s.scalars(select(Run).order_by(Run.id.desc()).limit(10)).all()
    return {
        "agents": agents,
        "recipient": get_setting(s, "recipient"),
        "tenders": [
            {
                "id": t.id,
                "title": t.title,
                "publisher": t.publisher,
                "source": t.source,
                "deadline": t.deadline.isoformat() if t.deadline else None,
                "url": t.url,
                "score": t.score.score,
                "relevant": t.score.relevant,
                "reasons": t.score.reasons,
                "baseline": t.baseline,
                "decision": t.decision.decision if t.decision else None,
            }
            for t in tenders
        ],
        "total_tenders": s.query(Tender).count(),
        "runs": [{"id": r.id, "started_at": r.started_at.isoformat(), "summary": r.summary} for r in runs],
    }


class Toggle(BaseModel):
    enabled: bool


@app.post("/api/agents/{name}", dependencies=[Depends(require_admin)])
def toggle_agent(name: str, body: Toggle, s: Session = Depends(session)):
    row = s.get(AgentSetting, name)
    if row is None:
        raise HTTPException(404, "סוכן לא קיים")
    row.enabled = body.enabled
    row.updated_at = utcnow()
    s.commit()
    return {"name": name, "enabled": row.enabled}


class Recipient(BaseModel):
    email: str


@app.post("/api/recipient", dependencies=[Depends(require_admin)])
def update_recipient(body: Recipient, s: Session = Depends(session)):
    email = body.email.strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(400, "כתובת מייל לא תקינה")
    set_setting(s, "recipient", email)
    s.commit()
    return {"recipient": email}


class DecisionIn(BaseModel):
    decision: str
    note: str | None = None


@app.post("/api/tenders/{tender_id}/decision", dependencies=[Depends(require_admin)])
def decide(tender_id: int, body: DecisionIn, s: Session = Depends(session)):
    if body.decision not in ("approved", "rejected"):
        raise HTTPException(400, "decision must be approved or rejected")
    if s.get(Tender, tender_id) is None:
        raise HTTPException(404, "מכרז לא קיים")
    row = s.get(Decision, tender_id)
    if row:
        row.decision, row.note, row.decided_at = body.decision, body.note, utcnow()
    else:
        s.add(Decision(tender_id=tender_id, decision=body.decision, note=body.note))
    s.commit()
    return {"tender_id": tender_id, "decision": body.decision}


@app.post("/api/run", dependencies=[Depends(require_admin)])
def run(s: Session = Depends(session)):
    """Called by n8n every morning. Runs the enabled agents and returns the email to send."""
    return run_pipeline(s)


class Ids(BaseModel):
    ids: list[int]


@app.post("/api/mark-notified", dependencies=[Depends(require_admin)])
def notified(body: Ids, s: Session = Depends(session)):
    """Called by n8n after the email was sent successfully."""
    return {"marked": mark_notified(s, body.ids)}
