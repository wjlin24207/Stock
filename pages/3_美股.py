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
st.title("📊 期貨與美股看版")

# 監控的商品代號與對應點數跳轉的外部連結
market_tickers = {
    "小道瓊": {"ticker": "YM=F", "url": "https://finance.yahoo.com.tw/quote/YM=F"},
    "小S&P500": {"ticker": "ES=F", "url": "https://finance.yahoo.com.tw/quote/ES=F"},
    "小那斯達克": {"ticker": "NQ=F", "url": "https://finance.yahoo.com.tw/quote/NQ=F"},
    "台指期夜盤": {"ticker": "WTX&", "url": "https://tw.stock.yahoo.com/future/WTX&"},
    "道瓊指數": {"ticker": "^DJI", "url": "https://finance.yahoo.com.tw/quote/^DJI"},
    "S&P500": {"ticker": "^GSPC", "url": "https://finance.yahoo.com.tw/quote/^GSPC"},
    "那斯達克": {"ticker": "^IXIC", "url": "https://finance.yahoo.com.tw/quote/^IXIC"},
    "費城半導體": {"ticker": "^SOX", "url": "https://finance.yahoo.com.tw/quote/^SOX"},
    "台積電ADR": {"ticker": "TSM", "url": "https://finance.yahoo.com/quote/TSM"},
    "日月光ADR": {"ticker": "ASX", "url": "https://finance.yahoo.com/quote/ASX"}
}


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


def create_sparkline(times, prices, prev_close, color):
    """ 建立極簡即時走勢圖 (含昨收平盤虛線) """
    fig = go.Figure()
    if not prices:
        fig.update_layout(
            height=90,
            margin=dict(l=0, r=0, t=4, b=0),
            paper_bgcolor="#1E222D",
            plot_bgcolor="#1E222D",
            xaxis=dict(visible=False),
            yaxis=dict(visible=False)
        )
        return fig

    if color == "#FF4B4B":
        fill_color = "rgba(255, 75, 75, 0.15)"
    elif color == "#00B050":
        fill_color = "rgba(0, 176, 80, 0.15)"
    else:
        fill_color = "rgba(136, 136, 136, 0.15)"

    fig.add_trace(go.Scatter(
        x=times,
        y=prices,
        mode="lines",
        line=dict(color=color, width=2),
        fill="tozeroy",
        fillcolor=fill_color,
        hovertemplate="%{x}<br>點位: %{y:,.2f}<extra></extra>"
    ))

    # 昨收平盤參考線
    if prev_close and prev_close > 0:
        fig.add_hline(
            y=prev_close,
            line_dash="dot",
            line_color="rgba(255, 255, 255, 0.35)",
            line_width=1
        )

    all_y = prices + ([prev_close] if prev_close and prev_close > 0 else [])
    y_min, y_max = min(all_y), max(all_y)
    pad = (y_max - y_min) * 0.12 if y_max != y_min else 1

    fig.update_layout(
        height=90,
        margin=dict(l=0, r=0, t=4, b=0),
        paper_bgcolor="#1E222D",
        plot_bgcolor="#1E222D",
        xaxis=dict(visible=False),
        yaxis=dict(visible=False, range=[y_min - pad, y_max + pad]),
        showlegend=False,
        hovermode="x unified"
    )
    return fig


def render_custom_metric_with_chart(item, tickers_dict):
    name = item["商品名稱"]
    price = item["最新價格"]
    change = item["漲跌點數"]
    pct = item["漲跌幅 (%)"]
    prev_close = item["昨收"]
    target_url = tickers_dict.get(name, {}).get("url", "#")

    if price > 0:
        if change > 0:
            color, icon, sign = "#FF4B4B", "▲", "+"
        elif change < 0:
            color, icon, sign = "#00B050", "▼", ""
        else:
            color, icon, sign = "#888888", "—", ""

        # 上半部：報價字卡
        st.markdown(
            f"""
            <a href="{target_url}" target="_blank" style="text-decoration: none; color: inherit;">
                <div style="
                    background-color: #1E222D;
                    padding: 14px 16px 8px 16px;
                    border-radius: 10px 10px 0 0;
                    border-left: 6px solid {color};
                    cursor: pointer;
                    transition: transform 0.2s ease, box-shadow 0.2s ease;
                " onmouseover="this.style.transform='translateY(-2px)'; this.style.boxShadow='0 6px 12px rgba(0,0,0,0.2)';"
                   onmouseout="this.style.transform='translateY(0)'; this.style.boxShadow='none';">
                    <div style="color: #AEB3B7; font-size: 20px; font-weight: 500; margin-bottom: 4px;">{name} ↗</div>
                    <div style="color: #FFFFFF; font-size: 26px; font-weight: 700; font-family: monospace; line-height: 1.2;">{price:,.2f}</div>
                    <div style="color: {color}; font-size: 20px; font-weight: 600; margin-top: 4px; font-family: monospace;">
                        {icon} {sign}{change:,.2f} ({sign}{pct:.2f}%)
                    </div>
                </div>
            </a>
            """,
            unsafe_allow_html=True
        )

        # 下半部：即時走勢圖
        fig = create_sparkline(item["times"], item["prices"], prev_close, color)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False}, key=f"chart_{name}")


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

# 1. 美國重要指數期貨
st.subheader("🇺🇸 美國重要指數期貨 (夜盤即時動態)")
cols_fut = st.columns(4)
for name, col in zip(["小道瓊", "小S&P500", "小那斯達克", "台指期夜盤"], cols_fut):
    with col:
        if name in data_map:
            render_custom_metric_with_chart(data_map[name], market_tickers)

st.markdown("---")

# 2. 美國現貨指數
st.subheader("🏛️ 美國現貨指數")
cols_idx = st.columns(4)
for name, col in zip(["道瓊指數", "S&P500", "那斯達克", "費城半導體"], cols_idx):
    with col:
        if name in data_map:
            render_custom_metric_with_chart(data_map[name], market_tickers)

# 3. 數據總覽表
st.markdown("### 📋 數據總覽")
df_display = pd.DataFrame(market_data)[["商品名稱", "最新價格", "漲跌點數", "漲跌幅 (%)"]].copy()
df_display[["最新價格", "漲跌點數", "漲跌幅 (%)"]] = df_display[["最新價格", "漲跌點數", "漲跌幅 (%)"]].round(2)


def make_link_value(name):
    url = market_tickers.get(name, {}).get("url", "")
    if url:
        return f"{url}#{name} ↗"
    return name


df_display["商品名稱"] = df_display["商品名稱"].apply(make_link_value)


def style_positive_negative(val):
    if isinstance(val, (int, float)):
        if val > 0:
            return "color: #FF4B4B; font-weight: bold;"
        elif val < 0:
            return "color: #00B050; font-weight: bold;"
    return ""


styled_df = df_display.fillna("N/A").style.map(style_positive_negative, subset=["漲跌點數", "漲跌幅 (%)"])
st.dataframe(
    styled_df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "商品名稱": st.column_config.LinkColumn(
            "商品名稱",
            display_text=r"#(.*)$"
        ),
        "最新價格": st.column_config.NumberColumn(format="%.2f"),
        "漲跌點數": st.column_config.NumberColumn(format="%.2f"),
        "漲跌幅 (%)": st.column_config.NumberColumn(format="%.2f%%")
    }
)

# ===== 自動刷新 =====
if auto_refresh:
    time.sleep(refresh_sec)
    st.rerun()
