# MFDS crawler
# MFDS 신제품 수집기
# - CCBAE01(품목허가현황)에서 '취소/취하일자 공란' 항목만 신규로 간주
# - 상세 페이지에서 필요한 정보 파싱
# - Supabase(Postgres)에 itemSeq 기준 누적 저장(upsert)

import os
import re
import time
import random
import hashlib
from datetime import datetime

import requests
from bs4 import BeautifulSoup
import psycopg


BASE_URL = "https://nedrug.mfds.go.kr"
LIST_URL = "https://nedrug.mfds.go.kr/pbp/CCBAE01"
DETAIL_URL = "https://nedrug.mfds.go.kr/pbp/CCBBB01/getItemDetail"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (MFDS-NewDrug-Tracker/1.0; +internal)"
}


# -------------------------
# 유틸
# -------------------------
def sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def get_db_conn():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL 환경변수가 설정되지 않았습니다.")
    return psycopg.connect(db_url)


def http_get(url, params=None):
    r = requests.get(url, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


# -------------------------
# 목록 페이지 파싱
# -------------------------
def parse_list_page(html: str):
    """
    품목허가현황(CCBAE01) 테이블에서
    '취소/취하일자'가 비어있는 항목만 반환
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if not table:
        return []

    rows = table.find_all("tr")
    results = []

    for tr in rows[1:]:
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue

        # 제품명 + itemSeq
        a = tds[0].find("a")
        if not a:
            continue

        product_name = a.get_text(strip=True)

        href = a.get("href", "")
        m = re.search(r"itemSeq=(\d+)", href)
        if not m:
            onclick = a.get("onclick", "")
            m = re.search(r"itemSeq=(\d+)", onclick)
        if not m:
            continue

        item_seq = m.group(1)

        company_name = tds[1].get_text(" ", strip=True)
        rx_otc = tds[2].get_text(" ", strip=True)
        approval_date = tds[3].get_text(" ", strip=True)

        cancel_withdraw = tds[4].get_text(" ", strip=True)

        # 핵심 조건: 취소/취하일자 공란
        if cancel_withdraw:
            continue

        results.append({
            "item_seq": item_seq,
            "product_name": product_name,
            "company_name": company_name,
            "rx_otc": rx_otc,
            "approval_date": approval_date
        })

    return results


# -------------------------
# 상세 페이지 파싱
# -------------------------
def extract_labeled_value(soup: BeautifulSoup, label: str) -> str:
    """
    '업체명', '위탁제조업체' 등 라벨 기반으로 값 추출
    """
    label_node = soup.find(string=re.compile(rf"^{re.escape(label)}$"))
    if not label_node:
        return ""

    th = label_node.find_parent(["th", "dt"])
    if not th:
        return ""

    td = th.find_next_sibling(["td", "dd"])
    if not td:
        td = th.find_next(["td", "dd"])

    return td.get_text(" ", strip=True) if td else ""


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
