"""
台股當日大盤走勢 & 近90日K線技術分析 — 純證交所官方即時版 (pages/)
(Streamlit + TWSE/TPEx OpenAPI + yfinance + Plotly)
放置方式:
    將此檔案放入專案的 pages/ 資料夾（例如 pages/4_當日大盤走勢.py）
執行方式:
    pip install streamlit requests yfinance plotly pandas
    streamlit run taiex_intraday_app-v19.py
"""

import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import streamlit as st
import yfinance as yf

# ==========================================
# 頁面基本設定（獨立 page 模式）
# ==========================================
st.set_page_config(
    page_title="當日大盤與K線走勢",
    page_icon="📈",
    layout="wide",
)

# 台股慣用配色：紅漲綠跌
COLOR_UP = "#E53935"      # 紅色（上漲 / 買超 / 融資增）
COLOR_DOWN = "#00897B"    # 綠色（下跌 / 賣超 / 融資減）
COLOR_FLAT = "#757575"    # 灰色（平盤）
COLOR_WARN = "#FFB300"    # 琥珀黃（維持率警戒）

TZ_TAIPEI = ZoneInfo("Asia/Taipei")

st.markdown(
    """
    <style>
    .section-title {
        font-size: 1.08rem;
        font-weight: 700;
        color: #FAFAFA;
        margin: 6px 0 8px 0;
        line-height: 1.35;
    }
    .metric-card {
        background-color: #1E222D;
        border-radius: 10px;
        padding: 14px 18px;
        border-left: 5px solid #757575;
        margin-bottom: 10px;
    }
    .metric-label {
        font-size: 0.9rem;
        color: #9E9E9E;
        margin-bottom: 4px;
    }
    .metric-value {
        font-size: 1.65rem;
        font-weight: 700;
        color: #FFFFFF;
    }
    .metric-delta {
        font-size: 0.95rem;
        font-weight: 600;
        margin-top: 4px;
    }
    .mini-card {
        background-color: #1E222D;
        border-radius: 8px;
        padding: 10px 14px;
        border-left: 4px solid #757575;
        margin-bottom: 10px;
    }
    .mini-label {
        font-size: 0.82rem;
        color: #9E9E9E;
        margin-bottom: 2px;
    }
    .mini-value {
        font-size: 1.35rem;
        font-weight: 700;
        color: #FFFFFF;
    }
    .mini-delta {
        font-size: 0.85rem;
        font-weight: 600;
        margin-top: 2px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# 預設標的清單（台灣加權指數 + 指定 ETF 清單）
INDEX_OPTIONS = {
    "台灣加權指數 (證交所官方 TAIEX)": {"ticker": "^TWII", "tz": "Asia/Taipei", "use_twse": True},
    "0050 (元大台灣50)": {"ticker": "0050.TW", "tz": "Asia/Taipei", "use_twse": False},
    "009816": {"ticker": "009816.TW", "tz": "Asia/Taipei", "use_twse": False},
    "0056 (元大高股息)": {"ticker": "0056.TW", "tz": "Asia/Taipei", "use_twse": False},
    "00878 (國泰永續高股息)": {"ticker": "00878.TW", "tz": "Asia/Taipei", "use_twse": False},
    "00919 (群益台灣精選高息)": {"ticker": "00919.TW", "tz": "Asia/Taipei", "use_twse": False},
    "00981A": {"ticker": "00981A.TW", "tz": "Asia/Taipei", "use_twse": False},
    "00400A": {"ticker": "00400A.TW", "tz": "Asia/Taipei", "use_twse": False},
}

# 離線/API 異常時的基本備援清單
FALLBACK_TW_STOCKS = [
    {"code": "2330", "name": "台積電", "ticker": "2330.TW", "market": "上市"},
    {"code": "2317", "name": "鴻海", "ticker": "2317.TW", "market": "上市"},
    {"code": "2454", "name": "聯發科", "ticker": "2454.TW", "market": "上市"},
    {"code": "2308", "name": "台達電", "ticker": "2308.TW", "market": "上市"},
    {"code": "2382", "name": "廣達", "ticker": "2382.TW", "market": "上市"},
    {"code": "2881", "name": "富邦金", "ticker": "2881.TW", "market": "上市"},
    {"code": "2882", "name": "國泰金", "ticker": "2882.TW", "market": "上市"},
    {"code": "3711", "name": "日月光投控", "ticker": "3711.TW", "market": "上市"},
    {"code": "0050", "name": "元大台灣50", "ticker": "0050.TW", "market": "上市"},
    {"code": "0056", "name": "元大高股息", "ticker": "0056.TW", "market": "上市"},
    {"code": "00878", "name": "國泰永續高股息", "ticker": "00878.TW", "market": "上市"},
    {"code": "00919", "name": "群益台灣精選高息", "ticker": "00919.TW", "market": "上市"},
    {"code": "009816", "name": "009816", "ticker": "009816.TW", "market": "上市"},
    {"code": "00981A", "name": "00981A", "ticker": "00981A.TW", "market": "上市"},
    {"code": "00400A", "name": "00400A", "ticker": "00400A.TW", "market": "上市"},
]

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://www.twse.com.tw/",
}


def _to_float(val):
    if val is None:
        return None
    s = str(val).replace(",", "").replace("%", "").strip()
    if s in ("", "-", "--", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ==========================================
# 證交所 (TWSE) 大盤融資維持率（含 ETF / 全上市）官方實數計算
# ==========================================
@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_twse_close_prices_day(date_str: str) -> dict:
    """
    從證交所每日收盤行情 (MI_INDEX, type=ALLBUT0999) 抓取指定日期全上市個股與 ETF 價格，
    若當日無成交（收盤價為 --），依序以「最後揭示買價 / 最後揭示賣價」補值，回傳 {code: price}。
    """
    url = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
    try:
        resp = requests.get(
            url,
            params={"response": "json", "date": date_str, "type": "ALLBUT0999"},
            headers=HTTP_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("stat") != "OK" or not data.get("tables"):
            return {}

        price_map = {}
        for tbl in data["tables"]:
            fields = [str(f).strip() for f in tbl.get("fields", [])]
            if "證券代號" in fields and "收盤價" in fields and tbl.get("data"):
                idx_code = fields.index("證券代號")
                idx_close = fields.index("收盤價")
                idx_bid = fields.index("最後揭示買價") if "最後揭示買價" in fields else None
                idx_ask = fields.index("最後揭示賣價") if "最後揭示賣價" in fields else None
                for row in tbl["data"]:
                    if len(row) <= max(idx_code, idx_close):
                        continue
                    code = str(row[idx_code]).strip().upper()
                    p = _to_float(row[idx_close])
                    if (p is None or p <= 0) and idx_bid is not None and idx_bid < len(row):
                        p = _to_float(row[idx_bid])
                    if (p is None or p <= 0) and idx_ask is not None and idx_ask < len(row):
                        p = _to_float(row[idx_ask])
                    if code and p and p > 0:
                        price_map[code] = p
                if price_map:
                    break
        return price_map
    except Exception:
        return {}


def _calc_twse_incl_etf_ratio(
    total_margin_loan_yi: float,
    stocks_margin: dict,
    close_prices: dict,
    last_valid_prices: dict,
) -> float | None:
    """
    以證交所官方實數計算「含 ETF（全上市）」大盤融資維持率：
      (全上市融資餘額市值 ÷ 證交所大盤總融資餘額金額) × 100%
    並以 last_valid_prices 承接前日有效收盤價，避免無成交個股漏算分子市值。
    """
    if not total_margin_loan_yi or total_margin_loan_yi <= 0 or not stocks_margin:
        return None

    for code, p in close_prices.items():
        if p and p > 0:
            last_valid_prices[code] = p

    total_loan_ntd = total_margin_loan_yi * 1e8
    mv_all = 0.0
    for code, info in stocks_margin.items():
        lots = info.get("融資餘額", 0.0)
        if not lots or lots <= 0:
            continue
        p = close_prices.get(code) or last_valid_prices.get(code)
        if not p or p <= 0:
            continue
        mv_all += lots * 1000.0 * p

    if mv_all <= 0:
        return None
    return round((mv_all / total_loan_ntd) * 100.0, 2)


# ==========================================
# 台股上市 + 上櫃 中文名稱 / 代碼對照表 (快取 24 小時)
# ==========================================
@st.cache_data(ttl=86400, show_spinner=False)
def load_tw_stock_directory() -> list[dict]:
    """
    從證交所 (TWSE) 與櫃買中心 (TPEx) OpenAPI 抓取全台股上市/上櫃股票與 ETF 清單，
    建立「代碼 ↔ 中文簡稱」對照表，供中文名稱模糊搜尋與自動判定 .TW / .TWO。
    """
    directory = {}

    twse_urls = [
        "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
        "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_AVG_ALL",
    ]
    for url in twse_urls:
        try:
            resp = requests.get(url, headers=HTTP_HEADERS, timeout=6)
            resp.raise_for_status()
            rows = resp.json()
            if isinstance(rows, list) and rows:
                for row in rows:
                    code = str(row.get("Code", "")).strip().upper()
                    name = str(row.get("Name", "")).strip()
                    if code and name:
                        directory[code] = {
                            "code": code,
                            "name": name,
                            "ticker": f"{code}.TW",
                            "market": "上市",
                        }
                if directory:
                    break
        except Exception:
            continue

    tpex_urls = [
        "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes",
        "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
    ]
    for url in tpex_urls:
        try:
            resp = requests.get(url, headers=HTTP_HEADERS, timeout=6)
            resp.raise_for_status()
            rows = resp.json()
            if isinstance(rows, list) and rows:
                added_otc = False
                for row in rows:
                    code = str(
                        row.get("SecuritiesCompanyCode")
                        or row.get("公司代號")
                        or ""
                    ).strip().upper()
                    name = str(
                        row.get("CompanyName")
                        or row.get("公司簡稱")
                        or ""
                    ).strip()
                    if code and name and code not in directory:
                        directory[code] = {
                            "code": code,
                            "name": name,
                            "ticker": f"{code}.TWO",
                            "market": "上櫃",
                        }
                        added_otc = True
                if added_otc:
                    break
        except Exception:
            continue

    for item in FALLBACK_TW_STOCKS:
        if item["code"] not in directory:
            directory[item["code"]] = item

    return list(directory.values())


def resolve_custom_query(query: str, directory: list[dict]):
    """解析使用者輸入的自訂查詢（支援中文名稱、台股代碼、完整 .TW/.TWO、美股代碼、大盤別名）"""
    q = query.strip()
    q_upper = q.upper()

    if q in ("大盤", "加權", "加權指數", "台灣加權指數", "台股") or q_upper in ("^TWII", "TAIEX"):
        return "single", {
            "ticker": "^TWII",
            "display_name": "台灣加權指數 (證交所官方 TAIEX)",
            "tz": "Asia/Taipei",
            "use_twse": True,
        }
    if q in ("櫃買", "櫃買指數", "台灣櫃買指數") or q_upper == "^TWOII":
        return "single", {
            "ticker": "^TWOII",
            "display_name": "台灣櫃買指數 (^TWOII)",
            "tz": "Asia/Taipei",
            "use_twse": False,
        }

    by_code = {item["code"]: item for item in directory}

    if q_upper.endswith((".TW", ".TWO")):
        base_code = q_upper.rsplit(".", 1)[0]
        if base_code in by_code:
            item = by_code[base_code]
            return "single", {
                "ticker": q_upper,
                "display_name": f"{item['name']} ({q_upper})",
                "tz": "Asia/Taipei",
                "use_twse": False,
            }
        return "single", {
            "ticker": q_upper,
            "display_name": q_upper,
            "tz": "Asia/Taipei",
            "use_twse": False,
        }

    if q_upper in by_code:
        item = by_code[q_upper]
        return "single", {
            "ticker": item["ticker"],
            "display_name": f"{item['name']} ({item['ticker']})",
            "tz": "Asia/Taipei",
            "use_twse": False,
        }

    if q_upper.startswith("^") or re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", q_upper):
        return "single", {
            "ticker": q_upper,
            "display_name": q_upper,
            "tz": "America/New_York",
            "use_twse": False,
        }

    if re.fullmatch(r"\d{4,6}[A-Z]?", q_upper):
        tw_ticker = f"{q_upper}.TW"
        return "single", {
            "ticker": tw_ticker,
            "display_name": tw_ticker,
            "tz": "Asia/Taipei",
            "use_twse": False,
        }

    exact_matches = [item for item in directory if item["name"] == q]
    if len(exact_matches) == 1:
        item = exact_matches[0]
        return "single", {
            "ticker": item["ticker"],
            "display_name": f"{item['name']} ({item['ticker']})",
            "tz": "Asia/Taipei",
            "use_twse": False,
        }

    partial_matches = [
        item for item in directory
        if (q in item["name"]) or (q_upper in item["code"])
    ]
    if not partial_matches:
        return "not_found", q

    partial_matches.sort(
        key=lambda x: (
            0 if x["name"].startswith(q) else 1,
            len(x["name"]),
            x["code"],
        )
    )

    if len(partial_matches) == 1:
        item = partial_matches[0]
        return "single", {
            "ticker": item["ticker"],
            "display_name": f"{item['name']} ({item['ticker']})",
            "tz": "Asia/Taipei",
            "use_twse": False,
        }

    return "multiple", partial_matches[:30]


# ==========================================
# 近 5 日三大法人買賣超 & 融資券變化（TWSE / TPEx 官方 API）
# ==========================================
def _recent_weekday_dates(max_days: int = 16) -> list:
    """產生最近 N 個非週末日期（由近到遠）"""
    today = datetime.now(TZ_TAIPEI).date()
    dates = []
    for offset in range(max_days):
        d = today - timedelta(days=offset)
        if d.weekday() < 5:
            dates.append(d)
    return dates


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_twse_bfi82u_day(date_str: str):
    """抓取證交所大盤三大法人買賣金額統計表 (BFI82U)，單位：億元"""
    url = "https://www.twse.com.tw/rwd/zh/fund/BFI82U"
    try:
        resp = requests.get(
            url,
            params={"response": "json", "dayDate": date_str, "type": "day"},
            headers=HTTP_HEADERS,
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("stat") != "OK" or not data.get("data"):
            return None

        foreign = 0.0
        trust = 0.0
        dealer = 0.0
        total = None

        for row in data["data"]:
            if len(row) < 4:
                continue
            label = str(row[0]).strip()
            net = _to_float(row[3])
            if net is None:
                continue
            net_yi = net / 1e8
            if "合計" in label:
                total = net_yi
            elif "外資" in label:
                foreign += net_yi
            elif "投信" in label:
                trust += net_yi
            elif "自營商" in label:
                dealer += net_yi

        if total is None:
            total = foreign + trust + dealer

        return {
            "外資": round(foreign, 2),
            "投信": round(trust, 2),
            "自營商": round(dealer, 2),
            "合計": round(total, 2),
        }
    except Exception:
        return None


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_twse_t86_day(date_str: str) -> dict:
    """抓取證交所指定日期全上市個股/ETF 三大法人買賣超 (T86)，單位：張"""
    url = "https://www.twse.com.tw/rwd/zh/fund/T86"
    try:
        resp = requests.get(
            url,
            params={"response": "json", "date": date_str, "selectType": "ALLBUT0999"},
            headers=HTTP_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("stat") != "OK" or not data.get("data"):
            return {}

        fields = [str(f).strip() for f in data.get("fields", [])]

        def find_idx(include_terms, exclude_terms=()):
            for i, f in enumerate(fields):
                if all(t in f for t in include_terms) and not any(e in f for e in exclude_terms):
                    return i
            return None

        idx_code = 0
        idx_f1 = find_idx(("外陸資", "買賣超"), ("自營商",))
        idx_f2 = find_idx(("外資自營商", "買賣超"))
        idx_trust = find_idx(("投信", "買賣超"))
        idx_dealer = find_idx(("自營商", "買賣超"), ("外資", "自行買賣", "避險"))
        idx_total = find_idx(("三大法人", "買賣超"))

        result = {}
        for row in data["data"]:
            if len(row) <= idx_code:
                continue
            code = str(row[idx_code]).strip().upper()
            f_val = (_to_float(row[idx_f1]) or 0.0) if idx_f1 is not None and idx_f1 < len(row) else 0.0
            f2_val = (_to_float(row[idx_f2]) or 0.0) if idx_f2 is not None and idx_f2 < len(row) else 0.0
            t_val = (_to_float(row[idx_trust]) or 0.0) if idx_trust is not None and idx_trust < len(row) else 0.0
            d_val = (_to_float(row[idx_dealer]) or 0.0) if idx_dealer is not None and idx_dealer < len(row) else 0.0
            tot_val = (
                (_to_float(row[idx_total]) or 0.0)
                if idx_total is not None and idx_total < len(row)
                else (f_val + f2_val + t_val + d_val)
            )
            result[code] = {
                "外資": round((f_val + f2_val) / 1000.0, 1),
                "投信": round(t_val / 1000.0, 1),
                "自營商": round(d_val / 1000.0, 1),
                "合計": round(tot_val / 1000.0, 1),
            }
        return result
    except Exception:
        return {}


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_twse_margin_day(date_str: str):
    """抓取證交所指定日期信用交易統計 (MI_MARGN, selectType=ALL)"""
    url = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
    try:
        resp = requests.get(
            url,
            params={"response": "json", "date": date_str, "selectType": "ALL"},
            headers=HTTP_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("stat") != "OK" or not data.get("tables"):
            return None

        tables = data["tables"]
        market_info = None
        stocks_info = {}

        if len(tables) >= 1 and tables[0].get("data"):
            m_amt_prev = m_amt_curr = None
            s_prev = s_curr = None
            for row in tables[0]["data"]:
                if len(row) < 6:
                    continue
                item_name = str(row[0]).strip()
                prev_v = _to_float(row[4])
                curr_v = _to_float(row[5])
                if prev_v is None or curr_v is None:
                    continue
                if "融資金額" in item_name:
                    m_amt_prev = prev_v / 100_000.0
                    m_amt_curr = curr_v / 100_000.0
                elif "融券" in item_name:
                    s_prev = prev_v
                    s_curr = curr_v

            if m_amt_curr is not None and s_curr is not None:
                market_info = {
                    "融資增減": round(m_amt_curr - m_amt_prev, 2),
                    "融資餘額": round(m_amt_curr, 2),
                    "融券增減": round(s_curr - s_prev, 0),
                    "融券餘額": round(s_curr, 0),
                }

        if len(tables) >= 2 and tables[1].get("data"):
            fields = [str(f).strip() for f in tables[1].get("fields", [])]
            prev_indices = [i for i, f in enumerate(fields) if "前日餘額" in f]
            curr_indices = [i for i, f in enumerate(fields) if "今日餘額" in f]

            idx_m_prev = prev_indices[0] if len(prev_indices) >= 1 else 5
            idx_m_curr = curr_indices[0] if len(curr_indices) >= 1 else 6
            idx_s_prev = prev_indices[1] if len(prev_indices) >= 2 else 11
            idx_s_curr = curr_indices[1] if len(curr_indices) >= 2 else 12

            for row in tables[1]["data"]:
                if len(row) <= idx_s_curr:
                    continue
                code = str(row[0]).strip().upper()
                mp = _to_float(row[idx_m_prev])
                mc = _to_float(row[idx_m_curr])
                sp = _to_float(row[idx_s_prev])
                sc = _to_float(row[idx_s_curr])
                if None in (mp, mc, sp, sc):
                    continue
                stocks_info[code] = {
                    "融資增減": round(mc - mp, 0),
                    "融資餘額": round(mc, 0),
                    "融券增減": round(sc - sp, 0),
                    "融券餘額": round(sc, 0),
                }

        if market_info is None and not stocks_info:
            return None
        return {"market": market_info, "stocks": stocks_info}
    except Exception:
        return None


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_tpex_inst_day(date_fmt: str) -> dict:
    """抓取櫃買中心指定日期全上櫃個股/ETF 三大法人買賣超，單位：張"""
    dt = datetime.strptime(date_fmt, "%Y-%m-%d")
    roc_date = f"{dt.year - 1911}/{dt.month:02d}/{dt.day:02d}"
    west_date = dt.strftime("%Y/%m/%d")

    candidates = [
        (
            "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade",
            {"type": "Daily", "sect": "EW", "date": west_date, "response": "json"},
        ),
        (
            "https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php",
            {"l": "zh-tw", "o": "json", "se": "EW", "t": "D", "d": roc_date},
        ),
    ]

    for url, params in candidates:
        try:
            resp = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            rows = None
            fields = []
            if isinstance(data.get("tables"), list) and data["tables"]:
                rows = data["tables"][0].get("data")
                fields = [str(f).strip() for f in data["tables"][0].get("fields", [])]
            elif data.get("aaData"):
                rows = data["aaData"]

            if not rows:
                continue

            idx_f, idx_t, idx_d, idx_tot = 10, 13, 22, 23
            if fields:
                for i, f in enumerate(fields):
                    if "外資及陸資" in f and "買賣超" in f and "不含" not in f:
                        idx_f = i
                    elif "投信" in f and "買賣超" in f:
                        idx_t = i
                    elif "自營商" in f and "買賣超" in f and "自行" not in f and "避險" not in f and "外資" not in f:
                        idx_d = i
                    elif "三大法人" in f and "買賣超" in f:
                        idx_tot = i

            result = {}
            for row in rows:
                if len(row) <= max(idx_f, idx_t, idx_d):
                    continue
                code = str(row[0]).strip().upper()
                f_val = _to_float(row[idx_f]) or 0.0
                t_val = _to_float(row[idx_t]) or 0.0
                d_val = _to_float(row[idx_d]) or 0.0
                tot_val = (
                    (_to_float(row[idx_tot]) or 0.0)
                    if idx_tot < len(row)
                    else (f_val + t_val + d_val)
                )
                result[code] = {
                    "外資": round(f_val / 1000.0, 1),
                    "投信": round(t_val / 1000.0, 1),
                    "自營商": round(d_val / 1000.0, 1),
                    "合計": round(tot_val / 1000.0, 1),
                }
            if result:
                return result
        except Exception:
            continue

    return {}


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_tpex_margin_day(date_fmt: str) -> dict:
    """抓取櫃買中心指定日期全上櫃個股/ETF 融資融券餘額，單位：張"""
    dt = datetime.strptime(date_fmt, "%Y-%m-%d")
    roc_date = f"{dt.year - 1911}/{dt.month:02d}/{dt.day:02d}"
    west_date = dt.strftime("%Y/%m/%d")

    candidates = [
        (
            "https://www.tpex.org.tw/www/zh-tw/margin/balance",
            {"date": west_date, "response": "json"},
        ),
        (
            "https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/margin_bal_result.php",
            {"l": "zh-tw", "o": "json", "d": roc_date},
        ),
    ]

    for url, params in candidates:
        try:
            resp = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            rows = None
            fields = []
            if isinstance(data.get("tables"), list) and data["tables"]:
                rows = data["tables"][0].get("data")
                fields = [str(f).strip() for f in data["tables"][0].get("fields", [])]
            elif data.get("aaData"):
                rows = data["aaData"]

            if not rows:
                continue

            idx_mp, idx_mc, idx_sp, idx_sc = 2, 6, 10, 14
            if fields:
                for i, f in enumerate(fields):
                    if "前資餘額" in f:
                        idx_mp = i
                    elif f == "資餘額" or ("資餘額" in f and "前" not in f and "限" not in f):
                        idx_mc = i
                    elif "前券餘額" in f:
                        idx_sp = i
                    elif f == "券餘額" or ("券餘額" in f and "前" not in f and "限" not in f):
                        idx_sc = i

            result = {}
            for row in rows:
                if len(row) <= max(idx_mp, idx_mc, idx_sp, idx_sc):
                    continue
                code = str(row[0]).strip().upper()
                mp = _to_float(row[idx_mp])
                mc = _to_float(row[idx_mc])
                sp = _to_float(row[idx_sp])
                sc = _to_float(row[idx_sc])
                if None in (mp, mc, sp, sc):
                    continue
                result[code] = {
                    "融資增減": round(mc - mp, 0),
                    "融資餘額": round(mc, 0),
                    "融券增減": round(sc - sp, 0),
                    "融券餘額": round(sc, 0),
                }
            if result:
                return result
        except Exception:
            continue

    return {}


def fetch_recent_5d_chips(ticker: str, use_twse: bool, days: int = 5):
    """
    取得近 5 個交易日的「三大法人買賣超」與「融資券變化」：
      - 台灣加權指數 (^TWII)：三大法人、融資券與含 ETF 大盤融資維持率皆來自證交所官方即時 API。
      - 上市/上櫃個股與 ETF (.TW / .TWO)：三大法人與融資券單位皆為「張」。
    """
    is_taiex = use_twse or ticker == "^TWII"
    is_twse_stock = ticker.endswith(".TW")
    is_tpex_stock = ticker.endswith(".TWO")

    if not (is_taiex or is_twse_stock or is_tpex_stock):
        return pd.DataFrame(), pd.DataFrame(), None

    weekdays = _recent_weekday_dates(max_days=16)
    inst_records = []
    margin_records = []

    if is_taiex:
        # 多抓 1 個交易日 (days + 1) 供計算近 5 日維持率「較前日增減」與補齊無成交個股收盤價
        raw_margin_days = []
        for d in weekdays:
            if len(inst_records) >= days and len(raw_margin_days) >= days + 1:
                break
            d_compact = d.strftime("%Y%m%d")
            d_label = d.strftime("%m/%d")
            d_full = d.strftime("%Y-%m-%d")

            if len(inst_records) < days:
                res_inst = _fetch_twse_bfi82u_day(d_compact)
                if res_inst:
                    inst_records.append({"日期": d_label, "完整日期": d_full, **res_inst})

            if len(raw_margin_days) < days + 1:
                res_m = _fetch_twse_margin_day(d_compact)
                if res_m and res_m.get("market"):
                    raw_margin_days.append(
                        {
                            "d_compact": d_compact,
                            "d_label": d_label,
                            "d_full": d_full,
                            "market": dict(res_m["market"]),
                            "stocks": res_m.get("stocks", {}),
                        }
                    )

        # 由舊到新計算每日「含ETF維持率（證交所官方實數）」
        raw_margin_days.sort(key=lambda x: x["d_full"])
        last_valid_prices = {}
        maint_records = []

        for item in raw_margin_days:
            d_full = item["d_full"]
            close_map = _fetch_twse_close_prices_day(item["d_compact"])
            r_incl = _calc_twse_incl_etf_ratio(
                total_margin_loan_yi=item["market"]["融資餘額"],
                stocks_margin=item["stocks"],
                close_prices=close_map,
                last_valid_prices=last_valid_prices,
            )
            maint_records.append(
                {
                    "完整日期": d_full,
                    "含ETF維持率": r_incl,
                }
            )

        # 計算「較前日」增減，並擷取最近 5 個交易日
        df_maint_all = pd.DataFrame(maint_records)
        if not df_maint_all.empty:
            df_maint_all["較前日"] = df_maint_all["含ETF維持率"].diff().round(2)
            df_maint = df_maint_all.tail(days).reset_index(drop=True)
        else:
            df_maint = pd.DataFrame()

        for item in raw_margin_days[-days:]:
            margin_records.append(
                {
                    "日期": item["d_label"],
                    "完整日期": item["d_full"],
                    **item["market"],
                }
            )

        meta = {
            "inst_unit": "億元",
            "margin_unit": "億元",
            "short_unit": "張",
            "is_market": True,
            "df_maint": df_maint,
        }

    elif is_twse_stock:
        code = ticker.rsplit(".", 1)[0]
        for d in weekdays:
            if len(inst_records) >= days and len(margin_records) >= days:
                break
            d_compact = d.strftime("%Y%m%d")
            d_label = d.strftime("%m/%d")
            d_full = d.strftime("%Y-%m-%d")

            if len(inst_records) < days:
                day_map = _fetch_twse_t86_day(d_compact)
                if day_map:
                    row = day_map.get(code, {"外資": 0.0, "投信": 0.0, "自營商": 0.0, "合計": 0.0})
                    inst_records.append({"日期": d_label, "完整日期": d_full, **row})

            if len(margin_records) < days:
                res_m = _fetch_twse_margin_day(d_compact)
                if res_m and res_m.get("stocks") and code in res_m["stocks"]:
                    margin_records.append({"日期": d_label, "完整日期": d_full, **res_m["stocks"][code]})

        meta = {
            "inst_unit": "張",
            "margin_unit": "張",
            "short_unit": "張",
            "is_market": False,
        }

    else:  # is_tpex_stock (.TWO)
        code = ticker.rsplit(".", 1)[0]
        for d in weekdays:
            if len(inst_records) >= days and len(margin_records) >= days:
                break
            d_label = d.strftime("%m/%d")
            d_full = d.strftime("%Y-%m-%d")

            if len(inst_records) < days:
                day_map = _fetch_tpex_inst_day(d_full)
                if day_map:
                    row = day_map.get(code, {"外資": 0.0, "投信": 0.0, "自營商": 0.0, "合計": 0.0})
                    inst_records.append({"日期": d_label, "完整日期": d_full, **row})

            if len(margin_records) < days:
                day_m = _fetch_tpex_margin_day(d_full)
                if day_m and code in day_m:
                    margin_records.append({"日期": d_label, "完整日期": d_full, **day_m[code]})

        meta = {
            "inst_unit": "張",
            "margin_unit": "張",
            "short_unit": "張",
            "is_market": False,
        }

    df_inst = pd.DataFrame(inst_records).sort_values("完整日期").reset_index(drop=True) if inst_records else pd.DataFrame()
    df_margin = pd.DataFrame(margin_records).sort_values("完整日期").reset_index(drop=True) if margin_records else pd.DataFrame()
    return df_inst, df_margin, meta


# ==========================================
# 證交所 (TWSE) 官方資料抓取（當日分時用）
# ==========================================
@st.cache_data(ttl=15, show_spinner=False)
def fetch_twse_realtime_quote():
    """從證交所即時盤中系統 (mis.twse.com.tw) 取得加權指數最新即時/收盤報價"""
    try:
        session = requests.Session()
        session.headers.update(HTTP_HEADERS)
        session.get("https://mis.twse.com.tw/stock/index.jsp", timeout=5)
        url = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
        params = {
            "ex_ch": "tse_t00.tw",
            "json": "1",
            "delay": "0",
            "_": int(time.time() * 1000),
        }
        resp = session.get(url, params=params, timeout=8)
        resp.raise_for_status()
        payload = resp.json()
        msg_array = payload.get("msgArray", [])
        if not msg_array:
            return None

        item = msg_array[0]
        raw_date = str(item.get("d", "")).strip()
        raw_time = str(item.get("t", "")).strip()
        price = _to_float(item.get("z"))
        prev_close = _to_float(item.get("y"))
        open_p = _to_float(item.get("o"))
        high_p = _to_float(item.get("h"))
        low_p = _to_float(item.get("l"))

        if not raw_date or price is None:
            return None

        trade_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
        return {
            "date": trade_date,
            "date_compact": raw_date,
            "time": raw_time or "13:30:00",
            "price": price,
            "prev_close": prev_close,
            "open": open_p,
            "high": high_p,
            "low": low_p,
        }
    except Exception:
        return None


@st.cache_data(ttl=60, show_spinner=False)
def fetch_twse_5sec_turnover(trade_date_fmt: str) -> pd.Series:
    """從證交所官方 MI_5MINS 抓取每 5 秒區間成交金額（億元）"""
    date_str = trade_date_fmt.replace("-", "")
    endpoints = [
        "https://www.twse.com.tw/rwd/zh/afterTrading/MI_5MINS",
        "https://www.twse.com.tw/exchangeReport/MI_5MINS",
    ]

    for url in endpoints:
        try:
            resp = requests.get(
                url,
                params={"response": "json", "date": date_str},
                headers=HTTP_HEADERS,
                timeout=8,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("stat") != "OK" or not data.get("data"):
                continue

            fields = data.get("fields", [])
            amt_idx = 7
            for i, col_name in enumerate(fields):
                if "成交金額" in str(col_name):
                    amt_idx = i
                    break

            records = []
            for row in data["data"]:
                if len(row) <= amt_idx:
                    continue
                t_str = str(row[0]).strip()
                if t_str == "09:00:00":
                    continue
                val = _to_float(row[amt_idx])
                if val is None:
                    continue
                dt = pd.Timestamp(f"{trade_date_fmt} {t_str}", tz="Asia/Taipei")
                records.append({"Datetime": dt, "CumAmt": val})

            if not records:
                continue

            s_cum = pd.DataFrame(records).set_index("Datetime").sort_index()["CumAmt"]

            meta_text = " ".join(
                [str(data.get("title", "")), str(fields[amt_idx] if amt_idx < len(fields) else "")]
                + [str(n) for n in data.get("notes", [])]
            )
            max_val = float(s_cum.max())

            if "億元" in meta_text:
                divisor = 1.0
            elif "百萬元" in meta_text:
                divisor = 100.0
            elif "千元" in meta_text:
                divisor = 100_000.0
            else:
                if max_val > 5_000_000_000:
                    divisor = 1e8
                elif max_val > 5_000_000:
                    divisor = 100_000.0
                elif max_val > 20_000:
                    divisor = 100.0
                else:
                    divisor = 1.0

            s_cum_yi = s_cum / divisor
            s_interval_yi = s_cum_yi.diff().fillna(s_cum_yi.iloc[0]).clip(lower=0.0)
            s_interval_yi.name = "Volume"
            return s_interval_yi
        except Exception:
            continue

    return pd.Series(dtype=float, name="Volume")


@st.cache_data(ttl=60, show_spinner=False)
def fetch_twse_5sec_index(max_lookback_days: int = 10):
    """從證交所官方 MI_5MINS_INDEX 抓取最近交易日每 5 秒指數，並合併成交金額（億元）"""
    today = datetime.now(TZ_TAIPEI).date()
    endpoints = [
        "https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_INDEX",
        "https://www.twse.com.tw/exchangeReport/MI_5MINS_INDEX",
    ]

    for offset in range(max_lookback_days):
        target_date = today - timedelta(days=offset)
        if target_date.weekday() >= 5:
            continue
        date_str = target_date.strftime("%Y%m%d")

        for url in endpoints:
            try:
                resp = requests.get(
                    url,
                    params={"response": "json", "date": date_str},
                    headers=HTTP_HEADERS,
                    timeout=8,
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("stat") != "OK" or not data.get("data"):
                    continue

                rows = data["data"]
                records = []
                prev_close = None
                trade_date_fmt = target_date.strftime("%Y-%m-%d")

                for row in rows:
                    if len(row) < 2:
                        continue
                    t_str = str(row[0]).strip()
                    val = _to_float(row[1])
                    if val is None:
                        continue

                    if t_str == "09:00:00":
                        prev_close = val
                        continue

                    dt = pd.Timestamp(f"{trade_date_fmt} {t_str}", tz="Asia/Taipei")
                    records.append({"Datetime": dt, "Close": val})

                if not records:
                    continue

                df = pd.DataFrame(records).set_index("Datetime").sort_index()
                if prev_close is None:
                    prev_close = float(df["Close"].iloc[0])

                turnover_s = fetch_twse_5sec_turnover(trade_date_fmt)
                if not turnover_s.empty:
                    df = df.join(turnover_s, how="left")
                    df["Volume"] = df["Volume"].fillna(0.0)
                else:
                    df["Volume"] = 0.0

                return df, prev_close, trade_date_fmt
            except Exception:
                continue

    return pd.DataFrame(), None, None


def resample_ohlc(df_5s: pd.DataFrame, interval: str) -> pd.DataFrame:
    """將證交所每 5 秒序列依選擇週期重採樣"""
    if interval == "5s":
        out = pd.DataFrame(index=df_5s.index)
        out["Open"] = df_5s["Close"]
        out["High"] = df_5s["Close"]
        out["Low"] = df_5s["Close"]
        out["Close"] = df_5s["Close"]
        out["Volume"] = df_5s["Volume"] if "Volume" in df_5s.columns else 0.0
        return out

    rule_map = {"1m": "1min", "2m": "2min", "5m": "5min", "15m": "15min"}
    rule = rule_map.get(interval, "1min")
    ohlc = df_5s["Close"].resample(rule, label="right", closed="right").ohlc().dropna()
    ohlc.columns = ["Open", "High", "Low", "Close"]
    if "Volume" in df_5s.columns:
        vol_sum = df_5s["Volume"].resample(rule, label="right", closed="right").sum()
        ohlc["Volume"] = vol_sum.reindex(ohlc.index).fillna(0.0)
    else:
        ohlc["Volume"] = 0.0
    return ohlc


# ==========================================
# yfinance 抓取（當日分時 & 近 90 日日線）
# ==========================================
@st.cache_data(ttl=30, show_spinner=False)
def fetch_yfinance_intraday(ticker: str, interval: str, tz_name: str):
    yf_interval = "1m" if interval == "5s" else interval
    stock = yf.Ticker(ticker)
    df = stock.history(period="5d", interval=yf_interval, auto_adjust=False)

    if df is None or df.empty:
        return pd.DataFrame(), None, None, "Yahoo Finance"

    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC").tz_convert(tz_name)
    else:
        df.index = df.index.tz_convert(tz_name)

    df = df.dropna(subset=["Close"])
    if df.empty:
        return pd.DataFrame(), None, None, "Yahoo Finance"

    unique_dates = sorted(df.index.normalize().unique())
    latest_date = unique_dates[-1]
    today_df = df[df.index.normalize() == latest_date].copy()

    prev_close = None
    if len(unique_dates) >= 2:
        prev_df = df[df.index.normalize() == unique_dates[-2]]
        if not prev_df.empty:
            prev_close = float(prev_df["Close"].iloc[-1])

    try:
        daily = stock.history(period="5d", interval="1d", auto_adjust=False).dropna(subset=["Close"])
        if len(daily) >= 2:
            if daily.index.tz is None:
                daily.index = daily.index.tz_localize("UTC").tz_convert(tz_name)
            else:
                daily.index = daily.index.tz_convert(tz_name)

            daily_dates = daily.index.normalize()
            if daily_dates[-1] == latest_date:
                prev_close = float(daily["Close"].iloc[-2])
                official_close = float(daily["Close"].iloc[-1])
                if abs(float(today_df["Close"].iloc[-1]) - official_close) > 0.01:
                    last_ts = today_df.index[-1] + pd.Timedelta(minutes=1)
                    patch_row = pd.DataFrame(
                        {
                            "Open": [float(today_df["Close"].iloc[-1])],
                            "High": [max(float(today_df["Close"].iloc[-1]), official_close)],
                            "Low": [min(float(today_df["Close"].iloc[-1]), official_close)],
                            "Close": [official_close],
                            "Volume": [0],
                        },
                        index=[last_ts],
                    )
                    today_df = pd.concat([today_df, patch_row])
    except Exception:
        pass

    if prev_close is None:
        try:
            prev_close = float(stock.fast_info.get("previousClose"))
        except Exception:
            prev_close = float(today_df["Open"].iloc[0])

    return today_df, prev_close, latest_date.strftime("%Y-%m-%d"), "Yahoo Finance (日線校準)"


@st.cache_data(ttl=300, show_spinner=False)
def fetch_daily_90d_data(ticker: str, trading_days: int = 90) -> pd.DataFrame:
    """
    抓取近 1 年日線資料，先計算 MA5 / MA20(月線) / MA60(季線)、
    布林通道 (20日, 2倍標準差) 與 KD (9, 3, 3)，再擷取最近 90 個交易日。
    """
    stock = yf.Ticker(ticker)
    df = stock.history(period="1y", interval="1d", auto_adjust=False)
    if df is None or df.empty:
        return pd.DataFrame()

    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"]).copy()
    if df.empty:
        return pd.DataFrame()

    if ticker.endswith((".TW", ".TWO")):
        df["Volume"] = df["Volume"] / 1000.0

    df["MA5"] = df["Close"].rolling(window=5).mean()
    df["MA20"] = df["Close"].rolling(window=20).mean()
    df["MA60"] = df["Close"].rolling(window=60).mean()

    bb_std = df["Close"].rolling(window=20).std()
    df["BB_Mid"] = df["MA20"]
    df["BB_Upper"] = df["BB_Mid"] + 2.0 * bb_std
    df["BB_Lower"] = df["BB_Mid"] - 2.0 * bb_std

    low_min = df["Low"].rolling(window=9, min_periods=1).min()
    high_max = df["High"].rolling(window=9, min_periods=1).max()
    denom = (high_max - low_min).replace(0, np.nan)
    rsv = ((df["Close"] - low_min) / denom * 100.0).fillna(50.0)

    k_vals = np.zeros(len(df), dtype=float)
    d_vals = np.zeros(len(df), dtype=float)
    k_prev, d_prev = 50.0, 50.0
    for i, r in enumerate(rsv.values):
        k_curr = k_prev * (2.0 / 3.0) + r * (1.0 / 3.0)
        d_curr = d_prev * (2.0 / 3.0) + k_curr * (1.0 / 3.0)
        k_vals[i] = k_curr
        d_vals[i] = d_curr
        k_prev, d_prev = k_curr, d_curr

    df["K"] = k_vals
    df["D"] = d_vals

    df_recent = df.tail(trading_days).copy()
    df_recent["DateStr"] = df_recent.index.strftime("%Y-%m-%d")
    return df_recent


# ==========================================
# 當日分時統一入口
# ==========================================
def load_market_data(ticker: str, interval: str, tz_name: str, use_twse: bool):
    if use_twse:
        rt_quote = fetch_twse_realtime_quote()
        df_5s, prev_close_5s, date_5s = fetch_twse_5sec_index()

        if not df_5s.empty and (rt_quote is None or date_5s >= rt_quote["date"]):
            ohlc_df = resample_ohlc(df_5s, interval)
            total_turnover = float(df_5s["Volume"].sum()) if "Volume" in df_5s.columns else 0.0
            summary = {
                "latest_price": float(df_5s["Close"].iloc[-1]),
                "prev_close": float(prev_close_5s),
                "open": float(df_5s["Close"].iloc[0]),
                "high": float(df_5s["Close"].max()),
                "low": float(df_5s["Close"].min()),
                "last_time": df_5s.index[-1].strftime("%Y-%m-%d %H:%M:%S"),
                "total_volume": total_turnover,
                "volume_mode": "turnover_yi",
            }
            src = (
                "臺灣證券交易所官方 API (MI_5MINS_INDEX + MI_5MINS)"
                if total_turnover > 0
                else "臺灣證券交易所官方 API (MI_5MINS_INDEX)"
            )
            return ohlc_df, summary, date_5s, src

        if rt_quote is not None:
            yf_df, yf_prev, yf_date, _ = fetch_yfinance_intraday("^TWII", interval, tz_name)
            if not yf_df.empty and yf_date == rt_quote["date"]:
                rt_ts = pd.Timestamp(f"{rt_quote['date']} {rt_quote['time']}", tz="Asia/Taipei")
                if rt_ts > yf_df.index[-1]:
                    patch = pd.DataFrame(
                        {
                            "Open": [rt_quote["price"]],
                            "High": [rt_quote["price"]],
                            "Low": [rt_quote["price"]],
                            "Close": [rt_quote["price"]],
                            "Volume": [0.0],
                        },
                        index=[rt_ts],
                    )
                    yf_df = pd.concat([yf_df, patch])
                summary = {
                    "latest_price": rt_quote["price"],
                    "prev_close": rt_quote["prev_close"] or yf_prev,
                    "open": rt_quote["open"] or float(yf_df["Open"].iloc[0]),
                    "high": rt_quote["high"] or float(yf_df["High"].max()),
                    "low": rt_quote["low"] or float(yf_df["Low"].min()),
                    "last_time": f"{rt_quote['date']} {rt_quote['time']}",
                    "total_volume": 0.0,
                    "volume_mode": "turnover_yi",
                }
                return yf_df, summary, rt_quote["date"], "證交所盤中即時 API + Yahoo 分時走勢"

    df, prev_close, trade_date, source_label = fetch_yfinance_intraday(ticker, interval, tz_name)
    if df.empty or prev_close is None:
        return pd.DataFrame(), None, None, source_label

    is_tw_stock = ticker.endswith((".TW", ".TWO"))
    if is_tw_stock and "Volume" in df.columns:
        df = df.copy()
        df["Volume"] = df["Volume"] / 1000.0
        volume_mode = "lots"
    else:
        volume_mode = "shares"

    total_vol = float(df["Volume"].sum()) if "Volume" in df.columns else 0.0
    summary = {
        "latest_price": float(df["Close"].iloc[-1]),
        "prev_close": float(prev_close),
        "open": float(df["Open"].iloc[0]),
        "high": float(df["High"].max()),
        "low": float(df["Low"].min()),
        "last_time": df.index[-1].strftime("%Y-%m-%d %H:%M:%S"),
        "total_volume": total_vol,
        "volume_mode": volume_mode,
    }
    return df, summary, trade_date, source_label


# ==========================================
# 繪圖函式 1：當日分時走勢圖（十字準星貫穿 + 成交量連動）
# ==========================================
def build_intraday_chart(
    df: pd.DataFrame,
    prev_close: float,
    latest_price: float,
    title: str,
    volume_mode: str = "shares",
):
    has_volume = "Volume" in df.columns and df["Volume"].sum() > 0

    if has_volume:
        fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=False,
            vertical_spacing=0.05,
            row_heights=[0.74, 0.26],
        )
    else:
        fig = make_subplots(rows=1, cols=1)

    if latest_price > prev_close:
        line_color = COLOR_UP
        fill_rgba = "rgba(229, 57, 53, 0.15)"
    elif latest_price < prev_close:
        line_color = COLOR_DOWN
        fill_rgba = "rgba(0, 137, 123, 0.15)"
    else:
        line_color = COLOR_FLAT
        fill_rgba = "rgba(117, 117, 117, 0.15)"

    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["Close"],
            mode="lines",
            name="指數/價格",
            line=dict(color=line_color, width=2.2),
            fill="tozeroy",
            fillcolor=fill_rgba,
            hovertemplate="點數/價格: %{y:,.2f}<extra></extra>",
        ),
        row=1,
        col=1,
    )

    fig.add_shape(
        type="line",
        x0=0,
        x1=1,
        xref="paper",
        y0=prev_close,
        y1=prev_close,
        yref="y",
        line=dict(color="#90A4AE", width=1.2, dash="dash"),
    )
    fig.add_annotation(
        x=0.005,
        xref="paper",
        y=prev_close,
        yref="y",
        text=f"昨收 {prev_close:,.2f}",
        showarrow=False,
        xanchor="left",
        yanchor="bottom",
        font=dict(color="#78909C", size=12),
    )

    y_min = min(df["Low"].min(), prev_close)
    y_max = max(df["High"].max(), prev_close)
    y_pad = max((y_max - y_min) * 0.12, prev_close * 0.001)
    fig.update_yaxes(range=[y_min - y_pad, y_max + y_pad], tickformat=",.2f", row=1, col=1)

    if has_volume:
        prev_close_series = df["Close"].shift(1).fillna(prev_close)
        vol_colors = [
            COLOR_UP if (c > o or (c == o and c >= pc)) else COLOR_DOWN
            for c, o, pc in zip(df["Close"], df["Open"], prev_close_series)
        ]

        if volume_mode == "turnover_yi":
            vol_name = "成交金額 (億元)"
            vol_yaxis_title = "成交金額 (億元)"
            vol_hover = "成交金額: %{y:,.2f} 億元<extra></extra>"
            vol_tickformat = ",.2f"
        elif volume_mode == "lots":
            vol_name = "成交量 (張)"
            vol_yaxis_title = "成交量 (張)"
            vol_hover = "成交量: %{y:,.1f} 張<extra></extra>"
            vol_tickformat = ",.0f"
        else:
            vol_name = "成交數量"
            vol_yaxis_title = "成交數量"
            vol_hover = "成交數量: %{y:,.0f}<extra></extra>"
            vol_tickformat = ",.0f"

        fig.add_trace(
            go.Bar(
                x=df.index,
                y=df["Volume"],
                name=vol_name,
                marker_color=vol_colors,
                opacity=0.8,
                hovertemplate=vol_hover,
            ),
            row=2,
            col=1,
        )
        fig.update_yaxes(title_text=vol_yaxis_title, tickformat=vol_tickformat, row=2, col=1)

        fig.update_traces(xaxis="x2")
        fig.update_layout(xaxis=dict(visible=False))
        fig.update_xaxes(
            range=[df.index.min(), df.index.max()],
            tickformat="%H:%M",
            showspikes=True,
            spikemode="across",
            spikesnap="cursor",
            spikethickness=1,
            spikedash="dash",
            spikecolor="#90A4AE",
            row=2,
            col=1,
        )
    else:
        fig.update_xaxes(
            range=[df.index.min(), df.index.max()],
            tickformat="%H:%M",
            showspikes=True,
            spikemode="across",
            spikesnap="cursor",
            spikethickness=1,
            spikedash="dash",
            spikecolor="#90A4AE",
            row=1,
            col=1,
        )

    fig.update_yaxes(
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikethickness=1,
        spikedash="dot",
        spikecolor="#78909C",
    )

    fig.update_layout(
        title=dict(text=title, font=dict(size=18)),
        template="plotly_dark",
        height=620 if has_volume else 500,
        margin=dict(l=20, r=20, t=50, b=20),
        hovermode="x unified",
        spikedistance=-1,
        xaxis_rangeslider_visible=False,
        xaxis2_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    return fig


def _style_signed_val(val):
    if isinstance(val, (int, float)) and not pd.isna(val):
        if val > 0:
            return f"color: {COLOR_UP}; font-weight: 600;"
        if val < 0:
            return f"color: {COLOR_DOWN}; font-weight: 600;"
    return ""


def _style_maintenance_ratio(val):
    """維持率低於 140% 顯示警戒色、低於 130% 顯示紅色"""
    if isinstance(val, (int, float)) and not pd.isna(val):
        if val < 130.0:
            return f"color: {COLOR_UP}; font-weight: 700;"
        if val < 140.0:
            return f"color: {COLOR_WARN}; font-weight: 700;"
    return ""


# ==========================================
# 繪圖函式 2：近 90 個交易日 K 線 + 日成交量 + KD(9,3,3) 副圖
# ==========================================
def build_kline_90d_chart(
    df: pd.DataFrame,
    title: str,
    ticker: str,
    show_ma5: bool = True,
    show_ma20: bool = True,
    show_ma60: bool = True,
    show_bb: bool = False,
):
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=False,
        vertical_spacing=0.04,
        row_heights=[0.54, 0.22, 0.24],
    )

    x_dates = df["DateStr"]

    fig.add_trace(
        go.Candlestick(
            x=x_dates,
            open=df["Open"],
            high=df["High"],
            low=df["Low"],
            close=df["Close"],
            name="K線",
            increasing_line_color=COLOR_UP,
            increasing_fillcolor=COLOR_UP,
            decreasing_line_color=COLOR_DOWN,
            decreasing_fillcolor=COLOR_DOWN,
        ),
        row=1,
        col=1,
    )

    if show_ma5:
        fig.add_trace(
            go.Scatter(
                x=x_dates,
                y=df["MA5"],
                mode="lines",
                name="5日線 (MA5)",
                line=dict(color="#FFB300", width=1.4),
                hovertemplate="MA5: %{y:,.2f}<extra></extra>",
            ),
            row=1,
            col=1,
        )
    if show_ma20:
        fig.add_trace(
            go.Scatter(
                x=x_dates,
                y=df["MA20"],
                mode="lines",
                name="月線 (MA20)",
                line=dict(color="#42A5F5", width=1.5),
                hovertemplate="月線: %{y:,.2f}<extra></extra>",
            ),
            row=1,
            col=1,
        )
    if show_ma60:
        fig.add_trace(
            go.Scatter(
                x=x_dates,
                y=df["MA60"],
                mode="lines",
                name="季線 (MA60)",
                line=dict(color="#AB47BC", width=1.6),
                hovertemplate="季線: %{y:,.2f}<extra></extra>",
            ),
            row=1,
            col=1,
        )

    if show_bb:
        fig.add_trace(
            go.Scatter(
                x=x_dates,
                y=df["BB_Upper"],
                mode="lines",
                name="布林上軌",
                line=dict(color="#26C6DA", width=1.2, dash="dash"),
                hovertemplate="布林上軌: %{y:,.2f}<extra></extra>",
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=x_dates,
                y=df["BB_Lower"],
                mode="lines",
                name="布林下軌",
                line=dict(color="#26C6DA", width=1.2, dash="dash"),
                fill="tonexty",
                fillcolor="rgba(38, 198, 218, 0.08)",
                hovertemplate="布林下軌: %{y:,.2f}<extra></extra>",
            ),
            row=1,
            col=1,
        )
        if not show_ma20:
            fig.add_trace(
                go.Scatter(
                    x=x_dates,
                    y=df["BB_Mid"],
                    mode="lines",
                    name="布林中軌 (20MA)",
                    line=dict(color="#80DEEA", width=1.1, dash="dot"),
                    hovertemplate="布林中軌: %{y:,.2f}<extra></extra>",
                ),
                row=1,
                col=1,
            )

    is_tw_stock = ticker.endswith((".TW", ".TWO"))
    vol_label = "日成交量 (張)" if is_tw_stock else "日成交量"
    vol_hover = "成交量: %{y:,.0f} 張<extra></extra>" if is_tw_stock else "成交量: %{y:,.0f}<extra></extra>"

    vol_colors = [
        COLOR_UP if c >= o else COLOR_DOWN
        for c, o in zip(df["Close"], df["Open"])
    ]
    fig.add_trace(
        go.Bar(
            x=x_dates,
            y=df["Volume"],
            name=vol_label,
            marker_color=vol_colors,
            opacity=0.8,
            hovertemplate=vol_hover,
        ),
        row=2,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=x_dates,
            y=df["K"],
            mode="lines",
            name="K(9)",
            line=dict(color="#FFCA28", width=1.7),
            hovertemplate="K值: %{y:.2f}<extra></extra>",
        ),
        row=3,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=x_dates,
            y=df["D"],
            mode="lines",
            name="D(9)",
            line=dict(color="#29B6F6", width=1.7),
            hovertemplate="D值: %{y:.2f}<extra></extra>",
        ),
        row=3,
        col=1,
    )
    fig.add_shape(
        type="line", x0=0, x1=1, xref="paper", y0=80, y1=80, yref="y3",
        line=dict(color="#EF5350", width=1, dash="dot"),
    )
    fig.add_shape(
        type="line", x0=0, x1=1, xref="paper", y0=20, y1=20, yref="y3",
        line=dict(color="#26A69A", width=1, dash="dot"),
    )

    fig.update_traces(xaxis="x3")
    fig.update_layout(xaxis=dict(visible=False), xaxis2=dict(visible=False))

    fig.update_yaxes(title_text="價格 / 點數", tickformat=",.2f", row=1, col=1)
    fig.update_yaxes(title_text=vol_label, tickformat=",.0f", row=2, col=1)
    fig.update_yaxes(title_text="KD (9,3,3)", range=[0, 100], tickvals=[20, 50, 80], row=3, col=1)

    fig.update_xaxes(
        type="category",
        nticks=10,
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikethickness=1,
        spikedash="dash",
        spikecolor="#90A4AE",
        row=3,
        col=1,
    )
    fig.update_yaxes(
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikethickness=1,
        spikedash="dot",
        spikecolor="#78909C",
    )

    fig.update_layout(
        title=dict(text=title, font=dict(size=18)),
        template="plotly_dark",
        height=820,
        margin=dict(l=20, r=20, t=55, b=20),
        hovermode="x unified",
        spikedistance=-1,
        xaxis_rangeslider_visible=False,
        xaxis3_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    return fig


def render_metric_card(label: str, value: str, delta_text: str = "", color: str = COLOR_FLAT, mini: bool = False):
    cls_card = "mini-card" if mini else "metric-card"
    cls_label = "mini-label" if mini else "metric-label"
    cls_val = "mini-value" if mini else "metric-value"
    cls_delta = "mini-delta" if mini else "metric-delta"
    delta_html = (
        f'<div class="{cls_delta}" style="color: {color};">{delta_text}</div>'
        if delta_text
        else ""
    )
    st.markdown(
        f"""
        <div class="{cls_card}" style="border-left-color: {color};">
            <div class="{cls_label}">{label}</div>
            <div class="{cls_val}">{value}</div>
            {delta_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


# ==========================================
# 主畫面（共用控制面板 + 分頁切換）
# ==========================================
st.title("📈 大盤與 ETF 走勢儀表板")

tw_directory = load_tw_stock_directory()

with st.container(border=True):
    ctrl1, ctrl2, ctrl3, ctrl4 = st.columns([2.8, 2.5, 1.3, 1.4], vertical_alignment="bottom")

    with ctrl1:
        selected_name = st.selectbox("選擇預設指數 / 標的", list(INDEX_OPTIONS.keys()), index=0)
        option = INDEX_OPTIONS[selected_name]
        ticker = option["ticker"]
        tz_name = option["tz"]
        use_twse = option["use_twse"]

    with ctrl2:
        custom_input = st.text_input(
            "搜尋中文名稱或代碼（選填）",
            placeholder="例如: 台達電、2308、QQQ",
        )

    search_not_found = None
    multi_candidates = None

    if custom_input.strip():
        status, result = resolve_custom_query(custom_input, tw_directory)
        if status == "single":
            ticker = result["ticker"]
            selected_name = result["display_name"]
            tz_name = result["tz"]
            use_twse = result["use_twse"]
        elif status == "multiple":
            multi_candidates = result
        else:
            search_not_found = result

    if multi_candidates:
        cand_labels = [
            f"{item['name']} ({item['code']}｜{item['market']})"
            for item in multi_candidates
        ]
        picked_label = st.selectbox(
            f"找到 {len(multi_candidates)} 筆符合「{custom_input.strip()}」的標的，請選擇：",
            cand_labels,
            index=0,
        )
        picked_item = multi_candidates[cand_labels.index(picked_label)]
        ticker = picked_item["ticker"]
        selected_name = f"{picked_item['name']} ({picked_item['ticker']})"
        tz_name = "Asia/Taipei"
        use_twse = False

    with ctrl3:
        interval_choices = ["5s", "1m", "2m", "5m", "15m"] if use_twse else ["1m", "2m", "5m", "15m"]
        default_idx = 1 if use_twse else 0
        interval = st.selectbox("當日分時週期", interval_choices, index=default_idx)

    with ctrl4:
        if st.button("🔄 立即手動更新", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    sub1, sub2 = st.columns([1.8, 4], vertical_alignment="center")
    with sub1:
        auto_refresh = st.toggle("開啟自動更新", value=False)
    with sub2:
        refresh_sec = st.slider(
            "自動更新頻率（秒）",
            min_value=15,
            max_value=120,
            value=30,
            step=15,
            disabled=not auto_refresh,
            label_visibility="collapsed",
        )

if search_not_found is not None:
    st.warning(f"找不到符合「**{search_not_found}**」的台股名稱或代碼，請確認名稱是否正確，或改輸入完整代碼（例如 `2308`、`2308.TW`、`QQQ`）。")
    st.stop()

# 分頁切換：當日走勢 vs 近 90 日 K 線
tab_intraday, tab_kline = st.tabs(["📊 當日分時走勢", "🕯️ 近 90 個交易日 K 線"])

# ------------------------------------------
# Tab 1: 當日分時走勢 + 近 5 日三大法人與融資券表格（玩股網大盤融資維持率）
# ------------------------------------------
with tab_intraday:
    with st.spinner(f"正在載入 {selected_name} 當日資料..."):
        df_intra, summary, trade_date, data_source = load_market_data(ticker, interval, tz_name, use_twse)

    if df_intra.empty or summary is None:
        st.error(f"無法取得 `{ticker}` 的當日分時資料，請確認網路連線或代碼是否正確。")
    else:
        latest_price = summary["latest_price"]
        prev_close = summary["prev_close"]
        open_price = summary["open"]
        high_price = summary["high"]
        low_price = summary["low"]
        last_time = summary["last_time"]
        total_volume = summary["total_volume"]
        volume_mode = summary["volume_mode"]

        change = latest_price - prev_close
        change_pct = (change / prev_close) * 100 if prev_close else 0.0

        if change > 0:
            status_color = COLOR_UP
            sign = "▲ +"
        elif change < 0:
            status_color = COLOR_DOWN
            sign = "▼ "
        else:
            status_color = COLOR_FLAT
            sign = ""

        vol_caption = ""
        if total_volume > 0:
            if volume_mode == "turnover_yi":
                vol_caption = f" ｜ 當日總成交金額：**{total_volume:,.2f} 億元**"
            elif volume_mode == "lots":
                vol_caption = f" ｜ 當日累計成交量：**{total_volume:,.0f} 張**"
            else:
                vol_caption = f" ｜ 當日累計成交量：**{total_volume:,.0f}**"

        st.caption(
            f"資料來源：**{data_source}** ｜ 交易日期：**{trade_date}** ｜ "
            f"最後報價：**{last_time}**{vol_caption} ｜ 畫面更新：{datetime.now(TZ_TAIPEI).strftime('%H:%M:%S')}"
        )

        price_unit_label = "最新點數" if use_twse or ticker.startswith("^") else "最新價格"

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            render_metric_card(
                label=f"{selected_name} {price_unit_label}",
                value=f"{latest_price:,.2f}",
                delta_text=f"{sign}{change:,.2f} ({change_pct:+.2f}%)",
                color=status_color,
            )
        with col2:
            open_diff = open_price - prev_close
            open_color = COLOR_UP if open_diff > 0 else (COLOR_DOWN if open_diff < 0 else COLOR_FLAT)
            render_metric_card(
                label="開盤 / 昨收",
                value=f"{open_price:,.2f}",
                delta_text=f"昨收 {prev_close:,.2f}",
                color=open_color,
            )
        with col3:
            high_pct = ((high_price - prev_close) / prev_close) * 100
            render_metric_card(
                label="當日最高",
                value=f"{high_price:,.2f}",
                delta_text=f"{high_pct:+.2f}%",
                color=COLOR_UP if high_price >= prev_close else COLOR_DOWN,
            )
        with col4:
            low_pct = ((low_price - prev_close) / prev_close) * 100
            render_metric_card(
                label="當日最低",
                value=f"{low_price:,.2f}",
                delta_text=f"{low_pct:+.2f}%",
                color=COLOR_UP if low_price >= prev_close else COLOR_DOWN,
            )

        fig_intra = build_intraday_chart(
            df=df_intra,
            prev_close=prev_close,
            latest_price=latest_price,
            title=f"{selected_name} 當日走勢 ({trade_date}, {interval})",
            volume_mode=volume_mode,
        )
        st.plotly_chart(fig_intra, use_container_width=True)

        if volume_mode == "turnover_yi" and ("Volume" not in df_intra.columns or df_intra["Volume"].sum() <= 0):
            st.info("ℹ️ 證交所「每 5 秒委託成交統計 (`MI_5MINS`)」為盤後公布資料，盤中即時階段暫不顯示分時成交金額柱狀圖，待盤後結算公布即會自動出現。")

    # ---- 近 5 日三大法人買賣超 & 融資券變化（純證交所即時版） ----
    st.divider()
    with st.spinner(f"正在載入 {selected_name} 近 5 日三大法人與融資券資料..."):
        df_inst, df_margin, chip_meta = fetch_recent_5d_chips(
            ticker, use_twse, days=5
        )

    if chip_meta is None:
        st.info("ℹ️ 三大法人買賣超與融資券變化僅支援「台灣加權指數」及台股上市 (`.TW`)／上櫃 (`.TWO`) 標的。")
    else:
        chip_col1, chip_col2 = st.columns(2)

        with chip_col1:
            inst_unit = chip_meta["inst_unit"]
            st.markdown(
                f'<div class="section-title">🏛️ 近 5 日三大法人買賣超 ({inst_unit})</div>',
                unsafe_allow_html=True,
            )
            if df_inst.empty:
                st.warning("暫無近期三大法人買賣超資料（可能尚未盤後公布或標的無資料）。")
            else:
                tbl_inst = df_inst[["完整日期", "外資", "投信", "自營商", "合計"]].iloc[::-1].copy()
                tbl_inst = tbl_inst.rename(columns={"完整日期": "日期"})
                fmt_str = "{:+,.2f}" if inst_unit == "億元" else "{:+,.1f}"
                st.dataframe(
                    tbl_inst.style.map(
                        _style_signed_val, subset=["外資", "投信", "自營商", "合計"]
                    ).format(
                        {col: fmt_str for col in ["外資", "投信", "自營商", "合計"]}
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

        with chip_col2:
            m_unit = chip_meta["margin_unit"]
            s_unit = chip_meta["short_unit"]
            header_unit = f"融資:{m_unit} / 融券:{s_unit}" if m_unit != s_unit else m_unit
            st.markdown(
                f'<div class="section-title">💳 近 5 日融資券變化 ({header_unit})</div>',
                unsafe_allow_html=True,
            )
            if df_margin.empty:
                st.warning("此標的暫無近期融資融券資料（部分新掛牌 ETF 或非信用交易標的無融資券）。")
            else:
                tbl_margin = df_margin[["完整日期", "融資增減", "融資餘額", "融券增減", "融券餘額"]].iloc[::-1].copy()
                tbl_margin = tbl_margin.rename(columns={"完整日期": "日期"})

                m_diff_fmt = "{:+,.2f}" if m_unit == "億元" else "{:+,.0f}"
                m_bal_fmt = "{:,.2f}" if m_unit == "億元" else "{:,.0f}"
                fmt_map = {
                    "融資增減": m_diff_fmt,
                    "融資餘額": m_bal_fmt,
                    "融券增減": "{:+,.0f}",
                    "融券餘額": "{:,.0f}",
                }
                st.dataframe(
                    tbl_margin.style.map(
                        _style_signed_val, subset=["融資增減", "融券增減"]
                    ).format(fmt_map),
                    use_container_width=True,
                    hide_index=True,
                )

        # 大盤專用：近 5 日大盤融資維持率表格（純證交所官方實數：含 ETF / 全上市）
        if chip_meta["is_market"]:
            df_maint = chip_meta.get("df_maint", pd.DataFrame())

            st.markdown(
                '<div class="section-title">⚖️ 近 5 日大盤融資維持率 (%)</div>',
                unsafe_allow_html=True,
            )
            if df_maint.empty:
                st.warning("暫無近期大盤融資維持率資料。")
            else:
                tbl_maint = df_maint[["完整日期", "含ETF維持率", "較前日"]].iloc[::-1].copy()
                tbl_maint = tbl_maint.rename(columns={"完整日期": "日期"})

                fmt_maint = {
                    "含ETF維持率": lambda v: f"{v:.2f}%" if pd.notna(v) else "-",
                    "較前日": lambda v: f"{v:+.2f}%" if pd.notna(v) else "-",
                }
                st.dataframe(
                    tbl_maint.style.map(
                        _style_maintenance_ratio, subset=["含ETF維持率"]
                    ).map(
                        _style_signed_val, subset=["較前日"]
                    ).format(fmt_maint),
                    use_container_width=True,
                    hide_index=True,
                )
                st.caption(
                    "資料來源：臺灣證券交易所官方即時計算（全上市含 ETF 融資市值 ÷ 總融資金額）。"
                    "`<140%` 黃字警戒、`<130%` 紅字追繳區。"
                )

# ------------------------------------------
# Tab 2: 近 90 個交易日 K 線 + 日成交量 + KD(9,3,3)
# ------------------------------------------
with tab_kline:
    ind_col1, ind_col2, ind_col3, ind_col4 = st.columns(4)
    with ind_col1:
        show_ma5 = st.checkbox("5日線 (MA5)", value=True)
    with ind_col2:
        show_ma20 = st.checkbox("月線 (MA20)", value=True)
    with ind_col3:
        show_ma60 = st.checkbox("季線 (MA60)", value=True)
    with ind_col4:
        show_bb = st.checkbox("布林通道 (20日, 2σ)", value=False)

    with st.spinner(f"正在載入 {selected_name} 近 90 個交易日 K 線資料..."):
        df_90d = fetch_daily_90d_data(ticker, trading_days=90)

    if df_90d.empty:
        st.error(f"無法取得 `{ticker}` 的日線資料，請確認代碼是否正確。")
    else:
        last_row = df_90d.iloc[-1]
        st.caption(
            f"資料區間：**{df_90d['DateStr'].iloc[0]} ~ {df_90d['DateStr'].iloc[-1]}**（共 {len(df_90d)} 個交易日） ｜ "
            f"最新收盤：**{last_row['Close']:,.2f}** ｜ "
            f"K(9)：**{last_row['K']:.2f}** ｜ D(9)：**{last_row['D']:.2f}**"
        )

        fig_kline = build_kline_90d_chart(
            df=df_90d,
            title=f"{selected_name} 近 90 個交易日 K 線、日成交量與 KD(9,3,3)",
            ticker=ticker,
            show_ma5=show_ma5,
            show_ma20=show_ma20,
            show_ma60=show_ma60,
            show_bb=show_bb,
        )
        st.plotly_chart(fig_kline, use_container_width=True)

if auto_refresh:
    time.sleep(refresh_sec)
    st.cache_data.clear()
    st.rerun()
