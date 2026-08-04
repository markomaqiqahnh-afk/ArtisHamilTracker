"""
Artis Hamil Tracker — v2
--------------------------
Perubahan dari v1:
1. Fix: refresh sekarang pakai header browser (User-Agent) supaya
   Google News tidak menganggap request sebagai bot dan hasilnya kosong
2. Fix: berita diurutkan berdasarkan TANGGAL TERBIT berita (bukan
   kapan sistem menemukannya), jadi yang paling baru selalu di atas
3. Fix: sekarang bisa hapus nama artis yang sudah ditambahkan ke daftar pantauan
4. Baru: halaman "Tracker Follow Up" — tabel CRM (Nama, Domisili, No WA,
   HPL, Kontak Pertama, Follow Up Lanjutan, Follow Up Terakhir, Bulan,
   Status Aktif) dengan tambah / edit / hapus data
"""

import sqlite3
import urllib.parse
import threading
import time
import csv
import io
import os
import json
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

import requests
import feedparser
from flask import Flask, render_template_string, request, redirect, url_for, jsonify

app = Flask(__name__)

DB_FILE = os.environ.get("DB_PATH", "berita.db")

# --- Konfigurasi Sinkron Google Sheets ---
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "").strip()
GOOGLE_SHEET_TAB = os.environ.get("GOOGLE_SHEET_TAB", "Sync_Tracker").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
SHEET_SYNC_INTERVAL = 15 * 60  # 15 menit

# Urutan kolom di tab sync — HARUS sama urutannya dengan header row di sheet
SHEET_KOLOM = [
    "nama", "domisili", "rate_card", "followers_ig", "followers_tiktok", "followers_fb",
    "rata2_views", "link_sosmed", "no_wa", "hpl", "kontak_pertama_tanggal",
    "kontak_pertama_hasil", "followup_lanjutan_tanggal", "followup_lanjutan_hasil",
    "followup_terakhir_tanggal", "hasil_akhir", "keterangan", "bulan", "aktif",
]
SHEET_HEADER = [
    "Nama Public Figure", "Domisili", "Rate Card", "Followers IG", "Followers TikTok",
    "Followers FB", "Rata2 Views", "Link Sosmed", "No WA", "HPL",
    "Kontak Pertama - Tanggal", "Kontak Pertama - Hasil",
    "Follow Up Lanjutan - Tanggal", "Follow Up Lanjutan - Hasil",
    "Follow Up Terakhir - Tanggal", "Hasil Akhir", "Keterangan", "Bulan", "Aktif",
]


def sheets_terkonfigurasi():
    return bool(GOOGLE_SHEET_ID and GOOGLE_SERVICE_ACCOUNT_JSON)


def get_worksheet():
    """Buka (atau buat) worksheet tujuan sinkron. Return None kalau belum dikonfigurasi."""
    if not sheets_terkonfigurasi():
        return None
    info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    client = gspread.authorize(creds)
    sh = client.open_by_key(GOOGLE_SHEET_ID)
    try:
        ws = sh.worksheet(GOOGLE_SHEET_TAB)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=GOOGLE_SHEET_TAB, rows=1000, cols=len(SHEET_HEADER) + 2)
        ws.append_row(SHEET_HEADER)
    return ws

DEFAULT_KEYWORDS = [
    "artis hamil",
    "selebgram hamil",
    '"tokoh publik" hamil',
    '"pejabat" hamil',
    '"istri pejabat" hamil',
    '"istri ustadz" hamil',
]

AUTO_REFRESH_INTERVAL = 3 * 60 * 60  # 3 jam

# Kata-kata penanda berita luar negeri — berita yang judulnya mengandung
# salah satu kata ini akan otomatis disembunyikan. Bisa diedit sesuai kebutuhan.
FOREIGN_BLOCKLIST = [
    "hollywood", "bollywood", "k-pop", "kpop", "korea selatan", "korea utara",
    "artis korea", "aktris korea", "aktor korea", "idol korea", "girband korea",
    "boyband korea", "artis jepang", "aktris jepang", "artis india", "bintang india",
    "artis hong kong", "artis taiwan", "artis china", "artis tiongkok",
    "amerika serikat", "aktris amerika", "aktor amerika", "artis amerika",
    "bintang hollywood", "selebriti hollywood", "inggris raya",
]

# Kata-kata penanda berita "generik" (program pemerintah/sosial desa, dll)
# yang cuma kebetulan menyebut kata "hamil" tapi bukan tentang public figure.
GENERIC_BLOCKLIST = [
    "stunting", "posyandu", "puskesmas", "asn jadi", "orang tua asuh",
    "ditandu", "diseberangkan dengan rakit", "kader kesehatan", "bidan desa",
    "dinas kesehatan", "cegah stunting", "gizi buruk", "kabupaten merdeka",
    "hut ri", "tahun indonesia merdeka", "kolaborasi pemkab", "kolaborasi pemkot",
]


def is_berita_luar_negeri(judul: str) -> bool:
    judul_lower = (judul or "").lower()
    return any(kata in judul_lower for kata in FOREIGN_BLOCKLIST)


def is_berita_tidak_relevan(judul: str) -> bool:
    judul_lower = (judul or "").lower()
    return any(kata in judul_lower for kata in GENERIC_BLOCKLIST)

# Header supaya request kita dianggap seperti browser biasa, bukan bot
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


# ---------------------------------------------------------
# DATABASE
# ---------------------------------------------------------

