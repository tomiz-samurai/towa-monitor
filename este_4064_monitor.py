#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""恵比寿メンズエステ「究極の美爆乳」さんの出勤予定を監視する。

出勤日の追加、または既存の出勤日の時間変更だけを通知する。
状態は este_4064_state.json に保存し、TOWA 監視とは分離する。
"""

import html as html_lib
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import requests

try:
    from zoneinfo import ZoneInfo

    JST = ZoneInfo("Asia/Tokyo")
except Exception:  # pragma: no cover - tzdata が無い環境向け
    JST = timezone(timedelta(hours=9), name="JST")

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

PAGE_URL = "https://mens-este.com/therapist/profile.php?id=4064"
THERAPIST_NAME = "究極の美爆乳"
STATE_FILE = "este_4064_state.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

DATE_RE = re.compile(r"^\d{1,2}月\d{1,2}日[（(][^）)]+[）)]$")
OFF_VALUES = {"", "-", "－", "—", "―", "ー", "休", "休み", "お休み", "未定", "なし", "×"}
SCHEDULE_RE = re.compile(
    r'<div class=["\']prof_schedule["\']>.*?<ul class=["\']prof_weekly["\']>(.*?)</ul>',
    re.S,
)
LI_RE = re.compile(r"<li[^>]*>(.*?)</li>", re.S)
TAG_RE = re.compile(r"<[^>]+>")


def now_jst() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")


def is_test_notify() -> bool:
    return os.environ.get("TEST_NOTIFY", "").strip().lower() in {"1", "true", "yes"}


def normalize_time(value: str) -> str:
    text = str(value).strip()
    text = text.replace("〜", "～").replace("~", "～")
    return re.sub(r"\s+", "", text)


def is_working(value: str) -> bool:
    return normalize_time(value) not in OFF_VALUES


def _li_text(fragment: str) -> str:
    text = TAG_RE.sub("", fragment)
    text = html_lib.unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def parse_schedule(page_html: str) -> dict:
    """出勤予定を {日付ラベル: 時間} にする。取れなければ ValueError。"""
    match = SCHEDULE_RE.search(page_html)
    if not match:
        raise ValueError("出勤予定（ul.prof_weekly）が見つかりません")

    items = [_li_text(raw) for raw in LI_RE.findall(match.group(1))]
    items = [item for item in items if item]
    if len(items) < 2 or len(items) % 2 != 0:
        raise ValueError(f"出勤予定の項目数が不正です: {len(items)}")

    schedule = {}
    for index in range(0, len(items), 2):
        date_label = items[index]
        time_label = items[index + 1]
        if not DATE_RE.match(date_label):
            raise ValueError(f"日付の形式が不正です: {date_label!r}")
        if date_label in schedule:
            raise ValueError(f"日付が重複しています: {date_label}")
        schedule[date_label] = time_label

    if not schedule:
        raise ValueError("出勤予定が空です")
    return schedule


def fetch_schedule() -> dict:
    response = requests.get(PAGE_URL, headers=HEADERS, timeout=30)
    response.raise_for_status()
    if not response.encoding:
        response.encoding = "utf-8"
    return parse_schedule(response.text)


def load_state():
    if not os.path.exists(STATE_FILE):
        return None
    with open(STATE_FILE, "r", encoding="utf-8") as handle:
        return json.load(handle)


def save_state(state: dict) -> None:
    temporary = STATE_FILE + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temporary, STATE_FILE)


def diff_schedule(previous: dict, current: dict) -> list:
    """追加された出勤日と、時間が変わった出勤日だけを返す。"""
    changes = []
    for date_label, time_label in current.items():
        if not is_working(time_label):
            continue
        old = previous.get(date_label)
        if old is None or not is_working(str(old)):
            changes.append({"kind": "new", "date": date_label, "time": time_label})
        elif normalize_time(str(old)) != normalize_time(time_label):
            changes.append(
                {
                    "kind": "changed",
                    "date": date_label,
                    "time": time_label,
                    "previous": str(old),
                }
            )
    return changes


def format_schedule(schedule: dict) -> str:
    return "\n".join(f"{date_label} {time_label}" for date_label, time_label in schedule.items())


def format_change_message(changes: list, checked_at: str) -> str:
    has_new = any(change["kind"] == "new" for change in changes)
    if has_new:
        header = f"🎉 出勤日が追加されました（{THERAPIST_NAME}さん）"
    else:
        header = f"🎉 出勤時間が変更されました（{THERAPIST_NAME}さん）"

    lines = []
    for change in changes:
        if change["kind"] == "new":
            lines.append(f"{change['date']} {change['time']}")
        else:
            lines.append(
                f"{change['date']} {change['time']}（変更前: {change['previous']}）"
            )
    body = "\n".join(lines)
    return (
        f"{header}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{body}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"検出時刻: {checked_at}\n"
        f"{PAGE_URL}"
    )


def format_test_message(schedule: dict) -> str:
    return (
        "🧪 テスト通知：恵比寿 出勤日監視\n"
        "━━━━━━━━━━━━━━━\n"
        f"{format_schedule(schedule)}\n"
        "━━━━━━━━━━━━━━━\n"
        f"{PAGE_URL}"
    )


def send_slack_message(message: str) -> None:
    if not SLACK_WEBHOOK_URL:
        logger.info("SLACK_WEBHOOK_URL が未設定のためSlack通知をスキップします。")
        return
    try:
        response = requests.post(
            SLACK_WEBHOOK_URL,
            json={"text": message},
            timeout=15,
        )
        logger.info(f"Slack応答ステータス: {response.status_code}")
        if response.status_code == 200:
            logger.info("Slack通知を送信しました。")
        else:
            logger.error(f"Slack通知に失敗しました: {response.status_code} {response.text}")
    except Exception as exc:
        logger.error(f"Slack通知の送信中にエラーが発生しました: {exc}")


def send_line_message(message: str) -> None:
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        logger.info("LINE_CHANNEL_ACCESS_TOKEN または LINE_USER_ID が未設定のためLINE通知をスキップします。")
        return

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }
    payload = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": message}],
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        logger.info(f"LINE応答ステータス: {response.status_code}")
        if response.status_code == 200:
            logger.info("LINE通知を送信しました。")
        else:
            logger.error(f"LINE通知に失敗しました: {response.status_code} {response.text}")
    except Exception as exc:
        logger.error(f"LINE通知の送信中にエラーが発生しました: {exc}")


def send_notifications(message: str) -> None:
    logger.info("通知内容:\n%s", message)
    send_slack_message(message)
    send_line_message(message)


def check_and_notify() -> None:
    checked_at = now_jst()
    logger.info(f"チェック開始: {checked_at}")

    current = fetch_schedule()
    logger.info("出勤予定:\n%s", format_schedule(current))

    if is_test_notify():
        send_notifications(format_test_message(current))
        logger.info("テスト通知モードのため状態ファイルは更新しません。")
        return

    previous = load_state()
    if previous is None:
        save_state({"schedule": current, "last_checked": checked_at})
        logger.info("初回実行のため状態を保存しました。通知は行いません。")
        return

    if not isinstance(previous, dict) or not isinstance(previous.get("schedule"), dict):
        raise ValueError("状態ファイルの形式が不正です。上書きせず終了します。")

    changes = diff_schedule(previous["schedule"], current)
    if changes:
        logger.info(f"通知対象の変化: {len(changes)}件")
        send_notifications(format_change_message(changes, checked_at))
    else:
        logger.info("通知対象の変化なし")

    save_state({"schedule": current, "last_checked": checked_at})
    logger.info("チェック完了。")


if __name__ == "__main__":
    try:
        check_and_notify()
    except Exception as exc:
        logger.error(f"監視処理に失敗しました: {exc}")
    sys.exit(0)
