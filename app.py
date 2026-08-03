"""
Artis Hamil Tracker — Aplikasi Web
------------------------------------
Satu aplikasi Flask yang:
1. Otomatis mencari berita dari Google News RSS setiap beberapa jam (scheduler)
2. Menyimpan hasil ke database SQLite (biar tidak hilang saat restart)
3. Menampilkan hasil di halaman web dengan tombol "Refresh Sekarang"
4. Punya endpoint pencarian untuk cek artis tertentu

Cara jalankan lokal:
    pip install -r requirements.txt
    python app.py
    buka http://localhost:5000 di browser

Cara deploy online: lihat README.md
"""

import sqlite3
import urllib.parse
import threading
import time
from datetime import datetime

import feedparser
from flask import Flask, render_template_string, request, redirect, url_for, jsonify

app = Flask(__name__)

DB_FILE = "berita.db"

# Kata kunci umum yang selalu dipantau
DEFAULT_KEYWORDS = [
    "artis hamil",
    "selebriti hamil",
    "umumkan kehamilan",
]

# Jarak waktu auto-refresh otomatis (dalam detik). Default: 3 jam.
AUTO_REFRESH_INTERVAL = 3 * 60 * 60


# ---------------------------------------------------------
# DATABASE
# ---------------------------------------------------------

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS berita (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            judul TEXT NOT NULL,
            link TEXT UNIQUE NOT NULL,
            sumber TEXT,
            tanggal_terbit TEXT,
            kata_kunci TEXT,
            ditemukan_pada TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS keyword_tambahan (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama TEXT UNIQUE NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def get_all_keywords():
    conn = get_db()
    rows = conn.execute("SELECT nama FROM keyword_tambahan").fetchall()
    conn.close()
    extra = [f'"{r["nama"]}" hamil' for r in rows]
    return DEFAULT_KEYWORDS + extra


def simpan_berita(items):
    conn = get_db()
    baru = 0
    for item in items:
        try:
            conn.execute(
                """INSERT INTO berita (judul, link, sumber, tanggal_terbit, kata_kunci, ditemukan_pada)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    item["judul"],
                    item["link"],
                    item["sumber"],
                    item["tanggal"],
                    item["kata_kunci"],
                    datetime.now().isoformat(),
                ),
            )
            baru += 1
        except sqlite3.IntegrityError:
            # link sudah ada, skip (dedupe otomatis)
            pass
    conn.commit()
    conn.close()
    return baru


# ---------------------------------------------------------
# FETCH DARI GOOGLE NEWS RSS
# ---------------------------------------------------------

def build_query_url(term: str) -> str:
    encoded = urllib.parse.quote(term)
    return f"https://news.google.com/rss/search?q={encoded}&hl=id&gl=ID&ceid=ID:id"


def fetch_news_for_term(term: str):
    url = build_query_url(term)
    feed = feedparser.parse(url)
    results = []
    for entry in feed.entries:
        results.append({
            "judul": entry.title,
            "link": entry.link,
            "sumber": entry.get("source", {}).get("title", "Tidak diketahui"),
            "tanggal": entry.get("published", ""),
            "kata_kunci": term,
        })
    return results


def jalankan_pencarian():
    """Cari berita untuk semua keyword, simpan ke DB. Return jumlah berita baru."""
    total_baru = 0
    for term in get_all_keywords():
        items = fetch_news_for_term(term)
        total_baru += simpan_berita(items)
    return total_baru


# ---------------------------------------------------------
# SCHEDULER OTOMATIS (background thread)
# ---------------------------------------------------------

def background_scheduler():
    while True:
        try:
            jumlah = jalankan_pencarian()
            print(f"[{datetime.now()}] Auto-refresh selesai, {jumlah} berita baru.")
        except Exception as e:
            print(f"[{datetime.now()}] Gagal auto-refresh: {e}")
        time.sleep(AUTO_REFRESH_INTERVAL)


# ---------------------------------------------------------
# ROUTES
# ---------------------------------------------------------

TEMPLATE = """
<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<title>Artis Hamil Tracker</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
    body { font-family: -apple-system, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; background: #faf7f5; color: #222; }
    h1 { color: #b5478c; }
    .toolbar { display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; align-items: center; }
    button, input[type=submit] { background: #b5478c; color: white; border: none; padding: 10px 16px; border-radius: 6px; cursor: pointer; font-size: 14px; }
    button:hover, input[type=submit]:hover { background: #99396f; }
    input[type=text] { padding: 10px; border-radius: 6px; border: 1px solid #ccc; flex: 1; min-width: 180px; }
    .card { background: white; border-radius: 10px; padding: 16px; margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
    .card a { text-decoration: none; color: #222; font-weight: 600; }
    .card a:hover { text-decoration: underline; }
    .meta { color: #888; font-size: 13px; margin-top: 6px; }
    .badge { display: inline-block; background: #f3e3ec; color: #b5478c; padding: 2px 8px; border-radius: 12px; font-size: 12px; margin-right: 6px; }
    .empty { text-align: center; color: #999; padding: 40px 0; }
</style>
</head>
<body>
    <h1>🎀 Artis Hamil Tracker</h1>
    <p>Total berita tersimpan: <strong>{{ total }}</strong> — auto-refresh tiap {{ interval_jam }} jam</p>

    <div class="toolbar">
        <form action="{{ url_for('refresh') }}" method="post">
            <button type="submit">🔄 Refresh Sekarang</button>
        </form>
        <form action="{{ url_for('tambah_keyword') }}" method="post" style="display:flex; gap:8px; flex:1;">
            <input type="text" name="nama_artis" placeholder="Tambah nama artis untuk dipantau...">
            <input type="submit" value="Tambah">
        </form>
    </div>

    {% if keywords_tambahan %}
    <p style="font-size: 13px; color: #666;">Sedang memantau: {{ keywords_tambahan|join(', ') }}</p>
    {% endif %}

    {% if berita|length == 0 %}
        <div class="empty">Belum ada berita. Klik "Refresh Sekarang" untuk mulai mencari.</div>
    {% endif %}

    {% for b in berita %}
    <div class="card">
        <a href="{{ b.link }}" target="_blank" rel="noopener">{{ b.judul }}</a>
        <div class="meta">
            <span class="badge">{{ b.sumber }}</span>
            {{ b.tanggal_terbit }}
        </div>
    </div>
    {% endfor %}

</body>
</html>
"""


@app.route("/")
def index():
    conn = get_db()
    berita = conn.execute(
        "SELECT * FROM berita ORDER BY ditemukan_pada DESC LIMIT 100"
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) as c FROM berita").fetchone()["c"]
    kw_rows = conn.execute("SELECT nama FROM keyword_tambahan").fetchall()
    conn.close()
    return render_template_string(
        TEMPLATE,
        berita=berita,
        total=total,
        interval_jam=AUTO_REFRESH_INTERVAL // 3600,
        keywords_tambahan=[r["nama"] for r in kw_rows],
    )


@app.route("/refresh", methods=["POST"])
def refresh():
    jalankan_pencarian()
    return redirect(url_for("index"))


@app.route("/tambah-keyword", methods=["POST"])
def tambah_keyword():
    nama = request.form.get("nama_artis", "").strip()
    if nama:
        conn = get_db()
        try:
            conn.execute("INSERT INTO keyword_tambahan (nama) VALUES (?)", (nama,))
            conn.commit()
        except sqlite3.IntegrityError:
            pass
        conn.close()
        # langsung cari berita untuk nama baru ini
        items = fetch_news_for_term(f'"{nama}" hamil')
        simpan_berita(items)
    return redirect(url_for("index"))


@app.route("/api/berita")
def api_berita():
    """Endpoint JSON kalau mau dipakai aplikasi mobile / frontend lain."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM berita ORDER BY ditemukan_pada DESC LIMIT 200"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ---------------------------------------------------------
# START
# ---------------------------------------------------------

init_db()

# Jalankan scheduler otomatis di background thread
scheduler_thread = threading.Thread(target=background_scheduler, daemon=True)
scheduler_thread.start()

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