def get_db():
    folder = os.path.dirname(DB_FILE)
    if folder and not os.path.exists(folder):
        os.makedirs(folder, exist_ok=True)
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
            tanggal_terbit_iso TEXT,
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama TEXT NOT NULL,
            domisili TEXT,
            rate_card TEXT,
            followers_ig TEXT,
            followers_tiktok TEXT,
            followers_fb TEXT,
            rata2_views TEXT,
            link_sosmed TEXT,
            no_wa TEXT,
            hpl TEXT,
            kontak_pertama_tanggal TEXT,
            kontak_pertama_hasil TEXT,
            followup_lanjutan_tanggal TEXT,
            followup_lanjutan_hasil TEXT,
            followup_terakhir_tanggal TEXT,
            hasil_akhir TEXT,
            keterangan TEXT,
            bulan TEXT,
            aktif TEXT DEFAULT 'AKTIF',
            dibuat_pada TEXT
        )
    """)
    # Tambahkan kolom baru kalau database lama sudah ada duluan (migrasi ringan)
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(leads)").fetchall()}
    kolom_baru = {
        "rate_card": "TEXT", "followers_ig": "TEXT", "followers_tiktok": "TEXT",
        "followers_fb": "TEXT", "rata2_views": "TEXT", "link_sosmed": "TEXT",
    }
    for kolom, tipe in kolom_baru.items():
        if kolom not in existing_cols:
            conn.execute(f"ALTER TABLE leads ADD COLUMN {kolom} {tipe}")
    conn.commit()
    conn.close()


def get_all_keywords_rows():
    conn = get_db()
    rows = conn.execute("SELECT id, nama FROM keyword_tambahan").fetchall()
    conn.close()
    return rows


def get_all_search_terms():
    rows = get_all_keywords_rows()
    extra = [f'"{r["nama"]}" hamil' for r in rows]
    return DEFAULT_KEYWORDS + extra


BULAN_INDO = {
    "januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "agustus": 8, "september": 9, "oktober": 10, "november": 11, "desember": 12,
}


def parse_hpl(teks):
    """Ubah teks HPL semacam 'September 2026' atau '31 Juli 2026' jadi datetime.
    Return None kalau tidak bisa dibaca (kosong, '?', format aneh, dll)."""
    if not teks:
        return None
    teks = teks.strip().lower()
    if not teks or teks == "?":
        return None

    tahun = None
    bulan = None
    for kata in teks.replace(",", " ").split():
        kata_bersih = "".join(ch for ch in kata if ch.isalpha())
        if kata_bersih in BULAN_INDO:
            bulan = BULAN_INDO[kata_bersih]
        elif kata.isdigit() and len(kata) == 4:
            tahun = int(kata)

    if bulan and tahun:
        try:
            return datetime(tahun, bulan, 1)
        except ValueError:
            return None
    return None


def simpan_berita(items):
    conn = get_db()
    baru = 0
    for item in items:
        try:
            conn.execute(
                """INSERT INTO berita
                   (judul, link, sumber, tanggal_terbit, tanggal_terbit_iso, kata_kunci, ditemukan_pada)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    item["judul"],
                    item["link"],
                    item["sumber"],
                    item["tanggal"],
                    item["tanggal_iso"],
                    item["kata_kunci"],
                    datetime.now().isoformat(),
                ),
            )
            baru += 1
        except sqlite3.IntegrityError:
            pass  # link sudah ada, skip
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
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except Exception as e:
        print(f"Gagal fetch untuk '{term}': {e}")
        return []

    results = []
    for entry in feed.entries:
        if is_berita_luar_negeri(entry.title) or is_berita_tidak_relevan(entry.title):
            continue  # lewati berita luar negeri atau yang tidak relevan
        tanggal_iso = ""
        if getattr(entry, "published_parsed", None):
            try:
                tanggal_iso = datetime(*entry.published_parsed[:6]).isoformat()
            except Exception:
                tanggal_iso = ""
        results.append({
            "judul": entry.title,
            "link": entry.link,
            "sumber": entry.get("source", {}).get("title", "Tidak diketahui"),
            "tanggal": entry.get("published", ""),
            "tanggal_iso": tanggal_iso,
            "kata_kunci": term,
        })
    return results


def jalankan_pencarian():
    total_baru = 0
    error_terjadi = False
    for term in get_all_search_terms():
        items = fetch_news_for_term(term)
        if not items:
            error_terjadi = True
        total_baru += simpan_berita(items)
    return total_baru, error_terjadi


def background_scheduler():
    while True:
        try:
            jumlah, _ = jalankan_pencarian()
            print(f"[{datetime.now()}] Auto-refresh berita selesai, {jumlah} berita baru.")
        except Exception as e:
            print(f"[{datetime.now()}] Gagal auto-refresh berita: {e}")
        time.sleep(AUTO_REFRESH_INTERVAL)


def background_sheet_sync():
    if not sheets_terkonfigurasi():
        print("Sinkron Google Sheets belum dikonfigurasi, auto-sync tidak dijalankan.")
        return
    while True:
        time.sleep(SHEET_SYNC_INTERVAL)
        try:
            hasil = sinkron_sheet()
            print(f"[{datetime.now()}] Auto-sync sheet selesai: {hasil}")
        except Exception as e:
            print(f"[{datetime.now()}] Gagal auto-sync sheet: {e}")


# ---------------------------------------------------------
# TEMPLATE
# ---------------------------------------------------------

