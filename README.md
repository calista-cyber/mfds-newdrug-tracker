# MFDS 신제품 자동 수집 & 누적 관리 시스템

본 저장소는 **식약처 N-Drug(의약품안전나라)**의  
「품목허가현황(CCBAE01)」을 기준으로  
**취소/취하일자가 없는 신규 품목**을 자동 수집하여  
사내에서 검색·누적 관리하기 위한 시스템입니다.

---

## 📌 수집 기준
- 데이터 소스: https://nedrug.mfds.go.kr
- 기준 페이지: 품목허가현황(CCBAE01)
- 신규 정의:
  - **취소/취하일자가 공란인 품목**
- 수집 주기:
  - **매주 금요일 21:00 (KST)** 자동 실행

---

## 📦 수집 항목
- 제품명
- 업체명
- 위탁제조업체
- 전문 / 일반
- 허가심사유형
- 허가일자
- 원료약품 및 분량 중 **성분명**
- 효능효과 (텍스트)

---

## 🗄️ 데이터 저장
- DB: Supabase (PostgreSQL)
- 기준 키: **itemSeq (품목기준코드)**
- 동작 방식:
  - itemSeq 기준 **Upsert**
  - 내용 변경 시 자동 업데이트

---

## 🖥️ 사내 웹 (Streamlit)
- 파일: `app.py`
- 기능:
  - 신규 품목 리스트 조회
  - 전문/일반, 기간 필터
  - 키워드 검색 (제품명 / 업체명 / 성분명 / 효능효과)
  - CSV 다운로드
  - itemSeq 기반 상세 조회

---

## ⚙️ 자동 실행
- GitHub Actions 사용
- 설정 파일: `.github/workflows/fetch.yml`
- 수동 테스트:
  - Actions → Fetch MFDS New Products → Run workflow

---

## 🔐 환경 변수
다음 환경 변수가 필요합니다:

- `DATABASE_URL`
  - Supabase PostgreSQL Connection string (URI)

> ⚠️ 본 저장소에는 DB 비밀번호를 직접 작성하지 않습니다.  
> GitHub Secrets / Streamlit Environment Variables에만 설정합니다.

---

## 📎 참고
- 본 시스템은 **사내 정보 모니터링/기획 참고용**이며  
  공식 데이터의 해석 및 사용에 대해서는  
  최종적으로 MFDS 공지를 기준으로 합니다.
