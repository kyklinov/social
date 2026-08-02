"""
Сбор статистики сообщества VK через официальный VK API.

Что собирает:
- рост числа подписчиков (members_count) -> history.json (для графика динамики)
- охват, посетители, демография (пол/возраст), география, доля мобильных
  посетителей за последние 7 дней -> latest.json
- топ-10 публикаций за последние 100 постов по вовлечённости (лайки+репосты+комменты)

Что VK API НЕ отдаёт (честное ограничение):
- Детальную статистику обработки сообщений в сообществе (кто ответил, как быстро)
  нельзя получить через stats.get. Для этого нужен отдельный трекинг через
  Callback API или messages.getConversations с токеном, имеющим scope "messages".
  Это можно добавить отдельным шагом, если понадобится.

Требуемые переменные окружения:
  VK_TOKEN     — токен сообщества (Групповой токен доступа) с правом "stats"
                 Настройки сообщества -> Работа с API -> Создать ключ доступа
  VK_GROUP_ID  — числовой ID сообщества БЕЗ минуса (например 123456789)
"""

import os
import json
import datetime
import requests

VK_TOKEN = os.environ["VK_TOKEN"]
GROUP_ID = os.environ["VK_GROUP_ID"]
API_VERSION = "5.199"
BASE_URL = "https://api.vk.com/method"

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "vk")


def vk_call(method, **params):
    params.update({"access_token": VK_TOKEN, "v": API_VERSION})
    resp = requests.get(f"{BASE_URL}/{method}", params=params, timeout=30)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"VK API error in {method}: {data['error']}")
    return data["response"]


def get_stats():
    """Статистика за последние 7 дней: охват, демография, гео, устройства."""
    today = datetime.date.today()
    date_from = (today - datetime.timedelta(days=7)).isoformat()
    date_to = today.isoformat()
    return vk_call(
        "stats.get",
        group_id=GROUP_ID,
        date_from=date_from,
        date_to=date_to,
        extended=1,
    )


def get_group_info():
    return vk_call("groups.getById", group_id=GROUP_ID, fields="members_count")


def get_top_posts(count=10, scan=100):
    posts = vk_call("wall.get", owner_id=f"-{GROUP_ID}", count=scan)["items"]
    posts_sorted = sorted(
        posts,
        key=lambda p: p.get("likes", {}).get("count", 0)
        + p.get("reposts", {}).get("count", 0)
        + p.get("comments", {}).get("count", 0),
        reverse=True,
    )[:count]
    return [
        {
            "id": p["id"],
            "date": datetime.datetime.utcfromtimestamp(p["date"]).isoformat(),
            "text": (p.get("text") or "")[:200],
            "likes": p.get("likes", {}).get("count", 0),
            "reposts": p.get("reposts", {}).get("count", 0),
            "comments": p.get("comments", {}).get("count", 0),
            "views": p.get("views", {}).get("count", 0),
            "url": f"https://vk.com/wall-{GROUP_ID}_{p['id']}",
        }
        for p in posts_sorted
    ]


def main():
    today = datetime.date.today().isoformat()
    stats = get_stats()
    info = get_group_info()[0]
    top_posts = get_top_posts()

    snapshot = {
        "date": today,
        "members_count": info.get("members_count"),
        "stats": stats,
        "top_posts": top_posts,
    }

    os.makedirs(DATA_DIR, exist_ok=True)

    latest_path = os.path.join(DATA_DIR, "latest.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    history_path = os.path.join(DATA_DIR, "history.json")
    history = []
    if os.path.exists(history_path):
        with open(history_path, "r", encoding="utf-8") as f:
            history = json.load(f)

    history = [h for h in history if h["date"] != today]
    history.append({"date": today, "members_count": info.get("members_count")})
    history.sort(key=lambda h: h["date"])

    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    print(f"Сохранён снимок за {today}: {info.get('members_count')} подписчиков")


if __name__ == "__main__":
    main()