BASE_STYLE = """
<style>
    * { box-sizing: border-box; }
    body { font-family: -apple-system, sans-serif; margin: 0; padding: 0; background: #faf7f5; color: #222; }
    .wrap { max-width: 1200px; margin: 0 auto; padding: 20px; }
    h1 { color: #b5478c; margin-bottom: 4px; }
    .tabs { display: flex; gap: 8px; margin: 16px 0; border-bottom: 2px solid #eee; }
    .tab { padding: 10px 18px; text-decoration: none; color: #666; border-bottom: 3px solid transparent; font-weight: 600; }
    .tab.active { color: #b5478c; border-bottom-color: #b5478c; }
    button, input[type=submit], .btn { background: #b5478c; color: white; border: none; padding: 9px 16px; border-radius: 6px; cursor: pointer; font-size: 14px; text-decoration: none; display: inline-block; }
    button:hover, input[type=submit]:hover, .btn:hover { background: #99396f; }
    .btn-secondary { background: #888; }
    .btn-secondary:hover { background: #666; }
    .btn-danger { background: #c0392b; }
    .btn-danger:hover { background: #992d22; }
    input[type=text], select, textarea { padding: 8px; border-radius: 6px; border: 1px solid #ccc; font-size: 14px; }
    .toolbar { display: flex; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; align-items: center; }
    .card { background: white; border-radius: 10px; padding: 16px; margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
    .card a { text-decoration: none; color: #222; font-weight: 600; }
    .card a:hover { text-decoration: underline; }
    .meta { color: #888; font-size: 13px; margin-top: 6px; }
    .badge { display: inline-block; background: #f3e3ec; color: #b5478c; padding: 2px 8px; border-radius: 12px; font-size: 12px; margin-right: 6px; }
    .empty { text-align: center; color: #999; padding: 40px 0; }
    .chip { display: inline-flex; align-items: center; gap: 6px; background: #f3e3ec; color: #b5478c; padding: 4px 6px 4px 12px; border-radius: 14px; font-size: 13px; margin: 3px; }
    .chip form { margin: 0; }
    .chip button.hapus-chip { background: none; color: #b5478c; padding: 0 8px; font-size: 15px; font-weight: bold; }
    .flash { padding: 10px 14px; border-radius: 6px; margin-bottom: 14px; font-size: 14px; }
    .flash-ok { background: #e2f5e9; color: #1e7e42; }
    .flash-error { background: #fdecea; color: #b3261e; }
    table.tracker { width: 100%; border-collapse: collapse; background: white; font-size: 13px; }
    table.tracker th, table.tracker td { border: 1px solid #eee; padding: 8px; text-align: left; vertical-align: top; }
    table.tracker th { background: #f3e3ec; color: #99396f; white-space: nowrap; }
    table.tracker tr:hover { background: #fdf9fb; }
    .status-aktif { color: #1e7e42; font-weight: 600; }
    .status-tidak { color: #999; }
    .table-scroll { overflow-x: auto; border-radius: 10px; }
    .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; background: white; padding: 20px; border-radius: 10px; }
    .form-grid label { font-size: 13px; font-weight: 600; color: #555; display: block; margin-bottom: 4px; }
    .form-grid .full { grid-column: 1 / -1; }
    .form-grid input, .form-grid select, .form-grid textarea { width: 100%; }
    .form-actions { grid-column: 1 / -1; display: flex; gap: 10px; margin-top: 8px; }
    .aksi-cell { white-space: nowrap; }
    .aksi-cell a, .aksi-cell button { font-size: 12px; padding: 5px 9px; margin-right: 4px; }
</style>
"""

TEMPLATE_BERITA = """
<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<title>Artis Hamil Tracker</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
""" + BASE_STYLE + """
</head>
<body>
<div class="wrap">
    <h1>🎀 Artis Hamil Tracker</h1>
    <div class="tabs">
        <a class="tab active" href="{{ url_for('index') }}">Berita Terbaru</a>
        <a class="tab" href="{{ url_for('tracker') }}">Tracker Follow Up</a>
    </div>

    {% if flash_msg %}
    <div class="flash {{ 'flash-ok' if flash_ok else 'flash-error' }}">{{ flash_msg }}</div>
    {% endif %}

    <p>Total berita tersimpan: <strong>{{ total }}</strong> — auto-refresh tiap {{ interval_jam }} jam</p>

    <div class="toolbar">
        <form action="{{ url_for('refresh') }}" method="post" onsubmit="document.getElementById('btnRefresh').innerText='Memproses...'; document.getElementById('btnRefresh').disabled=true;">
            <button type="submit" id="btnRefresh">🔄 Refresh Sekarang</button>
        </form>
        <form action="{{ url_for('tambah_keyword') }}" method="post" style="display:flex; gap:8px; flex:1;">
            <input type="text" name="nama_artis" placeholder="Tambah nama artis untuk dipantau...">
            <input type="submit" value="Tambah">
        </form>
    </div>

    {% if keywords_tambahan %}
    <div style="margin-bottom: 16px;">
        <span style="font-size: 13px; color: #666;">Sedang memantau:</span><br>
        {% for kw in keywords_tambahan %}
        <span class="chip">
            {{ kw.nama }}
            <form action="{{ url_for('hapus_keyword', keyword_id=kw.id) }}" method="post" onsubmit="return confirm('Hapus {{ kw.nama }} dari daftar pantauan?');">
                <button type="submit" class="hapus-chip">✕</button>
            </form>
        </span>
        {% endfor %}
    </div>
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
</div>
</body>
</html>
"""

