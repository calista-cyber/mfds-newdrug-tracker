import os
import re
import time
import random
import hashlib
from datetime import datetime

import requests
from bs4 import BeautifulSoup
import psycopg


LIST_URL = "https://nedrug.mfds.go.kr/pbp/CCBAE01"
DETAIL_URL = "https://nedrug.mfds.go.kr/pbp/CCBBB01/getItemDetail"
UA = "Mozilla/5.0 (MFDS-NewDrug-Tracker/2.0)"


def sha256(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def get_db_conn():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL is missing in env.")
    return psycopg.connect(db_url)


def http_get(url: str, params=None) -> str:
    r = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    return r.text


def _normalize_header(text: str) -> str:
    return re.sub(r"\s+", "", (text or ""))


def parse_list_candidates(html: str):
    """
    목록 테이블에서 '취소/취하일자'가 공란인 품목의 itemSeq를 추출.
    - 컬럼 위치가 바뀌어도 헤더명 기반으로 인덱스를 찾도록 구현.
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if not table:
        return []

    # 헤더 찾기
    header_tr = table.find("tr")
    if not header_tr:
        return []

    ths = header_tr.find_all(["th", "td"])
    headers = [_normalize_header(th.get_text(" ", strip=True)) for th in ths]

    # 필수 컬럼(이름은 환경에 따라 조금 다를 수 있어서 유사 매칭)
    def find_col(*candidates):
        for cand in candidates:
            cand_n = _normalize_header(cand)
            for i, h in enumerate(headers):
                if cand_n in h:
                    return i
        return None

    # 일반적으로: 제품명/업체명/전문일반/허가일자/취소취하일자 등이 있음
    col_product = find_col("제품명", "품목명")
    col_cancel = find_col("취소/취하일자", "취소취하일자", "취소일자", "취하일자")
    # 없으면 기존 방식 fallback(5번째 칼럼 가정) — 그래도 최대한 안전하게
    if col_product is None:
        col_product = 0
    if col_cancel is None:
        col_cancel = 4  # fallback

    out = []
    for tr in table.find_all("tr")[1:]:
        tds = tr.find_all("td")
        if len(tds) <= max(col_product, col_cancel):
            continue

        a = tds[col_product].find("a")
        if not a:
            continue

        href = a.get("href", "") or ""
        onclick = a.get("onclick", "") or ""
        m = re.search(r"itemSeq=(\d+)", href) or re.search(r"itemSeq=(\d+)", onclick)
        if not m:
            continue
        item_seq = m.group(1)

        cancel_text = tds[col_cancel].get_text(" ", strip=True)
        if cancel_text:
            continue  # 취소/취하일자 있으면 신규가 아님

        out.append(item_seq)

    # 중복 제거
    return list(dict.fromkeys(out))


def extract_by_label(soup: BeautifulSoup, label: str) -> str:
    """
    상세 페이지에서 라벨 텍스트(예: 업체명) 기준으로 값 추출
    """
    node = soup.find(string=re.compile(rf"^{re.escape(label)}$"))
    if not node:
        return ""
    th = node.find_parent(["th", "dt"])
    if not th:
        return ""
    td = th.find_next_sibling(["td", "dd"]) or th.find_next(["td", "dd"])
    return td.get_text(" ", strip=True) if td else ""


def extract_efficacy(soup: BeautifulSoup) -> str:
    """
    효능효과 텍스트를 넓게 긁어옴(구조 변동 대비)
    """
    node = soup.find(string=re.compile(r"효능\s*효과"))
    if not node:
        return ""
    parent = node.find_parent()
    if not parent:
        return ""
    block = parent.find_next(["div", "table", "td", "dd", "p"])
    return block.get_text("\n", strip=True) if block else ""


def extract_ingredients(soup: BeautifulSoup):
    """
    원료약품 및 분량 테이블에서 성분명만 추출 (MVP)
    """
    ingredients = []
    node = soup.find(string=re.compile(r"원료약품\s*및\s*분량"))
    if not node:
        return ingredients

    table = node.find_parent()
    if table:
        table = table.find_next("table")
    if not table:
        return ingredients

    for tr in table.find_all("tr")[1:]:
        tds = tr.find_all("td")
        if not tds:
            continue
        name = tds[0].get_text(" ", strip=True)
        if name:
            ingredients.append(name)

    return sorted(set(ingredients))


def fetch_detail(item_seq: str):
    html = http_get(DETAIL_URL, params={"itemSeq": item_seq})
    soup = BeautifulSoup(html, "lxml")

    product_name = extract_by_label(soup, "제품명")
    company_name = extract_by_label(soup, "업체명")
    cmo_names = extract_by_label(soup, "위탁제조업체")
    rx_otc = extract_by_label(soup, "전문/일반")
    review_type = extract_by_label(soup, "허가심사유형")
    approval_date = extract_by_label(soup, "허가일자")

    efficacy_text = extract_efficacy(soup)
    ingredients = extract_ingredients(soup)
    source_url = f"{DETAIL_URL}?itemSeq={item_seq}"

    signature = "||".join([
        item_seq, product_name, company_name, cmo_names, rx_otc,
        review_type, approval_date, efficacy_text, ",".join(ingredients)
    ])
    content_hash = sha256(signature)

    # dict는 최소 필드만, 구조 단순
    return (
        item_seq, product_name, company_name, cmo_names, rx_otc,
        review_type, approval_date, efficacy_text, source_url, content_hash, ingredients
    )


def upsert(conn, row):
    (
        item_seq, product_name, company_name, cmo_names, rx_otc,
        review_type, approval_date, efficacy_text, source_url, content_hash, ingredients
    ) = row

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO products (
              item_seq, product_name, company_name, cmo_names, rx_otc,
              review_type, approval_date, efficacy_text, source_url, content_hash,
              first_seen_at, last_seen_at, last_updated_at
            ) VALUES (
              %s, %s, %s, %s, %s,
              %s, NULLIF(%s,'')::date, %s, %s, %s,
              NOW(), NOW(), NOW()
            )
            ON CONFLICT (item_seq) DO UPDATE SET
              product_name = EXCLUDED.product_name,
              company_name = EXCLUDED.company_name,
              cmo_names = EXCLUDED.cmo_names,
              rx_otc = EXCLUDED.rx_otc,
              review_type = EXCLUDED.review_type,
              approval_date = EXCLUDED.approval_date,
              efficacy_text = EXCLUDED.efficacy_text,
              source_url = EXCLUDED.source_url,
              last_seen_at = NOW(),
              last_updated_at = CASE
                WHEN products.content_hash IS DISTINCT FROM EXCLUDED.content_hash THEN NOW()
                ELSE products.last_updated_at
              END,
              content_hash = EXCLUDED.content_hash
            """,
            (
                item_seq, product_name, company_name, cmo_names, rx_otc,
                review_type, approval_date, efficacy_text, source_url, content_hash
            )
        )

        cur.execute("DELETE FROM ingredients WHERE item_seq = %s", (item_seq,))
        for ing in ingredients:
            cur.execute(
                "INSERT INTO ingredients (item_seq, ingredient_name) VALUES (%s, %s)",
                (item_seq, ing)
            )


def main():
    print("[mfds] start", datetime.now().isoformat())

    html = http_get(LIST_URL)
    item_seqs = parse_list_candidates(html)
    print("[mfds] candidates(no cancel/withdraw):", len(item_seqs))

    if not item_seqs:
        print("[mfds] nothing to do")
        return

    conn = get_db_conn()
    try:
        for i, item_seq in enumerate(item_seqs, 1):
            time.sleep(random.uniform(0.6, 1.4))
            row = fetch_detail(item_seq)
            upsert(conn, row)
            conn.commit()
            print(f"[mfds] upsert {i}/{len(item_seqs)} itemSeq={item_seq}")
    finally:
        conn.close()

    print("[mfds] done", datetime.now().isoformat())


if __name__ == "__main__":
    main()
