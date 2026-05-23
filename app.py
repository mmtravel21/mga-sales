"""
명가삼대떡집 판매 분석 - 일일/월별 보고서
- 파일 업로드 → 송장입력일 기준 자동 분류
- 일일 종합 보고서 (캡쳐 보고용)
  ① 일일 매출 요약 (전체/생산 × 전월 평균/월요일/월제외 비교)
  ② 월 목표 달성률 (3개 카드)
  ③ 일자별 4셀 매트릭스
  ④ 마진 현황 (금일/월 누계)
"""
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import sqlite3
import calendar
import os
from datetime import datetime, date, timedelta
from io import StringIO
from pathlib import Path
import json
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import URL

st.set_page_config(page_title="명가삼대떡집 판매분석", page_icon="🍡", layout="wide")

APP_DIR = Path(__file__).parent
DB_PATH = APP_DIR / "sales.db"
CONFIG_PATH = APP_DIR / "config.json"
BACKUP_DIR = APP_DIR / "backup"
PUBLIC_DIR = APP_DIR / "public"
BACKUP_DIR.mkdir(exist_ok=True)
PUBLIC_DIR.mkdir(exist_ok=True)


# ===== DB Engine (SQLite local / PostgreSQL on cloud) =====
def get_db_url():
    """환경변수 DATABASE_URL 우선 (Streamlit Cloud secrets),
    없으면 로컬 SQLite로 폴백."""
    url = os.environ.get('DATABASE_URL')
    if not url:
        # Streamlit secrets 시도 (Streamlit Cloud에서 사용)
        try:
            url = st.secrets.get('DATABASE_URL', None)
        except Exception:
            url = None
    if url:
        # SQLAlchemy postgres:// → postgresql+psycopg2:// 변환
        if url.startswith('postgres://'):
            url = url.replace('postgres://', 'postgresql+psycopg2://', 1)
        elif url.startswith('postgresql://') and '+psycopg2' not in url:
            url = url.replace('postgresql://', 'postgresql+psycopg2://', 1)
        return url
    return f"sqlite:///{DB_PATH}"


_engine_cache = None
def get_engine():
    global _engine_cache
    if _engine_cache is None:
        url = get_db_url()
        _engine_cache = create_engine(url, pool_pre_ping=True, pool_recycle=300)
    return _engine_cache


def is_postgres():
    return 'postgres' in get_db_url()


def build_summary_dict(all_df: pd.DataFrame, box_fee: int = 3000) -> dict:
    """전체 DB 데이터를 일별/월별 요약 dict로 구성. AI 분석용."""
    if all_df.empty:
        return {'generated_at': datetime.now().isoformat(), 'daily': [], 'monthly': [], 'meta': {'total_rows': 0}}

    def metrics(ddf):
        ec_c = int(_filter(ddf, SELF_CHANNELS, BASE_SUPPLIERS)['원가'].sum())
        ec_b = int(_filter(ddf, SELF_CHANNELS, BASE_SUPPLIERS)['송장번호'].dropna().nunique())
        pr_c = int(_filter(ddf, SELF_CHANNELS, PROD_SUPPLIERS)['원가'].sum())
        pr_b = int(_filter(ddf, SELF_CHANNELS, PROD_SUPPLIERS)['송장번호'].dropna().nunique())
        op_c = int(_filter(ddf, OPEN_MARKETS, None)['원가'].sum())
        op_b = int(_filter(ddf, OPEN_MARKETS, BASE_SUPPLIERS)['송장번호'].dropna().nunique())
        op_r = int(_filter(ddf, OPEN_MARKETS, None)['정산금액'].sum())
        opp_c = int(_filter(ddf, OPEN_MARKETS, PROD_SUPPLIERS)['원가'].sum())
        opp_b = int(_filter(ddf, OPEN_MARKETS, PROD_SUPPLIERS)['송장번호'].dropna().nunique())
        opp_r = int(_filter(ddf, OPEN_MARKETS, PROD_SUPPLIERS)['정산금액'].sum())
        nxt_total = ec_c + ec_b * box_fee + op_r
        nxt_prod  = pr_c + pr_b * box_fee + opp_r
        return {
            '에컴_원가': ec_c, '에컴_배송': ec_b, '에컴_택배비': ec_b * box_fee,
            '생산_원가': pr_c, '생산_배송': pr_b, '생산_택배비': pr_b * box_fee,
            '오픈전체_원가': op_c, '오픈전체_배송': op_b, '오픈전체_택배비': op_b * box_fee,
            '오픈전체_매출': op_r,
            '오픈생산_원가': opp_c, '오픈생산_배송': opp_b, '오픈생산_택배비': opp_b * box_fee,
            '오픈생산_매출': opp_r,
            '넥스트고_전체_매출': nxt_total,
            '넥스트고_생산_매출': nxt_prod,
            '오픈전체_마진': op_r - op_c - op_b * box_fee,
            '오픈생산_마진': opp_r - opp_c - opp_b * box_fee,
            '주문수': len(ddf),
        }

    daily_list = []
    for d in sorted(all_df['기준일'].dropna().unique()):
        ddf = all_df[all_df['기준일'] == d]
        row = {'기준일': d, **metrics(ddf)}
        daily_list.append(row)

    # 월별 누계
    monthly = {}
    for d in daily_list:
        m = d['기준일'][:7]
        if m not in monthly:
            monthly[m] = {'월': m, '일수': 0}
            for k, v in d.items():
                if k != '기준일' and isinstance(v, (int, float)):
                    monthly[m][k] = 0
        for k, v in d.items():
            if k != '기준일' and isinstance(v, (int, float)):
                monthly[m][k] += v
        monthly[m]['일수'] += 1

    return {
        'generated_at': datetime.now().isoformat(),
        'meta': {
            'total_rows': len(all_df),
            'date_range': [all_df['기준일'].min(), all_df['기준일'].max()],
            'days_count': all_df['기준일'].nunique(),
            'box_fee': box_fee,
        },
        'channels': {
            'self': SELF_CHANNELS,
            'open_market': OPEN_MARKETS,
        },
        'suppliers': {
            'base (넥+물)': BASE_SUPPLIERS,
            'production (넥)': PROD_SUPPLIERS,
        },
        'monthly': list(monthly.values()),
        'daily': daily_list,
        'formulas': {
            '넥스트고_전체_매출': '에컴_원가 + 에컴_배송*박스비 + 오픈전체_매출',
            '넥스트고_생산_매출': '생산_원가 + 생산_배송*박스비 + 오픈생산_매출',
            '마진': '매출 - 원가 - 택배비',
        },
    }


