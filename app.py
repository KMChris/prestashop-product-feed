import uuid
from pathlib import Path
from flask import Flask, request, abort, send_from_directory
from werkzeug.utils import secure_filename
import subprocess
import time

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {"csv"}


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

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
             "--shop-name", "Twój sklep",
             "--site-link", "https://www.twojsklep.pl",
             "--product-url-template", "https://twojsklep.pl/{category_slug}/{id_product}-{id_product_attribute}-{link_rewrite}.html",
             "--image-url-template", "https://twojsklep.pl/{id_image}-large_default/{link_rewrite}.jpg",
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