TEMPLATE_TRACKER = """
<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<title>Tracker Follow Up</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
""" + BASE_STYLE + """
</head>
<body>
<div class="wrap">
    <h1>🎀 Artis Hamil Tracker</h1>
    <div class="tabs">
        <a class="tab" href="{{ url_for('index') }}">Berita Terbaru</a>
        <a class="tab active" href="{{ url_for('tracker') }}">Tracker Follow Up</a>
    </div>

    {% if flash_msg %}
    <div class="flash {{ 'flash-ok' if flash_ok else 'flash-error' }}">{{ flash_msg }}</div>
    {% endif %}

    <div class="toolbar">
        <a href="{{ url_for('tambah_lead') }}" class="btn">+ Tambah Public Figure</a>
        <a href="{{ url_for('import_csv') }}" class="btn btn-secondary">📤 Import dari CSV</a>
        {% if sheets_aktif %}
        <form action="{{ url_for('sinkron_manual') }}" method="post">
            <button type="submit">🔗 Sinkron Spreadsheet</button>
        </form>
        <span style="font-size:12px; color:#1e7e42;">● Terhubung, auto-sync tiap 15 menit</span>
        {% else %}
        <span style="font-size:12px; color:#999;">● Sinkron spreadsheet belum diaktifkan</span>
        {% endif %}

        <form method="get" style="display:flex; gap:8px; align-items:center; margin-left:auto;">
            <label style="font-size:13px; color:#666;">Urutkan:</label>
            <select name="sort" onchange="this.form.submit()">
                <option value="terbaru" {{ 'selected' if sort == 'terbaru' else '' }}>Baru ditambahkan</option>
                <option value="hpl_terdekat" {{ 'selected' if sort == 'hpl_terdekat' else '' }}>HPL Paling Dekat</option>
                <option value="hpl_terjauh" {{ 'selected' if sort == 'hpl_terjauh' else '' }}>HPL Paling Jauh</option>
                <option value="bulan" {{ 'selected' if sort == 'bulan' else '' }}>Kode Sort (Bulan)</option>
                <option value="nama" {{ 'selected' if sort == 'nama' else '' }}>Nama A-Z</option>
            </select>

            <label style="font-size:13px; color:#666;">Status:</label>
            <select name="status" onchange="this.form.submit()">
                <option value="semua" {{ 'selected' if status_filter == 'semua' else '' }}>Semua</option>
                <option value="AKTIF" {{ 'selected' if status_filter == 'AKTIF' else '' }}>Aktif saja</option>
                <option value="TIDAK AKTIF" {{ 'selected' if status_filter == 'TIDAK AKTIF' else '' }}>Tidak Aktif saja</option>
            </select>

            <label style="font-size:13px; color:#666;">Hasil Akhir:</label>
            <select name="hasil" onchange="this.form.submit()">
                <option value="semua" {{ 'selected' if hasil_filter == 'semua' else '' }}>Semua</option>
                {% for h in pilihan_hasil %}
                <option value="{{ h }}" {{ 'selected' if hasil_filter == h else '' }}>{{ h }}</option>
                {% endfor %}
                <option value="KOSONG" {{ 'selected' if hasil_filter == 'KOSONG' else '' }}>(Belum diisi)</option>
            </select>
        </form>
    </div>

    <div class="table-scroll">
    <table class="tracker">
        <thead>
            <tr>
                <th>No</th>
                <th>Nama Public Figure</th>
                <th>Domisili</th>
                <th>Rate Card</th>
                <th>Followers IG</th>
                <th>Followers TikTok</th>
                <th>Followers FB</th>
                <th>Rata2 Views</th>
                <th>Link Sosmed</th>
                <th>No WA</th>
                <th>HPL</th>
                <th>Kontak Pertama (Tgl)</th>
                <th>Kontak Pertama (Hasil)</th>
                <th>Follow Up Lanjutan (Tgl)</th>
                <th>Follow Up Lanjutan (Hasil)</th>
                <th>Follow Up Terakhir (Tgl)</th>
                <th>Hasil Akhir</th>
                <th>Keterangan</th>
                <th>Bulan</th>
                <th>Status</th>
                <th>Aksi</th>
            </tr>
        </thead>
        <tbody>
            {% for l in leads %}
            <tr>
                <td>{{ loop.index }}</td>
                <td>{{ l.nama }}</td>
                <td>{{ l.domisili or '' }}</td>
                <td>{{ l.rate_card or '' }}</td>
                <td>{{ l.followers_ig or '' }}</td>
                <td>{{ l.followers_tiktok or '' }}</td>
                <td>{{ l.followers_fb or '' }}</td>
                <td>{{ l.rata2_views or '' }}</td>
                <td>{% if l.link_sosmed %}<a href="{{ l.link_sosmed.split(',')[0].strip() }}" target="_blank">Link</a>{% endif %}</td>
                <td>{{ l.no_wa or '' }}</td>
                <td>{{ l.hpl or '' }}</td>
                <td>{{ l.kontak_pertama_tanggal or '' }}</td>
                <td>{{ l.kontak_pertama_hasil or '' }}</td>
                <td>{{ l.followup_lanjutan_tanggal or '' }}</td>
                <td>{{ l.followup_lanjutan_hasil or '' }}</td>
                <td>{{ l.followup_terakhir_tanggal or '' }}</td>
                <td>{{ l.hasil_akhir or '' }}</td>
                <td>{{ l.keterangan or '' }}</td>
                <td>{{ l.bulan or '' }}</td>
                <td class="{{ 'status-aktif' if l.aktif == 'AKTIF' else 'status-tidak' }}">{{ l.aktif }}</td>
                <td class="aksi-cell">
                    <a href="{{ url_for('edit_lead', lead_id=l.id) }}" class="btn btn-secondary">Edit</a>
                    <form action="{{ url_for('hapus_lead', lead_id=l.id) }}" method="post" style="display:inline;" onsubmit="return confirm('Hapus data {{ l.nama }}?');">
                        <button type="submit" class="btn-danger">Hapus</button>
                    </form>
                </td>
            </tr>
            {% endfor %}
            {% if leads|length == 0 %}
            <tr><td colspan="21" class="empty">Belum ada data. Klik "+ Tambah Public Figure" untuk mulai.</td></tr>
            {% endif %}
        </tbody>
    </table>
    </div>
</div>
</body>
</html>
"""

