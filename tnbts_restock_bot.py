#!/usr/bin/env python3
import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path


BASE_URL = "https://bromotenggersemeru.id/"
CAPACITY_URL = urllib.parse.urljoin(BASE_URL, "website/home/get_view")
DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; TNBTSRestockBot/1.0; polite capacity monitor)"
SITES = {
    "bromo": {"id_site": "4", "name": "Bromo"},
    "semeru": {"id_site": "8", "name": "Semeru"},
    "ranu-regulo": {"id_site": "7", "name": "Ranu Regulo", "jenis_kegiatan": "Berkunjung"},
    "regulo": {"id_site": "7", "name": "Ranu Regulo", "jenis_kegiatan": "Berkunjung"},
}
MENU_SITES = [
    ("bromo", "Bromo"),
    ("semeru", "Semeru"),
    ("ranu-regulo", "Ranu Regulo"),
]


class CapacityTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self._in_td = False
        self._current_row = None
        self._current_cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._current_row = []
        elif tag == "td" and self._current_row is not None:
            self._in_td = True
            self._current_cell = []

    def handle_data(self, data):
        if self._in_td and self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self._in_td and self._current_cell is not None:
            text = html.unescape(" ".join(self._current_cell))
            text = re.sub(r"\s+", " ", text).strip()
            self._current_row.append(text)
            self._current_cell = None
            self._in_td = False
        elif tag == "tr" and self._current_row is not None:
            if len(self._current_row) >= 2:
                self.rows.append(self._current_row[:2])
            self._current_row = None


@dataclass(frozen=True)
class Target:
    site: str
    month: str
    date_contains: str | None
    threshold: int

    @property
    def key(self):
        suffix = f":{self.date_contains.lower()}" if self.date_contains else ""
        return f"{self.site}:{self.month}{suffix}"


def http_request(url, data=None, timeout=30):
    headers = {
        "User-Agent": os.environ.get("USER_AGENT", DEFAULT_USER_AGENT),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": BASE_URL,
    }
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        headers["X-Requested-With"] = "XMLHttpRequest"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def fetch_capacity(site_key, month):
    site = SITES[site_key]
    params = {"action": "kapasitas", "year_month": month, "id_site": site["id_site"]}
    if site.get("jenis_kegiatan"):
        params["jenis_kegiatan"] = site["jenis_kegiatan"]
    payload = urllib.parse.urlencode(params).encode()
    return http_request(CAPACITY_URL, payload)


def parse_capacity(html_text):
    parser = CapacityTableParser()
    parser.feed(html_text)
    result = []
    for date_text, capacity_text in parser.rows:
        numbers = [int(num) for num in re.findall(r"-?\d+", capacity_text)]
        capacity = max(numbers) if numbers else 0
        status = "available" if capacity > 0 and "Kuota Penuh" not in capacity_text else "full"
        result.append(
            {
                "date": date_text,
                "capacity": capacity if status == "available" else 0,
                "raw_capacity": capacity_text,
                "status": status,
            }
        )
    return result


def date_matches(date_text, query):
    date_lower = date_text.lower()
    query_lower = query.lower()
    if re.match(r"^\d+\s+\S+\s+\d{4}$", query_lower):
        return re.search(rf"(?<!\d){re.escape(query_lower)}(?!\d)", date_lower) is not None
    return query_lower in date_lower


def load_state(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def send_telegram(token, chat_id, text):
    return telegram_api(
        token,
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        },
    )


def telegram_api(token, method, params):
    payload = urllib.parse.urlencode(params).encode()
    api_url = f"https://api.telegram.org/bot{token}/{method}"
    response = http_request(api_url, payload)
    data = json.loads(response)
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error: {data}")
    return data


def find_chat_ids(token):
    api_url = f"https://api.telegram.org/bot{token}/getUpdates"
    data = json.loads(http_request(api_url))
    chat_ids = []
    for item in data.get("result", []):
        message = item.get("message") or item.get("channel_post") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is not None and chat_id not in chat_ids:
            chat_ids.append(chat_id)
    return chat_ids


def get_updates(token, offset=None, timeout=25):
    params = {"timeout": str(timeout)}
    if offset is not None:
        params["offset"] = str(offset)
    return telegram_api(token, "getUpdates", params).get("result", [])


