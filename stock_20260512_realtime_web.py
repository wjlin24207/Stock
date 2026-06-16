import requests
import yfinance as yf
import pandas as pd
import urllib3
import time
from datetime import datetime, timedelta
import streamlit as st
import plotly.graph_objects as go  # 為了畫簡易走勢圖

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===== 1. 頁面設定 (一定要放在最前面) =====
st.set_page_config(page_title="KD監控儀表板 (三欄布局版)", layout="wide")

# ===== 2. 側邊欄 (Sidebar) - 放功能按鈕和時間 =====
st.sidebar.title("📊 控制面板")

taiwan_time = datetime.utcnow() + timedelta(hours=8)
st.sidebar.write(f"⏱️ 上次更新：{taiwan_time.strftime('%Y-%m-%d %H:%M:%S')}")

if st.sidebar.button("🔄 手動刷新資料"):
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.info("這是一個專業版的 KD 監控儀表板，提供即時數據與技術指標分析。")


# ===== 3. 資料抓取與處理函式 (保留原本邏輯) =====
session = requests.Session()
session.headers.update({'User-Agent': 'Mozilla/5.0'})

@st.cache_data(ttl=60) # 加上簡單的快取，避免頻繁請求
def get_all_live_prices(stock_list):
    ex_ch_list = []
    for sid in stock_list:
        if sid == "^TWII":
            ex_ch_list.append("tse_t00.tw")
        else:
            ex_ch_list.append(f"tse_{sid}.tw")
            ex_ch_list.append(f"otc_{sid}.tw")

    url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={'|'.join(ex_ch_list)}&json=1&delay=0"

    try:
        res = session.get(url, timeout=10, verify=False)
        data = res.json()
        price_map = {}

        if 'msgArray' in data:
            for info in data['msgArray']:
                key = info.get('c')
                if key == 't00':
                    key = '^TWII'
                price_map[key] = info
        return price_map
    except:
        return {}

@st.cache_data(ttl=300) # 歷史資料快取時間長一點
def get_all_yahoo_hist(stock_list):
    tickers = [f"{sid}.TW" if not sid.startswith("^") else sid for sid in stock_list]
    return yf.download(
        tickers,
        period="6mo",
        interval="1d",
        progress=False,
        group_by='ticker',
        auto_adjust=True
    )

def process_kd_logic(stock_id, live_info, hist_df):
    try:
        if hist_df is None or hist_df.empty:
            return None

        hist = hist_df.dropna().copy()
        hist.columns = [c.lower() for c in hist.columns]

        z = live_info.get('z', '-')
        b = live_info.get('b', '-')
        b = b.split('_')[0] if b else '-'
        y = live_info.get('y', '0')

        if z not in ['-', '']:
            live_price = float(z)
        elif b not in ['-', '']:
            live_price = float(b)
        else:
            live_price = float(y)

        y_price = float(y)

        temp = hist.astype(float).copy()
        temp.iloc[-1, temp.columns.get_loc('close')] = live_price

        temp['9h'] = temp['high'].rolling(9).max()
        temp['9l'] = temp['low'].rolling(9).min()

        temp['rsv'] = 100 * (temp['close'] - temp['9l']) / (temp['9h'] - temp['9l'] + 1e-9)
        temp['rsv'] = temp['rsv'].fillna(50)

        k, d = 50, 50
        for rsv in temp['rsv']:
            k = k * (2/3) + rsv * (1/3)
            d = d * (2/3) + k * (1/3)

        ma5 = temp['close'].rolling(5).mean()
        ma10 = temp['close'].rolling(10).mean()
        ma20 = temp['close'].rolling(20).mean()

        ma5_t = ma5.iloc[-1]
        ma10_t = ma10.iloc[-1]
        ma20_t = ma20.iloc[-1]

        ma5_y = ma5.iloc[-2]
        ma10_y = ma10.iloc[-2]

        diff = live_price - y_price
        percent = (diff / y_price * 100) if y_price > 0 else 0

        signal = []
        signal.append("📈 多" if k > d else "📉 空")

        if k < 30:
            signal.append("⚠️超賣")
        elif k > 80:
            signal.append("🔥超買")

        # 這裡縮短訊號文字，避免表格太寬
        if ma5_y <= ma10_y and ma5_t > ma10_t:
            signal.append("✨黃金")
        elif ma5_y >= ma10_y and ma5_t < ma10_t:
            signal.append("❌死亡")

        if live_price > ma5_t > ma10_t > ma20_t:
            ma_status = "🚀多頭"
        elif live_price < ma5_t < ma10_t < ma20_t:
            ma_status = "💥空頭"
        else:
            ma_status = "➖盤整"

        name = live_info.get('n', stock_id)
        if stock_id == "^TWII":
            name = "加權指數"

        return {
            "代號": stock_id,
            "名稱": name,
            "價格": round(live_price, 2),
            "漲跌": round(diff, 2),
            "漲幅%": round(percent, 2),
            "K": round(k, 2),
            "D": round(d, 2),
            "MA5": round(ma5_t, 2),
            "MA10": round(ma10_t, 2),
            "MA20": round(ma20_t, 2),
            "均線": ma_status,
            "訊號": " ".join(signal)
        }

    except:
        return None