TEMPLATE_FORM_LEAD = """
<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<title>{{ 'Edit' if lead else 'Tambah' }} Public Figure</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
""" + BASE_STYLE + """
</head>
<body>
<div class="wrap">
    <h1>🎀 {{ 'Edit' if lead else 'Tambah' }} Public Figure</h1>
    <div class="tabs">
        <a class="tab" href="{{ url_for('index') }}">Berita Terbaru</a>
        <a class="tab active" href="{{ url_for('tracker') }}">Tracker Follow Up</a>
    </div>

    <form method="post" class="form-grid">
        <div>
            <label>Nama Public Figure *</label>
            <input type="text" name="nama" required value="{{ lead.nama if lead else '' }}">
        </div>
        <div>
            <label>Domisili</label>
            <input type="text" name="domisili" value="{{ lead.domisili if lead else '' }}">
        </div>
        <div>
            <label>Rate Card</label>
            <input type="text" name="rate_card" value="{{ lead.rate_card if lead else '' }}">
        </div>
        <div>
            <label>Followers Instagram</label>
            <input type="text" name="followers_ig" value="{{ lead.followers_ig if lead else '' }}">
        </div>
        <div>
            <label>Followers TikTok</label>
            <input type="text" name="followers_tiktok" value="{{ lead.followers_tiktok if lead else '' }}">
        </div>
        <div>
            <label>Followers Facebook</label>
            <input type="text" name="followers_fb" value="{{ lead.followers_fb if lead else '' }}">
        </div>
        <div>
            <label>Rata-rata Views</label>
            <input type="text" name="rata2_views" value="{{ lead.rata2_views if lead else '' }}">
        </div>
        <div class="full">
            <label>Link Sosmed</label>
            <input type="text" name="link_sosmed" value="{{ lead.link_sosmed if lead else '' }}">
        </div>
        <div>
            <label>No WA</label>
            <input type="text" name="no_wa" value="{{ lead.no_wa if lead else '' }}">
        </div>
        <div>
            <label>HPL</label>
            <input type="text" name="hpl" placeholder="misal: Mei 2026" value="{{ lead.hpl if lead else '' }}">
        </div>
        <div>
            <label>Kontak Pertama — Tanggal</label>
            <input type="text" name="kontak_pertama_tanggal" placeholder="DD/MM/YYYY" value="{{ lead.kontak_pertama_tanggal if lead else '' }}">
        </div>
        <div>
            <label>Kontak Pertama — Hasil</label>
            <input type="text" name="kontak_pertama_hasil" value="{{ lead.kontak_pertama_hasil if lead else '' }}">
        </div>
        <div>
            <label>Follow Up Lanjutan — Tanggal</label>
            <input type="text" name="followup_lanjutan_tanggal" placeholder="DD/MM/YYYY" value="{{ lead.followup_lanjutan_tanggal if lead else '' }}">
        </div>
        <div>
            <label>Follow Up Lanjutan — Hasil</label>
            <input type="text" name="followup_lanjutan_hasil" value="{{ lead.followup_lanjutan_hasil if lead else '' }}">
        </div>
        <div>
            <label>Follow Up Terakhir — Tanggal</label>
            <input type="text" name="followup_terakhir_tanggal" placeholder="DD/MM/YYYY" value="{{ lead.followup_terakhir_tanggal if lead else '' }}">
        </div>
        <div>
            <label>Hasil Akhir</label>
            <select name="hasil_akhir">
                {% for opt in ['BELUM', 'TIDAK', 'CLOSING', 'NON MUSLIM / KRISTEN'] %}
                <option value="{{ opt }}" {{ 'selected' if lead and lead.hasil_akhir == opt else '' }}>{{ opt }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="full">
            <label>Keterangan</label>
            <textarea name="keterangan" rows="2">{{ lead.keterangan if lead else '' }}</textarea>
        </div>
        <div>
            <label>Bulan (kode sort)</label>
            <input type="text" name="bulan" value="{{ lead.bulan if lead else '' }}">
        </div>
        <div>
            <label>Status</label>
            <select name="aktif">
                <option value="AKTIF" {{ 'selected' if lead and lead.aktif == 'AKTIF' else '' }}>AKTIF</option>
                <option value="TIDAK AKTIF" {{ 'selected' if lead and lead.aktif == 'TIDAK AKTIF' else '' }}>TIDAK AKTIF</option>
            </select>
        </div>
        <div class="form-actions">
            <button type="submit">Simpan</button>
            <a href="{{ url_for('tracker') }}" class="btn btn-secondary">Batal</a>
        </div>
    </form>
</div>
</body>
</html>
"""


TEMPLATE_IMPORT = """
<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<title>Import CSV</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
""" + BASE_STYLE + """
</head>
<body>
<div class="wrap">
    <h1>🎀 Import Data dari CSV</h1>
    <div class="tabs">
        <a class="tab" href="{{ url_for('index') }}">Berita Terbaru</a>
        <a class="tab active" href="{{ url_for('tracker') }}">Tracker Follow Up</a>
    </div>

    {% if flash_msg %}
    <div class="flash {{ 'flash-ok' if flash_ok else 'flash-error' }}">{{ flash_msg }}</div>
    {% endif %}

    <div class="card">
        <p style="margin-top:0;">
            Upload file CSV dengan format kolom seperti spreadsheet tracker kamu:
            <strong>NO, NAMA PUBLIC FIGURE, DOMISILI, RATE CARD, JUMLAH FOLLOWERS (Instagram/TikTok/FB),
            RATA2 VIEWS, LINK SOSMED, NO WA, HPL, KONTAK PERTAMA (Tanggal/Hasil),
            FOLLOW UP LANJUTAN (Tanggal/Hasil), FOLLOW UP TERAKHIR (Tanggal/Hasil Akhir/Keterangan),
            KODE SORT (BULAN/AKTIF)</strong>.
        </p>
        <p style="color:#888; font-size: 13px;">
            Baris duplikat (nama + no WA yang sama persis dengan data yang sudah ada) akan dilewati otomatis,
            jadi aman kalau kamu upload file yang sama dua kali.
        </p>
        <form method="post" enctype="multipart/form-data">
            <input type="file" name="file_csv" accept=".csv" required>
            <br><br>
            <button type="submit">Upload &amp; Import</button>
            <a href="{{ url_for('tracker') }}" class="btn btn-secondary">Batal</a>
        </form>
    </div>
</div>
</body>
</html>
"""


