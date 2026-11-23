import json
import re
import html
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import urllib3
import requests
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

urllib3.disable_warnings()

# 固定自動刷新秒數 (寫死在程式內，不開放介面修改)
AUTO_REFRESH_SEC = 60

# 設定網頁標題與配置
st.set_page_config(page_title="期貨與美股", layout="wide")

# 注入響應式 CSS：
# 1. 標題與刷新按鈕在桌面與手機皆維持同一行左右對齊
# 2. 走勢圖區塊在手機版強制維持 2x2 並排
st.markdown(
    """
    <style>
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .mobile-header-anchor) div[data-testid="stHorizontalBlock"],
    .st-key-mobile_header_row div[data-testid="stHorizontalBlock"] {
        align-items: center !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .mobile-header-anchor) div[data-testid="stColumn"]:last-child .stButton,
    .st-key-mobile_header_row div[data-testid="stColumn"]:last-child .stButton {
        display: flex;
        justify-content: flex-end;
    }
    @media (max-width: 640px) {
        .block-container {
            padding-left: 0.6rem !important;
            padding-right: 0.6rem !important;
        }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .mobile-header-anchor) div[data-testid="stHorizontalBlock"],
        .st-key-mobile_header_row div[data-testid="stHorizontalBlock"] {
            flex-direction: row !important;
            flex-wrap: nowrap !important;
            align-items: center !important;
            gap: 8px !important;
        }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .mobile-header-anchor) div[data-testid="stColumn"]:first-child,
        .st-key-mobile_header_row div[data-testid="stColumn"]:first-child {
            flex: 1 1 auto !important;
            width: auto !important;
            min-width: 0 !important;
        }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .mobile-header-anchor) div[data-testid="stColumn"]:last-child,
        .st-key-mobile_header_row div[data-testid="stColumn"]:last-child {
            flex: 0 0 auto !important;
            width: auto !important;
            min-width: 0 !important;
        }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .mobile-2col-anchor) div[data-testid="stHorizontalBlock"],
        .st-key-mobile_chart_grid div[data-testid="stHorizontalBlock"] {
            flex-direction: row !important;
            flex-wrap: nowrap !important;
            gap: 6px !important;
        }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .mobile-2col-anchor) div[data-testid="stColumn"],
        .st-key-mobile_chart_grid div[data-testid="stColumn"] {
            width: calc(50% - 3px) !important;
            flex: 1 1 calc(50% - 3px) !important;
            min-width: 0 !important;
        }
    }
    </style>
    """,
    unsafe_allow_html=True
)

# 上方 2x2 走勢圖商品 (美國期貨、台指期夜盤、美國現貨指數)
chart_tickers = {
    "小道瓊": {"ticker": "YM=F", "url": "https://finance.yahoo.com.tw/quote/YM=F"},
    "小S&P500": {"ticker": "ES=F", "url": "https://finance.yahoo.com.tw/quote/ES=F"},
    "小那斯達克": {"ticker": "NQ=F", "url": "https://finance.yahoo.com.tw/quote/NQ=F"},
    "台指期夜盤": {"ticker": "WTX&", "url": "https://tw.stock.yahoo.com/future/WTX&"},
    "道瓊指數": {"ticker": "^DJI", "url": "https://finance.yahoo.com.tw/quote/^DJI"},
    "S&P500": {"ticker": "^GSPC", "url": "https://finance.yahoo.com.tw/quote/^GSPC"},
    "那斯達克": {"ticker": "^IXIC", "url": "https://finance.yahoo.com.tw/quote/^IXIC"},
    "費城半導體": {"ticker": "^SOX", "url": "https://finance.yahoo.com.tw/quote/^SOX"},
}

