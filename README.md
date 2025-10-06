# CSV → Google Merchant XML (PrestaShop)

Konwerter CSV (eksport z PrestaShop) do feedu XML zgodnego z Google Merchant (RSS 2.0 z przestrzenią `g:`). Repo zawiera gotową aplikację web (Flask) do wgrywania CSV oraz narzędzie CLI do konwersji wsadowej. Do generowania CSV możesz użyć dołączonego zapytania SQL.

## Co jest w środku

- `query.sql` – zapytanie SQL dla PrestaShop generujące CSV z wymaganymi kolumnami.
- `convert.py` – narzędzie CLI konwertujące CSV na XML Google Merchant.
- `app.py` – lekki serwer Flask z UI do wgrywania CSV i automatycznego pobierania XML.
- `public/index.html` – proste UI do wgrywania pliku w przeglądarce.

## Wymagania

- Python 3.8+ (sprawdzane przez `convert.py`).
- Do trybu web: `Flask` (biblioteka Pythona). Sam konwerter (`convert.py`) używa tylko standardowej biblioteki.
- CSV zakodowany w UTF‑8 z separatorem `;` (średnik) wygenerowany przez `query.sql`.

## Eksport CSV z PrestaShop

Możesz użyć jednej z dwóch metod:

- Użyj zapytania z pliku `query.sql` w swojej bazie PrestaShop (np. MySQL). Zapytanie zwraca wszystkie kolumny, których oczekuje `convert.py`.
- Alternatywnie z panelu administracyjnego PrestaShop (bez dostępu do serwera bazy):
  1. Wejdź w Zaawansowane → Baza danych → Menedżer SQL.
  2. Kliknij „Dodaj nowe zapytanie SQL”.
  3. Skopiuj i wklej treść pliku `query.sql`, następnie zapisz.
  4. Użyj ikony chmurki (Eksportuj), aby pobrać wynik jako plik CSV.

Zapytanie zwraca m.in. kolumny: `id_product`, `reference`, `name`, `link_rewrite`, `description`, `description_short`, `category_slug`, `id_product_attribute`, `id_image`, `additional_image_ids`, `quantity`, `out_of_stock_mode`, `condition`, `available_date`, `brand`, `ean13/upc/isbn`, `mpn`, `price_tax_excluded`, `final_price_tax_excluded`, itd. To pokrywa dane potrzebne do zbudowania poprawnego feedu.

W razie potrzeby możesz zmienić ID języka/sklepu w `query.sql` (w klauzulach `id_lang`, `id_shop`).

## Szybki start

### 1) Interfejs webowy (Flask)

- Zainstaluj zależności:
  ```bash
  pip install Flask
  ```
- Uruchom serwer:
  ```bash
  python app.py
  ```
- Otwórz w przeglądarce: http://localhost:8000/convert
- Przeciągnij i upuść CSV (lub wybierz plik), kliknij „Konwertuj”. Przeglądarka pobierze gotowy plik `XML`.

Domyślne parametry (nazwa sklepu, URL sklepu, szablony linków produktów/obrazów, waluta) są ustawione w `app.py` w wywołaniu `convert.py`. Dostosuj je do własnego sklepu (sekcja „Dostosowanie”).

Uwaga: serwer przyjmuje pliki do 20 MB, zapisuje je tymczasowo w `uploads/` i generuje XML do `outputs/`. Pliki XML starsze niż 24h są czyszczone.

### 2) Tryb CLI (bez serwera)

Przykład minimalny:

```powershell
python convert.py `
  --csv-path "export.csv" `
  --out-xml "feed.xml" `
  --shop-name "Twój sklep" `
  --site-link "https://www.twojsklep.pl" `
  --product-url-template "https://twojsklep.pl/{category_slug}/{id_product}-{id_product_attribute}-{link_rewrite}.html" `
  --image-url-template "https://twojsklep.pl/{id_image}-large_default/{link_rewrite}.jpg" `
  --currency PLN
