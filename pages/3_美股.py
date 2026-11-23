import json
import re
import html
import time
from datetime import datetime
import urllib3
import requests
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

urllib3.disable_warnings()

# 設定網頁標題與配置
st.set_page_config(page_title="期貨與美股", layout="wide")

# 注入響應式 CSS：僅鎖定「走勢圖區塊」在手機版也強制維持 2x2 並排，不影響其他元件
st.markdown(
    """
    <style>
    @media (max-width: 640px) {
        .block-container {
            padding-left: 0.6rem !important;
            padding-right: 0.6rem !important;
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

st.title("📊 期貨與美股看版")

# 監控的商品代號與對應外部連結
market_tickers = {
    "小道瓊": {"ticker": "YM=F", "url": "https://finance.yahoo.com.tw/quote/YM=F"},
    "小S&P500": {"ticker": "ES=F", "url": "https://finance.yahoo.com.tw/quote/ES=F"},
    "小那斯達克": {"ticker": "NQ=F", "url": "https://finance.yahoo.com.tw/quote/NQ=F"},
    "台指期夜盤": {"ticker": "WTX&", "url": "https://tw.stock.yahoo.com/future/WTX&"},
    "道瓊指數": {"ticker": "^DJI", "url": "https://finance.yahoo.com.tw/quote/^DJI"},
    "S&P500": {"ticker": "^GSPC", "url": "https://finance.yahoo.com.tw/quote/^GSPC"},
    "那斯達克": {"ticker": "^IXIC", "url": "https://finance.yahoo.com.tw/quote/^IXIC"},
    "費城半導體": {"ticker": "^SOX", "url": "https://finance.yahoo.com.tw/quote/^SOX"},
    "台積電ADR": {"ticker": "TSM", "url": "https://tw.stock.yahoo.com/quote/TSM"},
    "日月光ADR": {"ticker": "ASX", "url": "https://tw.stock.yahoo.com/quote/ASX"}
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
def fetch_yahoo_market_data(tickers_dict):
    """ 抓取 Yahoo Finance 即時報價與當日 5 分 K 走勢 """
    data_list = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    for name, info in tickers_dict.items():
        if name == "台指期夜盤":
            continue

        ticker = info["ticker"]
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
                if valid_pairs:
                    times = [datetime.fromtimestamp(t).strftime("%H:%M") for t, _ in valid_pairs]
                    prices = [float(c) for _, c in valid_pairs]

                live_price = meta.get("regularMarketPrice") or (prices[-1] if prices else 0.0)
                live_prev = meta.get("chartPreviousClose") or meta.get("previousClose") or (prices[0] if prices else 0.0)

                if live_price and live_prev:
                    current_price = float(live_price)
                    prev_close = float(live_prev)
                    change = current_price - prev_close
                    change_pct = (change / prev_close) * 100
        except Exception:
            pass

        if current_price == 0.0:
            current_price, change, change_pct, prev_close = fetch_yahoo_historical_fallback(ticker, headers)

        data_list.append({
            "商品名稱": name,
            "最新價格": current_price,
            "漲跌點數": change,
            "漲跌幅 (%)": change_pct,
            "昨收": prev_close,
            "times": times,
            "prices": prices
        })

    return data_list


def get_color_style(change):
    if change > 0:
        return "#FF4B4B", "▲", "+", "rgba(255, 75, 75, 0.14)"
    elif change < 0:
        return "#00B050", "▼", "", "rgba(0, 176, 80, 0.14)"
    return "#888888", "—", "", "rgba(136, 136, 136, 0.14)"


def create_independent_chart(item):
    """ 建立 2x2 緊湊即時走勢圖：鎖定拖拉與縮放，保留點擊查看價位 """
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

    # 昨收平盤虛線 (2x2 版面精簡，保留參考線不加過長文字以免遮擋)
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
            side="right",
            showgrid=True,
            gridcolor="rgba(255, 255, 255, 0.06)",
            nticks=3,
            tickfont=dict(color="#8A919E", size=10),
            tickformat=",.0f"
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


def render_clickable_html_table(market_data, tickers_dict):
    """ 手機友善 HTML 總表：原生 <a> 超連結，單指輕點即開啟，不會觸發編輯儲存格 """
    rows_html = []
    for item in market_data:
        name = item["商品名稱"]
        price = item["最新價格"]
        change = item["漲跌點數"]
        pct = item["漲跌幅 (%)"]
        url = tickers_dict.get(name, {}).get("url", "#")
        color, _, sign, _ = get_color_style(change)

        rows_html.append(compact_html(f"""
            <tr style="border-bottom: 1px solid #2A2E39;">
                <td style="padding: 12px 10px; text-align: left; white-space: nowrap;">
                    <a href="{url}" target="_blank" style="color: #60A5FA; text-decoration: none; font-weight: 600; display: inline-block; padding: 4px 0;">{name} ↗</a>
                </td>
                <td style="padding: 12px 10px; text-align: right; color: #FFFFFF; font-family: monospace; white-space: nowrap;">{price:,.2f}</td>
                <td style="padding: 12px 10px; text-align: right; color: {color}; font-weight: 600; font-family: monospace; white-space: nowrap;">{sign}{change:,.2f}</td>
                <td style="padding: 12px 10px; text-align: right; color: {color}; font-weight: 600; font-family: monospace; white-space: nowrap;">{sign}{pct:.2f}%</td>
            </tr>
        """))

    table_html = compact_html(f"""
        <div style="overflow-x: auto; border-radius: 10px; border: 1px solid #2A2E39; background-color: #1E222D;">
            <table style="width: 100%; border-collapse: collapse; font-size: 15px;">
                <thead>
                    <tr style="background-color: #161922; border-bottom: 2px solid #2A2E39; color: #9BA3B4;">
                        <th style="padding: 11px 10px; text-align: left; white-space: nowrap;">商品名稱</th>
                        <th style="padding: 11px 10px; text-align: right; white-space: nowrap;">最新價格</th>
                        <th style="padding: 11px 10px; text-align: right; white-space: nowrap;">漲跌點數</th>
                        <th style="padding: 11px 10px; text-align: right; white-space: nowrap;">漲跌幅</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join(rows_html)}
                </tbody>
            </table>
        </div>
    """)
    st.markdown(table_html, unsafe_allow_html=True)


# --- 控制列 ---
col_refresh1, col_refresh2, col_refresh3 = st.columns([1, 1, 2])
with col_refresh1:
    if st.button("🔄 點擊強制刷新最新跳動"):
        st.cache_data.clear()
        st.rerun()

with col_refresh2:
    auto_refresh = st.toggle("自動刷新", value=False)

with col_refresh3:
    refresh_sec = st.number_input("刷新秒數", min_value=30, max_value=3600, value=30, step=30)

# --- 取得資料 ---
with st.spinner("正在精準同步全球市場最新數據..."):
    market_data = fetch_yahoo_market_data(market_tickers).copy()
    txf_item = get_txf_night_data()
    market_data.insert(3, txf_item)
    data_map = {d["商品名稱"]: d for d in market_data}

futures_names = ["小道瓊", "小S&P500", "小那斯達克", "台指期夜盤"]
index_names = ["道瓊指數", "S&P500", "那斯達克", "費城半導體"]

# --- 1. 分段按鈕切換走勢圖 (支援自動刷新記憶狀態，不會跳回第一頁) ---
tab_options = ["🇺🇸 期貨與夜盤", "🏛️ 美股現貨"]
if "selected_market_tab" not in st.session_state:
    st.session_state["selected_market_tab"] = tab_options[0]

if hasattr(st, "segmented_control"):
    selected_tab = st.segmented_control(
        "切換走勢圖分頁",
        options=tab_options,
        default=st.session_state["selected_market_tab"],
        label_visibility="collapsed"
    )
    if selected_tab is None:
        selected_tab = st.session_state["selected_market_tab"]
    else:
        st.session_state["selected_market_tab"] = selected_tab
else:
    selected_tab = st.radio(
        "切換走勢圖分頁",
        options=tab_options,
        horizontal=True,
        key="selected_market_tab",
        label_visibility="collapsed"
    )

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
            if name1 in data_map:
                render_independent_chart_block(data_map[name1], market_tickers)
        with c2:
            if i + 1 < len(chart_targets):
                name2 = chart_targets[i + 1]
                if name2 in data_map:
                    render_independent_chart_block(data_map[name2], market_tickers)

st.markdown("---")

# --- 2. 數據總覽表 (獨立在下方，不隨分頁切換，含台積電ADR、日月光ADR) ---
st.subheader("📋 數據總覽")
render_clickable_html_table(market_data, market_tickers)

# ===== 自動刷新 =====
if auto_refresh:
    time.sleep(refresh_sec)
    st.rerun()
