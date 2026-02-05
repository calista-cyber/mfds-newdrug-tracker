def parse_detail_page(item_seq: str):
    html = http_get(DETAIL_URL, params={"itemSeq": item_seq})
    soup = BeautifulSoup(html, "lxml")

    product_name = extract_labeled_value(soup, "제품명")
    company_name = extract_labeled_value(soup, "업체명")
    cmo_names = extract_labeled_value(soup, "위탁제조업체")
    rx_otc = extract_labeled_value(soup, "전문/일반")
    review_type = extract_labeled_value(soup, "허가심사유형")
    approval_date = extract_labeled_value(soup, "허가일자")

    # 효능효과
    efficacy_text = ""
    eff_header = soup.find(string=re.compile(r"효능\s*효과"))
    if eff_header:
        container = eff_header.find_parent()
        if container:
            block = container.find_next(["div", "table", "td", "dd"])
            if block:
                efficacy_text = block.get_text("\n", strip=True)

    # 원료약품 및 분량 → 성분명만
    ingredients = []
    ing_header = soup.find(string=re.compile(r"원료약품\s*및\s*분량"))
    if ing_header:
        table = ing_header.find_parent().find_next("table")
        if table:
            for tr in table.find_all("tr")[1:]:
                tds = tr.find_all("td")
                if not tds:
                    continue
                name = tds[0].get_text(" ", strip=True)
                if name:
                    ingredients.append(name)

    ingredients = sorted(set(ingredients))

    source_url = f"{DETAIL_URL}?itemSeq={item_seq}"

    signature = "|".join([
        item_seq,
        product_name,
        company_name,
        cmo_names,
        rx_otc,
        review_type,
        approval_date,
        efficacy_text,
        ",".join(ingredients)
    ])

    content_hash = sha256(signature)

    return {
        "item_seq": item_seq,
        "product_name": product_name,
        "company_name": company_name,
        "cmo_names": cmo_names,
        "rx_otc": rx_otc,
        "review_type": review_type,
        "approval_date": approval_date,
        "efficacy_text": efficacy_text,
        "ingredients": ingredients,
        "source_url": source_url,
        "content_hash": content_hash
    }
