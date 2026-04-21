"""
YouTube Oracle - FastAPI Backend
"""

import os
import re
import logging
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import requests
import shap
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("YOUTUBE_API_KEY")
MODEL_PATH = Path(__file__).parent.parent / "models" / "v0_xgboost.pkl"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("backend")

if not MODEL_PATH.exists():
    raise RuntimeError(f"Model not found at {MODEL_PATH}. Run notebooks/train_v0.ipynb first.")

log.info(f"Loading model from {MODEL_PATH}")
_bundle = joblib.load(MODEL_PATH)
MODEL = _bundle["model"]
FEATURE_COLS = _bundle["feature_cols"]
VIRAL_THRESHOLD = _bundle["viral_threshold"]
TRAINED_ON = _bundle.get("trained_on", "unknown")
TEST_AUC = _bundle.get("test_auc", None)
log.info(f"Model loaded. {len(FEATURE_COLS)} features, AUC={TEST_AUC}")

EXPLAINER = shap.TreeExplainer(MODEL)

app = FastAPI(title="YouTube Oracle", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class ScoreRequest(BaseModel):
    video: str = Field(..., description="YouTube video ID or URL")


class FeatureContribution(BaseModel):
    feature: str
    value: float
    shap: float


class ScoreResponse(BaseModel):
    video_id: str
    title: str
    channel: str
    category: str
    probability: float
    verdict: str
    base_rate: float
    top_contributions: list[FeatureContribution]
    metadata: dict


YOUTUBE_ID_RE = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})")


def extract_video_id(text: str) -> str:
    text = text.strip()
    if len(text) == 11 and re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
        return text
    m = YOUTUBE_ID_RE.search(text)
    if m:
        return m.group(1)
    raise HTTPException(status_code=400, detail=f"Could not extract YouTube video ID from: {text!r}")


def fetch_video(video_id: str) -> dict:
    if not API_KEY:
        raise HTTPException(status_code=500, detail="YOUTUBE_API_KEY not configured")
    r = requests.get(
        "https://www.googleapis.com/youtube/v3/videos",
        params={"part": "snippet,statistics,contentDetails", "id": video_id, "key": API_KEY},
        timeout=10,
    )
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"YouTube API error {r.status_code}")
    items = r.json().get("items", [])
    if not items:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found or private")
    return items[0]


def build_feature_row(video: dict) -> pd.DataFrame:
    snippet = video["snippet"]
    stats = video.get("statistics", {})

    title = snippet.get("title", "") or ""
    description = snippet.get("description", "") or ""
    tags = snippet.get("tags", []) or []
    category_id = int(snippet.get("categoryId", 0))

    views = int(stats.get("viewCount", 0))
    likes = int(stats.get("likeCount", 0))
    dislikes = 0
    comments = int(stats.get("commentCount", 0))

    published_at = snippet.get("publishedAt", "")
    try:
        pub_dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except Exception:
        pub_dt = datetime.now(timezone.utc)
    now = datetime.now(timezone.utc)
    hours_to_trending = max((now - pub_dt).total_seconds() / 3600, 0.0)

    features = {
        "title_length": len(title),
        "title_word_count": len(title.split()),
        "title_has_question": int("?" in title),
        "title_has_exclaim": int("!" in title),
        "title_caps_ratio": sum(1 for c in title if c.isupper()) / max(len(title), 1),
        "title_has_number": int(bool(re.search(r"\d", title))),
        "publish_hour": pub_dt.hour,
        "publish_dayofweek": pub_dt.weekday(),
        "publish_is_weekend": int(pub_dt.weekday() >= 5),
        "category_id": category_id,
        "tag_count": len(tags),
        "description_length": len(description),
        "description_has_link": int("http" in description),
        "views": views,
        "likes": likes,
        "dislikes": dislikes,
        "comment_count": comments,
        "like_rate": likes / (views + 1),
        "comment_rate": comments / (views + 1),
        "dislike_rate": dislikes / (views + 1),
        "hours_to_trending": hours_to_trending,
    }
    return pd.DataFrame([[features[c] for c in FEATURE_COLS]], columns=FEATURE_COLS)


def verdict_from_prob(p: float) -> str:
    if p >= 0.75: return "Strong viral signal"
    if p >= 0.55: return "Likely viral"
    if p >= 0.35: return "Uncertain"
    if p >= 0.15: return "Unlikely to go viral"
    return "Very unlikely to go viral"


@app.get("/")
def root():
    return {
        "name": "YouTube Oracle",
        "version": "0.1.0",
        "model": {"trained_on": TRAINED_ON, "test_auc": TEST_AUC, "features": len(FEATURE_COLS)},
        "endpoints": ["/", "/health", "POST /score"],
    }


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": True}


@app.post("/score", response_model=ScoreResponse)
def score(req: ScoreRequest):
    video_id = extract_video_id(req.video)
    log.info(f"Scoring video {video_id}")
    video = fetch_video(video_id)

    X = build_feature_row(video)
    prob = float(MODEL.predict_proba(X)[0, 1])

    shap_vals = EXPLAINER.shap_values(X)[0]
    contributions = [
        FeatureContribution(feature=col, value=float(X.iloc[0][col]), shap=float(sv))
        for col, sv in zip(FEATURE_COLS, shap_vals)
    ]
    contributions.sort(key=lambda c: abs(c.shap), reverse=True)

    snippet = video["snippet"]
    base = EXPLAINER.expected_value
    return ScoreResponse(
        video_id=video_id,
        title=snippet.get("title", ""),
        channel=snippet.get("channelTitle", ""),
        category=str(snippet.get("categoryId", "")),
        probability=prob,
        verdict=verdict_from_prob(prob),
        base_rate=float(base) if np.isscalar(base) else float(base[0]),
        top_contributions=contributions[:8],
        metadata={
            "current_views": int(video.get("statistics", {}).get("viewCount", 0)),
            "current_likes": int(video.get("statistics", {}).get("likeCount", 0)),
            "published_at": snippet.get("publishedAt"),
            "model_auc_on_holdout": TEST_AUC,
            "note": "Trained on 2017-18 Kaggle. Dislikes always 0 (API change). Will retrain on live data in Week 3.",
        },
    )