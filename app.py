import os
import hmac
import streamlit as st
import psycopg
import pandas as pd

# -----------------------------
# 🔐 접근 비밀번호
# -----------------------------
def require_password():
    pwd = None
    if "APP_PASSWORD" in st.secrets:
        pwd = st.secrets["APP_PASSWORD"]
    else:
        pwd = os.environ.get("APP_PASSWORD")

    if not pwd:
        return  # 비번 미설정 시 통과

    if st.session_state.get("authed"):
        return

    st.title("MFDS 신제품 트래커")
    entered = st.text_input("접근 비밀번호", type="password")

    if entered and hmac.compare_digest(entered, pwd):
        st.session_state["authed"] = True
        st.rerun()
    else:
        st.stop()

require_password()

# -----------------------------
# 🗄 DB URL 가져오기
# -----------------------------
def get_db_url():
    if "DATABASE_URL" in st.secrets:
        return st.secrets["DATABASE_URL"]

    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        return db_url

    st.error("DATABASE_URL이 설정되지 않았습니다 (Streamlit Secrets 확인)")
    st.stop()

DB_URL = get_db_url()

# -----------------------------
# 📊 DB 연결
# -----------------------------
@st.cache_data(ttl=300)
def load_products():
    with psycopg.connect(DB_URL) as conn:
        query = """
        select
            p.item_seq,
            p.product_name,
            p.company_name,
            p.rx_otc,
            p.review_type,
            p.approval_date,
            p.first_seen_at,
            p.last_seen_at
        from products p
        order by p.first_seen_at desc
        limit 500
        """
        return pd.read_sql(query, conn)

# -----------------------------
# 🖥 UI
# -----------------------------
st.header("📦 MFDS 신제품 현황")

df = load_products()

st.caption(f"총 {len(df)}건")

st.dataframe(
    df,
    use_container_width=True,
    hide_index=True
)

import subprocess
from datetime import datetime
import time

st.divider()
st.subheader("🧪 (임시) 수동 수집 테스트")

# [YOU EDIT] 안전장치: 비밀번호 다시 한 번 확인 (운영 중에는 삭제 권장)
confirm = st.text_input("수동 수집 실행 확인용 비밀번호(다시 입력)", type="password")
expected = (st.secrets.get("APP_PASSWORD") if "APP_PASSWORD" in st.secrets else os.environ.get("APP_PASSWORD", ""))

if st.button("지금 MFDS 데이터 수집 실행"):
    if expected and confirm != expected:
        st.error("비밀번호가 일치하지 않습니다.")
        st.stop()

    with st.spinner("MFDS 사이트에서 데이터 수집 중... (1~2분 걸릴 수 있어요)"):
        try:
            started = datetime.now()
            result = subprocess.run(
                ["python", "src/fetch_mfds.py"],
                capture_output=True,
                text=True,
                check=True,
            )
            ended = datetime.now()

            st.success(f"수집 완료! ({(ended-started).seconds}초)")
            if result.stdout.strip():
                st.code(result.stdout, language="text")
            if result.stderr.strip():
                st.warning("stderr 출력이 있어요(참고용).")
                st.code(result.stderr, language="text")

            st.info("아래 버튼을 눌러 화면 데이터를 새로고침하세요.")

        except subprocess.CalledProcessError as e:
            st.error("수집 중 오류 발생 ❌")
            if e.stdout:
                st.code(e.stdout, language="text")
            if e.stderr:
                st.code(e.stderr, language="text")

if st.button("🔄 화면 데이터 새로고침"):
    st.cache_data.clear()
    st.experimental_rerun()