# 下方數據總覽表商品 (不含美國大盤與期貨，保留 ADR 並新增重點科技股)
table_tickers = {
    "台積電ADR": {"ticker": "TSM", "url": "https://tw.stock.yahoo.com/quote/TSM"},
    "日月光ADR": {"ticker": "ASX", "url": "https://tw.stock.yahoo.com/quote/ASX"},
    "輝達": {"ticker": "NVDA", "url": "https://tw.stock.yahoo.com/quote/NVDA"},
    "谷歌": {"ticker": "GOOGL", "url": "https://tw.stock.yahoo.com/quote/GOOGL"},
    "蘋果": {"ticker": "AAPL", "url": "https://tw.stock.yahoo.com/quote/AAPL"},
    "美光": {"ticker": "MU", "url": "https://tw.stock.yahoo.com/quote/MU"},
    "海力士": {"ticker": "000660.KS", "url": "https://finance.yahoo.com/quote/000660.KS"},
    "微軟": {"ticker": "MSFT", "url": "https://tw.stock.yahoo.com/quote/MSFT"},
    "英特爾": {"ticker": "INTC", "url": "https://tw.stock.yahoo.com/quote/INTC"},
    "Meta": {"ticker": "META", "url": "https://tw.stock.yahoo.com/quote/META"},
    "博通": {"ticker": "AVGO", "url": "https://tw.stock.yahoo.com/quote/AVGO"},
    "超微": {"ticker": "AMD", "url": "https://tw.stock.yahoo.com/quote/AMD"},
    "亞馬遜": {"ticker": "AMZN", "url": "https://tw.stock.yahoo.com/quote/AMZN"},
    "特斯拉": {"ticker": "TSLA", "url": "https://tw.stock.yahoo.com/quote/TSLA"},
}


def compact_html(html_str):
    """ 移除每行縮排與多餘換行，避免 Streamlit Markdown 將 4 格以上縮排誤判為程式碼區塊 """
    return "".join(line.strip() for line in html_str.splitlines())


def fetch_yahoo_historical_fallback(ticker, headers):
    """ 核心歷史日線保底：免套件，純 requests 下載 5 天日線 JSON """
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d"
        response = requests.get(url, headers=headers, timeout=4)
        if response.status_code == 200:
            res_json = response.json()
            result = res_json.get("chart", {}).get("result", [{}])[0]
            indicators = result.get("indicators", {}).get("quote", [{}])[0]
            close_prices = [float(p) for p in indicators.get("close", []) if p is not None]

            if len(close_prices) >= 2:
                current_price = close_prices[-1]
                prev_price = close_prices[-2]
                change = current_price - prev_price
                change_pct = (change / prev_price) * 100
                return current_price, change, change_pct, prev_price
    except Exception:
        pass
    return 0.0, 0.0, 0.0, 0.0


def fetch_single_yahoo_item(name, ticker, include_intraday=True):
    """ 抓取單一商品的 Yahoo Finance 即時報價 (可選擇是否附帶 5 分 K 走勢) """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    current_price, change, change_pct, prev_close = 0.0, 0.0, 0.0, 0.0
    times, prices = [], []

    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=5m&range=1d"
        response = requests.get(url, headers=headers, timeout=4)
        if response.status_code == 200:
            res_json = response.json()
            result = res_json.get("chart", {}).get("result", [{}])[0]
            meta = result.get("meta", {})
            timestamps = result.get("timestamp", [])
            closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])

            valid_pairs = [(t, c) for t, c in zip(timestamps, closes) if c is not None]
            if include_intraday and valid_pairs:
                times = [datetime.fromtimestamp(t).strftime("%H:%M") for t, _ in valid_pairs]
                prices = [float(c) for _, c in valid_pairs]

            last_valid_close = float(valid_pairs[-1][1]) if valid_pairs else 0.0
            first_valid_close = float(valid_pairs[0][1]) if valid_pairs else 0.0

            live_price = meta.get("regularMarketPrice") or last_valid_close
            live_prev = meta.get("chartPreviousClose") or meta.get("previousClose") or first_valid_close

            if live_price and live_prev:
                current_price = float(live_price)
                prev_close = float(live_prev)
                change = current_price - prev_close
                change_pct = (change / prev_close) * 100
    except Exception:
        pass

    if current_price == 0.0:
        current_price, change, change_pct, prev_close = fetch_yahoo_historical_fallback(ticker, headers)

    return {
        "商品名稱": name,
        "最新價格": current_price,
        "漲跌點數": change,
        "漲跌幅 (%)": change_pct,
        "昨收": prev_close,
        "times": times,
        "prices": prices
    }


