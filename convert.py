import argparse
import csv
from decimal import Decimal, ROUND_HALF_UP
import sys
import xml.etree.ElementTree as ET
from xml.dom import minidom
from html import unescape
from html.parser import HTMLParser

G_NS = "http://base.google.com/ns/1.0"
ET.register_namespace('g', G_NS)

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

    # Create RSS root with g namespace
    rss = ET.Element("rss", attrib={"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = args.shop_name
    ET.SubElement(channel, "link").text = args.site_link
    ET.SubElement(channel, "description").text = strip_html(args.channel_description)

    # Read CSV
    with open(args.csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=';', quoting=csv.QUOTE_MINIMAL)
        for row in reader:
            if "id_product" not in row:
                continue

            item = ET.SubElement(channel, "item")

            # Basic identifiers
            pid = row.get("id_product") or row.get("reference") or ""
            add_g(item, "id", pid)

            # Titles and descriptions
            title = row.get("name") or row.get("title") or pid
            if row.get("description_short"):
                title = title + " " + strip_html(row.get("description_short"))
            ET.SubElement(item, "title").text = title
            raw_desc = row.get("description") or title
            desc = strip_html(raw_desc) or title
            ET.SubElement(item, "description").text = desc

            # Build product link
            link_rewrite = (row.get("link_rewrite") or "").strip().strip("/")
            category_slug = (row.get("category_slug") or row.get("category") or "").strip().strip("/")
            id_product_attribute = (row.get("id_product_attribute") or "0").strip()
            link = args.product_url_template.format(
                id_product=pid,
                id_product_attribute=id_product_attribute,
                link_rewrite=link_rewrite,
                category_slug=category_slug
            )
            ET.SubElement(item, "link").text = link

            # Main image
            id_image = (row.get("id_image") or "").strip()
            if id_image:
                image_link = args.image_url_template.format(
                    id_image=id_image,
                    link_rewrite=link_rewrite
                )
                add_g(item, "image_link", image_link)

            # Additional images
            add_ids = split_ids(row.get(args.additional_images_column))
            count_added = 0
            for iid in add_ids:
                if count_added >= max(0, args.max_additional_images):
                    break
                if not iid or iid == id_image:
                    continue
                add_link = args.image_url_template.format(
                    id_image=iid,
                    link_rewrite=link_rewrite
                )
                add_g(item, "additional_image_link", add_link)
                count_added += 1

            # Availability (from stock and policy)
            qty_val = row.get("quantity")
            out_of_stock_mode = row.get("out_of_stock_mode") or row.get("out_of_stock")
            availability = infer_availability(qty_val, out_of_stock_mode, args.availability_default)
            add_g(item, "availability", availability)

            # Availability date (for preorder/backorder)
            if row.get("available_date") and availability in ("preorder", "backorder") and row.get("available_date") != "0000-00-00":
                add_g(item, "availability_date", row.get("available_date"))

            # Condition
            cond = (row.get("condition") or args.condition_default).strip()
            add_g(item, "condition", cond)

            # Price (with optional VAT)
            base_price_str = row.get(args.price_column) or row.get("price") or "0"
            price_value = apply_vat(base_price_str, args.vat_rate) if args.add_vat else base_price_str
            add_g(item, "price", fmt_price(price_value, args.currency))

            # Brand and identifiers
            brand = row.get("brand") or row.get("manufacturer_name") or args.brand_default
            if brand:
                add_g(item, "brand", brand)

            # Prefer GTIN from ean13/upc/isbn when present
            gtin = row.get("gtin") or row.get("ean13") or row.get("upc") or row.get("isbn")
            if gtin:
                add_g(item, "gtin", gtin)

            # MPN only if GTIN missing per best practices
            mpn = row.get("mpn") or row.get("reference")
            if mpn and not gtin:
                add_g(item, "mpn", mpn)

            # Product type and Google category
            pt_col = args.product_type_from
            if pt_col in row and row[pt_col]:
                add_g(item, "product_type", row[pt_col])
            if args.google_product_category:
                add_g(item, "google_product_category", args.google_product_category)

            # Dimensions and weight (optional)
            # You can map to shipping info or custom labels as needed
            # Not standard GMC attributes unless used in shipping calculations

            # Optional shipping block
            if args.shipping_country and args.shipping_service and args.shipping_price:
                shipping = ET.SubElement(item, f"{{{G_NS}}}shipping")
                add_g(shipping, "country", args.shipping_country)
                add_g(shipping, "service", args.shipping_service)
                add_g(shipping, "price", args.shipping_price)

    # Pretty print
    xml_bytes = ET.tostring(rss, encoding="utf-8")
    pretty = minidom.parseString(xml_bytes).toprettyxml(indent="  ", encoding="utf-8")
    with open(args.out_xml, "wb") as out:
        out.write(pretty)

if __name__ == "__main__":
    if sys.version_info < (3, 8):
        print("Python 3.8+ required", file=sys.stderr)
        sys.exit(1)
    main()