def menu_markup():
    return json.dumps(
        {
            "inline_keyboard": [
                [{"text": label, "callback_data": f"site:{site}"}]
                for site, label in MENU_SITES
            ]
        }
    )


def send_menu(token, chat_id):
    telegram_api(
        token,
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": "Pilih kawasan yang ingin dicek:",
            "reply_markup": menu_markup(),
        },
    )


def answer_callback(token, callback_id, text=None):
    params = {"callback_query_id": callback_id}
    if text:
        params["text"] = text
    try:
        telegram_api(token, "answerCallbackQuery", params)
    except urllib.error.HTTPError as exc:
        if exc.code != 400:
            raise


def summarize_site(site_key, month, limit=8):
    try:
        rows = parse_capacity(fetch_capacity(site_key, month))
    except urllib.error.HTTPError as exc:
        site_name = SITES[site_key]["name"]
        if exc.code == 500:
            return f"<b>{site_name}</b>\nServer TNBTS belum mengembalikan data untuk periode {month}."
        raise
    available = [row for row in rows if row["capacity"] > 0]
    site_name = SITES[site_key]["name"]
    if not available:
        return f"<b>{site_name}</b>\nPeriode {month}: belum ada kuota tersedia."
    lines = [
        f"<b>{site_name}</b>",
        f"Periode {month}: {len(available)} tanggal tersedia.",
        "",
    ]
    for row in available[:limit]:
        lines.append(f"- {html.escape(row['date'])}: <b>{row['capacity']}</b>")
    if len(available) > limit:
        lines.append(f"... dan {len(available) - limit} tanggal lain.")
    lines.append("")
    lines.append("Bot monitor CLI tetap bisa dijalankan untuk alert otomatis.")
    return "\n".join(lines)


def run_telegram_menu(token, default_month=None, allowed_chat_id=None, once=False):
    if not default_month:
        default_month = datetime.now().strftime("%Y-%m")
    print("Telegram menu bot running. Send /start to the bot.")
    offset = None
    while True:
        updates = get_updates(token, offset=offset, timeout=25)
        for update in updates:
            offset = update["update_id"] + 1
            message = update.get("message") or {}
            callback = update.get("callback_query") or {}
            chat = message.get("chat") or (callback.get("message") or {}).get("chat") or {}
            chat_id = chat.get("id")
            if allowed_chat_id and str(chat_id) != str(allowed_chat_id):
                continue
            text = (message.get("text") or "").strip().lower()
            if text in {"/start", "start", "menu"}:
                send_menu(token, chat_id)
                continue
            data = callback.get("data") or ""
            if data.startswith("site:"):
                callback_id = callback.get("id")
                site_key = data.split(":", 1)[1]
                if callback_id:
                    answer_callback(token, callback_id, "Mengecek kuota...")
                try:
                    send_telegram(token, chat_id, summarize_site(site_key, default_month))
                except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
                    send_telegram(token, chat_id, f"Gagal cek kuota: {html.escape(str(exc))}")
        if once:
            break


def format_alert(target, row, previous):
    site_name = SITES[target.site]["name"]
    previous_text = "belum ada data sebelumnya" if previous is None else f"sebelumnya {previous}"
    return (
        f"Restock TNBTS: <b>{site_name}</b>\n"
        f"Tanggal: <b>{html.escape(row['date'])}</b>\n"
        f"Kuota: <b>{row['capacity']}</b> ({previous_text})\n"
        f"Periode: {target.month}\n"
        f"Link: {BASE_URL}"
    )


