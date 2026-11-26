from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from .config import DATABASE_URL, DEFAULT_RECIPIENT


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class AgentSetting(Base):
    __tablename__ = "agent_settings"
    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Tender(Base):
    __tablename__ = "tenders"
    __table_args__ = (UniqueConstraint("source", "external_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(Text)
    publisher: Mapped[str | None] = mapped_column(String(255))
    deadline: Mapped[date | None] = mapped_column(Date)
    url: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    found_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # True for tenders stored on a source's first run: kept for de-duplication, never emailed.
    baseline: Mapped[bool] = mapped_column(Boolean, default=False)
    notified: Mapped[bool] = mapped_column(Boolean, default=False)
    score: Mapped["TenderScore | None"] = relationship(back_populates="tender", uselist=False)
    decision: Mapped["Decision | None"] = relationship(back_populates="tender", uselist=False)


class TenderScore(Base):
    __tablename__ = "tender_scores"
    tender_id: Mapped[int] = mapped_column(ForeignKey("tenders.id", ondelete="CASCADE"), primary_key=True)
    score: Mapped[int] = mapped_column(Integer)
    relevant: Mapped[bool] = mapped_column(Boolean)
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    tender: Mapped[Tender] = relationship(back_populates="score")


class Decision(Base):
    __tablename__ = "decisions"
    tender_id: Mapped[int] = mapped_column(ForeignKey("tenders.id", ondelete="CASCADE"), primary_key=True)
    decision: Mapped[str] = mapped_column(String(16))  # approved | rejected
    note: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    tender: Mapped[Tender] = relationship(back_populates="decision")


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[dict] = mapped_column(JSON, default=dict)


AGENTS = [
    ("scanner", "סורק", "אוסף מכרזים חדשים מהמקורות", True),
    ("filter", "מסנן", "ציון התאמה לפי פרופיל העסק", True),
    ("analyzer", "מנתח", "קריאת מסמכי המכרז (בגרסה 2)", False),
    ("menu_checker", "בודק תפריט", "השוואת התפריט לדרישות דרך שרת התזונה (בגרסה 2)", False),
    ("writer", "מנסח", "המלצה ורשימת משימות (בגרסה 2)", False),
]

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        for name, *_ in AGENTS:
            if s.get(AgentSetting, name) is None:
                s.add(AgentSetting(name=name, enabled=False))  # every agent starts paused
        if s.get(Setting, "recipient") is None:
            s.add(Setting(key="recipient", value=DEFAULT_RECIPIENT))
        s.commit()


def get_setting(s: Session, key: str, default: str = "") -> str:
    row = s.get(Setting, key)
    return row.value if row else default


def set_setting(s: Session, key: str, value: str) -> None:
    row = s.get(Setting, key)
    if row:
        row.value = value
    else:
        s.add(Setting(key=key, value=value))


def enabled_agents(s: Session) -> set[str]:
    return {a.name for a in s.scalars(select(AgentSetting)) if a.enabled}
