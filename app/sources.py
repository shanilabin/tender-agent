"""Tender sources. Each source returns RawTender items; the Scanner stores the new ones.

Rules (see SPEC.md): only sources whose API / robots.txt we checked, once a day, polite pacing.
"""

import html
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from urllib.parse import urlencode, urljoin

import httpx
from bs4 import BeautifulSoup

from .config import USER_AGENT


@dataclass
class RawTender:
    external_id: str
    title: str
    url: str | None = None
    publisher: str | None = None
    deadline: date | None = None
    raw: dict = field(default_factory=dict)


def parse_il_date(value: str | None) -> date | None:
    """Parses dd/mm/yyyy (optionally followed by a time)."""
    m = re.search(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})", value or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip()


class BeerShevaSource:
    """Be'er Sheva municipality tenders — official open dataset on data.gov.il (CKAN API)."""

    name = "beersheva"
    label = "עיריית באר שבע (data.gov.il)"
    api = "https://data.gov.il/api/3/action/datastore_search"
    resource_id = "6a281768-6327-420b-a1c5-fb84af1fa8ae"

    def fetch(self, client: httpx.Client) -> tuple[list[RawTender], str | None]:
        res = client.get(self.api, params={"resource_id": self.resource_id, "limit": 2000})
        res.raise_for_status()
        out = []
        for r in res.json()["result"]["records"]:
            title = clean(r.get("שם מכרז"))
            if not title:
                continue
            url = r.get("URL") or None
            m = re.search(r"ID=(\d+)", url or "")
            out.append(
                RawTender(
                    external_id=m.group(1) if m else f"row-{r['_id']}",
                    title=title,
                    url=url,
                    publisher="עיריית באר שבע",
                    deadline=parse_il_date(r.get("תאריך אחרון להגשה")),
                    raw={"number": clean(r.get("מספר מכרז")), "winner": clean(r.get("זוכה במכרז"))},
                )
            )
        return out, None


class GovProcurementSource:
    """Government procurement administration (mr.gov.il).

    No API or RSS exists. robots.txt (ilgstorefront) asks for Crawl-delay 10 and
    Visit-time 04:00-08:45 UTC, so we only run inside that window, one keyword search
    at a time, 10+ seconds apart, reading the results page only.
    """

    name = "mrgov"
    label = "מנהל הרכש הממשלתי (mr.gov.il)"
    base = "https://mr.gov.il/ilgstorefront/he/search/"
    keywords = ["הזנה", "הסעדה", "ארוחות", "מזון", "צהרונים", "מילגם", "מאפים"]
    delay_seconds = 11

    @staticmethod
    def in_visit_window(now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        minutes = now.hour * 60 + now.minute
        return 4 * 60 <= minutes <= 8 * 60 + 45

    @staticmethod
    def parse_results(page_html: str, page_url: str) -> list[RawTender]:
        """Extracts tender links (/p/{10 digits}) from a search results page.

        NOTE: written against the URL pattern only; verify against the live page
        (see SPEC.md, open items) and extend with deadline / publisher if available.
        """
        soup = BeautifulSoup(page_html, "html.parser")
        found: dict[str, RawTender] = {}
        for a in soup.find_all("a", href=True):
            m = re.search(r"/ilgstorefront/he/p/(\d{10})(?:[/?#]|$)", a["href"])
            if not m:
                continue
            title = clean(a.get_text(" "))
            if len(title) < 5:
                continue
            ext = m.group(1)
            if ext not in found or len(title) > len(found[ext].title):
                found[ext] = RawTender(external_id=ext, title=title, url=urljoin(page_url, a["href"]))
        return list(found.values())

    def fetch(self, client: httpx.Client) -> tuple[list[RawTender], str | None]:
        if not self.in_visit_window():
            return [], "דילוג: מחוץ לשעות שהאתר מתיר לרובוטים (06:00–10:45 שעון ישראל)"
        out: dict[str, RawTender] = {}
        for i, kw in enumerate(self.keywords):
            if i:
                time.sleep(self.delay_seconds)
            url = f"{self.base}?{urlencode({'s': 'TENDER', 'text': kw})}"
            res = client.get(url)
            res.raise_for_status()
            for t in self.parse_results(res.text, url):
                out.setdefault(t.external_id, t)
        return list(out.values()), None


SOURCES = [BeerShevaSource(), GovProcurementSource()]


def http_client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True)