def check_once(targets, state_path, telegram_token=None, telegram_chat_id=None, dry_run=False, quiet=False):
    state = load_state(state_path)
    alerts = []
    summaries = []

    for target in targets:
        rows = parse_capacity(fetch_capacity(target.site, target.month))
        if target.date_contains:
            rows = [row for row in rows if date_matches(row["date"], target.date_contains)]
        available = [row for row in rows if row["capacity"] >= target.threshold]
        summaries.append(
            {
                "target": target.key,
                "available_count": len(available),
                "rows_checked": len(rows),
                "available": available,
            }
        )

        previous_capacities = state.get(target.key, {})
        current_capacities = {row["date"]: row["capacity"] for row in rows}
        for row in available:
            previous = previous_capacities.get(row["date"])
            previous = int(previous) if previous is not None else None
            if previous is None or previous < target.threshold:
                alerts.append((target, row, previous))
        state[target.key] = current_capacities

    if not dry_run:
        save_state(state_path, state)

    for target, row, previous in alerts:
        text = format_alert(target, row, previous)
        if telegram_token and telegram_chat_id and not dry_run:
            send_telegram(telegram_token, telegram_chat_id, text)
        if not quiet:
            print(text)
            print("-" * 40)

    if not alerts and not quiet:
        print(f"{datetime.now().isoformat(timespec='seconds')} - no new restock alerts")

    if not quiet:
        print(json.dumps(summaries, indent=2, ensure_ascii=False))
    return len(alerts)


def parse_targets(args):
    targets = []
    for site in args.site:
        site_key = site.lower()
        if site_key not in SITES:
            raise SystemExit(f"Unknown site '{site}'. Options: {', '.join(SITES)}")
        for month in args.month:
            targets.append(Target(site_key, month, args.date_contains, args.threshold))
    return targets


def main():
    parser = argparse.ArgumentParser(description="Monitor kuota TNBTS dan kirim notifikasi Telegram.")
    parser.add_argument("--site", action="append", default=[], help="bromo, semeru, atau ranu-regulo. Bisa diulang.")
    parser.add_argument("--month", action="append", default=[], help="Periode YYYY-MM. Bisa diulang.")
    parser.add_argument("--date-contains", help="Filter tanggal, contoh: '2 Mei 2026'.")
    parser.add_argument("--threshold", type=int, default=1, help="Alert jika kuota >= threshold.")
    parser.add_argument("--interval", type=int, default=300, help="Jeda polling dalam detik untuk mode loop.")
    parser.add_argument("--loop", action="store_true", help="Jalankan terus menerus.")
    parser.add_argument("--dry-run", action="store_true", help="Tidak simpan state dan tidak kirim Telegram.")
    parser.add_argument("--quiet", action="store_true", help="Jangan print hasil normal ke stdout; cocok untuk VPS.")
    parser.add_argument("--state-file", default="/home/ubuntu/tnbts-restock-bot/state.json")
    parser.add_argument("--telegram-token", default=os.environ.get("TELEGRAM_BOT_TOKEN"))
    parser.add_argument("--telegram-chat-id", default=os.environ.get("TELEGRAM_CHAT_ID"))
    parser.add_argument("--get-chat-ids", action="store_true", help="Cetak chat_id dari getUpdates.")
    parser.add_argument("--telegram-menu", action="store_true", help="Jalankan bot menu Telegram /start.")
    parser.add_argument("--public-menu", action="store_true", help="Izinkan semua chat memakai menu /start.")
    parser.add_argument("--menu-month", help="Periode YYYY-MM untuk hasil menu Telegram.")
    parser.add_argument("--menu-once", action="store_true", help="Proses update Telegram sekali lalu keluar.")
    args = parser.parse_args()

    if args.get_chat_ids:
        if not args.telegram_token:
            raise SystemExit("TELEGRAM_BOT_TOKEN belum tersedia.")
        print(json.dumps(find_chat_ids(args.telegram_token), indent=2))
        return

    if args.telegram_menu:
        if not args.telegram_token:
            raise SystemExit("TELEGRAM_BOT_TOKEN belum tersedia.")
        run_telegram_menu(
            args.telegram_token,
            default_month=args.menu_month,
            allowed_chat_id=None if args.public_menu else args.telegram_chat_id,
            once=args.menu_once,
        )
        return

    if not args.site:
        args.site = ["bromo"]
    if not args.month:
        args.month = [datetime.now().strftime("%Y-%m")]

    targets = parse_targets(args)
    state_path = Path(args.state_file)

    while True:
        try:
            check_once(
                targets,
                state_path,
                telegram_token=args.telegram_token,
                telegram_chat_id=args.telegram_chat_id,
                dry_run=args.dry_run,
                quiet=args.quiet,
            )
        except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            print(f"{datetime.now().isoformat(timespec='seconds')} - error: {exc}", file=sys.stderr)
        if not args.loop:
            break
        time.sleep(max(args.interval, 60))


if __name__ == "__main__":
    main()