# ===== 簡易走勢圖繪製函式 (新增) =====
def plot_mini_chart(df, title):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df['Close'], mode='lines', name='收盤價', line=dict(color='royalblue', width=2)))
    fig.update_layout(
        title=title,
        xaxis_title="日期",
        yaxis_title="點數",
        margin=dict(l=20, r=20, t=40, b=20),
        height=300,
        template="plotly_white"
    )
    return fig


# ==========================================
# ===== 4. 主頁面布局與內容 (核心修改區) =====
# ==========================================

st.title("📊 策略監控儀表板")
st.markdown("---")

# 這裡定義你的庫存股和自選股
inventory_stocks = ["2330", "0050", "3711"] # 假設這幾檔是庫存
watchlist_stocks = ["^TWII", "0056", "00878", "00919", "00981A", "00988A", "00631L"] # 這是自選股
all_target_stocks = list(set(inventory_stocks + watchlist_stocks)) # 整合所有要抓取的代號

# 預先抓取所有資料
with st.spinner('正在獲取即時數據...'):
    prices = get_all_live_prices(all_target_stocks)
    hists = get_all_yahoo_hist(all_target_stocks)

# ===== 第一層布局：使用槽中槽 (Nested Columns) 達到 2x2 但下方合併的效果 =====

# 宣告兩個主列，比例可以調整，這裡讓左邊窄一點，右邊寬一點
main_col_left, main_col_right = st.columns([1, 2])

# --- 左上：庫存區 ---
with main_col_left:
    st.subheader("📋 我的庫存")
    
    # 這裡放原本的表格生成邏輯，但只針對庫存股
    inv_rows = []
    for sid in inventory_stocks:
        live = prices.get(sid)
        key = f"{sid}.TW" if not sid.startswith("^") else sid
        hist = None
        if isinstance(hists.columns, pd.MultiIndex):
            if key in hists.columns.levels[0]: hist = hists[key]
        else: hist = hists

        if live and hist is not None:
            result = process_kd_logic(sid, live, hist)
            if result: inv_rows.append(result)

    if inv_rows:
        inv_df = pd.DataFrame(inv_rows)
        # (這裡省略複雜的表格格式化，直接顯示簡單版，確保空間夠用)
        st.dataframe(inv_df[["代號", "名稱", "價格", "漲幅%", "訊號"]], use_container_width=True, hide_index=True)
    else:
        st.info("尚無庫存資料或資料載入中...")


# --- 右上：指數走勢圖 + 其他區 ---
with main_col_right:
    # 在右側主列中，再切割兩個子列
    sub_col_chart, sub_col_other = st.columns(2)
    
    with sub_col_chart:
        st.subheader("📈 當日加權指數走勢")
        # 這裡需要另外抓取大盤的當日即時 K 線，Yahoo Finance 需要指定 interval='1m' 且 period='1d'
        try:
            twii_daily = yf.download("^TWII", period="1d", interval="1m", progress=False)
            if not twii_daily.empty:
                st.plotly_chart(plot_mini_chart(twii_daily, "加權指數 (1分K)"), use_container_width=True)
            else:
                st.warning("無法取得大盤當日走勢。")
        except:
            st.error("繪製走勢圖時發生錯誤。")

    with sub_col_other:
        st.subheader("🔍 其他關鍵指標")
        # 這裡可以放一些簡單的數據卡片
        twii_live = prices.get("^TWII", {})
        if twii_live:
            st.metric(label="加權指數", value=f"{float(twii_live.get('z',0)):,.2f}", delta=f"{float(twii_live.get('z',0))-float(twii_live.get('y',0)):,.2f}")
            st.metric(label="成交比重 (電子)", value="75.2%") # 範例
            st.metric(label="三大法人買賣超", value="+123 億") # 範例
        else:
            st.info("大盤即時數據不可用")