@st.cache_data(ttl=15)
def fetch_yahoo_tw_txf():
    """ 抓取 Yahoo 奇摩股市 台指期近一 (WTX&) 即時報價與完整分時走勢 """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://tw.stock.yahoo.com/future/WTX&"
    }
    url = "https://tw.stock.yahoo.com/_td-stock/api/resource/FinanceChartService.ApacLibraCharts;symbols=%5B%22WTX%26%22%5D;type=tick"

    try:
        r = requests.get(url, headers=headers, timeout=6)
        if r.status_code != 200:
            return None

        data = r.json()
        if not data or not isinstance(data, list):
            return None

        chart = data[0].get("chart", {})
        meta = chart.get("meta", {})
        timestamps = chart.get("timestamp", [])
        closes = chart.get("indicators", {}).get("quote", [{}])[0].get("close", [])

        valid_pairs = [(t, c) for t, c in zip(timestamps, closes) if c is not None]
        times = [datetime.fromtimestamp(t).strftime("%H:%M") for t, _ in valid_pairs]
        prices = [float(c) for _, c in valid_pairs]

        live_price = meta.get("regularMarketPrice") or (prices[-1] if prices else 0.0)
        prev_close = meta.get("previousClose") or meta.get("chartPreviousClose") or (prices[0] if prices else 0.0)

        if not live_price:
            return None

        price = float(live_price)
        prev_close = float(prev_close) if prev_close else price
        change = price - prev_close
        pct = (change / prev_close) * 100 if prev_close else 0.0

        return {
            "商品名稱": "台指期夜盤",
            "最新價格": price,
            "漲跌點數": change,
            "漲跌幅 (%)": pct,
            "昨收": prev_close,
            "times": times,
            "prices": prices
        }
    except Exception as e:
        print("Yahoo TW TXF Error:", e)
        return None


@st.cache_data(ttl=15)
def fetch_cmoney_txf_fallback():
    """ 保底：若 Yahoo 奇摩股市暫時無資料，退回 CMoney 抓取最新報價 """
    try:
        url = "https://www.cmoney.tw/forum/futures/TXF1?s=p"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, verify=False, timeout=10)
        m = re.search(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', r.text, re.S)
        if not m:
            return None

        json_text = html.unescape(m.group(1))
        data = json.loads(json_text)
        props = data[0]["@graph"][2]["additionalProperty"]
        result = {item["name"]: item["value"] for item in props}

        price = float(result["成交"])
        change = float(result["漲跌"])
        pct = float(result["漲跌幅"])
        prev_close = price - change

        return {
            "商品名稱": "台指期夜盤",
            "最新價格": price,
            "漲跌點數": change,
            "漲跌幅 (%)": pct,
            "昨收": prev_close,
            "times": [],
            "prices": []
        }
    except Exception as e:
        print("CMoney TXF Error:", e)
        return None


def get_txf_night_data():
    """ 優先使用 Yahoo 奇摩股市 (WTX&) 完整分時走勢，失敗時才退回 CMoney """
    data = fetch_yahoo_tw_txf()
    if data and data["最新價格"] > 0:
        return data

    fallback = fetch_cmoney_txf_fallback()
    if fallback:
        return fallback

    return {
        "商品名稱": "台指期夜盤",
        "最新價格": 0.0,
        "漲跌點數": 0.0,
        "漲跌幅 (%)": 0.0,
        "昨收": 0.0,
        "times": [],
        "prices": []
    }


@st.cache_data(ttl=15)
def fetch_yahoo_batch(tickers_dict, include_intraday=True):
    """ 平行抓取多檔 Yahoo Finance 商品資料，大幅加快載入速度 """
    items_to_fetch = [
        (name, info["ticker"])
        for name, info in tickers_dict.items()
        if name != "台指期夜盤"
    ]
    results_map = {}

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(fetch_single_yahoo_item, name, ticker, include_intraday): name
            for name, ticker in items_to_fetch
        }
        for fut in futures:
            name = futures[fut]
            try:
                results_map[name] = fut.result()
            except Exception:
                results_map[name] = {
                    "商品名稱": name,
                    "最新價格": 0.0,
                    "漲跌點數": 0.0,
                    "漲跌幅 (%)": 0.0,
                    "昨收": 0.0,
                    "times": [],
                    "prices": []
                }

    return [results_map[name] for name, _ in items_to_fetch]


