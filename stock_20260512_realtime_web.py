import requests
import yfinance as yf
import pandas as pd
import urllib3
import time
from datetime import datetime, timedelta
import streamlit as st

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
# ==================== 1. 頁面基本設定 ====================
st.set_page_config(page_title="KD監控儀表板", layout="wide")
st.title("📊 策略監控儀表板（專業版）")

session = requests.Session()
session.headers.update({'User-Agent': 'Mozilla/5.0'})

# 初始化 session_state（確保重新整理時自選紀錄不丟失）
if "portfolio_list" not in st.session_state:
    st.session_state.portfolio_list = ["0056", "00878", "00919", "0050", "2330", "3711"]
if "watchlist_list" not in st.session_state:
    st.session_state.watchlist_list = ["^TWII", "0050", "2454", "2317"]

# ===== 股票資料抓取與 KD 計算函式 (保持不變) =====
def get_all_live_prices(stock_list):
    if not stock_list: return {}
    ex_ch_list = []
    for sid in stock_list:
        if sid == "^TWII": ex_ch_list.append("tse_t00.tw")
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
                if key == 't00': key = '^TWII'
                price_map[key] = info
        return price_map
    except: return {}

def get_all_yahoo_hist(stock_list):
    if not stock_list: return pd.DataFrame()
    tickers = [f"{sid}.TW" if not sid.startswith("^") else sid for sid in stock_list]
    return yf.download(tickers, period="6mo", interval="1d", progress=False, group_by='ticker', auto_adjust=True)

def process_kd_logic(stock_id, live_info, hist_df):
    try:
        if hist_df is None or hist_df.empty: return None
        hist = hist_df.dropna().copy()
        hist.columns = [c.lower() for c in hist.columns]
        z, b, y = live_info.get('z', '-'), live_info.get('b', '-'), live_info.get('y', '0')
        b = b.split('_')[0] if b else '-'
        live_price = float(z) if z not in ['-', ''] else (float(b) if b not in ['-', ''] else float(y))
        y_price = float(y)
        庫存 = hist.astype(float).copy()
        庫存.iloc[-1, 庫存.columns.get_loc('close')] = live_price
        庫存['9h'], 庫存['9l'] = 庫存['high'].rolling(9).max(), 庫存['low'].rolling(9).min()
        庫存['rsv'] = 100 * (庫存['close'] - 庫存['9l']) / (庫存['9h'] - 庫存['9l'] + 1e-9)
        庫存['rsv'] = 庫存['rsv'].fillna(50)
        k, d = 50, 50
        for rsv in 庫存['rsv']:
            k = k * (2/3) + rsv * (1/3)
            d = d * (2/3) + k * (1/3)
        ma5, ma10, ma20 = 庫存['close'].rolling(5).mean(), 庫存['close'].rolling(10).mean(), 庫存['close'].rolling(20).mean()
        ma5_t, ma10_t, ma20_t = ma5.iloc[-1], ma10.iloc[-1], ma20.iloc[-1]
        ma5_y, ma10_y = ma5.iloc[-2], ma10.iloc[-2]
        diff = live_price - y_price
        percent = (diff / y_price * 100) if y_price > 0 else 0
        signal = ["📈 KD多方" if k > d else "📉 KD空方"]
        if k < 30: signal.append("⚠️ KD超賣")
        elif k > 80: signal.append("🔥 KD超買")
        if ma5_y <= ma10_y and ma5_t > ma10_t: signal.append("✨ 均線黃金交叉")
        elif ma5_y >= ma10_y and ma5_t < ma10_t: signal.append("❌ 均線死亡交叉")
        ma_status = "🚀 均線多頭" if live_price > ma5_t > ma10_t > ma20_t else ("💥 均線空頭" if live_price < ma5_t < ma10_t < ma20_t else "➖ 均線盤整")
        name = "加權指數" if stock_id == "^TWII" else live_info.get('n', stock_id)
        return {"代號": stock_id, "名稱": name, "價格": round(live_price, 2), "漲跌": round(diff, 2), "漲幅%": round(percent, 2), "K": round(k, 2), "D": round(d, 2), "MA5": round(ma5_t, 2), "MA10": round(ma10_t, 2), "MA20": round(ma20_t, 2), "均線狀態": ma_status, "訊號": " | ".join(signal)}
    except: return None

