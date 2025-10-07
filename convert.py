import argparse
import csv
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Mapping, Optional, Any
import sys
import xml.etree.ElementTree as ET
from xml.dom import minidom
from html import unescape
from html.parser import HTMLParser

G_NS = "http://base.google.com/ns/1.0"
ET.register_namespace('g', G_NS)


@dataclass
class FeedConfig:
    shop_name: str
    site_link: str
    channel_description: str = "Product feed"
    product_url_template: str = ""
    image_url_template: str = ""
    currency: str = ""
    price_column: str = "final_price_tax_excluded"
    add_vat: bool = False
    vat_rate: float = 23.0
    availability_default: str = "out_of_stock"
    condition_default: str = "new"
    brand_default: Optional[str] = None
    google_product_category: Optional[str] = None
    product_type_from: str = "category_slug"
    shipping_country: Optional[str] = None
    shipping_service: Optional[str] = None
    shipping_price: Optional[str] = None
    additional_images_column: str = "additional_image_ids"
    max_additional_images: int = 10

def fmt_price(value: str, currency: str) -> str:
    try:
        quant = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        quant = Decimal("0.00")
    return f"{quant} {currency}"

def apply_vat(base_value: str, vat_rate: float) -> str:
    try:
        amount = Decimal(base_value)
        gross = amount * (Decimal(1) + Decimal(vat_rate) / Decimal(100))
    except Exception:
        gross = Decimal("0.00")
    return str(gross)

def build_text(el, text):
    if text is None:
        text = ""
    el.text = str(text)
    return el

def add_g(parent, tag, text):
    el = ET.SubElement(parent, f"{{{G_NS}}}{tag}")
    build_text(el, text)
    return el

def infer_availability(qty_val, out_of_stock_mode, default_value):
    # qty_val: numeric string; out_of_stock_mode: 0/1/2 (PS policy); default fallback
    try:
        qty = int(float(qty_val))
    except Exception:
        qty = 0
    # PrestaShop: when qty>0 => in_stock; when qty<=0 and allow orders => backorder; else out_of_stock
    if qty > 0:
        return "in_stock"
    # out_of_stock_mode: 1/2 often indicates allow orders depending on shop config; treat non-zero as allow
    if out_of_stock_mode and str(out_of_stock_mode) not in ("0", ""):
        return "backorder"
    return default_value or "out_of_stock"

def split_ids(csv_val):
    if not csv_val:
        return []
    return [x.strip() for x in str(csv_val).split(",") if x.strip()]


class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._chunks = []

    def handle_data(self, data):
        if data:
            self._chunks.append(data)

    def get_data(self):
        return "".join(self._chunks)


def strip_html(value):
    if not value:
        return ""
    stripper = _HTMLStripper()
    stripper.feed(str(value))
    stripper.close()
    return unescape(stripper.get_data())

def _normalize_row(row: Mapping[str, Any]) -> Mapping[str, Any]:
    normalized = {}
    for key, value in row.items():
        if value is None:
            normalized[key] = ""
        elif isinstance(value, (bytes, bytearray)):
            normalized[key] = value.decode("utf-8", errors="ignore")
        elif isinstance(value, (Decimal, int, float)):
            normalized[key] = str(value)
        elif isinstance(value, (date, datetime)):
            normalized[key] = value.isoformat()
        else:
            normalized[key] = value
    return normalized


