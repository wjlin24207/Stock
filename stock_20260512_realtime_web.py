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
st.title("📊 策略監控儀表板 V001")

session = requests.Session()
session.headers.update({'User-Agent': 'Mozilla/5.0'})

# 初始化資料庫陣列
if "stored_portfolio" not in st.session_state:
    st.session_state.stored_portfolio = ["0056", "00878", "00919", "0050", "2330", "3711"]
if "stored_watchlist" not in st.session_state:
    st.session_state.stored_watchlist = ["^TWII", "0050", "2454", "2317"]

# ===== 股票資料抓取與 KD 計算函式 =====
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

def get_single_yahoo_hist(sid):
    ticker = f"{sid}.TW" if not sid.startswith("^") else sid
    try:
        df = yf.download(ticker, period="6mo", interval="1d", progress=False, auto_adjust=True)
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except: return None

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


# ==================== 2. 側邊欄控制台（動態偵測刪除） ====================
st.sidebar.header("🛠️ 監控清單控制台")

mode = st.sidebar.selectbox(
    "請選擇要管理的清單：",
    options=["📌 庫存個股管理", "💼 自選明細管理"]
)
st.sidebar.markdown("---")

# 💡 核心刪除回呼機制：當點擊 ❌ 時，會驅動這兩個文字框，一有變動立刻執行刪除並 rerun！
def handle_invisible_del_p():
    val = st.session_state.get("hidden_del_p", "")
    if val in st.session_state.stored_portfolio:
        st.session_state.stored_portfolio.remove(val)
    st.session_state.hidden_del_p = ""

def handle_invisible_del_w():
    val = st.session_state.get("hidden_del_w", "")
    if val in st.session_state.stored_watchlist:
        st.session_state.stored_watchlist.remove(val)
    st.session_state.hidden_del_w = ""

# 隱藏在底層的安全下架接收器
st.sidebar.text_input("隱藏下架P", key="hidden_del_p", on_change=handle_invisible_del_p, label_visibility="collapsed")
st.sidebar.text_input("隱藏下架W", key="hidden_del_w", on_change=handle_invisible_del_w, label_visibility="collapsed")


def do_add_portfolio():
    val = st.session_state.get("p_input_field", "").replace("，", ",").strip()
    if val:
        new_stocks = [s.strip() for s in val.split(",") if s.strip()]
        st.session_state.stored_portfolio = list(dict.fromkeys(st.session_state.stored_portfolio + new_stocks))

def do_add_watchlist():
    val = st.session_state.get("w_input_field", "").replace("，", ",").strip()
    if val:
        new_stocks = [s.strip() for s in val.split(",") if s.strip()]
        st.session_state.stored_watchlist = list(dict.fromkeys(st.session_state.stored_watchlist + new_stocks))


if mode == "📌 庫存個股管理":
    st.sidebar.subheader("📌 庫存個股配置")
    st.sidebar.info(f"當前庫存：\n{', '.join(st.session_state.stored_portfolio)}")
    st.sidebar.text_input("輸入要加的庫存代號：", key="p_input_field", placeholder="例如: 2317", on_change=do_add_portfolio)
    st.sidebar.button("➕ 新增到庫存", key="p_btn", use_container_width=True, on_click=do_add_portfolio)
else:
    st.sidebar.subheader("💼 自選明細配置")
    st.sidebar.info(f"當前自選：\n{', '.join(st.session_state.stored_watchlist)}")
    st.sidebar.text_input("輸入要加的自選代號：", key="w_input_field", placeholder="例如: 2454", on_change=do_add_watchlist)
    st.sidebar.button("➕ 新增到自選", key="w_btn", use_container_width=True, on_click=do_add_watchlist)


final_portfolio_list = st.session_state.stored_portfolio
final_watchlist_list = st.session_state.stored_watchlist
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
    st.warning("⚠️ 請在左側設定至少一檔股票。")
    time.sleep(2)
    st.rerun()

prices = get_all_live_prices(target_stocks)
rows = []
for sid in target_stocks:
    live = prices.get(sid)
    hist = get_single_yahoo_hist(sid)
    if live and hist is not None and not hist.empty:
        result = process_kd_logic(sid, live, hist)
        if result: rows.append(result)

df_all = pd.DataFrame(rows)
if not df_all.empty:
    df_all = df_all.rename(columns={"代號": "代號/K線", "名稱": "名稱/成份股"})
    df_all["代號_raw"] = df_all["代號/K線"]

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

# ==================== 4. 畫面排版與表格美化 ====================
st.markdown("""
<style>
table { width: 100% !important; table-layout: auto; }
td, th { white-space: nowrap; font-size: 14px; padding: 6px 10px !important; text-align: center !important; }
div[data-testid='stMarkdownContainer'] { overflow-x: auto; }
.del-icon { color: #ff4b4b; font-weight: bold; font-size: 16px; text-decoration: none; cursor: pointer; }
.del-icon:hover { color: #ff0000; font-size: 18px; }
</style>
""", unsafe_allow_html=True)