def tarik_dari_sheet():
    """Sheet -> App. Baris baru di-insert, baris yang sudah ada di-update ikut isi sheet."""
    ws = get_worksheet()
    if ws is None:
        return 0, 0

    semua_baris = ws.get_all_records()  # list of dict, key = header row
    conn = get_db()
    leads_ada = {}
    for row in conn.execute("SELECT * FROM leads").fetchall():
        kunci = (row["nama"].strip().lower(), (row["no_wa"] or "").strip())
        leads_ada[kunci] = row["id"]

    ditambah = 0
    diupdate = 0
    for baris in semua_baris:
        nama = str(baris.get("Nama Public Figure", "")).strip()
        if not nama:
            continue
        no_wa = str(baris.get("No WA", "")).strip()
        kunci = (nama.lower(), no_wa)

        nilai = {
            "nama": nama,
            "domisili": str(baris.get("Domisili", "")).strip(),
            "rate_card": str(baris.get("Rate Card", "")).strip(),
            "followers_ig": str(baris.get("Followers IG", "")).strip(),
            "followers_tiktok": str(baris.get("Followers TikTok", "")).strip(),
            "followers_fb": str(baris.get("Followers FB", "")).strip(),
            "rata2_views": str(baris.get("Rata2 Views", "")).strip(),
            "link_sosmed": str(baris.get("Link Sosmed", "")).strip(),
            "no_wa": no_wa,
            "hpl": str(baris.get("HPL", "")).strip(),
            "kontak_pertama_tanggal": str(baris.get("Kontak Pertama - Tanggal", "")).strip(),
            "kontak_pertama_hasil": str(baris.get("Kontak Pertama - Hasil", "")).strip(),
            "followup_lanjutan_tanggal": str(baris.get("Follow Up Lanjutan - Tanggal", "")).strip(),
            "followup_lanjutan_hasil": str(baris.get("Follow Up Lanjutan - Hasil", "")).strip(),
            "followup_terakhir_tanggal": str(baris.get("Follow Up Terakhir - Tanggal", "")).strip(),
            "hasil_akhir": str(baris.get("Hasil Akhir", "")).strip(),
            "keterangan": str(baris.get("Keterangan", "")).strip(),
            "bulan": str(baris.get("Bulan", "")).strip() or None,
            "aktif": str(baris.get("Aktif", "")).strip() or "AKTIF",
        }

        if kunci in leads_ada:
            conn.execute(
                """UPDATE leads SET domisili=?, rate_card=?, followers_ig=?, followers_tiktok=?,
                   followers_fb=?, rata2_views=?, link_sosmed=?, hpl=?,
                   kontak_pertama_tanggal=?, kontak_pertama_hasil=?,
                   followup_lanjutan_tanggal=?, followup_lanjutan_hasil=?,
                   followup_terakhir_tanggal=?, hasil_akhir=?, keterangan=?, bulan=?, aktif=?
                   WHERE id=?""",
                (
                    nilai["domisili"], nilai["rate_card"], nilai["followers_ig"], nilai["followers_tiktok"],
                    nilai["followers_fb"], nilai["rata2_views"], nilai["link_sosmed"], nilai["hpl"],
                    nilai["kontak_pertama_tanggal"], nilai["kontak_pertama_hasil"],
                    nilai["followup_lanjutan_tanggal"], nilai["followup_lanjutan_hasil"],
                    nilai["followup_terakhir_tanggal"], nilai["hasil_akhir"], nilai["keterangan"],
                    nilai["bulan"], nilai["aktif"], leads_ada[kunci],
                ),
            )
            diupdate += 1
        else:
            conn.execute(
                """INSERT INTO leads
                   (nama, domisili, rate_card, followers_ig, followers_tiktok, followers_fb,
                    rata2_views, link_sosmed, no_wa, hpl, kontak_pertama_tanggal, kontak_pertama_hasil,
                    followup_lanjutan_tanggal, followup_lanjutan_hasil, followup_terakhir_tanggal,
                    hasil_akhir, keterangan, bulan, aktif, dibuat_pada)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    nilai["nama"], nilai["domisili"], nilai["rate_card"], nilai["followers_ig"],
                    nilai["followers_tiktok"], nilai["followers_fb"], nilai["rata2_views"],
                    nilai["link_sosmed"], nilai["no_wa"], nilai["hpl"],
                    nilai["kontak_pertama_tanggal"], nilai["kontak_pertama_hasil"],
                    nilai["followup_lanjutan_tanggal"], nilai["followup_lanjutan_hasil"],
                    nilai["followup_terakhir_tanggal"], nilai["hasil_akhir"], nilai["keterangan"],
                    nilai["bulan"], nilai["aktif"], datetime.now().isoformat(),
                ),
            )
            leads_ada[kunci] = True
            ditambah += 1

    conn.commit()
    conn.close()
    return ditambah, diupdate


def kirim_baris_baru_ke_sheet():
    """App -> Sheet. Hanya kirim baris yang ADA di app tapi BELUM ada di sheet (tidak menimpa)."""
    ws = get_worksheet()
    if ws is None:
        return 0

    semua_baris = ws.get_all_records()
    kunci_di_sheet = set()
    for baris in semua_baris:
        nama = str(baris.get("Nama Public Figure", "")).strip().lower()
        wa = str(baris.get("No WA", "")).strip()
        if nama:
            kunci_di_sheet.add((nama, wa))

    conn = get_db()
    leads = conn.execute("SELECT * FROM leads").fetchall()
    conn.close()

    baris_baru = []
    for l in leads:
        kunci = ((l["nama"] or "").strip().lower(), (l["no_wa"] or "").strip())
        if kunci in kunci_di_sheet:
            continue
        baris_baru.append([str(l[kol] or "") for kol in SHEET_KOLOM])

    if baris_baru:
        ws.append_rows(baris_baru)

    return len(baris_baru)


def sinkron_sheet():
    """Jalankan siklus sinkron penuh: tarik dulu dari sheet, baru kirim baris baru dari app."""
    if not sheets_terkonfigurasi():
        return None
    ditambah, diupdate = tarik_dari_sheet()
    dikirim = kirim_baris_baru_ke_sheet()
    return {"ditambah": ditambah, "diupdate": diupdate, "dikirim": dikirim}


# ---------------------------------------------------------
# ROUTES — BERITA
# ---------------------------------------------------------

@app.route("/")
def index():
    conn = get_db()
    semua_berita = conn.execute(
        """SELECT * FROM berita
           ORDER BY
             CASE WHEN tanggal_terbit_iso = '' OR tanggal_terbit_iso IS NULL THEN 1 ELSE 0 END,
             tanggal_terbit_iso DESC
           LIMIT 200"""
    ).fetchall()
    # Saring juga berita lama yang mungkin sudah tersimpan sebelum filter ini ada
    berita = [
        b for b in semua_berita
        if not is_berita_luar_negeri(b["judul"]) and not is_berita_tidak_relevan(b["judul"])
    ][:100]
    total = conn.execute("SELECT COUNT(*) as c FROM berita").fetchone()["c"]
    kw_rows = get_all_keywords_rows()
    conn.close()

    flash_msg = request.args.get("msg")
    flash_ok = request.args.get("ok") == "1"

    return render_template_string(
        TEMPLATE_BERITA,
        berita=berita,
        total=total,
        interval_jam=AUTO_REFRESH_INTERVAL // 3600,
        keywords_tambahan=kw_rows,
        flash_msg=flash_msg,
        flash_ok=flash_ok,
    )


@app.route("/refresh", methods=["POST"])
def refresh():
    jumlah, error_terjadi = jalankan_pencarian()
    if jumlah == 0 and error_terjadi:
        msg = "Refresh selesai tapi tidak ada berita baru ditemukan (bisa jadi belum ada berita baru, atau Google News sedang membatasi request — coba lagi beberapa saat lagi)."
        ok = "0"
    elif jumlah == 0:
        msg = "Refresh selesai, tidak ada berita baru (semua berita yang ada sudah tersimpan sebelumnya)."
        ok = "1"
    else:
        msg = f"Refresh selesai, {jumlah} berita baru ditemukan."
        ok = "1"
    return redirect(url_for("index", msg=msg, ok=ok))


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
        items = fetch_news_for_term(f'"{nama}" hamil')
        simpan_berita(items)
    return redirect(url_for("index"))


@app.route("/hapus-keyword/<int:keyword_id>", methods=["POST"])
def hapus_keyword(keyword_id):
    conn = get_db()
    conn.execute("DELETE FROM keyword_tambahan WHERE id = ?", (keyword_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("index"))


@app.route("/api/berita")
def api_berita():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM berita ORDER BY tanggal_terbit_iso DESC LIMIT 200"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ---------------------------------------------------------
# ROUTES — TRACKER (CRM)
# ---------------------------------------------------------

@app.route("/tracker")
def tracker():
    sort = request.args.get("sort", "terbaru")
    status_filter = request.args.get("status", "semua")
    hasil_filter = request.args.get("hasil", "semua")

    conn = get_db()
    query = "SELECT * FROM leads"
    kondisi = []
    params = []
    if status_filter in ("AKTIF", "TIDAK AKTIF"):
        kondisi.append("aktif = ?")
        params.append(status_filter)
    if hasil_filter == "KOSONG":
        kondisi.append("(hasil_akhir IS NULL OR hasil_akhir = '')")
    elif hasil_filter != "semua":
        kondisi.append("hasil_akhir = ?")
        params.append(hasil_filter)
    if kondisi:
        query += " WHERE " + " AND ".join(kondisi)
    query += " ORDER BY id DESC"
    leads = conn.execute(query, params).fetchall()

    # Ambil daftar nilai Hasil Akhir yang benar-benar ada di data, untuk isi dropdown
    pilihan_hasil = [
        r["hasil_akhir"] for r in conn.execute(
            "SELECT DISTINCT hasil_akhir FROM leads WHERE hasil_akhir IS NOT NULL AND hasil_akhir != '' ORDER BY hasil_akhir"
        ).fetchall()
    ]
    conn.close()

    leads = list(leads)
    if sort == "hpl_terdekat":
        leads.sort(key=lambda l: (parse_hpl(l["hpl"]) is None, parse_hpl(l["hpl"]) or datetime.max))
    elif sort == "hpl_terjauh":
        leads.sort(key=lambda l: (parse_hpl(l["hpl"]) is None, parse_hpl(l["hpl"]) or datetime.min), reverse=True)
        # baris tanpa HPL tetap taruh di akhir meski reverse
        leads.sort(key=lambda l: parse_hpl(l["hpl"]) is None)
    elif sort == "nama":
        leads.sort(key=lambda l: (l["nama"] or "").lower())
    elif sort == "bulan":
        leads.sort(key=lambda l: (l["bulan"] is None or l["bulan"] == "", l["bulan"] or ""))
    # sort == "terbaru" -> biarkan urutan default (ORDER BY id DESC dari query)

    flash_msg = request.args.get("msg")
    flash_ok = request.args.get("ok") == "1"
    return render_template_string(
        TEMPLATE_TRACKER, leads=leads, flash_msg=flash_msg, flash_ok=flash_ok,
        sort=sort, status_filter=status_filter, hasil_filter=hasil_filter,
        pilihan_hasil=pilihan_hasil, sheets_aktif=sheets_terkonfigurasi(),
    )


def form_ke_dict(form):
    return {
        "nama": form.get("nama", "").strip(),
        "domisili": form.get("domisili", "").strip(),
        "rate_card": form.get("rate_card", "").strip(),
        "followers_ig": form.get("followers_ig", "").strip(),
        "followers_tiktok": form.get("followers_tiktok", "").strip(),
        "followers_fb": form.get("followers_fb", "").strip(),
        "rata2_views": form.get("rata2_views", "").strip(),
        "link_sosmed": form.get("link_sosmed", "").strip(),
        "no_wa": form.get("no_wa", "").strip(),
        "hpl": form.get("hpl", "").strip(),
        "kontak_pertama_tanggal": form.get("kontak_pertama_tanggal", "").strip(),
        "kontak_pertama_hasil": form.get("kontak_pertama_hasil", "").strip(),
        "followup_lanjutan_tanggal": form.get("followup_lanjutan_tanggal", "").strip(),
        "followup_lanjutan_hasil": form.get("followup_lanjutan_hasil", "").strip(),
        "followup_terakhir_tanggal": form.get("followup_terakhir_tanggal", "").strip(),
        "hasil_akhir": form.get("hasil_akhir", "").strip(),
        "keterangan": form.get("keterangan", "").strip(),
        "bulan": form.get("bulan", "").strip() or None,
        "aktif": form.get("aktif", "AKTIF"),
    }


@app.route("/tracker/sinkron", methods=["POST"])
def sinkron_manual():
    if not sheets_terkonfigurasi():
        return redirect(url_for(
            "tracker",
            msg="Sinkron Google Sheets belum dikonfigurasi. Lihat panduan setup untuk isi GOOGLE_SHEET_ID dan GOOGLE_SERVICE_ACCOUNT_JSON.",
            ok="0",
        ))
    try:
        hasil = sinkron_sheet()
        msg = (
            f"Sinkron selesai: {hasil['ditambah']} baris baru ditarik dari sheet, "
            f"{hasil['diupdate']} baris diperbarui dari sheet, "
            f"{hasil['dikirim']} baris baru dikirim ke sheet."
        )
        return redirect(url_for("tracker", msg=msg, ok="1"))
    except Exception as e:
        return redirect(url_for("tracker", msg=f"Sinkron gagal: {e}", ok="0"))


@app.route("/tracker/tambah", methods=["GET", "POST"])
def tambah_lead():
    if request.method == "POST":
        d = form_ke_dict(request.form)
        if not d["nama"]:
            return redirect(url_for("tambah_lead"))
        conn = get_db()
        conn.execute(
            """INSERT INTO leads
               (nama, domisili, rate_card, followers_ig, followers_tiktok, followers_fb,
                rata2_views, link_sosmed, no_wa, hpl, kontak_pertama_tanggal, kontak_pertama_hasil,
                followup_lanjutan_tanggal, followup_lanjutan_hasil, followup_terakhir_tanggal,
                hasil_akhir, keterangan, bulan, aktif, dibuat_pada)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                d["nama"], d["domisili"], d["rate_card"], d["followers_ig"], d["followers_tiktok"],
                d["followers_fb"], d["rata2_views"], d["link_sosmed"], d["no_wa"], d["hpl"],
                d["kontak_pertama_tanggal"], d["kontak_pertama_hasil"],
                d["followup_lanjutan_tanggal"], d["followup_lanjutan_hasil"],
                d["followup_terakhir_tanggal"], d["hasil_akhir"], d["keterangan"],
                d["bulan"], d["aktif"], datetime.now().isoformat(),
            ),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("tracker", msg="Data baru berhasil ditambahkan.", ok="1"))
    return render_template_string(TEMPLATE_FORM_LEAD, lead=None)


