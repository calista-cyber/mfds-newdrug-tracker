import os
import pandas as pd
import streamlit as st
import psycopg


st.set_page_config(page_title="MFDS 신제품 트래커", layout="wide")


def get_db_url() -> str:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        st.error("환경변수 DATABASE_URL이 설정되지 않았습니다. (GitHub Secrets / Streamlit 환경변수 확인)")
        st.stop()
    return db_url


@st.cache_resource
def get_conn():
    return psycopg.connect(get_db_url())


def query_df(sql: str, params=None) -> pd.DataFrame:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        cols = [d.name for d in cur.description]
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols)


def ensure_tables_exist():
    """
    Supabase SQL Editor에서 이미 테이블을 만들었으면 아무 일도 안 함.
    혹시 테이블 생성이 안 된 상태여도 앱이 바로 구동되도록 안전장치로 넣어둠.
    """
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
        create table if not exists products (
          item_seq text primary key,
          product_name text,
          company_name text,
          cmo_names text,
          rx_otc text,
          review_type text,
          approval_date date,
          efficacy_text text,
          source_url text,
          content_hash text,
          first_seen_at timestamptz default now(),
          last_seen_at timestamptz default now(),
          last_updated_at timestamptz default now()
        );
        """)
        cur.execute("""
        create table if not exists ingredients (
          id bigserial primary key,
          item_seq text references products(item_seq) on delete cascade,
          ingredient_name text
        );
        """)
        conn.commit()


# ---------- UI ----------
st.title("MFDS N-Drug 신제품 누적 관리")
st.caption("기준: 품목허가현황(CCBAE01)에서 **취소/취하일자 공란** 항목을 신제품으로 간주하여 누적합니다.")

ensure_tables_exist()

with st.sidebar:
    st.header("필터")
    keyword = st.text_input("키워드 (제품명/업체명/효능효과/성분명)", value="")
    rx = st.selectbox("전문/일반", ["전체", "전문", "일반"], index=0)
    period = st.selectbox("기간", ["최근 30일", "최근 90일", "전체"], index=0)
    limit = st.selectbox("표시 건수", [200, 500, 1000, 2000], index=2)

where = []
params = []

if period == "최근 30일":
    where.append("p.first_seen_at >= now() - interval '30 days'")
elif period == "최근 90일":
    where.append("p.first_seen_at >= now() - interval '90 days'")

if rx != "전체":
    where.append("p.rx_otc = %s")
    params.append(rx)

kw = (keyword or "").strip()
if kw:
    like = f"%{kw}%"
    where.append("""
    (
        p.product_name ILIKE %s
        OR p.company_name ILIKE %s
        OR COALESCE(p.efficacy_text,'') ILIKE %s
        OR EXISTS (
            SELECT 1 FROM ingredients i
            WHERE i.item_seq = p.item_seq
              AND i.ingredient_name ILIKE %s
        )
    )
    """)
    params += [like, like, like, like]

where_sql = ("WHERE " + " AND ".join(where)) if where else ""

list_sql = f"""
SELECT
  p.item_seq,
  p.product_name,
  p.company_name,
  p.cmo_names,
  p.rx_otc,
  p.review_type,
  p.approval_date,
  p.first_seen_at,
  p.last_updated_at,
  p.source_url
FROM products p
{where_sql}
ORDER BY p.first_seen_at DESC
LIMIT {int(limit)}
"""

df = query_df(list_sql, params)

c1, c2, c3 = st.columns([1, 1, 2])
with c1:
    st.metric("조회 건수", f"{len(df):,}")
with c2:
    # 최근 7일 신규
    recent7 = query_df("SELECT COUNT(*) AS cnt FROM products WHERE first_seen_at >= now() - interval '7 days'")
    st.metric("최근 7일 누적", f"{int(recent7.loc[0,'cnt']):,}" if not recent7.empty else "0")
with c3:
    st.write("")

st.dataframe(df, use_container_width=True)

# CSV 다운로드
csv = df.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    "CSV 다운로드",
    data=csv,
    file_name="mfds_new_products.csv",
    mime="text/csv"
)

st.divider()

# ---------- 상세 조회 ----------
st.subheader("품목 상세 보기")
st.caption("리스트에서 item_seq(품목기준코드)를 복사해서 아래에 붙여넣으면 상세 정보를 확인할 수 있습니다.")

item_seq = st.text_input("item_seq 입력 (예: 202600308)", value="")

if item_seq.strip():
    item_seq = item_seq.strip()

    prod = query_df("SELECT * FROM products WHERE item_seq = %s", (item_seq,))
    ings = query_df(
        "SELECT ingredient_name FROM ingredients WHERE item_seq = %s ORDER BY ingredient_name",
        (item_seq,)
    )

    if prod.empty:
        st.warning("해당 item_seq가 DB에 없습니다. (아직 수집이 안 되었거나 item_seq 오타일 수 있어요.)")
    else:
        st.write("### 기본 정보")
        st.dataframe(prod, use_container_width=True)

        st.write("### 성분명(원료약품 및 분량 중 성분명)")
        if ings.empty:
            st.info("성분 정보가 없습니다.")
        else:
            st.dataframe(ings, use_container_width=True)

        st.write("### 효능효과(텍스트)")
        eff = prod.loc[0, "efficacy_text"] if "efficacy_text" in prod.columns else ""
        st.text_area("효능효과", value=(eff or ""), height=240)

st.divider()

# ---------- 운영 정보 ----------
st.subheader("운영/수집 상태")
last = query_df("""
SELECT
  MAX(last_seen_at) AS last_seen_at,
  MAX(last_updated_at) AS last_updated_at
FROM products
""")
if not last.empty:
    st.write(f"- 마지막 수집(관측) 시간: **{last.loc[0,'last_seen_at']}**")
    st.write(f"- 마지막 내용 변경 업데이트 시간: **{last.loc[0,'last_updated_at']}**")

st.info("다음 단계: `.github/workflows/fetch.yml`을 추가하면 매주 금요일 21:00(KST)에 자동 수집됩니다.")
