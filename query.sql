SELECT
  p.id_product,
  p.reference,
  p.id_shop_default,
  ps.price AS price_tax_excluded,
  ps.ecotax AS ecotax_tax_excluded,
  ps.id_tax_rules_group,
  ps.active,
  pl.name,
  pl.link_rewrite,
  pl.description,
  pl.description_short,
  cl.link_rewrite AS category_slug,
  ps.id_category_default,
  m.name AS brand,
  p.ean13,
  p.upc,
  p.isbn,
  p.mpn,
  p.condition,
  p.available_date,
  COALESCE(sa.quantity, 0) AS quantity,
  COALESCE(sa.out_of_stock, p.out_of_stock) AS out_of_stock_mode,
  COALESCE(p.cache_default_attribute, pas.id_product_attribute, 0) AS id_product_attribute,
  img_cover.id_image AS id_image,
  img_lang.legend AS image_legend,
  GROUP_CONCAT(
    DISTINCT CASE
      WHEN (img_all_shop.cover = 0 OR img_all_shop.cover IS NULL)
      THEN img_all.id_image
    END
    ORDER BY img_all.position
    SEPARATOR ','
  ) AS additional_image_ids,
  p.weight,
  p.width,
  p.height,
  p.depth,
  (ps.price + ps.ecotax) AS final_price_tax_excluded,
  su.domain_ssl,
  su.physical_uri,
  su.virtual_uri

FROM ps_product p
JOIN ps_product_shop ps
  ON ps.id_product = p.id_product AND ps.id_shop = 1
LEFT JOIN ps_product_lang pl
  ON pl.id_product = p.id_product AND pl.id_lang = 1 AND pl.id_shop = 1
LEFT JOIN ps_manufacturer m
  ON m.id_manufacturer = p.id_manufacturer
LEFT JOIN ps_category_lang cl
  ON cl.id_category = ps.id_category_default AND cl.id_lang = 1 AND cl.id_shop = 1
LEFT JOIN ps_image_shop img_cover
  ON img_cover.id_product = ps.id_product AND img_cover.cover = 1 AND img_cover.id_shop = 1
LEFT JOIN ps_image_lang img_lang
  ON img_cover.id_image = img_lang.id_image AND img_lang.id_lang = 1
LEFT JOIN ps_image img_all
  ON img_all.id_product = ps.id_product
LEFT JOIN ps_image_shop img_all_shop
  ON img_all_shop.id_image = img_all.id_image AND img_all_shop.id_shop = 1
LEFT JOIN ps_product_attribute_shop pas
  ON pas.id_product = p.id_product AND pas.default_on = 1 AND pas.id_shop = 1
LEFT JOIN ps_stock_available sa
  ON sa.id_product = p.id_product
     AND sa.id_product_attribute = 0
     AND sa.id_shop = 1
LEFT JOIN ps_shop_url su
  ON su.id_shop = ps.id_shop AND su.main = 1

WHERE p.state = 1
GROUP BY
  p.id_product, p.reference, p.id_shop_default,
  ps.price, ps.ecotax, ps.id_tax_rules_group, ps.active,
  pl.name, pl.link_rewrite, pl.description, pl.description_short,
  cl.link_rewrite, ps.id_category_default,
  m.name,
  p.ean13, p.upc, p.isbn, p.mpn,
  p.condition, p.available_date,
  sa.quantity, sa.out_of_stock, p.out_of_stock,
  p.cache_default_attribute, pas.id_product_attribute,
  img_cover.id_image, img_lang.legend,
  p.weight, p.width, p.height, p.depth,
  su.domain_ssl, su.physical_uri, su.virtual_uri
ORDER BY p.id_product ASC;