def get_color_style(change):
    if change > 0:
        return "#FF4B4B", "▲", "+", "rgba(255, 75, 75, 0.14)"
    elif change < 0:
        return "#00B050", "▼", "", "rgba(0, 176, 80, 0.14)"
    return "#888888", "—", "", "rgba(136, 136, 136, 0.14)"


def create_independent_chart(item):
    """ 建立 2x2 緊湊即時走勢圖：隱藏 Y 軸數字、鎖定拖拉與縮放，保留點擊查看價位 """
    times = item["times"]
    prices = item["prices"]
    prev_close = item["昨收"]
    color, _, _, fill_color = get_color_style(item["漲跌點數"])

    fig = go.Figure()
    if not prices:
        fig.add_annotation(
            text="無分時資料",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(color="#888888", size=12)
        )
        fig.update_layout(
            height=175,
            margin=dict(l=4, r=4, t=6, b=18),
            paper_bgcolor="#161922",
            plot_bgcolor="#161922",
            xaxis=dict(visible=False, fixedrange=True),
            yaxis=dict(visible=False, fixedrange=True),
            dragmode=False
        )
        return fig

    fig.add_trace(go.Scatter(
        x=times,
        y=prices,
        mode="lines",
        line=dict(color=color, width=2),
        fill="tozeroy",
        fillcolor=fill_color,
        hovertemplate="%{x}<br>%{y:,.2f}<extra></extra>"
    ))

    # 昨收平盤虛線
    if prev_close and prev_close > 0:
        fig.add_hline(
            y=prev_close,
            line_dash="dot",
            line_color="rgba(255, 255, 255, 0.4)",
            line_width=1
        )

    all_y = prices + ([prev_close] if prev_close and prev_close > 0 else [])
    y_min, y_max = min(all_y), max(all_y)
    pad = (y_max - y_min) * 0.12 if y_max != y_min else 1

    fig.update_layout(
        height=175,
        margin=dict(l=4, r=4, t=8, b=20),
        paper_bgcolor="#161922",
        plot_bgcolor="#161922",
        dragmode=False,
        hovermode="x unified",
        showlegend=False,
        xaxis=dict(
            fixedrange=True,
            showgrid=False,
            nticks=3,
            tickfont=dict(color="#8A919E", size=10),
            linecolor="#2A2E39"
        ),
        yaxis=dict(
            fixedrange=True,
            range=[y_min - pad, y_max + pad],
            showticklabels=False,  # 拿掉 Y 軸數字
            showgrid=True,
            gridcolor="rgba(255, 255, 255, 0.06)",
            nticks=3
        )
    )
    return fig


