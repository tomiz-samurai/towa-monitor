#!/usr/bin/env python3
import os, json, logging, requests
from datetime import datetime

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")

SID = "34u9JdnCtW"
STAFF_NO = "105342"
MENU_NO = "5422"
DISPLAY_DAYS = 14
RESERVE_URL = f"https://grow-appt.com/reserve/order?SID={SID}&page=time&s=46"
API_BASE = f"https://grow-appt.com/reserve/api/reserve/{SID}/status"
STATE_FILE = "towa_calendar_state.json"

logging.basicConfig(level=logging.INFO, format="%(asctime )s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": RESERVE_URL,
}

def fetch_available_slots():
    today = datetime.now().strftime("%Y/%m/%d")
    available = {}
    for group_no in ["", "1", "2"]:
        params = {"sid": SID, "staff_no": STAFF_NO, "menu_no": MENU_NO,
                  "seldate": today, "coupon_no": "", "customer_no": "",
                  "displaydaynum": str(DISPLAY_DAYS)}
        if group_no:
            params["group_no"] = group_no
        try:
            r = requests.get(API_BASE, headers=HEADERS, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.error(f"API取得エラー: {e}")
            continue
        for dt_str, entries in data.get("sales", {}).items():
            for entry in entries:
                if entry.get("status") not in {1, 2}:
                    available[dt_str] = True
    return available

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def send_line_message(message):
    r = requests.post("https://api.line.me/v2/bot/message/push",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
        json={"to": LINE_USER_ID, "messages": [{"type": "text", "text": message}]},
        timeout=15 )
    if r.status_code == 200:
        logger.info("LINE通知を送信しました。")
    else:
        logger.error(f"LINE通知失敗: {r.status_code} {r.text}")

def format_slots(slots):
    by_date = {}
    for s in sorted(slots):
        by_date.setdefault(s[:10], []).append(s[11:])
    lines = []
    wd = ["月","火","水","木","金","土","日"]
    for date, times in sorted(by_date.items()):
        dt = datetime.strptime(date, "%Y-%m-%d")
        t = f"{times[0]}〜{times[-1]}" if len(times) >= 2 else times[0]
        lines.append(f"{dt.month}/{dt.day}({wd[dt.weekday()]}) {t}")
    return "\n".join(lines)

def check_and_notify():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"チェック開始: {now}")
    current = fetch_available_slots()
    logger.info(f"予約可能（○）枠数: {len(current)}")
    prev = load_state().get("available_slots", {})
    new_slots = sorted([s for s in current if s not in prev])
    if new_slots:
        logger.info(f"新規○枠: {len(new_slots)}件")
        send_line_message(
            f"🎉 TOWAさんの予約枠が追加されました！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{format_slots(new_slots)}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"新規追加: {len(new_slots)}枠\n"
            f"検出時刻: {now}\n"
            f"予約はこちら\n{RESERVE_URL}"
        )
    else:
        logger.info("変化なし")
    save_state({"available_slots": current, "last_checked": now, "total_available": len(current)})

if __name__ == "__main__":
    check_and_notify()