```

## Wszystkie opcje `convert.py`

Ważniejsze argumenty:

- Wejście/wyjście:
  - `--csv-path` (wymagany): ścieżka do CSV z PrestaShop (separator `;`).
  - `--out-xml` (wymagany): ścieżka do wynikowego pliku XML.
- Metadane kanału:
  - `--shop-name` (wymagany): nazwa sklepu (`<channel><title>`).
  - `--site-link` (wymagany): URL strony głównej (`<channel><link>`).
  - `--channel-description` (opc.): opis kanału (tekst HTML jest czyszczony).
- Szablony URL:
  - `--product-url-template` (wymagany): link produktu (`{id_product}`, `{id_product_attribute}`, `{link_rewrite}`, `{category_slug}`).
  - `--image-url-template` (wymagany): link obrazka (`{id_image}`, `{link_rewrite}`).
- Ceny:
  - `--currency` (wymagany): np. `PLN`.
  - `--price-column` (opc., domyślnie `final_price_tax_excluded`): kolumna CSV z ceną netto bazową.
  - `--add-vat` (flaga): dolicz VAT do ceny z kolumny.
  - `--vat-rate` (opc., domyślnie `23.0`): procent VAT.
- Dostępność i stan:
  - `--availability-default` (opc., dom. `out_of_stock`): `in_stock|out_of_stock|preorder|backorder`.
  - `--condition-default` (opc., dom. `new`): `new|used|refurbished`.
- Identyfikatory i kategorie:
  - `--brand-default` (opc.): użyty, gdy brak `brand/manufacturer_name` w CSV.
  - `--google-product-category` (opc.): ID lub ścieżka kategorii Google.
  - `--product-type-from` (opc., dom. `category_slug`): nazwa kolumny CSV mapowanej do `<g:product_type>`.
- Dostawa (opcjonalny blok `<g:shipping>` — wszystkie trzy parametry muszą być ustawione):
  - `--shipping-country`, `--shipping-service`, `--shipping-price` (np. `15.00 PLN`).
- Dodatkowe zdjęcia:
  - `--additional-images-column` (opc., dom. `additional_image_ids`): kolumna CSV z ID obrazów rozdzielonych przecinkami.
  - `--max-additional-images` (opc., dom. `10`): limit zdjęć dodatkowych (limit Google).

## Jak powstaje feed

- Format: RSS 2.0 z przestrzenią nazw Google (`http://base.google.com/ns/1.0`).
- Dla każdego produktu (`<item>`) generowane są m.in.:
  - `<g:id>`, `<title>`, `<description>`, `<link>`
  - `<g:image_link>` i do 10× `<g:additional_image_link>`
  - `<g:availability>` (logika: `quantity>0` → `in_stock`; gdy `quantity<=0` i polityka „pozwól na zamówienie” → `backorder`; inaczej wartość domyślna)
  - `<g:availability_date>` (dla `preorder/backorder`, jeśli dostępna w danych)
  - `<g:condition>`
  - `<g:price>` (z walutą, opcjonalnie z doliczonym VAT)
  - `<g:brand>`, `<g:gtin>` (z `ean13/upc/isbn`), `<g:mpn>` (tylko gdy brak GTIN)
  - `<g:product_type>`, `<g:google_product_category>` (jeśli podano)
  - Opcjonalny blok `<g:shipping>`

Opisy HTML są czyszczone do tekstu, by uniknąć błędów walidacji GMC.

## Dostosowanie

- Parametry dla trybu web ustawione są w `app.py` w wywołaniu `subprocess.run([...])` (nazwa sklepu, URL, szablony linków, waluta). Zmień je pod swój sklep.
- Dostosuj ścieżkę do Pythona, jeśli polecenie `python` wskazuje na inną wersję/interpreter.

## Katalogi robocze i retencja

- `uploads/` – tymczasowy zapis plików CSV (usuwany po konwersji).
- `outputs/` – wygenerowane XML. Pliki starsze niż 24 godziny są automatycznie usuwane.

## Hostowanie na serwerze (reverse proxy)

Możesz hostować aplikację na serwerze (np. na tym samym, na którym działa PrestaShop) i przekierować ścieżkę `/convert` w reverse proxy do działającej aplikacji Pythona.

- Uruchom backend (przykładowo przez gunicorn):
  ```bash
  gunicorn -w 1 -b 127.0.0.1:8000 app:app
  ```
  Upewnij się, że `gunicorn` jest zainstalowany (`pip install gunicorn`).
- Skonfiguruj reverse proxy (np. Nginx), aby kierował zapytania na ścieżkę `/convert` do backendu:
  ```nginx
  location ^~ /convert {
      client_max_body_size 20m;
      proxy_http_version 1.1;
      proxy_set_header Host $host;
      proxy_set_header X-Real-IP $remote_addr;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header X-Forwarded-Proto $scheme;
      proxy_redirect off;
      proxy_pass http://127.0.0.1:8000;
  }
  ```

## Rozwiązywanie problemów

- „Błąd konwersji” w UI: sprawdź konsolę serwera — `app.py` loguje `STDOUT/STDERR` z `convert.py`.
- Nieprawidłowe znaki/Polskie znaki: upewnij się, że CSV jest w UTF‑8.
- Złe ceny/format liczb: CSV powinien mieć separator dziesiętny `.` (kropka). W razie potrzeby dostosuj eksport.
- Brak GTIN → Google może odrzucać oferty. Zapewnij `ean13/upc/isbn` albo `mpn` + `brand`.
- Dostępność: jeśli polityka braku stanów (allow orders) różni się od przyjętej, zmodyfikuj logikę w `infer_availability()` lub ustaw `--availability-default`.
