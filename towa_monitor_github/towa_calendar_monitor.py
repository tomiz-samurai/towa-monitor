#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TOWA カレンダー監視スクリプト（GitHub Actions版）
GitHub Actions の Scheduled Workflow で5分ごとに実行する。

認証情報は GitHub Secrets から環境変数として渡される。
"""

import os
import json
import logging
import requests
from datetime import datetime

# 環境変数から認証情報を取得（GitHub Secretsで設定）
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")

# ===== 監視設定 =====
SID = "34u9JdnCtW"
STAFF_NO = "105342"   # TOWA
MENU_NO = "5422"
DISPLAY_DAYS = 14

RESERVE_URL = f"https://grow-appt.com/reserve/order?SID={SID}&page=time&s=46"
API_BASE = f"https://grow-appt.com/reserve/api/reserve/{SID}/status"

STATE_FILE = "towa_calendar_state.json"
LOG_FILE = "towa_calendar_monitor.log"

# ===== ログ設定 =====
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": RESERVE_URL,
}

UNAVAILABLE_STATUSES = {1, 2}


def fetch_available_slots() -> dict:
    today = datetime.now().strftime("%Y/%m/%d")
    available = {}

    for group_no in ["", "1", "2"]:
        params = {
            "sid": SID,
            "staff_no": STAFF_NO,
            "menu_no": MENU_NO,
            "seldate": today,
            "coupon_no": "",
            "customer_no": "",
            "displaydaynum": str(DISPLAY_DAYS),
        }
        if group_no:
            params["group_no"] = group_no

        try:
            r = requests.get(API_BASE, headers=HEADERS, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.error(f"API取得エラー (group_no={group_no!r}): {e}")
            continue

        for dt_str, entries in data.get("sales", {}).items():
            for entry in entries:
                status = entry.get("status")
                if status not in UNAVAILABLE_STATUSES:
                    available[dt_str] = True

    return available


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def send_line_message(message: str) -> bool:
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        logger.warning("LINE_CHANNEL_ACCESS_TOKEN または LINE_USER_ID が設定されていません。")
        return False

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }
    payload = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": message}]
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        if r.status_code == 200:
            logger.info("LINE通知を送信しました。")
            return True
        else:
            logger.error(f"LINE通知に失敗しました: {r.status_code} {r.text}")
            return False
    except Exception as e:
        logger.error(f"LINE通知の送信中にエラーが発生しました: {e}")
        return False


def format_slots_by_date(slots: list) -> str:
    by_date = {}
    for slot in sorted(slots):
        date_part = slot[:10]
        time_part = slot[11:]
        by_date.setdefault(date_part, []).append(time_part)

    lines = []
    for date, times in sorted(by_date.items()):
        dt = datetime.strptime(date, "%Y-%m-%d")
        weekdays = ["月", "火", "水", "木", "金", "土", "日"]
        wd = weekdays[dt.weekday()]
        if len(times) >= 2:
            lines.append(f"{dt.month}/{dt.day}({wd}) {times[0]}〜{times[-1]}")
        else:
            lines.append(f"{dt.month}/{dt.day}({wd}) {times[0]}")

    return "\n".join(lines)


def check_and_notify() -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"チェック開始: {now}")

    try:
        current_available = fetch_available_slots()
    except Exception as e:
        logger.error(f"予約枠取得に失敗しました: {e}")
        return

    logger.info(f"現在の予約可能（○）枠数: {len(current_available)}")

    prev_state = load_state()
    prev_available = prev_state.get("available_slots", {})

    new_slots = sorted([s for s in current_available if s not in prev_available])
    removed_slots = [s for s in prev_available if s not in current_available]

    if new_slots:
        logger.info(f"新規○枠を検出: {len(new_slots)}件")
        slots_text = format_slots_by_date(new_slots)

        message = (
            f"🎉 TOWAさんの予約枠が追加されました！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{slots_text}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"新規追加: {len(new_slots)}枠\n"
            f"検出時刻: {now}\n"
            f"予約はこちら\n{RESERVE_URL}"
        )
        send_line_message(message)

    elif removed_slots:
        logger.info(f"○枠が{len(removed_slots)}件減少（予約済みになった可能性）")
    else:
        logger.info("変化なし")

    save_state({
        "available_slots": current_available,
        "last_checked": now,
        "total_available": len(current_available),
    })
    logger.info("チェック完了。")


if __name__ == "__main__":
    check_and_notify()