def color(val): return "color:red" if val > 0 else "color:green" if val < 0 else ""
def apply_price_color(df_src, row):
    diff = df_src.loc[row.name, "漲跌"]
    return ["color:red; font-weight:bold"] if diff > 0 else ["color:green; font-weight:bold"] if diff < 0 else [""]
def color_ma(val, price): return "color:red" if val < price else "color:green" if val > price else ""
def apply_ma_color(df_src, row):
    price = df_src.loc[row.name, "價格"]
    return [color_ma(row["MA5"], price), color_ma(row["MA10"], price), color_ma(row["MA20"], price)]


# 💡 【核心重構渲染函數】：不改寫索引，直接手動建立一個名為「操作」的全新欄位，保證 100% 成功
def render_styled_table(df_src, type_flag):
    if df_src.empty: return "💡 目前沒有資料"
    
    df_disp = df_src.copy()
    
    # 建立內嵌 JavaScript 的 ❌ 按鈕，點擊時會直接去填寫左邊側邊欄隱藏的 text_input，藉此觸發 Python 的刪除機制！
    if type_flag == "p":
        df_disp.insert(0, "操作", df_disp["代號_raw"].apply(lambda x: f'<a class="del-icon" onclick="window.parent.document.querySelector(\'input[aria-label=\\\'隱藏下架P\\']\').value=\'{x}\'; window.parent.document.querySelector(\'input[aria-label=\\\'隱藏下架P\\']\').dispatchEvent(new Event(\\'change\\', {{bubbles:true}}));">❌</a>'))
    else:
        df_disp.insert(0, "操作", df_disp["代號_raw"].apply(lambda x: f'<a class="del-icon" onclick="window.parent.document.querySelector(\'input[aria-label=\\\'隱藏下架W\\']\').value=\'{x}\'; window.parent.document.querySelector(\'input[aria-label=\\\'隱藏下架W\\']\').dispatchEvent(new Event(\\'change\\', {{bubbles:true}}));">❌</a>'))
        
    df_disp = df_disp.drop(columns=["代號_raw"])
    
    # 套用樣式
    styled = df_disp.style.format({"價格": "{:,.2f}", "漲跌": "{:+,.2f}", "漲幅%": "{:+,.2f}%", "K": "{:.2f}", "D": "{:.2f}", "MA5": "{:.2f}", "MA10": "{:.2f}", "MA20": "{:.2f}" if "MA5" in df_disp.columns else "{:.2f}"}).hide(axis="index") # 💡 直接隱藏原本討厭的 0 1 2 3 序號欄！
    styled = styled.map(color, subset=["漲跌", "漲幅%"])
    styled = styled.apply(lambda r: apply_price_color(df_disp, r), subset=["價格"], axis=1)
    if "MA5" in df_disp.columns:
        styled = styled.apply(lambda r: apply_ma_color(df_disp, r), subset=["MA5", "MA10", "MA20"], axis=1)
        
    return styled.to_html(escape=False)


top_col1, top_col2 = st.columns([6, 4])

# === 左側：庫存股監控 ===
with top_col1:
    st.subheader("📌 庫存股監控")
    if not df_all.empty and "代號_raw" in df_all.columns:
        df_portfolio = df_all[df_all["代號_raw"].isin(final_portfolio_list)].reset_index(drop=True)
        if not df_portfolio.empty:
            df_portfolio_display = df_portfolio.drop(columns=["MA5", "MA10", "MA20", "均線狀態", "訊號"])
            html_table = render_styled_table(df_portfolio_display, "p")
            st.markdown(html_table, unsafe_allow_html=True)
        else: st.info("💡 目前庫存股為空。")
    else: st.info("💡 目前沒有資料。")

# === 右側：新聞直播 ===
with top_col2:
    st.subheader("📺 財經新聞直播設定")
    video_id = st.text_input("請輸入最新 YouTube 直播 ID (11碼):", value="1I2iq41Akmo", key="yt_video_id")
    st.video(f"https://www.youtube.com/watch?v={video_id}")

# === 下半部：自選明細 ===
st.divider()
with st.container():
    st.subheader("💼 自選明細完整儀表板")
    if not df_all.empty and "代號_raw" in df_all.columns:
        df_watchlist = df_all[df_all["代號_raw"].isin(final_watchlist_list)].reset_index(drop=True)
        if not df_watchlist.empty:
            html_table_w = render_styled_table(df_watchlist, "w")
            st.markdown(html_table_w, unsafe_allow_html=True)
        else: st.info("💡 目前自選股為空。")
    else: st.info("💡 目前沒有資料。")

# ===== 5. 自動循環刷新 =====
time.sleep(30)
st.rerun()
