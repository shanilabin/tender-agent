# Tender Agents

A chain of agents that finds Israeli public tenders for catering (kindergartens, afternoon programs,
schools, hospitals, government), scores them against the business profile, and emails a daily summary
for human approval. **Nothing is ever submitted automatically.** Full spec (Hebrew): [SPEC.md](SPEC.md).

| Agent | Version | Uses AI tokens |
|---|---|---|
| Scanner — collects new tenders from checked sources | 1 ✅ | No |
| Filter — keyword score against `config/profile.json` | 1 ✅ | No |
| Analyzer, Menu Checker (via [kids-nutrition-mcp](https://github.com/shanilabin/kids-nutrition-mcp)), Writer | 2 | Yes |

Every agent can be paused or activated from the admin page. All agents start **paused**.

Stack: Python 3.12, FastAPI, SQLAlchemy (SQLite locally, Supabase Postgres in production), n8n for
scheduling and email.

## Run locally
```bash
uv sync
cp .env.example .env              # set ADMIN_TOKEN (long random), DEFAULT_RECIPIENT, EMAIL_FROM
uv run uvicorn app.main:app --port 8000
uv run pytest                     # tests
```
Open http://localhost:8000, enter the admin token, switch on Scanner and Filter, press "הרצה עכשיו".
The first scan of each source is stored as a baseline and is not emailed; only later additions are.

## n8n (daily schedule + email)
```bash
cd n8n && npm install && npx n8n start        # http://localhost:5678
```
1. Import `n8n/daily-tenders.workflow.json` (Workflows → Import from file).
2. Create two credentials:
   - **Header Auth** named "Tender agents admin token": name `Authorization`, value `Bearer <ADMIN_TOKEN>`.
   - **SMTP** named "Gmail SMTP": host `smtp.gmail.com`, port 465, SSL on, user = your Gmail,
     password = a Gmail **App Password** (Google account → Security → App passwords).
3. Activate the workflow. It runs Sunday–Friday at 08:00 Israel time (inside mr.gov.il's allowed hours).

## Sources
See the table in [SPEC.md](SPEC.md). Only sources with a checked API or robots.txt are scanned, once a day,
with polite pacing.