def render_independent_chart_block(item, tickers_dict):
    """ 獨立走勢圖區塊：上方兩行緊湊文字 (適配手機 2x2 寬度) + 下方鎖定防誤觸走勢圖 """
    name = item["商品名稱"]
    price = item["最新價格"]
    change = item["漲跌點數"]
    pct = item["漲跌幅 (%)"]
    target_url = tickers_dict.get(name, {}).get("url", "#")
    color, icon, sign, _ = get_color_style(change)

    header_html = compact_html(f"""
        <div style="
            background-color: #161922;
            border-left: 4px solid {color};
            border-radius: 6px 6px 0 0;
            padding: 6px 8px 4px 8px;
            font-family: monospace;
            overflow: hidden;
        ">
            <div style="
                display: flex;
                justify-content: space-between;
                align-items: baseline;
                white-space: nowrap;
                gap: 4px;
            ">
                <a href="{target_url}" target="_blank" style="
                    text-decoration: none;
                    color: #E0E3EB;
                    font-size: clamp(12px, 3.3vw, 15px);
                    font-weight: 700;
                ">{name} ↗</a>
                <span style="
                    color: #FFFFFF;
                    font-size: clamp(12px, 3.3vw, 16px);
                    font-weight: 700;
                ">{price:,.2f}</span>
            </div>
            <div style="
                color: {color};
                font-size: clamp(11px, 3.0vw, 14px);
                font-weight: 600;
                margin-top: 2px;
                white-space: nowrap;
            ">
                {icon} {sign}{change:,.2f} ({sign}{pct:.2f}%)
            </div>
        </div>
    """)
    st.markdown(header_html, unsafe_allow_html=True)

    fig = create_independent_chart(item)
    st.plotly_chart(
        fig,
        use_container_width=True,
        config={
            "displayModeBar": False,
            "scrollZoom": False,
            "doubleClick": False
        },
        key=f"ind_chart_{name}"
    )


def render_clickable_html_table(table_data, tickers_dict):
    """ 手機友善 HTML 總表：縮小字體與間距，原生 <a> 超連結單指輕點即開啟 """
    rows_html = []
    for item in table_data:
        name = item["商品名稱"]
        price = item["最新價格"]
        change = item["漲跌點數"]
        pct = item["漲跌幅 (%)"]
        url = tickers_dict.get(name, {}).get("url", "#")
        color, _, sign, _ = get_color_style(change)

        rows_html.append(compact_html(f"""
            <tr style="border-bottom: 1px solid #2A2E39;">
                <td style="padding: 8px 8px; text-align: left; white-space: nowrap;">
                    <a href="{url}" target="_blank" style="color: #60A5FA; text-decoration: none; font-weight: 600; display: inline-block; padding: 2px 0;">{name} ↗</a>
                </td>
                <td style="padding: 8px 8px; text-align: right; color: #FFFFFF; font-family: monospace; white-space: nowrap;">{price:,.2f}</td>
                <td style="padding: 8px 8px; text-align: right; color: {color}; font-weight: 600; font-family: monospace; white-space: nowrap;">{sign}{change:,.2f}</td>
                <td style="padding: 8px 8px; text-align: right; color: {color}; font-weight: 600; font-family: monospace; white-space: nowrap;">{sign}{pct:.2f}%</td>
            </tr>
        """))

    table_html = compact_html(f"""
        <div style="overflow-x: auto; border-radius: 10px; border: 1px solid #2A2E39; background-color: #1E222D;">
            <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                <thead>
                    <tr style="background-color: #161922; border-bottom: 2px solid #2A2E39; color: #9BA3B4;">
                        <th style="padding: 9px 8px; text-align: left; white-space: nowrap;">商品名稱</th>
                        <th style="padding: 9px 8px; text-align: right; white-space: nowrap;">最新價格</th>
                        <th style="padding: 9px 8px; text-align: right; white-space: nowrap;">漲跌點數</th>
                        <th style="padding: 9px 8px; text-align: right; white-space: nowrap;">漲跌幅</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join(rows_html)}
                </tbody>
            </table>
        </div>
    """)
    st.markdown(table_html, unsafe_allow_html=True)