# ==================== 2. 側邊欄：回呼函式與獨立控制區 ====================
st.sidebar.header("🛠️ 監控清單獨立設定")

# 透過 Callback 函式，在按下 Enter 的瞬間「立刻」更新清單並強制刷新網頁
def add_portfolio_stock():
    val = st.session_state.p_input.replace("，", ",").strip()
    if val:
        new_stocks = [s.strip() for s in val.split(",") if s.strip()]
        st.session_state.portfolio_list = list(dict.fromkeys(st.session_state.portfolio_list + new_stocks))
        st.session_state.p_input = "" # 清空輸入框

def add_watchlist_stock():
    val = st.session_state.w_input.replace("，", ",").strip()
    if val:
        new_stocks = [s.strip() for s in val.split(",") if s.strip()]
        st.session_state.watchlist_list = list(dict.fromkeys(st.session_state.watchlist_list + new_stocks))
        st.session_state.w_input = "" # 清空輸入框

# --- 2A. 庫存股管理 ---
st.sidebar.subheader("📌 庫存個股管理")
final_portfolio_list = st.sidebar.multiselect(
    "目前庫存清單（可在此刪除）：", 
    options=st.session_state.portfolio_list, 
    default=st.session_state.portfolio_list,
    key="portfolio_ms"
)
# 更新 session_state 確保同步
st.session_state.portfolio_list = final_portfolio_list

st.sidebar.text_input(
    "✍️ 新增庫存代號（按 Enter 確定）：", 
    key="p_input", 
    on_change=add_portfolio_stock
)

st.sidebar.markdown("---")

# --- 2B. 自選明細管理 ---
st.sidebar.subheader("💼 自選明細管理")
final_watchlist_list = st.sidebar.multiselect(
    "目前自選清單（可在此刪除）：", 
    options=st.session_state.watchlist_list, 
    default=st.session_state.watchlist_list,
    key="watchlist_ms"
)
# 更新 session_state 確保同步
st.session_state.watchlist_list = final_watchlist_list

st.sidebar.text_input(
    "✍️ 新增自選代號（按 Enter 確定）：", 
    key="w_input", 
    on_change=add_watchlist_stock
)

# === 合併總清單 ===
target_stocks = list(dict.fromkeys(final_portfolio_list + final_watchlist_list))

# ==================== 3. 資料準備與計算 ====================
time_col1, time_col2 = st.columns([8, 2])
with time_col1:
    taiwan_time = datetime.utcnow() + timedelta(hours=8)
    st.write("⏱️ 更新時間：", taiwan_time.strftime("%Y-%m-%d %H:%M:%S"))
with time_col2:
    if st.button("🔄 手動刷新", use_container_width=True):
        st.rerun()

if not target_stocks:
    st.warning("⚠️ 請在左側側邊欄設定至少一檔庫存股或自選股。")
    time.sleep(2)
    st.rerun()

prices = get_all_live_prices(target_stocks)
hists = get_all_yahoo_hist(target_stocks)

rows = []
for sid in target_stocks:
    live = prices.get(sid)
    key = f"{sid}.TW" if not sid.startswith("^") else sid
    hist = hists[key] if isinstance(hists.columns, pd.MultiIndex) and key in hists.columns.levels[0] else hists
    if live and hist is not None:
        result = process_kd_logic(sid, live, hist)
        if result: rows.append(result)

if not rows:
    st.error("❌ 抓不到任何股票資料，請檢查網路或代號。")
    time.sleep(2)
    st.rerun()

df_all = pd.DataFrame(rows)
df_all = df_all.rename(columns={"代號": "代號/K線", "名稱": "名稱/成份股"})
df_all["代號_raw"] = df_all["代號/K線"]

# 超連結處理
def make_id_link(row):
    sid = row["代號_raw"]
    url = "https://tw.stock.yahoo.com/tw-market" if sid == "^TWII" else f"https://tw.stock.yahoo.com/quote/{sid}/technical-analysis"
    return f'<a href="{url}" target="_blank">{sid}</a>'

