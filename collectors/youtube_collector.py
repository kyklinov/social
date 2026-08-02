"""
Сбор статистики канала YouTube через YouTube Data API v3 + YouTube Analytics API.
"""

import os
import json
import datetime

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

CLIENT_ID = os.environ["YOUTUBE_CLIENT_ID"]
CLIENT_SECRET = os.environ["YOUTUBE_CLIENT_SECRET"]
REFRESH_TOKEN = os.environ["YOUTUBE_REFRESH_TOKEN"]
CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "").strip() or None

TOKEN_URI = "https://oauth2.googleapis.com/token"
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "data", "youtube")


def get_credentials():
    creds = Credentials(
        token=None,
        refresh_token=REFRESH_TOKEN,
        token_uri=TOKEN_URI,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
    )
    creds.refresh(Request())
    return creds


def get_channel_info(youtube):
    kwargs = {"part": "statistics,snippet,contentDetails"}
    if CHANNEL_ID:
        kwargs["id"] = CHANNEL_ID
    else:
        kwargs["mine"] = True
    resp = youtube.channels().list(**kwargs).execute()
    if not resp.get("items"):
        raise RuntimeError("Канал не найден — проверь YOUTUBE_CHANNEL_ID или права доступа")
    return resp["items"][0]


def get_top_videos(youtube, uploads_playlist_id, count=10, scan=50):
    video_ids = []
    page_token = None
    while len(video_ids) < scan:
        resp = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=uploads_playlist_id,
            maxResults=50,
            pageToken=page_token,
        ).execute()
        video_ids += [item["contentDetails"]["videoId"] for item in resp.get("items", [])]
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    videos = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        resp = youtube.videos().list(part="statistics,snippet", id=",".join(batch)).execute()
        videos += resp.get("items", [])

    videos_sorted = sorted(
        videos, key=lambda v: int(v["statistics"].get("viewCount", 0)), reverse=True
    )[:count]

    return [
        {
            "id": v["id"],
            "title": v["snippet"]["title"],
            "published_at": v["snippet"]["publishedAt"],
            "views": int(v["statistics"].get("viewCount", 0)),
            "likes": int(v["statistics"].get("likeCount", 0)),
            "comments": int(v["statistics"].get("commentCount", 0)),
            "url": f"https://youtube.com/watch?v={v['id']}",
        }
        for v in videos_sorted
    ]


def get_analytics(youtube_analytics, channel_id, days=28):
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=days)).isoformat()
    end = today.isoformat()
    ids = f"channel=={channel_id}"

    age_gender = youtube_analytics.reports().query(
        ids=ids, startDate=start, endDate=end,
        metrics="viewerPercentage", dimensions="ageGroup,gender",
    ).execute()

    geography = youtube_analytics.reports().query(
        ids=ids, startDate=start, endDate=end,
        metrics="views", dimensions="country", sort="-views", maxResults=10,
    ).execute()

    devices = youtube_analytics.reports().query(
        ids=ids, startDate=start, endDate=end,
        metrics="views", dimensions="deviceType",
    ).execute()

    return {
        "age_gender": age_gender.get("rows", []),
        "geography": geography.get("rows", []),
        "devices": devices.get("rows", []),
    }


def main():
    creds = get_credentials()
    youtube = build("youtube", "v3", credentials=creds)
    youtube_analytics = build("youtubeAnalytics", "v2", credentials=creds)

    channel = get_channel_info(youtube)
    channel_id = channel["id"]
    subscriber_count = int(channel["statistics"].get("subscriberCount", 0))
    uploads_playlist = channel["contentDetails"]["relatedPlaylists"]["uploads"]

    top_videos = get_top_videos(youtube, uploads_playlist)
    analytics = get_analytics(youtube_analytics, channel_id)

    today = datetime.date.today().isoformat()

    os.makedirs(DATA_DIR, exist_ok=True)

    latest = {
        "date": today,
        "subscriber_count": subscriber_count,
        "view_count": int(channel["statistics"].get("viewCount", 0)),
        "video_count": int(channel["statistics"].get("videoCount", 0)),
        "top_videos": top_videos,
        "analytics": analytics,
    }
    with open(os.path.join(DATA_DIR, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, indent=2)

    history_path = os.path.join(DATA_DIR, "history.json")
    history = []
    if os.path.exists(history_path):
        with open(history_path, "r", encoding="utf-8") as f:
            history = json.load(f)
    history = [h for h in history if h["date"] != today]
    history.append({"date": today, "subscriber_count": subscriber_count})
    history.sort(key=lambda h: h["date"])
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    print(f"Сохранён снимок за {today}: {subscriber_count} подписчиков")


if __name__ == "__main__":
    main()