@app.route("/tracker/edit/<int:lead_id>", methods=["GET", "POST"])
def edit_lead(lead_id):
    conn = get_db()
    if request.method == "POST":
        d = form_ke_dict(request.form)
        conn.execute(
            """UPDATE leads SET nama=?, domisili=?, rate_card=?, followers_ig=?, followers_tiktok=?,
               followers_fb=?, rata2_views=?, link_sosmed=?, no_wa=?, hpl=?,
               kontak_pertama_tanggal=?, kontak_pertama_hasil=?,
               followup_lanjutan_tanggal=?, followup_lanjutan_hasil=?,
               followup_terakhir_tanggal=?, hasil_akhir=?, keterangan=?,
               bulan=?, aktif=? WHERE id=?""",
            (
                d["nama"], d["domisili"], d["rate_card"], d["followers_ig"], d["followers_tiktok"],
                d["followers_fb"], d["rata2_views"], d["link_sosmed"], d["no_wa"], d["hpl"],
                d["kontak_pertama_tanggal"], d["kontak_pertama_hasil"],
                d["followup_lanjutan_tanggal"], d["followup_lanjutan_hasil"],
                d["followup_terakhir_tanggal"], d["hasil_akhir"], d["keterangan"],
                d["bulan"], d["aktif"], lead_id,
            ),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("tracker", msg="Data berhasil diperbarui.", ok="1"))

    lead = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    conn.close()
    if lead is None:
        return redirect(url_for("tracker"))
    return render_template_string(TEMPLATE_FORM_LEAD, lead=lead)


