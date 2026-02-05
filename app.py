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
