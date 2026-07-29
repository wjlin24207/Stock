import json
import re
import html
import urllib3
import streamlit as st
import requests
import pandas as pd
import time

# 設定網頁標題與配置
st.set_page_config(page_title="期貨與美股", layout="wide")
st.title("📊 期貨與美股看版")

# 監控的商品代號與對應點數跳轉的外部連結
market_tickers = {
    #"小道瓊": {"ticker": "YM=F", "url": "https://finance.yahoo.com.tw/quote/YM=F"},
    #"小S&P500": {"ticker": "ES=F", "url": "https://finance.yahoo.com.tw/quote/ES=F"},
    #"小那斯達克": {"ticker": "NQ=F", "url": "https://finance.yahoo.com.tw/quote/NQ=F"},
    #"台指期夜盤": {"ticker": "TXF1", "url": "https://www.cmoney.tw/forum/futures/TXF1?s=p"},
    #"道瓊指數": {"ticker": "^DJI", "url": "https://finance.yahoo.com.tw/quote/^DJI"},
    #"S&P500": {"ticker": "^GSPC", "url": "https://finance.yahoo.com.tw/quote/^GSPC"},
    #"那斯達克": {"ticker": "^IXIC", "url": "https://finance.yahoo.com.tw/quote/^IXIC"},
    #"費城半導體": {"ticker": "^SOX", "url": "https://finance.yahoo.com.tw/quote/^SOX"},
    "台積電ADR": {"ticker": "TSM", "url": "https://finance.yahoo.com/quote/TSM"},
    "日月光ADR": {"ticker": "ASX", "url": "https://finance.yahoo.com/quote/ASX"}

}

def fetch_yahoo_historical_fallback(ticker):
    """ 核心歷史日線保底：免套件，純 requests 下載 5 天日線 JSON """
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=4)
        if response.status_code == 200:
            res_json = response.json()
            result = res_json.get('chart', {}).get('result', [{}])[0]
            indicators = result.get('indicators', {}).get('quote', [{}])[0]
            close_prices = [p for p in indicators.get('close', []) if p is not None]
            
            if len(close_prices) >= 2:
                current_price = close_prices[-1]
                prev_price = close_prices[-2]
                change = current_price - prev_price
                change_pct = (change / prev_price) * 100
                return current_price, change, change_pct
    except Exception:
        pass
    return None, None, None

def fetch_txf_night():
    try:
        urllib3.disable_warnings()

        url = "https://www.cmoney.tw/forum/futures/TXF1?s=p"

        r = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            verify=False,
            timeout=10
        )

        page = r.text

        m = re.search(
            r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>',
            page,
            re.S
        )

        if not m:
            return None

        json_text = html.unescape(m.group(1))
        data = json.loads(json_text)

        props = data[0]["@graph"][2]["additionalProperty"]

        result = {}

        for item in props:
            result[item["name"]] = item["value"]

        return {
            "商品名稱": "台指期夜盤",
            "最新價格": float(result["成交"]),
            "漲跌點數": float(result["漲跌"]),
            "漲跌幅 (%)": float(result["漲跌幅"])
        }

    except Exception as e:
        print("TXF Error:", e)
        return None

@st.cache_data(ttl=5)  # 快取 5 秒
def fetch_realtime_api_data(tickers_dict):
    data_list = []
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    raw_results = {}
    
    for name, info in tickers_dict.items():
        ticker = info["ticker"]
        # 先用日線拿歷史最後價格「預先打底」，保證絕不為 None
        base_price, base_change, base_pct = fetch_yahoo_historical_fallback(ticker)
        current_price = base_price if base_price else 0.0
        change = base_change if base_change else 0.0
        change_pct = base_pct if base_pct else 0.0
        
        try:
            # 1. 嘗試高優先權的 Yahoo Quote 接口 (即時快照)
            quote_url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={ticker}"
            quote_res = requests.get(quote_url, headers=headers, timeout=3)
            
            if quote_res.status_code == 200:
                quote_json = quote_res.json()
                result = quote_json.get('quoteResponse', {}).get('result', [{}])[0]
                if result:
                    live_price = result.get('regularMarketPrice') or result.get('postMarketPrice') or result.get('preMarketPrice')
                    live_prev = result.get('regularMarketPreviousClose')
                    if live_price and live_prev:
                        current_price = live_price
                        change = live_price - live_prev
                        change_pct = (change / live_prev) * 100
                        raw_results[name] = (current_price, change, change_pct)
                        continue

            # 2. 嘗試 Yahoo Chart 即時分 K 接口
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1m&range=1d"
            response = requests.get(url, headers=headers, timeout=3)
            if response.status_code == 200:
                res_json = response.json()
                meta = res_json.get('chart', {}).get('result', [{}])[0].get('meta', {})
                if meta:
                    live_price = meta.get('regularMarketPrice')
                    live_prev = meta.get('previousClose')
                    if live_price and live_prev:
                        current_price = live_price
                        change = live_price - live_prev
                        change_pct = (change / live_prev) * 100
                        raw_results[name] = (current_price, change, change_pct)
                        continue

            raw_results[name] = (current_price, change, change_pct)
        except Exception:
            raw_results[name] = (current_price, change, change_pct)

    # 按照標準順序組裝
    # 按照標準順序組裝
    for name in tickers_dict.keys():
        c_price, chg, chg_p = raw_results.get(name, (0.0, 0.0, 0.0))
    
        data_list.append({
            "商品名稱": name,
            "最新價格": float(c_price),
            "漲跌點數": float(chg),
            "漲跌幅 (%)": float(chg_p)
        })
    
    # 覆蓋台指期夜盤資料
    txf_data = fetch_txf_night()
    
    if txf_data:
        for i, row in enumerate(data_list):
            if row["商品名稱"] == "台指期夜盤":
                data_list[i] = txf_data
                break
    
    return pd.DataFrame(data_list)