def render_dashboard():
    # --- 標題列：左側大標題 + 右側點擊刷新按鈕 (手機維持同一行) ---
    try:
        header_container = st.container(key="mobile_header_row")
    except TypeError:
        header_container = st.container()

    with header_container:
        st.markdown('<span class="mobile-header-anchor"></span>', unsafe_allow_html=True)
        col_title, col_btn = st.columns([3, 1])
        with col_title:
            st.markdown(
                '<h2 style="font-size: clamp(19px, 5vw, 24px); font-weight: 700; margin: 0; padding: 0; white-space: nowrap;">📊 期貨與美股看版</h2>',
                unsafe_allow_html=True
            )
        with col_btn:
            if st.button("🔄 刷新", key="manual_refresh_btn"):
                st.cache_data.clear()
                st.rerun()

    # --- 取得資料 ---
    with st.spinner("正在精準同步全球市場最新數據..."):
        chart_data = fetch_yahoo_batch(chart_tickers, include_intraday=True)
        txf_item = get_txf_night_data()
        chart_data.insert(3, txf_item)
        chart_data_map = {d["商品名稱"]: d for d in chart_data}

        table_data = fetch_yahoo_batch(table_tickers, include_intraday=False)

    futures_names = ["小道瓊", "小S&P500", "小那斯達克", "台指期夜盤"]
    index_names = ["道瓊指數", "S&P500", "那斯達克", "費城半導體"]

    # --- 1. 分段按鈕切換走勢圖 (直接綁定 key，按 1 次即切換且自動刷新不跳回) ---
    tab_options = ["🇺🇸 期貨與夜盤", "🏛️ 美股現貨"]
    if "last_valid_tab" not in st.session_state:
        st.session_state["last_valid_tab"] = tab_options[0]

    if "selected_market_tab" not in st.session_state or st.session_state["selected_market_tab"] not in tab_options:
        st.session_state["selected_market_tab"] = st.session_state["last_valid_tab"]

    if hasattr(st, "segmented_control"):
        selected_tab = st.segmented_control(
            "切換走勢圖分頁",
            options=tab_options,
            key="selected_market_tab",
            label_visibility="collapsed"
        )
        if selected_tab in tab_options:
            st.session_state["last_valid_tab"] = selected_tab
        else:
            selected_tab = st.session_state["last_valid_tab"]
    else:
        selected_tab = st.radio(
            "切換走勢圖分頁",
            options=tab_options,
            horizontal=True,
            key="selected_market_tab",
            label_visibility="collapsed"
        )
        st.session_state["last_valid_tab"] = selected_tab

    chart_targets = futures_names if selected_tab == tab_options[0] else index_names

    # 使用獨立容器搭配 CSS 錨點，讓手機版也強制保持 2x2 畫面
    try:
        grid_container = st.container(key="mobile_chart_grid")
    except TypeError:
        grid_container = st.container()

    with grid_container:
        st.markdown('<span class="mobile-2col-anchor"></span>', unsafe_allow_html=True)
        for i in range(0, len(chart_targets), 2):
            c1, c2 = st.columns(2)
            with c1:
                name1 = chart_targets[i]
                if name1 in chart_data_map:
                    render_independent_chart_block(chart_data_map[name1], chart_tickers)
            with c2:
                if i + 1 < len(chart_targets):
                    name2 = chart_targets[i + 1]
                    if name2 in chart_data_map:
                        render_independent_chart_block(chart_data_map[name2], chart_tickers)

    st.markdown("---")

    # --- 2. 數據總覽表 (不含美國大盤與期貨，顯示 ADR 與重點科技股) ---
    st.markdown(
        '<h3 style="font-size: clamp(16px, 4.2vw, 20px); font-weight: 700; margin: 0 0 8px 0; padding: 0;">📋 數據總覽</h3>',
        unsafe_allow_html=True
    )
    render_clickable_html_table(table_data, table_tickers)


# ===== 固定每 60 秒自動刷新 =====
if hasattr(st, "fragment"):
    @st.fragment(run_every=AUTO_REFRESH_SEC)
    def auto_refresh_dashboard():
        render_dashboard()

    auto_refresh_dashboard()
else:
    render_dashboard()
    time.sleep(AUTO_REFRESH_SEC)
    st.rerun()