def make_name_link(row):
    sid = row["代號_raw"]
    name = row["名稱/成份股"]
    url = f"https://www.moneydj.com/ETF/X/Basic/Basic0007.xdjhtm?etfid={sid}.TW" if str(sid).startswith("00") else None
    return f'<a href="{url}" target="_blank">{name}</a>' if url else name

df_all["名稱/成份股"] = df_all.apply(make_name_link, axis=1)
df_all["代號/K線"] = df_all.apply(make_id_link, axis=1)

# ==================== 4. 畫面排版與分流渲染 ====================
st.markdown("<style>table { width: 100% !important; table-layout: auto; } td, th { white-space: nowrap; font-size: 14px; padding: 6px 10px !important; } div[data-testid='stMarkdownContainer'] { overflow-x: auto; }</style>", unsafe_allow_html=True)

def color(val): return "color:red" if val > 0 else "color:green" if val < 0 else ""
def apply_price_color(df_src, row):
    diff = df_src.loc[row.name, "漲跌"]
    return ["color:red; font-weight:bold"] if diff > 0 else ["color:green; font-weight:bold"] if diff < 0 else [""]
def color_ma(val, price): return "color:red" if val < price else "color:green" if val > price else ""
def apply_ma_color(df_src, row):
    price = df_src.loc[row.name, "價格"]
    return [color_ma(row["MA5"], price), color_ma(row["MA10"], price), color_ma(row["MA20"], price)]

top_col1, top_col2 = st.columns([6, 4])

# === 左側：庫存股監控 ===
with top_col1:
    st.subheader("📌 庫存股監控")
    df_portfolio = df_all[df_all["代號_raw"].isin(final_portfolio_list)].copy()
    if not df_portfolio.empty:
        df_portfolio_display = df_portfolio.drop(columns=["MA5", "MA10", "MA20", "均線狀態", "訊號", "代號_raw"])
        port_styled = df_portfolio_display.style.format({"價格": "{:,.2f}", "漲跌": "{:+,.2f}", "漲幅%": "{:+,.2f}%", "K": "{:.2f}", "D": "{:.2f}"}).map(color, subset=["漲跌", "漲幅%"])
        port_styled = port_styled.apply(lambda r: apply_price_color(df_portfolio_display, r), subset=["價格"], axis=1)
        st.markdown(port_styled.to_html(escape=False), unsafe_allow_html=True)
    else: st.info("💡 目前沒有設定任何庫存股。")

# === 右側：新聞直播 ===
with top_col2:
    st.subheader("📺 財經新聞直播設定")
    video_id = st.text_input("請輸入最新 YouTube 直播 ID (11碼):", value="1I2iq41Akmo", key="yt_video_id")
    st.video(f"https://www.youtube.com/watch?v={video_id}")

# === 下半部：自選明細 ===
st.divider()
with st.container():
    st.subheader("💼 自選明細完整儀表板")
    df_watchlist = df_all[df_all["代號_raw"].isin(final_watchlist_list)].copy()
    if not df_watchlist.empty:
        df_watchlist_display = df_watchlist.drop(columns=["代號_raw"])
        watch_styled = df_watchlist_display.style.format({"價格": "{:,.2f}", "漲跌": "{:+,.2f}", "漲幅%": "{:+,.2f}%", "K": "{:.2f}", "D": "{:.2f}", "MA5": "{:.2f}", "MA10": "{:.2f}", "MA20": "{:.2f}"}).map(color, subset=["漲跌", "漲幅%"])
        watch_styled = watch_styled.apply(lambda r: apply_price_color(df_watchlist_display, r), subset=["價格"], axis=1)
        watch_styled = watch_styled.apply(lambda r: apply_ma_color(df_watchlist_display, r), subset=["MA5", "MA10", "MA20"], axis=1)
        st.markdown(watch_styled.to_html(escape=False), unsafe_allow_html=True)
    else: st.info("💡 目前沒有設定任何自選股。")

# ===== 5. 自動循環刷新 =====
time.sleep(30)
st.rerun()
