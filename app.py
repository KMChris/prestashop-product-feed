import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List

import pymysql
from flask import Flask, request, abort, send_from_directory, send_file
from pymysql.cursors import DictCursor
from werkzeug.utils import secure_filename

from convert import FeedConfig, generate_feed

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024
BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

QUERY_SQL_PATH = BASE_DIR / "query.sql"

try:
    FEED_CACHE_SECONDS = max(0, int(os.environ.get("FEED_CACHE_SECONDS", 15 * 60)))
except (TypeError, ValueError):
    FEED_CACHE_SECONDS = 15 * 60
FEED_CACHE_PATH = OUTPUT_DIR / "product_feed.xml"
FEED_CACHE_LOCK = threading.Lock()

SITE_URL = os.environ.get("SITE_URL", "https://twojsklep.pl")
SHOP_NAME = os.environ.get("SHOP_NAME", "Twój sklep")
PRODUCT_FEED_CONFIG = FeedConfig(
    shop_name=SHOP_NAME,
    site_link=SITE_URL,
    channel_description="Product feed",
    product_url_template="{SITE_URL}/{category_slug}/{id_product}-{id_product_attribute}-{link_rewrite}.html",
    image_url_template="{SITE_URL}/{id_image}-large_default/{link_rewrite}.jpg",
    currency="PLN",
)
ALLOWED_EXTENSIONS = {"csv"}


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _get_db_connection():
    host = os.environ.get("DB_HOST")
    user = os.environ.get("DB_USER")
    password = os.environ.get("DB_PASSWORD")
    database = os.environ.get("DB_NAME")
    port = int(os.environ.get("DB_PORT", "3306"))

    missing = [name for name, value in (
        ("DB_HOST", host),
        ("DB_USER", user),
        ("DB_PASSWORD", password),
        ("DB_NAME", database)
    ) if not value]
    if missing:
        abort(500, description=f"Brak konfiguracji bazy danych: {', '.join(missing)}")

    return pymysql.connect(
        host=host,
        user=user,
        password=password,
        database=database,
        port=port,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=True,
    )


def _load_query() -> str:
    try:
        return QUERY_SQL_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        abort(500, description="Plik query.sql nie został znaleziony.")


def _fetch_products() -> List[Dict[str, object]]:
    query = _load_query()
    try:
        with _get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query)
                rows = cursor.fetchall()
                return list(rows)
    except pymysql.Error as exc:
        app.logger.exception("Nie udało się pobrać danych z bazy: %s", exc)
        abort(500, description="Błąd podczas pobierania danych z bazy.")

@app.route("/convert", methods=["GET", "POST"])
def convert():
    if request.method == "GET":
        return send_from_directory(PUBLIC_DIR, "index.html", mimetype="text/html")
    
    # Walidacja części pliku
    if "file" not in request.files:
        abort(400, description="Brak pliku w żądaniu (pole 'file').")
    f = request.files["file"]
    if f.filename == "":
        abort(400, description="Nie wybrano pliku.")
    if not allowed_file(f.filename):
        abort(400, description="Dozwolone są wyłącznie pliki .csv.")

    # Zapis wejścia
    uid = uuid.uuid4().hex
    csv_name = secure_filename(f"{uid}_{f.filename}")
    csv_path = UPLOAD_DIR / csv_name
    f.save(csv_path)

    # Wyjściowa ścieżka XML
    xml_name = f"{uid}.xml"
    xml_path = OUTPUT_DIR / xml_name

    try:
        result = subprocess.run(
            ["python", "convert.py",
             "--csv-path", str(csv_path),
             "--out-xml", str(xml_path),
             "--shop-name", SHOP_NAME,
             "--site-link", SITE_URL,
             "--product-url-template", "{SITE_URL}/{category_slug}/{id_product}-{id_product_attribute}-{link_rewrite}.html",
             "--image-url-template", "{SITE_URL}/{id_image}-large_default/{link_rewrite}.jpg",
             "--currency", "PLN"],
            capture_output=True, text=True
        )
        if result.returncode != 0 or not xml_path.exists():
            app.logger.error("Konwersja nie powiodła się.\nSTDOUT:\n%s\nSTDERR:\n%s", result.stdout, result.stderr)
            abort(500, description="Konwersja nie powiodła się.")

        return send_from_directory(
            OUTPUT_DIR, xml_name, mimetype="application/xml"
        )
    finally:
        try:
            csv_path.unlink(missing_ok=True)
            
            now = time.time()
            retention_seconds = 24 * 60 * 60
            for p in OUTPUT_DIR.glob("*.xml"):
                if p == xml_path:
                    continue
                if now - p.stat().st_mtime > retention_seconds:
                    p.unlink(missing_ok=True)
        except Exception:
            pass


def _cache_is_fresh() -> bool:
    if FEED_CACHE_SECONDS <= 0:
        return False
    if not FEED_CACHE_PATH.exists():
        return False
    try:
        mtime = FEED_CACHE_PATH.stat().st_mtime
    except FileNotFoundError:
        return False
    return (time.time() - mtime) < FEED_CACHE_SECONDS


@app.route("/product-feed.xml", methods=["GET"])
def product_feed():
    if _cache_is_fresh():
        return send_file(FEED_CACHE_PATH, mimetype="application/xml")

    with FEED_CACHE_LOCK:
        if _cache_is_fresh():
            return send_file(FEED_CACHE_PATH, mimetype="application/xml")

        rows = _fetch_products()
        feed_bytes = generate_feed(rows, PRODUCT_FEED_CONFIG)

        tmp_path = FEED_CACHE_PATH.with_suffix(".tmp")
        tmp_path.write_bytes(feed_bytes)
        tmp_path.replace(FEED_CACHE_PATH)

    return send_file(FEED_CACHE_PATH, mimetype="application/xml")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