def export_to_public():
    """public/ 폴더에 JSON/CSV 형태로 export. 외부 AI/API에서 fetch용."""
    try:
        all_df = load_orders()
        summary = build_summary_dict(all_df)
        with open(PUBLIC_DIR / "summary.json", 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
        # Raw CSV
        all_df.to_csv(PUBLIC_DIR / "raw.csv", index=False, encoding='utf-8-sig')
        # Index
        with open(PUBLIC_DIR / "index.html", 'w', encoding='utf-8') as f:
            f.write(f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>명가삼대 판매분석 데이터 API</title>
<style>body{{font-family:sans-serif;max-width:800px;margin:40px auto;padding:20px}}
a{{display:block;margin:10px 0;color:#0066cc;text-decoration:none;padding:12px;
border:1px solid #e0e0e0;border-radius:8px}}
a:hover{{background:#f5f5f5}}</style></head>
<body><h1>📊 명가삼대 판매분석 데이터 API</h1>
<p>외부 AI 에이전트가 분석용으로 fetch 가능한 데이터 endpoint.</p>
<a href="summary.json">📋 summary.json — 일별/월별 요약 (JSON)</a>
<a href="raw.csv">📦 raw.csv — 전체 원본 데이터 (CSV)</a>
<hr><p>업데이트: {datetime.now().isoformat()}</p>
<p>전체 행수: {len(all_df):,}건 / 기간: {all_df['기준일'].min() if not all_df.empty else '—'} ~ {all_df['기준일'].max() if not all_df.empty else '—'}</p>
</body></html>""")
        return True
    except Exception as e:
        print(f"Export error: {e}")
        return False


def backup_db():
    """업로드/UPSERT/초기화 직전에 sales.db 백업본 생성. 최근 30개만 유지."""
    if not DB_PATH.exists():
        return None
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = BACKUP_DIR / f"sales_{ts}.db"
    import shutil
    shutil.copy2(DB_PATH, backup_path)
    # 30개 초과시 오래된 파일 삭제
    backups = sorted(BACKUP_DIR.glob("sales_*.db"))
    while len(backups) > 30:
        backups[0].unlink()
        backups.pop(0)
    return backup_path

COLUMN_NAMES = [
    '관리번호', '판매처', '주문번호', '상태', 'CS', '품절', '사은품여부', '배송 보류', '선착불', '상품코드',
    '바코드', '공급처', '제조사', '판매처 상품코드', '상품명', '옵션명', '판매처 상품명', '판매처 옵션', '카테고리', '주문수량',
    '상품수량', '판매가', '정산금액', '수수료', '원가', '공급가', '총공급가', '추가금액', '주문일', '주문시간',
    '발주일', '발주시간', '송장입력일', '송장번호', '택배사', '수령자우편번호', '수령자주소', '배송일', '우선순위', '주문자이름',
    '주문자전화', '주문자휴대폰', '수령자이름', '수령자전화', '수령자휴대폰', '배송메모', '공급처 상품명', '공급처 옵션명', '상품 택배비', '로케이션',
    '중량', '코드1', '코드2', '원산지', '결제수단', '주문상세번호', '주문자 id', '선결제 금액', '취소교환사유'
]
SELF_CHANNELS = ['카페24', '스스 명가삼대떡집', '쿠팡', '캐시딜', '토스쇼핑', '카카오']
OPEN_MARKETS = ['11번가', 'G마켓', '옥션', '테무', '알리익스프레스', 'NS홈쇼핑', '롯데ON', 'Hmall', '쇼핑엔티']
ALL_CHANNELS = SELF_CHANNELS + OPEN_MARKETS
BASE_SUPPLIERS = ['넥스트고', '넥스트고 물류']
PROD_SUPPLIERS = ['넥스트고']
BOX_FEE = 3000

DEFAULT_CONFIG = {
    'target_nxt_total':  850_000_000,  # 넥스트고 5월 전체 OEM포함
    'target_nxt_prod':   800_000_000,  # 넥스트고 5월 생산만
    'target_open_total': 200_000_000,  # 오픈마켓 OEM포함
    'target_open_prod':  190_000_000,  # 오픈마켓 생산
    'box_fee':           3_000,
    # 전월 평균 수동 입력 {YYYY-MM: {key: {avg, mon, non_mon}}}
    # key = total_all / total_open / prod_all / prod_open
    'manual_prev_avg':   {},
}


def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ===== DB =====
def init_db():
    engine = get_engine()
    with engine.begin() as conn:
        if is_postgres():
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS orders (
                    "관리번호" TEXT PRIMARY KEY,
                    "판매처" TEXT, "공급처" TEXT,
                    "정산금액" DOUBLE PRECISION, "원가" DOUBLE PRECISION,
                    "송장번호" TEXT, "발주일" TEXT, "주문일" TEXT,
                    "기준일" TEXT, "업로드일시" TEXT
                )
            '''))
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS uploads (
                    id SERIAL PRIMARY KEY,
                    "파일명" TEXT, "업로드일시" TEXT, "기준일" TEXT,
                    "전체행수" INTEGER, "신규행수" INTEGER, "중복행수" INTEGER
                )
            '''))
        else:
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS orders (
                    관리번호 TEXT PRIMARY KEY,
                    판매처 TEXT, 공급처 TEXT,
                    정산금액 REAL, 원가 REAL,
                    송장번호 TEXT, 발주일 TEXT, 주문일 TEXT,
                    기준일 TEXT, 업로드일시 TEXT
                )
            '''))
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS uploads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    파일명 TEXT, 업로드일시 TEXT, 기준일 TEXT,
                    전체행수 INTEGER, 신규행수 INTEGER, 중복행수 INTEGER
                )
            '''))


def auto_correct_cost(df: pd.DataFrame) -> tuple:
    """동일 상품코드에 대해 단가가 다른 행을 최빈 단가로 자동 보정.
    Returns: (corrected_df, correction_log)
    """
    if '상품코드' not in df.columns or '상품수량' not in df.columns:
        return df, []
    df = df.copy()
    df['_qty']  = pd.to_numeric(df['상품수량'], errors='coerce').fillna(1)
    df['_unit'] = df['원가'] / df['_qty']

    log = []
    for code, grp in df.groupby('상품코드'):
        if pd.isna(code) or grp.empty:
            continue
        units = grp['_unit'].value_counts()
        if len(units) <= 1:
            continue
        # 최빈 단가
        normal_unit = units.idxmax()
        normal_count = units.iloc[0]
        # 이상치: 최빈 단가의 2배 이상 또는 0.5배 이하 + 건수 1건짜리
        for idx, row in grp.iterrows():
            if row['_unit'] != normal_unit and units[row['_unit']] == 1:
                ratio = row['_unit'] / normal_unit if normal_unit else 0
                if ratio >= 2.0 or (ratio > 0 and ratio <= 0.5):
                    new_cost = int(normal_unit * row['_qty'])
                    old_cost = int(row['원가'])
                    log.append({
                        '관리번호': row['관리번호'],
                        '판매처':   row['판매처'],
                        '상품명':   str(row.get('상품명', ''))[:30],
                        '수량':     int(row['_qty']),
                        '원본 원가': old_cost,
                        '보정 원가': new_cost,
                        '차이':     new_cost - old_cost,
                    })
                    df.at[idx, '원가'] = new_cost
    df = df.drop(columns=['_qty', '_unit'])
    return df, log


def parse_xls(file, auto_correct: bool = True):
    """Returns (DataFrame, correction_log)"""
    data = file.read()
    text = data.decode('utf-8')
    dfs = pd.read_html(StringIO(text), header=0)
    df = dfs[0]
    if len(df.columns) != len(COLUMN_NAMES):
        raise ValueError(f"컬럼 개수 불일치: {len(df.columns)} (기대: {len(COLUMN_NAMES)})")
    df.columns = COLUMN_NAMES
    df = df[df['판매처'].notna()].copy()
    for col in ['정산금액', '원가']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    df['주문일']     = pd.to_datetime(df['주문일'],   errors='coerce').dt.strftime('%Y-%m-%d')
    df['발주일']     = pd.to_datetime(df['발주일'],   errors='coerce').dt.strftime('%Y-%m-%d')
    df['송장입력일'] = pd.to_datetime(df['송장입력일'], errors='coerce').dt.strftime('%Y-%m-%d')

    log = []
    if auto_correct:
        df, log = auto_correct_cost(df)
    return df, log


def detect_main_date(df: pd.DataFrame) -> str:
    """파일 대표일 = 송장입력일(출고일) 최빈값, 없으면 발주일"""
    for col in ['송장입력일', '발주일', '주문일']:
        if col in df.columns:
            vals = df[col].dropna()
            if not vals.empty:
                return vals.mode().iloc[0]
    return datetime.now().strftime('%Y-%m-%d')


def save_to_db(df: pd.DataFrame, filename: str, base_date: str, update_existing: bool = False):
    """업로드 저장. update_existing 모드 지원."""
    backup_db()
    engine = get_engine()
    df = df.copy()
    df['관리번호'] = df['관리번호'].astype(str)
    total_raw = len(df)

    file_dup = df['관리번호'].duplicated().sum()
    if file_dup > 0:
        df = df.drop_duplicates(subset='관리번호', keep='first')

    db_cols = ['관리번호', '판매처', '공급처', '정산금액', '원가',
               '송장번호', '발주일', '주문일', '기준일', '업로드일시']
    for c in db_cols:
        if c not in df.columns:
            df[c] = None

    if update_existing:
        # 새 파일의 관리번호와 매칭되는 기존 DB 행 삭제 후 모두 INSERT
        kn_list = df['관리번호'].tolist()
        deleted = 0
        with engine.begin() as conn:
            for i in range(0, len(kn_list), 500):
                chunk = kn_list[i:i + 500]
                result = conn.execute(
                    text('DELETE FROM orders WHERE "관리번호" = ANY(:kns)'
                         if is_postgres() else
                         'DELETE FROM orders WHERE 관리번호 IN ({})'.format(
                             ','.join([f':k{j}' for j in range(len(chunk))]))),
                    {'kns': chunk} if is_postgres() else {f'k{j}': k for j, k in enumerate(chunk)},
                )
                deleted += result.rowcount or 0

        df['업로드일시'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        df['기준일']    = base_date
        df[db_cols].to_sql('orders', engine, if_exists='append', index=False, method='multi', chunksize=1000)
        new_added = len(df)
        replaced  = deleted
        db_dup    = 0
    else:
        existing = pd.read_sql_query('SELECT "관리번호" FROM orders' if is_postgres() else 'SELECT 관리번호 FROM orders', engine)
        col = existing.columns[0]
        existing_set = set(existing[col].astype(str))
        new_df = df[~df['관리번호'].isin(existing_set)].copy()
        db_dup = len(df) - len(new_df)

        new_df['업로드일시'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        new_df['기준일']    = base_date
        if len(new_df) > 0:
            new_df[db_cols].to_sql('orders', engine, if_exists='append', index=False, method='multi', chunksize=1000)
        new_added = len(new_df)
        replaced  = 0

    pd.DataFrame([{
        '파일명': filename,
        '업로드일시': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        '기준일': base_date,
        '전체행수': total_raw,
        '신규행수': new_added,
        '중복행수': file_dup + db_dup,
    }]).to_sql('uploads', engine, if_exists='append', index=False)
    export_to_public()
    return new_added, file_dup + db_dup, file_dup, db_dup, replaced


def load_orders() -> pd.DataFrame:
    engine = get_engine()
    try:
        return pd.read_sql_query("SELECT * FROM orders", engine)
    except Exception:
        init_db()
        return pd.read_sql_query("SELECT * FROM orders", engine)


def load_uploads() -> pd.DataFrame:
    engine = get_engine()
    try:
        return pd.read_sql_query("SELECT * FROM uploads ORDER BY id DESC", engine)
    except Exception:
        return pd.DataFrame()


def delete_batch(upload_dt: str):
    engine = get_engine()
    col = '"업로드일시"' if is_postgres() else '업로드일시'
    with engine.begin() as conn:
        r1 = conn.execute(text(f"DELETE FROM orders WHERE {col} = :dt"), {'dt': upload_dt})
        n = r1.rowcount or 0
        conn.execute(text(f"DELETE FROM uploads WHERE {col} = :dt"), {'dt': upload_dt})
    return n


def reset_db():
    backup_db()
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM orders"))
        conn.execute(text("DELETE FROM uploads"))


# ===== 계산 helpers =====
def _filter(df, channels, suppliers):
    f = df[df['판매처'].isin(channels)]
    if suppliers is not None:
        f = f[f['공급처'].isin(suppliers)]
    return f


def revenue(df, channels, suppliers):
    return int(_filter(df, channels, suppliers)['정산금액'].sum())


def cost(df, channels, suppliers):
    return int(_filter(df, channels, suppliers)['원가'].sum())


def box_count(df, channels, suppliers):
    f = _filter(df, channels, suppliers)
    return int(f['송장번호'].dropna().nunique()) if not f.empty else 0


def daily_total_series(df, channels, suppliers):
    """기준일별 매출 시리즈"""
    f = _filter(df, channels, suppliers)
    if f.empty:
        return pd.Series(dtype=float)
    return f.groupby('기준일')['정산금액'].sum()


def prev_month_avg(df, target_date, channels, suppliers):
    """전월 평균 (전체 / 월요일만 / 월요일 제외)"""
    t = pd.to_datetime(target_date)
    pm_year = t.year if t.month > 1 else t.year - 1
    pm_month = t.month - 1 if t.month > 1 else 12
    series = daily_total_series(df, channels, suppliers)
    if series.empty:
        return 0, 0, 0
    series.index = pd.to_datetime(series.index)
    pm = series[(series.index.year == pm_year) & (series.index.month == pm_month)]
    if pm.empty:
        return 0, 0, 0
    monday   = pm[pm.index.dayofweek == 0]
    non_mon  = pm[pm.index.dayofweek != 0]
    return int(pm.mean()), int(monday.mean()) if not monday.empty else 0, int(non_mon.mean()) if not non_mon.empty else 0


def prev_month_avg_custom(df, target_date, metric_func):
    """metric_func(day_df) -> int 형태의 임의 지표에 대한 전월 평균"""
    t = pd.to_datetime(target_date)
    pm_year = t.year if t.month > 1 else t.year - 1
    pm_month = t.month - 1 if t.month > 1 else 12
    if df.empty:
        return 0, 0, 0
    month_dates = sorted(df['기준일'].dropna().unique())
    daily_values = {}
    for d in month_dates:
        d_dt = pd.to_datetime(d)
        if d_dt.year == pm_year and d_dt.month == pm_month:
            daily_values[d_dt] = metric_func(df[df['기준일'] == d])
    if not daily_values:
        return 0, 0, 0
    all_vals = list(daily_values.values())
    mon_vals = [v for dt, v in daily_values.items() if dt.dayofweek == 0]
    non_mon_vals = [v for dt, v in daily_values.items() if dt.dayofweek != 0]
    avg_all = int(sum(all_vals) / len(all_vals)) if all_vals else 0
    avg_mon = int(sum(mon_vals) / len(mon_vals)) if mon_vals else 0
    avg_non = int(sum(non_mon_vals) / len(non_mon_vals)) if non_mon_vals else 0
    return avg_all, avg_mon, avg_non


def company_revenue(day_df, self_supplier, open_supplier, box_fee=None):
    """시트 공식 (넥스트고 제조법인 관점 일일 매출):
       자사 원가 + 자사 택배비 + 오픈마켓 정산금
    """
    fee = box_fee if box_fee is not None else 3000
    self_c = int(_filter(day_df, SELF_CHANNELS, self_supplier)['원가'].sum())
    self_b_f = _filter(day_df, SELF_CHANNELS, self_supplier)
    self_b = int(self_b_f['송장번호'].dropna().nunique()) if not self_b_f.empty else 0
    self_fee = self_b * fee
    open_r = int(_filter(day_df, OPEN_MARKETS, open_supplier)['정산금액'].sum())
    return self_c + self_fee + open_r


def get_prev_avg(df, target_date, metric_func, config, manual_key):
    """전월 평균: DB에 전월 데이터 있으면 자동 계산, 없으면 수동 입력값 사용.
    Returns (avg, mon_avg, non_mon_avg, is_manual: bool)
    """
    auto_all, auto_mon, auto_non = prev_month_avg_custom(df, target_date, metric_func)
    if auto_all > 0 or auto_mon > 0 or auto_non > 0:
        return auto_all, auto_mon, auto_non, False
    # DB에 전월 데이터 없으면 수동 입력값 사용
    t = pd.to_datetime(target_date)
    month_key = t.strftime('%Y-%m')  # 현재 보고월
    manual = config.get('manual_prev_avg', {}).get(month_key, {}).get(manual_key, {})
    return (int(manual.get('avg', 0)),
            int(manual.get('mon', 0)),
            int(manual.get('non_mon', 0)),
            True)


def month_cumulative(df, target_date, channels, suppliers):
    """선택일 포함 그 달 누계"""
    t = pd.to_datetime(target_date)
    series = daily_total_series(df, channels, suppliers)
    if series.empty:
        return 0
    series.index = pd.to_datetime(series.index)
    cum = series[(series.index.year == t.year) & (series.index.month == t.month) & (series.index <= t)]
    return int(cum.sum())


# ===== 포맷팅 =====
def won(n):
    return f"₩{int(n):,}"


def signed_won(n):
    n = int(n)
    return f"+₩{n:,}" if n >= 0 else f"-₩{abs(n):,}"


def pct(n, d):
    return f"{(n/d*100):.1f}%" if d else "0.0%"


# ===== UI =====
init_db()
config = load_config()

st.title("🍡 명가삼대떡집 판매분석")

# ----- 사이드바 -----
with st.sidebar:
    st.header("📤 일자별 파일 업로드")
    st.caption("1. 파일을 끌어다 놓거나 선택 → 2. 기준일 확인 → 3. 저장")
    uploaded = st.file_uploader("주문 검색 .xls", type=['xls', 'xlsx', 'html'],
                                accept_multiple_files=False)
    if uploaded is not None:
        try:
            df_new, correction_log = parse_xls(uploaded, auto_correct=True)
            auto_date = detect_main_date(df_new)
            st.success(f"📅 자동 감지 기준일: **{auto_date}**\n📊 전체 {len(df_new):,}건")
            if correction_log:
                with st.expander(f"⚠️ 원가 이상치 자동 보정 ({len(correction_log)}건)"):
                    st.dataframe(pd.DataFrame(correction_log), width='stretch', hide_index=True)
            base_date = st.date_input("📅 기준일 (필요시 수정)", pd.to_datetime(auto_date).date(), key='bd')
            upsert = st.checkbox(
                "🔄 기존 데이터 기준일 갱신 (UPSERT)",
                value=False,
                help="체크 시: 이미 DB에 있는 관리번호도 새 파일 기준으로 **덮어쓰기**.\n"
                     "예) 5/13 파일에 잘못 묶여서 들어간 5/12 관리번호들을 정확히 5/12로 재분류할 때 사용",
            )
            if st.button("💾 DB에 저장", type="primary", use_container_width=True):
                try:
                    new, dup, file_dup, db_dup, replaced = save_to_db(
                        df_new, uploaded.name, str(base_date), update_existing=upsert
                    )
                    if upsert:
                        msg = f"✅ 신규 {new:,}건 저장 (그 중 {replaced:,}건은 기존 행 덮어쓰기)"
                        if file_dup > 0:
                            msg += f" / ♻️ 파일내 중복 {file_dup}건 스킵"
                    else:
                        msg = f"✅ 신규 {new:,}건 추가"
                        if dup > 0:
                            detail = []
                            if file_dup > 0:
                                detail.append(f"파일내 중복 {file_dup}")
                            if db_dup > 0:
                                detail.append(f"DB 중복 {db_dup}")
                            msg += f" / ♻️ 중복 {dup:,}건 스킵 ({', '.join(detail)})"
                    st.success(msg)
                    st.balloons()
                    st.rerun()
                except Exception as e:
                    import traceback
                    st.error(f"❌ 저장 실패: {type(e).__name__}: {e}")
                    st.code(traceback.format_exc())
        except Exception as e:
            import traceback
            st.error(f"❌ 파싱 실패: {type(e).__name__}: {e}")
            st.code(traceback.format_exc())
    else:
        st.caption("💡 매일 한 번씩 이지어드민에서 다운받은 `확장주문검색_*.xls` 파일을 올려주세요. "
                   "같은 관리번호는 자동 중복 스킵됩니다.")

    st.divider()
    with st.expander("⚙️ 월 목표 설정", expanded=False):
        config['target_nxt_total']  = st.number_input("넥스트고 전체 OEM포함 월 목표(원)",
                                                       value=config['target_nxt_total'],  step=10_000_000)
        config['target_nxt_prod']   = st.number_input("넥스트고 생산만 월 목표(원)",
                                                       value=config['target_nxt_prod'],   step=10_000_000)
        config['target_open_total'] = st.number_input("오픈마켓 OEM포함 월 목표(원)",
                                                       value=config['target_open_total'], step=10_000_000)
        config['target_open_prod']  = st.number_input("오픈마켓 생산 월 목표(원)",
                                                       value=config['target_open_prod'],  step=10_000_000)
        config['box_fee']           = st.number_input("박스당 택배비(원)",
                                                       value=config['box_fee'], step=100)
        if st.button("저장", type="primary", key='save_targets'):
            save_config(config)
            st.success("✅ 설정 저장")

    with st.expander("📝 전월 평균 수동 입력", expanded=False):
        st.caption("DB에 전월 데이터가 쌓이면 자동 우선 적용됩니다. 그전까지만 수기 입력.")
        today_d = date.today()
        m_default = today_d.strftime('%Y-%m')
        m_key = st.text_input("보고월 (예: 2026-05)", m_default, key='prev_avg_month')
        prev_m_dt = pd.to_datetime(m_key + "-01") - pd.Timedelta(days=1)
        st.caption(f"※ 입력값은 **{prev_m_dt.strftime('%Y년 %m월')}** 평균값")

        existing = config.get('manual_prev_avg', {}).get(m_key, {})

        def _inp(group_key, label):
            g = existing.get(group_key, {})
            st.markdown(f"**{label}**")
            c1, c2, c3 = st.columns(3)
            v_avg = c1.number_input("평균", value=int(g.get('avg', 0)),
                                    step=100_000, key=f'pa_{group_key}_avg')
            v_mon = c2.number_input("월요일 평균", value=int(g.get('mon', 0)),
                                    step=100_000, key=f'pa_{group_key}_mon')
            v_non = c3.number_input("월 제외 평균", value=int(g.get('non_mon', 0)),
                                    step=100_000, key=f'pa_{group_key}_non')
            return {'avg': v_avg, 'mon': v_mon, 'non_mon': v_non}

        new_vals = {
            'total_all':  _inp('total_all',  '전체 - 금일 총매출'),
            'total_open': _inp('total_open', '전체 - 오픈마켓 총매출'),
            'prod_all':   _inp('prod_all',   '생산 - 금일 총매출'),
            'prod_open':  _inp('prod_open',  '생산 - 오픈마켓 총매출'),
        }

        if st.button("📝 전월 평균 저장", type="primary", key='save_prev_avg'):
            config.setdefault('manual_prev_avg', {})[m_key] = new_vals
            save_config(config)
            st.success(f"✅ {m_key} 보고월의 전월 평균값 저장")
            st.rerun()

    with st.expander("🤖 AI 에이전트용 데이터 export", expanded=False):
        st.caption("외부 AI/ChatGPT 등에게 분석 시킬 때 사용. 첨부 파일로 보내주세요.")
        all_df_for_export = load_orders()
        if not all_df_for_export.empty:
            summary = build_summary_dict(all_df_for_export, BOX_FEE)
            json_bytes = json.dumps(summary, ensure_ascii=False, indent=2, default=str).encode('utf-8')
            csv_bytes = all_df_for_export.to_csv(index=False).encode('utf-8-sig')

            st.download_button("📥 요약 JSON (일별/월별)", json_bytes,
                              f"summary_{date.today()}.json", "application/json")
            st.download_button("📥 원본 CSV (전체 행)", csv_bytes,
                              f"raw_{date.today()}.csv", "text/csv")
            st.markdown(f"**{summary['meta']['total_rows']:,}건** / "
                       f"{summary['meta']['date_range'][0]} ~ {summary['meta']['date_range'][1]}")
        else:
            st.info("데이터 없음")

        st.divider()
        st.caption("🌐 자동 fetch URL (선택)")
        st.code("/static (별도 cloudflared 터널)\n→ DEPLOY_GUIDE.md 참고")
        if st.button("🔄 public/ 폴더 즉시 재생성"):
            if export_to_public():
                st.success("✅ public/summary.json, public/raw.csv 갱신 완료")

    with st.expander("⚙️ 데이터 관리"):
        # DB 백업 복구
        backups = sorted(BACKUP_DIR.glob("sales_*.db"), reverse=True)
        if backups:
            backup_opts = [f"{b.stem.replace('sales_', '')} ({b.stat().st_size//1024:,}KB)"
                          for b in backups[:30]]
            sel_bkp = st.selectbox("📦 백업 파일", backup_opts, key='bkp_sel')
            if st.button("⏪ 선택 백업으로 복구"):
                import shutil
                idx = backup_opts.index(sel_bkp)
                shutil.copy2(backups[idx], DB_PATH)
                st.success(f"✅ {sel_bkp} 복구 완료")
                st.rerun()
        else:
            st.caption("아직 백업이 없습니다 (저장 시 자동 생성)")

        st.divider()
        confirm = st.text_input("⚠️ 위험: DB 전체 초기화하려면 'RESET' 입력",
                                placeholder="RESET", key='reset_confirm')
        if st.button("🗑️ DB 전체 초기화", disabled=(confirm != 'RESET')):
            reset_db()
            st.success("초기화 완료 (백업 자동 생성됨)")
            st.rerun()


# ----- 메인 -----
all_df = load_orders()
BOX_FEE = config['box_fee']

if all_df.empty:
    st.warning("⚠️ 업로드된 데이터가 없습니다. **사이드바에서 .xls 파일을 업로드**해주세요. "
               "(아래는 빈 화면 미리보기입니다)")

tab1, tab_cal, tab2, tab3, tab4 = st.tabs(
    ["📊 일일 종합 보고서", "📅 캘린더 & 기간집계", "📆 월별 합계", "💾 누적 전체", "📜 업로드 이력"]
)

# ===== 탭1: 일일 종합 보고서 (캡쳐 보고용) =====
with tab1:
    # ----- 헤더 (날짜 선택) -----
    dates = sorted(all_df['기준일'].dropna().unique(), reverse=True)
    is_empty = len(dates) == 0
    if is_empty:
        # 데이터가 없으면 오늘을 디폴트로
        dates = [date.today().strftime('%Y-%m-%d')]
    head_col1, head_col2 = st.columns([3, 1])
    with head_col1:
        sel = st.selectbox("📅 보고 일자", dates, index=0, key='daily_sel',
                          label_visibility="collapsed")
    target_dt = pd.to_datetime(sel)
    weekday_kor = ['월', '화', '수', '목', '금', '토', '일'][int(target_dt.dayofweek)]
    weekday_color = '#dc3545' if weekday_kor == '일' else ('#0d6efd' if weekday_kor == '토' else '#212529')

    st.markdown(f"""
    <div style="background:linear-gradient(90deg,#0d6efd 0%,#6610f2 100%);
                padding:18px 24px;border-radius:12px;color:#fff;margin-bottom:16px">
        <div style="font-size:13px;opacity:0.85">📊 명가삼대떡집 일일 종합 보고서</div>
        <div style="font-size:28px;font-weight:700;margin-top:4px">
            {sel} <span style="color:{('#ffcccc' if weekday_kor == '일' else ('#cce5ff' if weekday_kor == '토' else '#fff'))}">({weekday_kor})</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    day_df = all_df[all_df['기준일'] == sel]

    # ----- ① 일일 매출 요약 (넥스트고 제조법인 관점) -----
    # 시트 공식:
    #   금일 총매출 = 자사 원가 + 자사 택배비 + 오픈마켓 정산금
    #     (자사몰 부분은 명가삼대→넥스트고 납품가, 오픈마켓은 정산금 그대로)
    #   오픈마켓 총매출 = 오픈마켓 정산금 (그대로)
    st.markdown("#### ① 일일 매출 요약 (넥스트고 제조법인 관점)")
    st.caption(f"※ 이지어드민 송장일({sel}) 기준 / "
               f"매출 = 자사 납품가(원가+택배비) + 오픈마켓 정산금")

    def summary_block(label, self_sp, open_sp, key_total, key_open):
        # 현재 일자 값
        total_v = company_revenue(day_df, self_sp, open_sp, BOX_FEE)
        open_v  = revenue(day_df, OPEN_MARKETS, open_sp)

        # 전월 평균: DB > 수동 입력 fallback
        total_metric = lambda ddf: company_revenue(ddf, self_sp, open_sp, BOX_FEE)
        open_metric  = lambda ddf: revenue(ddf, OPEN_MARKETS, open_sp)
        pm_all,  pm_mon,  pm_non,  src_t = get_prev_avg(all_df, sel, total_metric, config, key_total)
        pm_all2, pm_mon2, pm_non2, src_o = get_prev_avg(all_df, sel, open_metric, config, key_open)

        tag_t = " 🖊️" if src_t else " 📊"
        tag_o = " 🖊️" if src_o else " 📊"

        rows = [
            {'구분': '금일 총매출',
             '금일': won(total_v), f'전월 평균{tag_t}': won(pm_all),
             '증감': signed_won(total_v - pm_all),
             '전월 평균 월요일': won(pm_mon), '전월 평균 (월 제외)': won(pm_non)},
            {'구분': '오픈마켓 총매출',
             '금일': won(open_v), f'전월 평균{tag_o}': won(pm_all2),
             '증감': signed_won(open_v - pm_all2),
             '전월 평균 월요일': won(pm_mon2), '전월 평균 (월 제외)': won(pm_non2)},
        ]
        st.markdown(f"**{label}**")
        df_show = pd.DataFrame(rows)
        # 컬럼 헤더 통일 (이모지 다르면 두 행 헤더가 다르게 보일 수 있어서)
        df_show.columns = [c.replace(' 🖊️', '').replace(' 📊', '') for c in df_show.columns]
        st.dataframe(df_show, width='stretch', hide_index=True)
        if src_t or src_o:
            st.caption("🖊️ 수동 입력값 사용 중 (사이드바 '전월 평균 수동 입력'에서 수정)")
        else:
            st.caption("📊 DB 데이터 기반 자동 계산")

    col_a, col_b = st.columns(2)
    with col_a:
        # 전체 = OEM포함: 자사 공급처는 넥+물, 오픈마켓은 모든 공급처
        summary_block("전체 매출 요약 (OEM포함)", BASE_SUPPLIERS, None,
                      'total_all', 'total_open')
    with col_b:
        # 생산만: 자사+오픈마켓 모두 넥스트고 공급처만
        summary_block("생산 매출 요약 (넥스트고만)", PROD_SUPPLIERS, PROD_SUPPLIERS,
                      'prod_all', 'prod_open')

    st.divider()

    # ----- ② 월 목표 달성률 -----
    # 시트 공식 (계산법 시트 + 5월 시트 분석):
    #   넥스트고 5월 전체 매출 = 에컴 원가 + 에컴 택배비 + 오픈 OEM포함 매출
    #     (자사몰은 "납품가" = 원가+택배비로 계산. 명가삼대→넥스트고/에스컴퍼니 납품)
    #   넥스트고 5월 생산 매출 = 생산 원가 + 생산 택배비 + 오픈 생산 매출
    #   오픈 OEM포함 매출 = 오픈+모든공급처 정산금
    #   오픈 생산 매출 = 오픈+넥 정산금
    st.markdown(f"#### ② {target_dt.month}월 목표 달성률")
    st.caption("💡 자사몰 매출 = 납품가 (에컴 원가 + 택배비). 오픈마켓 매출 = 정산금")

    # 금일 값 계산 (시트 I5/N5 공식)
    ecom_cost = cost(day_df, SELF_CHANNELS, BASE_SUPPLIERS)     # A4
    ecom_box  = box_count(day_df, SELF_CHANNELS, BASE_SUPPLIERS) # A6
    ecom_fee  = ecom_box * BOX_FEE                               # A8
    prod_cost = cost(day_df, SELF_CHANNELS, PROD_SUPPLIERS)     # B4
    prod_box  = box_count(day_df, SELF_CHANNELS, PROD_SUPPLIERS) # B6
    prod_fee  = prod_box * BOX_FEE                               # B8
    open_total_rev = revenue(day_df, OPEN_MARKETS, None)         # S5 (모든공급)
    open_prod_rev  = revenue(day_df, OPEN_MARKETS, PROD_SUPPLIERS) # X5 (넥만)

    nxt_total_today = ecom_cost + ecom_fee + open_total_rev      # I5
    nxt_prod_today  = prod_cost + prod_fee + open_prod_rev       # N5

    # 월 누계 — 같은 달 모든 일자 합산
    def month_cum_custom(target_func, target_date):
        """target_func(day_df) → int 형태로 일자별 계산 → 누계"""
        t = pd.to_datetime(target_date)
        month_dates = sorted(all_df['기준일'].dropna().unique())
        total = 0
        for d in month_dates:
            d_dt = pd.to_datetime(d)
            if d_dt.year == t.year and d_dt.month == t.month and d_dt <= t:
                total += target_func(all_df[all_df['기준일'] == d])
        return total

    nxt_total_cum = month_cum_custom(
        lambda ddf: cost(ddf, SELF_CHANNELS, BASE_SUPPLIERS)
                    + box_count(ddf, SELF_CHANNELS, BASE_SUPPLIERS) * BOX_FEE
                    + revenue(ddf, OPEN_MARKETS, None), sel)
    nxt_prod_cum = month_cum_custom(
        lambda ddf: cost(ddf, SELF_CHANNELS, PROD_SUPPLIERS)
                    + box_count(ddf, SELF_CHANNELS, PROD_SUPPLIERS) * BOX_FEE
                    + revenue(ddf, OPEN_MARKETS, PROD_SUPPLIERS), sel)
    open_total_cum = month_cum_custom(lambda ddf: revenue(ddf, OPEN_MARKETS, None), sel)
    open_prod_cum  = month_cum_custom(lambda ddf: revenue(ddf, OPEN_MARKETS, PROD_SUPPLIERS), sel)

    c1, c2, c3, c4 = st.columns(4)

    def render_card(col, title, target, today_v, cum_v, label):
        rate = cum_v / target if target else 0
        col.markdown(f"**{title}**")
        col.markdown(f"월 목표: {won(target)}")
        col.metric(label, won(today_v))
        col.metric("월 누계", won(cum_v))
        col.progress(min(rate, 1.0), text=f"달성률 {rate*100:.1f}%")
        col.caption(f"잔여 목표액: {won(max(target - cum_v, 0))}")

    render_card(c1, "🏢 넥스트고 5월 전체 (OEM포함)",
                config['target_nxt_total'], nxt_total_today, nxt_total_cum, '금일 매출')
    render_card(c2, "🏭 넥스트고 5월 생산만",
                config['target_nxt_prod'], nxt_prod_today, nxt_prod_cum, '금일 매출')
    render_card(c3, "🛒 오픈마켓 5월 (OEM포함)",
                config['target_open_total'], open_total_rev, open_total_cum, '금일 매출(전체)')
    render_card(c4, "🛍️ 오픈마켓 5월 생산만",
                config['target_open_prod'], open_prod_rev, open_prod_cum, '금일 매출(생산)')

    st.divider()

    # 4셀 매트릭스 + 마진 한 라인에 (시트 레이아웃 모방)
    matrix_col, margin_col = st.columns([5, 4])

    # ----- ③ 일자별 4셀 매트릭스 -----
    with matrix_col:
        st.markdown(f"#### ③ {target_dt.month}/{target_dt.day} 4셀 매트릭스")
        st.caption("원가=회계상 모든 공급처 / 택배건수=명가삼대 출고분(넥+물)만")

        matrix_rows = [
            ('에컴 상품 (전체)', SELF_CHANNELS, BASE_SUPPLIERS, BASE_SUPPLIERS),
            ('생산 상품 (생산)', SELF_CHANNELS, PROD_SUPPLIERS, PROD_SUPPLIERS),
            ('오픈 전체 (전)',   OPEN_MARKETS,  None,           BASE_SUPPLIERS),
            ('오픈 생산 (생)',   OPEN_MARKETS,  PROD_SUPPLIERS, PROD_SUPPLIERS),
        ]
        m_data = {'구분': [], '상품원가 합': [], '택배건수': [], '택배비': []}
        for label, ch, sp_cost, sp_box in matrix_rows:
            c_val = cost(day_df, ch, sp_cost)
            b_val = box_count(day_df, ch, sp_box)
            m_data['구분'].append(label)
            m_data['상품원가 합'].append(won(c_val))
            m_data['택배건수'].append(f"{b_val:,}")
            m_data['택배비'].append(won(b_val * BOX_FEE))
        st.dataframe(pd.DataFrame(m_data), width='stretch', hide_index=True)

    # ----- ④ 마진 현황 -----
    # 시트 공식 (5월 시트 AC4/AH4):
    #   오픈 전체 마진 = S5 - C4 - C8 = 오픈OEM포함 매출 - 오픈전체 원가 - 오픈전체 택배비
    #   오픈 생산 마진 = X5 - D4 - D8 = 오픈생산 매출 - 오픈생산 원가 - 오픈생산 택배비
    with margin_col:
        st.markdown(f"#### ④ {target_dt.month}월 오픈마켓 마진")

        # 금일 마진 계산
        open_total_cost = cost(day_df, OPEN_MARKETS, None)
        open_total_box  = box_count(day_df, OPEN_MARKETS, BASE_SUPPLIERS)
        open_total_fee  = open_total_box * BOX_FEE
        open_total_marg = open_total_rev - open_total_cost - open_total_fee

        open_prod_cost  = cost(day_df, OPEN_MARKETS, PROD_SUPPLIERS)
        open_prod_box   = box_count(day_df, OPEN_MARKETS, PROD_SUPPLIERS)
        open_prod_fee   = open_prod_box * BOX_FEE
        open_prod_marg  = open_prod_rev - open_prod_cost - open_prod_fee

        # 월 누계 마진 (일별 마진 합)
        def margin_total_cum(channels, sp_cost, sp_box, sp_rev):
            t = pd.to_datetime(sel)
            month_dates = sorted(all_df['기준일'].dropna().unique())
            total = 0
            for d in month_dates:
                d_dt = pd.to_datetime(d)
                if d_dt.year == t.year and d_dt.month == t.month and d_dt <= t:
                    ddf = all_df[all_df['기준일'] == d]
                    total += revenue(ddf, channels, sp_rev) \
                           - cost(ddf, channels, sp_cost) \
                           - box_count(ddf, channels, sp_box) * BOX_FEE
            return total

        cum_open_total_marg = margin_total_cum(OPEN_MARKETS, None, BASE_SUPPLIERS, None)
        cum_open_prod_marg  = margin_total_cum(OPEN_MARKETS, PROD_SUPPLIERS, PROD_SUPPLIERS, PROD_SUPPLIERS)

        mm1, mm2 = st.columns(2)
        with mm1:
            st.markdown("**전체 (OEM포함)**")
            st.metric("금일 마진", won(open_total_marg),
                      help=f"매출 {won(open_total_rev)} - 원가 {won(open_total_cost)} - 택배비 {won(open_total_fee)}")
            st.metric("월 누계", won(cum_open_total_marg))
        with mm2:
            st.markdown("**생산만**")
            st.metric("금일 마진", won(open_prod_marg),
                      help=f"매출 {won(open_prod_rev)} - 원가 {won(open_prod_cost)} - 택배비 {won(open_prod_fee)}")
            st.metric("월 누계", won(cum_open_prod_marg))

    st.divider()

    # ----- 매출 공식 보기 + CSV 다운로드 -----
    with st.expander("📐 매출/마진 계산 공식 자세히 보기"):
        st.markdown(f"""
**넥스트고 5월 전체 매출** = 에컴 원가 + 에컴 택배비 + 오픈마켓 OEM포함 정산금
`= {ecom_cost:,} + {ecom_fee:,} + {open_total_rev:,} = {nxt_total_today:,}`

**넥스트고 5월 생산 매출** = 생산 원가 + 생산 택배비 + 오픈마켓 생산 정산금
`= {prod_cost:,} + {prod_fee:,} + {open_prod_rev:,} = {nxt_prod_today:,}`

**오픈 전체 마진** = 오픈마켓 OEM포함 매출 - 오픈마켓 OEM포함 원가 - 오픈마켓 전체 택배비
`= {open_total_rev:,} - {open_total_cost:,} - {open_total_fee:,} = {open_total_marg:,}`

**오픈 생산 마진** = 오픈마켓 생산 매출 - 오픈마켓 생산 원가 - 오픈마켓 생산 택배비
`= {open_prod_rev:,} - {open_prod_cost:,} - {open_prod_fee:,} = {open_prod_marg:,}`
""")

    # 종합 CSV (모든 항목 포함)
    full_export = [
        ('보고일자', sel),
        ('요일', weekday_kor),
        ('--- ① 일일 매출 요약 (전체) ---', ''),
        ('전체-금일 총매출', revenue(day_df, ALL_CHANNELS, BASE_SUPPLIERS)),
        ('전체-오픈마켓 총매출', revenue(day_df, OPEN_MARKETS, BASE_SUPPLIERS)),
        ('--- ① 일일 매출 요약 (생산) ---', ''),
        ('생산-금일 총매출', revenue(day_df, ALL_CHANNELS, PROD_SUPPLIERS)),
        ('생산-오픈마켓 총매출', revenue(day_df, OPEN_MARKETS, PROD_SUPPLIERS)),
        ('--- ② 월 목표 달성률 ---', ''),
        ('넥스트고 전체 금일 매출', nxt_total_today),
        ('넥스트고 전체 월 누계',   nxt_total_cum),
        ('넥스트고 생산 금일 매출', nxt_prod_today),
        ('넥스트고 생산 월 누계',   nxt_prod_cum),
        ('오픈 OEM포함 금일 매출', open_total_rev),
        ('오픈 OEM포함 월 누계',   open_total_cum),
        ('오픈 생산 금일 매출',    open_prod_rev),
        ('오픈 생산 월 누계',      open_prod_cum),
        ('--- ③ 4셀 매트릭스 ---', ''),
        ('에컴 원가',      cost(day_df, SELF_CHANNELS, BASE_SUPPLIERS)),
        ('에컴 택배건수',  box_count(day_df, SELF_CHANNELS, BASE_SUPPLIERS)),
        ('에컴 택배비',    box_count(day_df, SELF_CHANNELS, BASE_SUPPLIERS) * BOX_FEE),
        ('생산 원가',      cost(day_df, SELF_CHANNELS, PROD_SUPPLIERS)),
        ('생산 택배건수',  box_count(day_df, SELF_CHANNELS, PROD_SUPPLIERS)),
        ('생산 택배비',    box_count(day_df, SELF_CHANNELS, PROD_SUPPLIERS) * BOX_FEE),
        ('오픈전체 원가',  open_total_cost),
        ('오픈전체 택배건수', open_total_box),
        ('오픈전체 택배비',   open_total_fee),
        ('오픈생산 원가',  open_prod_cost),
        ('오픈생산 택배건수', open_prod_box),
        ('오픈생산 택배비',   open_prod_fee),
        ('--- ④ 마진 ---', ''),
        ('오픈전체 금일 마진', open_total_marg),
        ('오픈전체 월 누계 마진', cum_open_total_marg),
        ('오픈생산 금일 마진', open_prod_marg),
        ('오픈생산 월 누계 마진', cum_open_prod_marg),
    ]
    csv_text = pd.DataFrame(full_export, columns=['항목', '값']).to_csv(index=False).encode('utf-8-sig')
    dlc1, dlc2 = st.columns([1, 5])
    dlc1.download_button(f"📥 {sel} 보고서 CSV", csv_text, f"일일보고서_{sel}.csv", "text/csv")
    dlc2.caption("💡 이 페이지를 캡쳐해서 그대로 대표님께 보고하시면 됩니다 (Win+Shift+S)")


# ===== 캘린더 & 기간집계 =====
with tab_cal:
    st.subheader("📅 업로드 캘린더 & 기간 집계")

    # 기준 월 선택
    today = date.today()
    available_months = sorted(
        all_df['기준일'].dropna().apply(lambda x: x[:7]).unique(),
        reverse=True
    )
    if not available_months:
        available_months = [today.strftime('%Y-%m')]

    cm1, cm2, cm3 = st.columns([1, 2, 1])
    sel_month_str = cm2.selectbox(
        "조회 월 선택",
        sorted(set(available_months + [today.strftime('%Y-%m')]), reverse=True),
        index=0, key='cal_month'
    )
    cal_year, cal_month = map(int, sel_month_str.split('-'))

    # 데이터 있는 날짜 set
    dates_with_data = set(all_df['기준일'].dropna().tolist())

    # 월 통계
    last_day = calendar.monthrange(cal_year, cal_month)[1]
    all_month_dates = {date(cal_year, cal_month, d).strftime('%Y-%m-%d') for d in range(1, last_day + 1)}
    filled = sorted(all_month_dates & dates_with_data)
    today_str = today.strftime('%Y-%m-%d')
    missing = sorted([d for d in all_month_dates - dates_with_data if d <= today_str])
    future = sorted([d for d in all_month_dates - dates_with_data if d > today_str])

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric("📗 입력된 날짜", f"{len(filled)}일")
    kpi2.metric("📕 누락된 날짜", f"{len(missing)}일")
    kpi3.metric("⏳ 미래/예정", f"{len(future)}일")
    kpi4.metric("총 일수", f"{last_day}일")

    # ----- 캘린더 HTML 렌더링 (components.html for guaranteed display) -----
    cal_obj = calendar.Calendar(firstweekday=0)  # 월요일 시작
    weeks = cal_obj.monthdatescalendar(cal_year, cal_month)

    rows_html = ""
    for week in weeks:
        rows_html += '<tr>'
        for day in week:
            ds = day.strftime('%Y-%m-%d')
            if day.month != cal_month:
                style = "background:#fafafa;color:#bbb;"
                content = f'<div style="opacity:0.4">{day.day}</div>'
            elif ds in dates_with_data:
                style = "background:#28a745;color:#fff;"
                day_df_local = all_df[all_df['기준일'] == ds]
                day_rev = int(day_df_local[
                    day_df_local['판매처'].isin(ALL_CHANNELS) &
                    day_df_local['공급처'].isin(BASE_SUPPLIERS)
                ]['정산금액'].sum())
                content = (
                    f'<div style="font-size:16px;font-weight:700">{day.day}</div>'
                    f'<div style="font-size:11px;font-weight:500;opacity:0.95">₩{day_rev/10000:.0f}만</div>'
                )
            elif ds > today_str:
                style = "background:#f1f3f5;color:#888;"
                content = f'<div style="font-size:16px">{day.day}</div>'
            else:
                style = "background:#dc3545;color:#fff;"
                content = (
                    f'<div style="font-size:16px;font-weight:700">{day.day}</div>'
                    f'<div style="font-size:10px;opacity:0.9">누락</div>'
                )

            if ds == today_str:
                style += "box-shadow:0 0 0 3px #ffc107 inset;"

            rows_html += (
                f'<td style="padding:10px 4px;border-radius:6px;text-align:center;'
                f'vertical-align:middle;height:60px;{style}">{content}</td>'
            )
        rows_html += '</tr>'

    headers = ['월', '화', '수', '목', '금', '토', '일']
    header_html = '<tr>'
    for h in headers:
        color = "#ff7878" if h == '일' else ("#7878ff" if h == '토' else "#fff")
        header_html += (
            f'<th style="background:#333;color:{color};padding:10px;'
            f'border-radius:4px;font-size:14px;font-weight:600">{h}</th>'
        )
    header_html += '</tr>'

    full_html = f"""
    <!DOCTYPE html>
    <html><head><meta charset="utf-8">
    <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin:0; padding:8px; }}
    table {{ width:100%; border-collapse:separate; border-spacing:5px; }}
    td {{ font-weight:600; min-width:60px; }}
    </style></head>
    <body>
    <table>
    {header_html}
    {rows_html}
    </table>
    </body></html>
    """

    cal_height = 110 + len(weeks) * 72
    components.html(full_html, height=cal_height, scrolling=False)

    st.caption("🟩 입력됨 (₩만 단위 표시) · 🟥 누락 · ⬜ 예정/미래 · 🟡 오늘 (노란 테두리)")

    if missing:
        with st.expander(f"⚠️ 누락된 날짜 {len(missing)}일 보기"):
            st.write(", ".join(missing))

    st.divider()

    # ----- 기간 집계 -----
    st.markdown("### 🔢 기간 집계")

    if dates_with_data:
        dmin = min(dates_with_data)
        dmax = max(dates_with_data)
    else:
        dmin = dmax = today_str

    rcol1, rcol2, rcol3 = st.columns([2, 2, 1])
    range_from = rcol1.date_input("시작일", pd.to_datetime(dmin).date(), key='range_from')
    range_to   = rcol2.date_input("종료일", pd.to_datetime(dmax).date(), key='range_to')

    # 빠른 선택 버튼
    rcol3.write("")
    rcol3.write("")
    quick = st.radio(
        "빠른 선택",
        ["사용자 지정", "이번 달", "지난 달", "최근 7일", "최근 30일", "전체"],
        horizontal=True, label_visibility="collapsed"
    )
    if quick == "이번 달":
        range_from = today.replace(day=1)
        range_to   = today
    elif quick == "지난 달":
        first_of_this = today.replace(day=1)
        last_of_prev  = first_of_this - timedelta(days=1)
        range_from = last_of_prev.replace(day=1)
        range_to   = last_of_prev
    elif quick == "최근 7일":
        range_from = today - timedelta(days=6)
        range_to   = today
    elif quick == "최근 30일":
        range_from = today - timedelta(days=29)
        range_to   = today
    elif quick == "전체":
        range_from = pd.to_datetime(dmin).date()
        range_to   = pd.to_datetime(dmax).date()

    rf, rt = str(range_from), str(range_to)
    range_df = all_df[(all_df['기준일'] >= rf) & (all_df['기준일'] <= rt)]
    in_range_dates = sorted(range_df['기준일'].dropna().unique())
    expected_dates = pd.date_range(range_from, range_to).strftime('%Y-%m-%d').tolist()
    missing_in_range = [d for d in expected_dates if d not in in_range_dates and d <= today_str]

    st.caption(
        f"📅 {range_from} ~ {range_to} ({len(expected_dates)}일) · "
        f"입력 {len(in_range_dates)}일 · 누락 {len(missing_in_range)}일 · 전체 {len(range_df):,}건"
    )
    if missing_in_range:
        with st.expander(f"⚠️ 기간 내 누락 {len(missing_in_range)}일"):
            st.write(", ".join(missing_in_range))

    if range_df.empty:
        st.warning("선택 기간에 데이터가 없습니다")
    else:
        rows = []
        for label, ch, sp in [
            ('에컴 상품 (자사+넥+물)',       SELF_CHANNELS, BASE_SUPPLIERS),
            ('생산 상품 (자사+넥)',          SELF_CHANNELS, PROD_SUPPLIERS),
            ('오픈마켓 전체 (모든 공급처)',   OPEN_MARKETS,  None),
            ('오픈마켓 생산 (넥만)',          OPEN_MARKETS, PROD_SUPPLIERS),
            ('제조법인 단독 (오픈+넥+물)',    OPEN_MARKETS, BASE_SUPPLIERS),
            ('넥스트고 생산 전체 (자사+오픈)', ALL_CHANNELS, PROD_SUPPLIERS),
        ]:
            r = revenue(range_df, ch, sp)
            c = cost(range_df, ch, sp)
            b = box_count(range_df, ch, sp)
            fee = b * BOX_FEE
            rows.append({
                '구분': label,
                '정산금': won(r), '원가합': won(c),
                '배송건수': f"{b:,}", '택배비': won(fee),
                '마진': won(r - c - fee),
            })
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)

        # 일별 추이 + 표
        st.markdown("#### 일별 추이")
        daily = range_df.groupby('기준일').apply(
            lambda x: pd.Series({
                '총매출(넥+물)':  x[x['판매처'].isin(ALL_CHANNELS) & x['공급처'].isin(BASE_SUPPLIERS)]['정산금액'].sum(),
                '오픈매출(넥+물)': x[x['판매처'].isin(OPEN_MARKETS) & x['공급처'].isin(BASE_SUPPLIERS)]['정산금액'].sum(),
                '넥스트고생산':    x[x['판매처'].isin(ALL_CHANNELS) & x['공급처'].isin(PROD_SUPPLIERS)]['정산금액'].sum(),
                '배송건수':       x['송장번호'].dropna().nunique(),
            }), include_groups=False).reset_index()
        st.line_chart(daily.set_index('기준일')[['총매출(넥+물)', '오픈매출(넥+물)', '넥스트고생산']])

        with st.expander("📋 일별 상세표"):
            daily_fmt = daily.copy()
            for c in ['총매출(넥+물)', '오픈매출(넥+물)', '넥스트고생산']:
                daily_fmt[c] = daily_fmt[c].apply(lambda x: f"{int(x):,}")
            daily_fmt['배송건수'] = daily_fmt['배송건수'].apply(lambda x: f"{int(x):,}")
            st.dataframe(daily_fmt, width='stretch', hide_index=True)

        csv = pd.DataFrame(rows).to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            f"📥 {range_from}~{range_to} 집계 CSV",
            csv, f"기간집계_{range_from}_{range_to}.csv", "text/csv"
        )


# ===== 탭2: 월별 합계 =====
with tab2:
    st.subheader("📆 월별 합계")
    all_df['월'] = pd.to_datetime(all_df['기준일'], errors='coerce').dt.strftime('%Y-%m')
    months = sorted(all_df['월'].dropna().unique(), reverse=True)
    if not months:
        st.warning("데이터 없음")
    else:
        sel_m = st.selectbox("월 선택", months, index=0)
        mdf = all_df[all_df['월'] == sel_m]
        st.caption(f"포함 일자: {mdf['기준일'].nunique()}일 / 행수 {len(mdf):,}")

        rows = []
        for label, ch, sp in [
            ('에컴 상품 (자사+넥+물)',       SELF_CHANNELS, BASE_SUPPLIERS),
            ('생산 상품 (자사+넥)',          SELF_CHANNELS, PROD_SUPPLIERS),
            ('전체 (오픈마켓 전체)',         OPEN_MARKETS,  None),
            ('생산 (오픈마켓+넥)',           OPEN_MARKETS,  PROD_SUPPLIERS),
            ('제조법인 단독 (오픈+넥+물)',    OPEN_MARKETS, BASE_SUPPLIERS),
            ('넥스트고 생산 전체 (자사+오픈)', ALL_CHANNELS, PROD_SUPPLIERS),
        ]:
            r = revenue(mdf, ch, sp)
            c = cost(mdf, ch, sp)
            b = box_count(mdf, ch, sp)
            fee = b * BOX_FEE
            rows.append({
                '구분': label,
                '정산금': won(r), '원가합': won(c),
                '배송건수': f"{b:,}", '택배비': won(fee),
                '마진': won(r - c - fee),
            })
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)

        # 일별 추이
        st.markdown("#### 일별 정산금 추이")
        daily = mdf.groupby('기준일').apply(
            lambda x: pd.Series({
                '전체매출_넥물':  x[x['판매처'].isin(ALL_CHANNELS) & x['공급처'].isin(BASE_SUPPLIERS)]['정산금액'].sum(),
                '오픈마켓_넥물':  x[x['판매처'].isin(OPEN_MARKETS) & x['공급처'].isin(BASE_SUPPLIERS)]['정산금액'].sum(),
                '넥스트고생산':    x[x['판매처'].isin(ALL_CHANNELS) & x['공급처'].isin(PROD_SUPPLIERS)]['정산금액'].sum(),
            }), include_groups=False).reset_index()
        st.line_chart(daily.set_index('기준일'))


# ===== 탭3: 누적 전체 =====
with tab3:
    st.subheader("💾 누적 전체 데이터")
    if all_df.empty:
        st.info("아직 누적된 데이터가 없습니다")
        date_range_str = "—"
    else:
        date_range_str = f"{all_df['기준일'].min()} ~ {all_df['기준일'].max()}"
    st.caption(f"전체 {len(all_df):,}건 / {date_range_str}")

    rows = []
    for label, ch, sp in [
        ('에컴 상품',                 SELF_CHANNELS, BASE_SUPPLIERS),
        ('생산 상품',                 SELF_CHANNELS, PROD_SUPPLIERS),
        ('오픈마켓 전체',              OPEN_MARKETS, None),
        ('오픈마켓 생산',              OPEN_MARKETS, PROD_SUPPLIERS),
        ('제조법인 단독 (오픈+넥+물)', OPEN_MARKETS, BASE_SUPPLIERS),
        ('넥스트고 생산 전체',         ALL_CHANNELS, PROD_SUPPLIERS),
    ]:
        r = revenue(all_df, ch, sp)
        c = cost(all_df, ch, sp)
        b = box_count(all_df, ch, sp)
        fee = b * BOX_FEE
        rows.append({
            '구분': label,
            '정산금': won(r), '원가합': won(c),
            '배송건수': f"{b:,}", '택배비': won(fee),
            '마진': won(r - c - fee),
        })
    st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)


# ===== 탭4: 업로드 이력 =====
with tab4:
    st.subheader("📜 업로드 이력")
    uploads = load_uploads()
    if uploads.empty:
        st.info("기록 없음")
    else:
        st.dataframe(uploads, width='stretch', hide_index=True)
        with st.expander("🗑️ 특정 업로드 삭제"):
            opts = uploads.apply(
                lambda r: f"{r['업로드일시']} | 기준일 {r['기준일']} | {r['파일명']} ({r['신규행수']}건)",
                axis=1).tolist()
            target = st.selectbox("삭제할 업로드", opts)
            if st.button("선택한 업로드 삭제"):
                dt = target.split(' | ')[0]
                n = delete_batch(dt)
                st.success(f"✅ {n}건 삭제")
                st.rerun()
