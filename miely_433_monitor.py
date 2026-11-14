#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""アロマミエリーのセラピスト出勤予定を監視する（profile id=433）。

出勤日の追加、または既存の出勤日の時間変更だけを通知する。
状態は miely_433_state.json に保存し、TOWA 監視・恵比寿監視とは分離する。
スケジュールはプロフィール HTML の section.schedule に入っている。
セラピスト名は同じページの「名前（年齢）」から読む。
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

PAGE_URL = "https://aroma-miely.com/therapist/profile.php?id=433"
SHOP_NAME = "アロマミエリー"
STATE_FILE = "miely_433_state.json"

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
AGE_RE = re.compile(r"\s*[（(]\s*\d+\s*歳\s*[）)]\s*$")
OFF_VALUES = {
    "",
    "-",
    "－",
    "—",
    "―",
    "ー",
    "休",
    "休み",
    "お休み",
    "未定",
    "なし",
    "×",
    "受付終了",
}
SCHEDULE_RE = re.compile(
    r'<section class="schedule">.*?<ul>(.*?)</ul>\s*</section>',
    re.S,
)
NAME_RE = re.compile(
    r'<h3 class="name">\s*<span>\s*名前（年齢）\s*</span>\s*<span>(.*?)</span>',
    re.S,
)
LI_RE = re.compile(r"<li[^>]*>(.*?)</li>", re.S)
P_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.S)
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


def _text(fragment: str) -> str:
    text = TAG_RE.sub("", fragment)
    text = html_lib.unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def parse_name(page_html: str) -> str:
    """プロフィールの名前を返す。年齢表記は除く。"""
    match = NAME_RE.search(page_html)
    if not match:
        raise ValueError("セラピスト名（h3.name）が見つかりません")
    name = AGE_RE.sub("", _text(match.group(1))).strip()
    if not name:
        raise ValueError("セラピスト名が空です")
    return name


def parse_schedule(page_html: str) -> dict:
    """出勤予定を {日付ラベル: 時間} にする。取れなければ ValueError。"""
    match = SCHEDULE_RE.search(page_html)
    if not match:
        raise ValueError("出勤予定（section.schedule）が見つかりません")

    rows = LI_RE.findall(match.group(1))
    if not rows:
        raise ValueError("出勤予定の日付がありません")

    schedule = {}
    for raw in rows:
        cells = [_text(part) for part in P_RE.findall(raw)]
        cells = [cell for cell in cells if cell]
        if len(cells) != 2:
            raise ValueError(f"出勤予定の項目が不正です: {cells!r}")
        date_label, time_label = cells
        if not DATE_RE.match(date_label):
            raise ValueError(f"日付の形式が不正です: {date_label!r}")
        if date_label in schedule:
            raise ValueError(f"日付が重複しています: {date_label}")
        schedule[date_label] = time_label

    if not schedule:
        raise ValueError("出勤予定が空です")
    return schedule


def parse_profile(page_html: str):
    """(セラピスト名, 出勤予定) を返す。"""
    return parse_name(page_html), parse_schedule(page_html)


def fetch_profile():
    response = requests.get(PAGE_URL, headers=HEADERS, timeout=30)
    response.raise_for_status()
    if not response.encoding:
        response.encoding = "utf-8"
    return parse_profile(response.text)


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


def format_change_message(name: str, changes: list, schedule: dict, checked_at: str) -> str:
    has_new = any(change["kind"] == "new" for change in changes)
    if has_new:
        header = f"🎉 出勤日が追加されました（{name}さん / {SHOP_NAME}）"
    else:
        header = f"🎉 出勤時間が変更されました（{name}さん / {SHOP_NAME}）"

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
        f"現在の出勤予定\n"
        f"{format_schedule(schedule)}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"検出時刻: {checked_at}\n"
        f"{PAGE_URL}"
    )


def format_test_message(name: str, schedule: dict) -> str:
    return (
        "🧪 テスト通知：アロマミエリー 出勤日監視\n"
        "━━━━━━━━━━━━━━━\n"
        f"{name}さん\n"
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

    name, current = fetch_profile()
    logger.info("セラピスト: %s（%s）", name, SHOP_NAME)
    logger.info("出勤予定:\n%s", format_schedule(current))

    if is_test_notify():
        send_notifications(format_test_message(name, current))
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
        send_notifications(format_change_message(name, changes, current, checked_at))
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