def generate_feed(rows: Iterable[Mapping[str, Any]], config: FeedConfig) -> bytes:
    rss = ET.Element("rss", attrib={"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = config.shop_name
    ET.SubElement(channel, "link").text = config.site_link
    ET.SubElement(channel, "description").text = strip_html(config.channel_description)

    shipping_enabled = all([
        config.shipping_country,
        config.shipping_service,
        config.shipping_price
    ])

    for raw_row in rows:
        if raw_row is None:
            continue
        row = _normalize_row(raw_row)
        if "id_product" not in row:
            continue

        item = ET.SubElement(channel, "item")

        pid = row.get("id_product") or row.get("reference") or ""
        add_g(item, "id", pid)

        title = row.get("name") or row.get("title") or pid
        if row.get("description_short"):
            title = f"{title} {strip_html(row.get('description_short'))}".strip()
        ET.SubElement(item, "title").text = title
        raw_desc = row.get("description") or title
        desc = strip_html(raw_desc) or title
        ET.SubElement(item, "description").text = desc

        link_rewrite = (row.get("link_rewrite") or "").strip().strip("/")
        category_slug = (row.get("category_slug") or row.get("category") or "").strip().strip("/")
        id_product_attribute = (row.get("id_product_attribute") or "0").strip()
        link = config.product_url_template.format(
            id_product=pid,
            id_product_attribute=id_product_attribute,
            link_rewrite=link_rewrite,
            category_slug=category_slug
        )
        ET.SubElement(item, "link").text = link

        id_image = (row.get("id_image") or "").strip()
        if id_image:
            image_link = config.image_url_template.format(
                id_image=id_image,
                link_rewrite=link_rewrite
            )
            add_g(item, "image_link", image_link)

        add_ids = split_ids(row.get(config.additional_images_column))
        count_added = 0
        for iid in add_ids:
            if count_added >= max(0, config.max_additional_images):
                break
            if not iid or iid == id_image:
                continue
            add_link = config.image_url_template.format(
                id_image=iid,
                link_rewrite=link_rewrite
            )
            add_g(item, "additional_image_link", add_link)
            count_added += 1

        qty_val = row.get("quantity")
        out_of_stock_mode = row.get("out_of_stock_mode") or row.get("out_of_stock")
        availability = infer_availability(qty_val, out_of_stock_mode, config.availability_default)
        add_g(item, "availability", availability)

        if row.get("available_date") and availability in ("preorder", "backorder") and row.get("available_date") != "0000-00-00":
            add_g(item, "availability_date", row.get("available_date"))

        cond = (row.get("condition") or config.condition_default).strip()
        add_g(item, "condition", cond)

        base_price_str = row.get(config.price_column) or row.get("price") or "0"
        price_value = apply_vat(str(base_price_str), config.vat_rate) if config.add_vat else str(base_price_str)
        add_g(item, "price", fmt_price(price_value, config.currency))

        brand = row.get("brand") or row.get("manufacturer_name") or config.brand_default
        if brand:
            add_g(item, "brand", brand)

        gtin = row.get("gtin") or row.get("ean13") or row.get("upc") or row.get("isbn")
        if gtin:
            add_g(item, "gtin", gtin)

        mpn = row.get("mpn") or row.get("reference")
        if mpn and not gtin:
            add_g(item, "mpn", mpn)

        pt_col = config.product_type_from
        if pt_col in row and row[pt_col]:
            add_g(item, "product_type", row[pt_col])
        if config.google_product_category:
            add_g(item, "google_product_category", config.google_product_category)

        if shipping_enabled:
            shipping = ET.SubElement(item, f"{{{G_NS}}}shipping")
            add_g(shipping, "country", config.shipping_country)
            add_g(shipping, "service", config.shipping_service)
            add_g(shipping, "price", config.shipping_price)

    xml_bytes = ET.tostring(rss, encoding="utf-8")
    pretty = minidom.parseString(xml_bytes).toprettyxml(indent="  ", encoding="utf-8")
    return pretty


def main():
    ap = argparse.ArgumentParser(description="Convert PrestaShop CSV export to Google Merchant XML (RSS 2.0)")
    ap.add_argument("--csv-path", required=True, help="Path to input CSV exported from PrestaShop (delimiter ';')")
    ap.add_argument("--out-xml", required=True, help="Path to output XML file")
    ap.add_argument("--shop-name", required=True, help="Shop name for <channel><title>")
    ap.add_argument("--site-link", required=True, help="Shop homepage for <channel><link>")
    ap.add_argument("--channel-description", default="Product feed", help="<channel><description> text")

    # URL templates
    ap.add_argument("--product-url-template", required=True,
                    help="Template for product URL, placeholders: {id_product}, {id_product_attribute}, {link_rewrite}, {category_slug}")
    ap.add_argument("--image-url-template", required=True,
                    help="Template for image URL, placeholders: {id_image}, {link_rewrite}")

    # Pricing
    ap.add_argument("--currency", required=True, help="ISO 4217 currency, e.g. PLN")
    ap.add_argument("--price-column", default="final_price_tax_excluded",
                    help="CSV column for base price (e.g. final_price_tax_excluded or price_tax_excluded)")
    ap.add_argument("--add-vat", action="store_true", help="If set, add VAT percentage to base price")
    ap.add_argument("--vat-rate", type=float, default=23.0, help="VAT percentage to add when --add-vat is set")

    # Availability and condition
    ap.add_argument("--availability-default", default="out_of_stock",
                    choices=["in_stock", "out_of_stock", "preorder", "backorder"],
                    help="Default availability if not inferred")
    ap.add_argument("--condition-default", default="new", choices=["new", "used", "refurbished"],
                    help="Condition for items lacking explicit condition")

    # Identifiers and taxonomy
    ap.add_argument("--brand-default", default=None, help="Default brand when CSV lacks brand/manufacturer")
    ap.add_argument("--google-product-category", default=None, help="Optional Google product category ID or full path")
    ap.add_argument("--product-type-from", default="category_slug",
                    help="CSV column to map into <g:product_type>")

    # Optional Shipping
    ap.add_argument("--shipping-country", default=None, help="Country code for <g:shipping>/<g:country>")
    ap.add_argument("--shipping-service", default=None, help="Service name for <g:shipping>/<g:service>")
    ap.add_argument("--shipping-price", default=None, help="Price (e.g. 15.00 PLN) for <g:shipping>/<g:price>")

    # Additional images control
    ap.add_argument("--additional-images-column", default="additional_image_ids",
                    help="CSV column with comma-separated image IDs for additional images")
    ap.add_argument("--max-additional-images", type=int, default=10,
                    help="Max number of additional images to include (Google limit is 10)")

    args = ap.parse_args()

    config = FeedConfig(
        shop_name=args.shop_name,
        site_link=args.site_link,
        channel_description=args.channel_description,
        product_url_template=args.product_url_template,
        image_url_template=args.image_url_template,
        currency=args.currency,
        price_column=args.price_column,
        add_vat=args.add_vat,
        vat_rate=args.vat_rate,
        availability_default=args.availability_default,
        condition_default=args.condition_default,
        brand_default=args.brand_default,
        google_product_category=args.google_product_category,
        product_type_from=args.product_type_from,
        shipping_country=args.shipping_country,
        shipping_service=args.shipping_service,
        shipping_price=args.shipping_price,
        additional_images_column=args.additional_images_column,
        max_additional_images=args.max_additional_images,
    )

    with open(args.csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=';', quoting=csv.QUOTE_MINIMAL)
        xml_bytes = generate_feed(reader, config)

    with open(args.out_xml, "wb") as out:
        out.write(xml_bytes)

if __name__ == "__main__":
    if sys.version_info < (3, 8):
        print("Python 3.8+ required", file=sys.stderr)
        sys.exit(1)
    main()
