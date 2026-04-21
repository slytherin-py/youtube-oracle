# YouTube Oracle

A live ML system that predicts YouTube video virality at the 6-hour mark and publicly logs every prediction for honest accuracy validation.

**Status:** Week 1 — ingestion scaffolding.

---

## What this does right now

Two scripts:

1. `ingestion/collect.py` — every hour, finds YouTube videos that are ~6 hours old, captures their feature snapshot (views, likes, comments, channel stats, title, category, etc.), stores them in SQLite.
2. `ingestion/backfill_outcomes.py` — every day, re-checks videos that are now 7+ days old and records their final stats. Labels them viral (500K+ views) or not.

These two together build the labeled training dataset.

---

## One-time setup (do this today)

### 1. Get a YouTube Data API key

1. Go to https://console.cloud.google.com/
2. Create a new project (name it `youtube-oracle`)
3. In the left nav: **APIs & Services → Library**
4. Search for "YouTube Data API v3", click **Enable**
5. Go to **APIs & Services → Credentials**
6. Click **Create Credentials → API Key**
7. Copy the key

Free tier: 10,000 units/day. Each `collect.py` run costs ~200 units, so an hourly cron uses ~4,800 units/day. Plenty of headroom.

### 2. Local install

```bash
cd youtube-oracle
python -m venv .venv
source .venv/bin/activate          # on Windows: .venv\Scripts\activate
pip install -r ingestion/requirements.txt
cp .env.example .env
# open .env and paste your API key
```

### 3. First run (verify it works)

```bash
python ingestion/collect.py
```

You should see log output like:
```
  Music: 42 candidates
  Gaming: 50 candidates
  ...
47 new videos to process
Inserted 47 new videos
```

Check the data:
```bash
sqlite3 data/videos.db "SELECT COUNT(*), category_name FROM videos GROUP BY category_name;"
```

---

## Running it continuously

The whole point is that this runs *now* so by week 3 you have labeled data. Two options:

### Option A — your laptop (fine for now)

Add to crontab (`crontab -e`):
```
0 * * * * cd /path/to/youtube-oracle && /path/to/.venv/bin/python ingestion/collect.py >> data/collect.log 2>&1
0 8 * * * cd /path/to/youtube-oracle && /path/to/.venv/bin/python ingestion/backfill_outcomes.py >> data/backfill.log 2>&1
```

Your laptop must be on and awake at those times. Works if you're the kind of person who keeps your machine running overnight.

### Option B — Railway (recommended)

Deploy the ingestion folder as a scheduled service on Railway. Free tier handles this easily. I'll write the Railway config in Week 2 when we wire up the backend — for now laptop cron is fine.

---

## What's next

- **This week:** let the collector run, get the Kaggle dataset, train a v0 XGBoost model in a notebook.
- **Week 2:** add Tier 2 features (title LLM analysis, thumbnail vision features), build the FastAPI backend and the React frontend.
- **Week 3:** swap in our own data, build the public scorecard.
- **Week 4:** launch, LinkedIn post, recruiter outreach.

---

## Design decisions worth noting

- **Viral threshold = 500K views in 7 days.** Rare enough to be meaningful, common enough to have training signal.
- **Catch at 6 hours (±45 min).** Early enough to feel predictive, late enough for signal to show up.
- **Min 1K views at catch** — filters the long tail; the model should focus on videos that already have some traction.
- **English, US region, 9 major categories** — keeps scope tight for v1.