# 重新整理按鈕
col_refresh1, col_refresh2, col_refresh3 = st.columns([1, 1, 2])

with col_refresh1:
    if st.button("🔄 點擊強制刷新最新跳動"):
        st.cache_data.clear()
        st.rerun()

with col_refresh2:
    auto_refresh = st.toggle(
        "自動刷新",
        value=False
    )

with col_refresh3:
    refresh_sec = st.number_input(
        "刷新秒數",
        min_value=30,
        max_value=3600,
        value=30,
        step=30
    )




with st.spinner("正在精準同步全球市場最新數據..."):
    df_market = fetch_realtime_api_data(market_tickers)

# --- 數據優化處理 ---
df_display = df_market.copy()
numeric_cols = ["最新價格", "漲跌點數", "漲跌幅 (%)"]
df_display[numeric_cols] = df_display[numeric_cols].round(2)

# --- 自訂精美即時字卡元件 (紅漲綠跌邏輯 + 支援超連結與懸停動畫) ---
def render_custom_metric(name, df, tickers_dict):
    row_filter = df[df["商品名稱"] == name]
    if not row_filter.empty:
        row = row_filter.iloc[0]
        price = row["最新價格"]
        change = row["漲跌點數"]
        pct = row["漲跌幅 (%)"]
        
        # 取得該商品預設的外部連結
        target_url = tickers_dict.get(name, {}).get("url", "#")
        
        if price > 0:
            if change > 0:
                color = "#FF4B4B"  # 紅漲
                icon = "▲"
                sign = "+"
            elif change < 0:
                color = "#00B050"  # 綠跌
                icon = "▼"
                sign = ""
            else:
                color = "#888888"  # 平盤
                icon = "—"
                sign = ""
            
            # 使用 <a> 標籤包裹整個卡片，並移除底線與文字顏色干擾
            st.markdown(
                f"""
                <a href="{target_url}" target="_blank" style="text-decoration: none; color: inherit;">
                    <div style="
                        background-color: #1E222D; 
                        padding: 16px; 
                        border-radius: 10px; 
                        border-left: 6px solid {color};
                        margin-bottom: 12px;
                        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                        cursor: pointer;
                        transition: transform 0.2s ease, box-shadow 0.2s ease;
                    " onmouseover="this.style.transform='translateY(-2px)'; this.style.boxShadow='0 6px 12px rgba(0,0,0,0.2)';" 
                       onmouseout="this.style.transform='translateY(0)'; this.style.boxShadow='0 4px 6px rgba(0,0,0,0.1)';">
                        <div style="color: #AEB3B7; font-size: 14px; font-weight: 500; margin-bottom: 6px;">{name} ↗</div>
                        <div style="color: #FFFFFF; font-size: 28px; font-weight: 700; font-family: monospace; line-height: 1.2;">{price:,.2f}</div>
                        <div style="color: {color}; font-size: 15px; font-weight: 600; margin-top: 4px; font-family: monospace;">
                            {icon} {sign}{change:,.2f} ({sign}{pct:.2f}%)
                        </div>
                    </div>
                </a>
                """, 
                unsafe_allow_html=True
            )

# --- 介面呈現 ---

# 1. 美國三大期貨區塊
st.subheader("🇺🇸 美國重要指數期貨 (夜盤即時動態)")
col1, col2, col3, col4 = st.columns(4)
futures_names = ["小道瓊", "小S&P500", "小那斯達克", "台指期夜盤"]
cols = [col1, col2, col3, col4]

for name, col in zip(futures_names, cols):
    with col:
        render_custom_metric(name, df_display, market_tickers)

st.markdown("---")

# 2. 美國四大現貨指數區塊
st.subheader("🏛️ 美國現貨指數")
col4, col5, col6, col7 = st.columns(4)
index_names = ["道瓊指數", "S&P500", "那斯達克", "費城半導體"]
cols_idx = [col4, col5, col6, col7]

for name, col in zip(index_names, cols_idx):
    with col:
        render_custom_metric(name, df_display, market_tickers)

# 3. 資料總表
st.markdown("### 📋 數據總覽")

def style_positive_negative(val):
    if isinstance(val, (int, float)):
        if val > 0:
            return 'color: #FF4B4B; font-weight: bold;'
        elif val < 0:
            return 'color: #00B050; font-weight: bold;'
    return ''

df_final_table = df_display.fillna("N/A")
styled_df = df_final_table.style.map(style_positive_negative, subset=["漲跌點數", "漲跌幅 (%)"])

st.dataframe(
    styled_df, 
    use_container_width=True,
    hide_index=True,
    column_config={
        "最新價格": st.column_config.NumberColumn(format="%.2f"),
        "漲跌點數": st.column_config.NumberColumn(format="%.2f"),
        "漲跌幅 (%)": st.column_config.NumberColumn(format="%.2f%%")
    }
)

# ===== 自動刷新 =====
if auto_refresh:
    time.sleep(refresh_sec)
    st.rerun()