def parse_angka_bulan(nilai):
    """Ambil angka dari teks kode sort bulan, kalau tidak ada angka return None."""
    nilai = (nilai or "").strip()
    if nilai.isdigit():
        return nilai
    return nilai or None


@app.route("/tracker/import", methods=["GET", "POST"])
def import_csv():
    if request.method == "GET":
        return render_template_string(TEMPLATE_IMPORT, flash_msg=None, flash_ok=True)

    file = request.files.get("file_csv")
    if not file or file.filename == "":
        return render_template_string(
            TEMPLATE_IMPORT, flash_msg="Pilih file CSV terlebih dahulu.", flash_ok=False
        )

    try:
        konten = file.stream.read().decode("utf-8-sig")
        reader = list(csv.reader(io.StringIO(konten)))
    except Exception as e:
        return render_template_string(
            TEMPLATE_IMPORT, flash_msg=f"Gagal membaca file: {e}", flash_ok=False
        )

    # Lewati 2 baris header (baris judul kolom & sub-judul kolom)
    baris_data = reader[2:] if len(reader) > 2 else []

    conn = get_db()
    # Ambil kombinasi nama+wa yang sudah ada, untuk cegah duplikat
    sudah_ada = set()
    for row in conn.execute("SELECT nama, no_wa FROM leads").fetchall():
        sudah_ada.add((row["nama"].strip().lower(), (row["no_wa"] or "").strip()))

    ditambahkan = 0
    dilewati = 0

    for row in baris_data:
        # Pastikan baris punya cukup kolom, isi kosong kalau kurang
        row = row + [""] * (20 - len(row))

        nama = row[1].strip()
        if not nama:
            continue  # baris kosong, lewati

        no_wa = row[9].strip()
        kunci = (nama.lower(), no_wa)
        if kunci in sudah_ada:
            dilewati += 1
            continue

        conn.execute(
            """INSERT INTO leads
               (nama, domisili, rate_card, followers_ig, followers_tiktok, followers_fb,
                rata2_views, link_sosmed, no_wa, hpl, kontak_pertama_tanggal, kontak_pertama_hasil,
                followup_lanjutan_tanggal, followup_lanjutan_hasil, followup_terakhir_tanggal,
                hasil_akhir, keterangan, bulan, aktif, dibuat_pada)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                nama,
                row[2].strip(),
                row[3].strip(),
                row[4].strip(),
                row[5].strip(),
                row[6].strip(),
                row[7].strip(),
                row[8].strip(),
                no_wa,
                row[10].strip(),
                row[11].strip(),
                row[12].strip(),
                row[13].strip(),
                row[14].strip(),
                row[15].strip(),
                row[16].strip(),
                row[17].strip(),
                parse_angka_bulan(row[18]),
                row[19].strip() or "AKTIF",
                datetime.now().isoformat(),
            ),
        )
        sudah_ada.add(kunci)
        ditambahkan += 1

    conn.commit()
    conn.close()

    msg = f"Import selesai: {ditambahkan} data baru ditambahkan"
    if dilewati:
        msg += f", {dilewati} dilewati karena sudah ada sebelumnya"
    msg += "."

    return redirect(url_for("tracker", msg=msg, ok="1"))


@app.route("/tracker/hapus/<int:lead_id>", methods=["POST"])
def hapus_lead(lead_id):
    conn = get_db()
    conn.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("tracker", msg="Data berhasil dihapus.", ok="1"))


# ---------------------------------------------------------
# START
# ---------------------------------------------------------

init_db()

scheduler_thread = threading.Thread(target=background_scheduler, daemon=True)
scheduler_thread.start()

sheet_sync_thread = threading.Thread(target=background_sheet_sync, daemon=True)
sheet_sync_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
