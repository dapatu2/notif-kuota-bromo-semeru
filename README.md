# TNBTS Restock Bot

Bot Python untuk memantau kuota publik `https://bromotenggersemeru.id/` dan mengirim notifikasi Telegram saat kuota tersedia.

## Yang dipantau

Endpoint publik yang dipakai:

```text
POST https://bromotenggersemeru.id/website/home/get_view
action=kapasitas&year_month=YYYY-MM&id_site=<site>
```

Site:

- `bromo` = `id_site=4`
- `semeru` = `id_site=8`
- `ranu-regulo` = `id_site=7`, default `jenis_kegiatan=Berkunjung`

Polling dibuat wajar; default interval loop 300 detik dan minimum 60 detik.

## Konfigurasi Telegram

```bash
export TELEGRAM_BOT_TOKEN="token-dari-BotFather"
export TELEGRAM_CHAT_ID="chat-id-tujuan"
```

Untuk mencari `chat_id`, kirim pesan dulu ke bot Telegram lalu jalankan:

```bash
python3 /home/ubuntu/tnbts-restock-bot/tnbts_restock_bot.py --get-chat-ids
```

## Contoh pemakaian

Cek sekali tanpa mengirim Telegram:

```bash
python3 /home/ubuntu/tnbts-restock-bot/tnbts_restock_bot.py --site bromo --month 2026-05 --dry-run
```

Monitor Bromo Mei 2026 setiap 5 menit:

```bash
python3 /home/ubuntu/tnbts-restock-bot/tnbts_restock_bot.py --site bromo --month 2026-05 --loop --interval 300
```

## Menu Telegram `/start`

Jalankan mode menu:

```bash
TELEGRAM_CHAT_ID=534089460 python3 /home/ubuntu/tnbts-restock-bot/tnbts_restock_bot.py --telegram-menu --menu-month 2026-05
```

Mode di atas hanya memproses chat `TELEGRAM_CHAT_ID`.

Jika menu `/start` ingin bisa dipakai semua orang:

```bash
python3 /home/ubuntu/tnbts-restock-bot/tnbts_restock_bot.py --telegram-menu --public-menu --menu-month 2026-05
```

Lalu buka Telegram dan kirim `/start` ke bot. Bot akan menampilkan tombol:

- Bromo
- Semeru
- Ranu Regulo

Saat tombol dipilih, bot mengirim ringkasan kuota untuk periode `--menu-month`.

Monitor Semeru dan Ranu Regulo:

```bash
python3 /home/ubuntu/tnbts-restock-bot/tnbts_restock_bot.py --site semeru --site ranu-regulo --month 2026-05 --loop
```

Monitor Semeru Mei dan Juni 2026:

```bash
TELEGRAM_CHAT_ID=534089460 python3 /home/ubuntu/tnbts-restock-bot/tnbts_restock_bot.py --site semeru --month 2026-05 --month 2026-06 --loop --interval 300 --quiet
```

Bot menyimpan state kecil di `state.json` supaya hanya mengirim notifikasi saat kuota berubah dari tidak tersedia ke tersedia. File ini hanya berisi tanggal dan angka kuota terakhir, bukan cache HTML besar.

Monitor tanggal tertentu saja:

```bash
python3 /home/ubuntu/tnbts-restock-bot/tnbts_restock_bot.py --site semeru --month 2026-05 --date-contains "10 Mei 2026" --loop
```

Alert hanya jika kuota minimal 2:

```bash
python3 /home/ubuntu/tnbts-restock-bot/tnbts_restock_bot.py --site semeru --month 2026-05 --threshold 2 --loop
```

## Menjalankan di VPS/server

Gunakan `systemd`, `screen`, `tmux`, atau cron. Contoh cron setiap 5 menit:

```cron
*/5 * * * * TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=yyy python3 /home/ubuntu/tnbts-restock-bot/tnbts_restock_bot.py --site bromo --month 2026-05 >> /home/ubuntu/tnbts-restock-bot/bot.log 2>&1
```
