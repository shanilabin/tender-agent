from datetime import date, datetime, timezone

from app.agents import load_profile, score_title
from app.sources import GovProcurementSource, parse_il_date

PROFILE = load_profile()


def score(title: str) -> int:
    return score_title(title, PROFILE)[0]


def test_hot_meals_for_schools_is_relevant():
    assert score("הכנה ואספקת ארוחות חמות למוסדות החינוך המיוחד") >= PROFILE["relevance_threshold"]


def test_afternoon_program_meals_is_relevant():
    assert score("מכרז לאספקת ארוחות צהריים לצהרונים") >= PROFILE["relevance_threshold"]


def test_animal_food_is_not_relevant():
    assert score("לאספקה של מזון, ציוד רפואי ותרופות לבעלי חיים") < PROFILE["relevance_threshold"]


def test_land_sale_is_not_relevant():
    assert score("הזמנה לקבלת הצעות לרכישת מגרשים 103, 104") == 0


def test_longer_keyword_not_double_counted():
    _, reasons = score_title("ארוחות חמות", PROFILE)
    assert reasons == ["ארוחות חמות (+35)"]


def test_parse_il_date():
    assert parse_il_date("01/12/2026 23:55:00") == date(2026, 12, 1)
    assert parse_il_date("") is None


def test_visit_window():
    assert GovProcurementSource.in_visit_window(datetime(2026, 11, 27, 5, 30, tzinfo=timezone.utc))
    assert not GovProcurementSource.in_visit_window(datetime(2026, 11, 27, 19, 0, tzinfo=timezone.utc))


def test_parse_results_finds_tender_links():
    html = """
      <a href="/ilgstorefront/he/p/4000624975">מכרז לאספקת ארוחות חמות לגני ילדים</a>
      <a href="/ilgstorefront/he/p/4000624975"><img></a>
      <a href="/ilgstorefront/he/search/?s=TENDER">חיפוש</a>
    """
    items = GovProcurementSource.parse_results(html, "https://mr.gov.il/ilgstorefront/he/search/")
    assert len(items) == 1
    assert items[0].external_id == "4000624975"
    assert items[0].url == "https://mr.gov.il/ilgstorefront/he/p/4000624975"