st.markdown("---") # 分隔線


# --- 下方：自選股區 (橫跨全寬) ---
st.subheader("⭐ 自選股監控")

# 這裡放原本的表格生成邏輯，針對自選股
watch_rows = []
for sid in watchlist_stocks:
    live = prices.get(sid)
    key = f"{sid}.TW" if not sid.startswith("^") else sid
    hist = None
    if isinstance(hists.columns, pd.MultiIndex):
        if key in hists.columns.levels[0]: hist = hists[key]
    else: hist = hists

    if live and hist is not None:
        result = process_kd_logic(sid, live, hist)
        if result: watch_rows.append(result)

if watch_rows:
    df = pd.DataFrame(watch_rows)
    
    # ===== 以下完全保留你原本的表格格式化邏輯 =====
    df = df.rename(columns={"代號": "代號/K線", "名稱": "名稱/成份股"})
    df["代號_raw"] = df["代號/K線"]

    def make_id_link(row):
        sid = row["代號_raw"]
        if sid == "^TWII": url = "https://tw.stock.yahoo.com/tw-market"
        else: url = f"https://tw.stock.yahoo.com/quote/{sid}/technical-analysis"
        return f'<a href="{url}" target="_blank">{sid}</a>'

    def make_name_link(row):
        sid = row["代號_raw"]
        name = row["名稱/成份股"]
        url = None
        if str(sid).startswith("00"): url = f"https://www.moneydj.com/ETF/X/Basic/Basic0007.xdjhtm?etfid={sid}.TW"
        if url: return f'<a href="{url}" target="_blank">{name}</a>'
        return name

    df["名稱/成份股"] = df.apply(make_name_link, axis=1)
    df["代號/K線"] = df.apply(make_id_link, axis=1)
    df = df.drop(columns=["代號_raw"])

    styled = df.style.format({
        "價格": "{:,.2f}", "漲跌": "{:+,.2f}", "漲幅%": "{:+,.2f}%",
        "K": "{:.2f}", "D": "{:.2f}", "MA5": "{:.2f}", "MA10": "{:.2f}", "MA20": "{:.2f}"
    })

    def color(val): return "color:red" if val > 0 else "color:green" if val < 0 else ""
    styled = styled.map(color, subset=["漲跌", "漲幅%"])

    def apply_price(row):
        diff = df.loc[row.name, "漲跌"]
        return ["color:red; font-weight:bold"] if diff > 0 else ["color:green; font-weight:bold"] if diff < 0 else [""]
    styled = styled.apply(apply_price, subset=["價格"], axis=1)

    def color_ma(val, price): return "color:red" if val < price else "color:green" if val > price else ""
    def apply_ma(row):
        price = df.loc[row.name, "價格"]
        return [color_ma(row["MA5"], price), color_ma(row["MA10"], price), color_ma(row["MA20"], price)]
    styled = styled.apply(apply_ma, subset=["MA5", "MA10", "MA20"], axis=1)

    # 調整 CSS，讓文字更緊湊
    st.markdown("""
    <style>
    table { width: 100% !important; table-layout: auto; }
    td, th { white-space: nowrap; font-size: 13px; padding: 4px 8px !important; }
    div[data-testid="stMarkdownContainer"] { overflow-x: auto; }
    </style>
    """, unsafe_allow_html=True)

    st.markdown(styled.to_html(escape=False), unsafe_allow_html=True)
else:
    st.info("尚無自選股資料。")


# ===== 5. 自動刷新 (保留) =====
# 注意：在開發時，頻繁的自動刷新可能會導致 API 被封鎖。請手動刷新或設定較長的 sleep 時間。
time.sleep(60) # 改為 60 秒刷新一次
st.rerun()
