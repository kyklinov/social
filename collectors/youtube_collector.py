"""
youtube_collector.py — v1.4

Сбор статистики канала YouTube через YouTube Data API v3 + YouTube Analytics API.

Что собирает:
- рост числа подписчиков -> history.json
- топ-10 видео по просмотрам за всё время
- демография (возраст/пол), география, тип устройства за последние 28 дней
- источники трафика (откуда приходят зрители)
- глубина просмотра (watch time, средняя длительность, % досмотра)
- показы превью и CTR
- приток/отток подписчиков раздельно
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


def get_all_public_videos(youtube, uploads_playlist_id):
    """Полный проход по плейлисту загрузок — забирает ВСЕ видео канала
    (не ограничиваясь последними N), затем оставляет только публичные."""
    video_ids = []
    page_token = None
    while True:
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
        resp = youtube.videos().list(
            part="statistics,snippet,status", id=",".join(batch)
        ).execute()
        videos += resp.get("items", [])

    public_videos = [v for v in videos if v.get("status", {}).get("privacyStatus") == "public"]

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
        for v in public_videos
    ]


def build_top_lists(all_videos, recent_days=30, recent_count=10):
    all_time_sorted = sorted(all_videos, key=lambda v: v["views"], reverse=True)

    cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=recent_days))
    recent = [
        v for v in all_videos
        if datetime.datetime.fromisoformat(v["published_at"].replace("Z", "+00:00")) >= cutoff
    ]
    recent_sorted = sorted(recent, key=lambda v: v["views"], reverse=True)[:recent_count]

    return all_time_sorted, recent_sorted


def safe_query(youtube_analytics, **kwargs):
    """Некоторые метрики (например, показы) доступны не на всех каналах —
    не роняем весь сбор, если конкретный запрос отклонён."""
    try:
        return youtube_analytics.reports().query(**kwargs).execute()
    except Exception as e:
        print(f"Предупреждение: запрос аналитики не выполнен ({kwargs.get('metrics')}): {e}")
        return {"rows": []}


def get_analytics(youtube_analytics, channel_id, days=28):
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=days)).isoformat()
    end = today.isoformat()
    ids = f"channel=={channel_id}"

    age_gender = safe_query(
        youtube_analytics, ids=ids, startDate=start, endDate=end,
        metrics="viewerPercentage", dimensions="ageGroup,gender",
    )

    geography = safe_query(
        youtube_analytics, ids=ids, startDate=start, endDate=end,
        metrics="views", dimensions="country", sort="-views", maxResults=10,
    )

    devices = safe_query(
        youtube_analytics, ids=ids, startDate=start, endDate=end,
        metrics="views", dimensions="deviceType",
    )

    operating_systems = safe_query(
        youtube_analytics, ids=ids, startDate=start, endDate=end,
        metrics="views", dimensions="operatingSystem", sort="-views", maxResults=15,
    )

    traffic_sources = safe_query(
        youtube_analytics, ids=ids, startDate=start, endDate=end,
        metrics="views", dimensions="insightTrafficSourceType", sort="-views", maxResults=10,
    )

    engagement = safe_query(
        youtube_analytics, ids=ids, startDate=start, endDate=end,
        metrics="estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained,subscribersLost",
    )

    impressions = safe_query(
        youtube_analytics, ids=ids, startDate=start, endDate=end,
        metrics="impressions,impressionsClickThroughRate",
    )

    subscribed_status = safe_query(
        youtube_analytics, ids=ids, startDate=start, endDate=end,
        metrics="views", dimensions="subscribedStatus",
    )

    sharing_services = safe_query(
        youtube_analytics, ids=ids, startDate=start, endDate=end,
        metrics="shares", dimensions="sharingService", sort="-shares", maxResults=10,
    )

    engagement_rows = engagement.get("rows") or [[0, 0, 0, 0, 0]]
    impressions_rows = impressions.get("rows") or [[0, 0]]
    engagement_row = engagement_rows[0]
    impressions_row = impressions_rows[0]

    return {
        "age_gender": age_gender.get("rows", []),
        "geography": geography.get("rows", []),
        "devices": devices.get("rows", []),
        "operating_systems": operating_systems.get("rows", []),
        "traffic_sources": traffic_sources.get("rows", []),
        "subscribed_status": subscribed_status.get("rows", []),
        "sharing_services": sharing_services.get("rows", []),
        "engagement": {
            "estimated_minutes_watched": engagement_row[0],
            "average_view_duration_seconds": engagement_row[1],
            "average_view_percentage": engagement_row[2],
            "subscribers_gained": engagement_row[3],
            "subscribers_lost": engagement_row[4],
        },
        "impressions": {
            "impressions": impressions_row[0],
            "click_through_rate": impressions_row[1],
        },
    }


def get_retention(youtube_analytics, channel_id, video_id, published_at):
    """Кривая удержания для одного видео: на какой секунде зрители уходят.
    Диапазон дат — с момента публикации видео до сегодня, чтобы захватить
    все просмотры за всё время его существования."""
    start = published_at[:10]
    end = datetime.date.today().isoformat()
    ids = f"channel=={channel_id}"

    resp = safe_query(
        youtube_analytics, ids=ids, startDate=start, endDate=end,
        metrics="audienceWatchRatio,relativeRetentionPerformance",
        dimensions="elapsedVideoTimeRatio",
        filters=f"video=={video_id}",
    )
    return resp.get("rows", [])


def main():
    creds = get_credentials()
    youtube = build("youtube", "v3", credentials=creds)
    youtube_analytics = build("youtubeAnalytics", "v2", credentials=creds)

    channel = get_channel_info(youtube)
    channel_id = channel["id"]
    subscriber_count = int(channel["statistics"].get("subscriberCount", 0))
    uploads_playlist = channel["contentDetails"]["relatedPlaylists"]["uploads"]

    all_videos = get_all_public_videos(youtube, uploads_playlist)
    all_time_videos, top_videos_30d = build_top_lists(all_videos)
    analytics = get_analytics(youtube_analytics, channel_id)

    retention_video = (top_videos_30d[0] if top_videos_30d else
                        (all_time_videos[0] if all_time_videos else None))
    if retention_video:
        retention_curve = get_retention(
            youtube_analytics, channel_id,
            retention_video["id"], retention_video["published_at"],
        )
        analytics["retention"] = {
            "video_id": retention_video["id"],
            "video_title": retention_video["title"],
            "video_url": retention_video["url"],
            "curve": retention_curve,
        }
    else:
        analytics["retention"] = {"video_id": None, "video_title": None, "video_url": None, "curve": []}

    today = datetime.date.today().isoformat()

    os.makedirs(DATA_DIR, exist_ok=True)

    latest = {
        "date": today,
        "subscriber_count": subscriber_count,
        "view_count": int(channel["statistics"].get("viewCount", 0)),
        "video_count": int(channel["statistics"].get("videoCount", 0)),
        "top_videos_30d": top_videos_30d,
        "all_time_videos": all_time_videos,
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
