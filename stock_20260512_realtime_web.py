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
st.title("📊 策略監控儀表板（100% 原生極速版）")

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


# ==================== 2. 側邊欄控制台 ====================
st.sidebar.header("🛠️ 監控清單控制台")

mode = st.sidebar.selectbox(
    "請選擇要管理的清單：",
    options=["📌 庫存個股管理", "💼 自選明細管理"]
)
st.sidebar.markdown("---")

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


# ==================== 4. 畫面排版與【100% 原生分欄渲染】 ====================
# 全域文字美化與微調
st.markdown("""
<style>
div[data-testid="stMetric"] { background: #f8f9fa; padding: 5px 10px; border-radius: 5px; text-align: center; }
hr { margin: 15px 0 !important; }
</style>
""", unsafe_allow_html=True)

# 💡 數字格式化與顏色標記輔助函式
def get_colored_text(val, text_str, is_bold=False):
    bold_style = "font-weight:bold;" if is_bold else ""
    if val > 0: return f'<span style="color:red;{bold_style}">{text_str}</span>'
    elif val < 0: return f'<span style="color:green;{bold_style}">{text_str}</span>'
    return f'<span style="{bold_style}">{text_str}</span>'

def get_ma_color_text(val, price):
    if val < price: return f'<span style="color:red;">{val:,.2f}</span>'
    return f'<span style="color:green;">{val:,.2f}</span>'

def make_html_link(sid, name, is_etf=False):
    if sid == "^TWII":
        return '<a href="https://tw.stock.yahoo.com/tw-market" target="_blank">加權指數</a>'
    
    id_link = f'<a href="https://tw.stock.yahoo.com/quote/{sid}/technical-analysis" target="_blank">{sid}</a>'
    if is_etf:
        name_link = f'<a href="https://www.moneydj.com/ETF/X/Basic/Basic0007.xdjhtm?etfid={sid}.TW" target="_blank">{name}</a>'
    else:
        name_link = name
    return id_link, name_link


top_col1, top_col2 = st.columns([6, 4])

# === 左側：📌 庫存股監控 (原生排版) ===
with top_col1:
    st.subheader("📌 庫存股監控")
    
    # 篩選庫存股資料
    df_portfolio = df_all[df_all["代號"].isin(final_portfolio_list)].copy()
    
    if not df_portfolio.empty:
        # 表頭列配置
        h_cols = st.columns([0.6, 1.2, 2.0, 1.2, 1.2, 1.2, 1.0, 1.0])
        h_cols[0].markdown("**操作**")
        h_cols[1].markdown("**代號**")
        h_cols[2].markdown("**名稱**")
        h_cols[3].markdown("**價格**")
        h_cols[4].markdown("**漲跌**")
        h_cols[5].markdown("**漲幅%**")
        h_cols[6].markdown("**K**")
        h_cols[7].markdown("**D**")
        st.divider()
        
        # 逐筆渲染股票數據，並在最前面配備真正的 st.button ❌
        for idx, row in df_portfolio.iterrows():
            sid = row["代號"]
            diff = row["漲跌"]
            
            # 超連結轉換
            id_html, name_html = make_html_link(sid, row["名稱"], str(sid).startswith("00"))
            
            r_cols = st.columns([0.6, 1.2, 2.0, 1.2, 1.2, 1.2, 1.0, 1.0])
            
            # 💡 核心刪除：點擊 ❌ 後直接後台移除，完全不需要網頁指令穿透，絕不失效！
            if r_cols[0].button("❌", key=f"del_p_{sid}", help=f"刪除 {sid}", use_container_width=True):
                st.session_state.stored_portfolio.remove(sid)
                st.rerun()
                
            r_cols[1].markdown(id_html, unsafe_allow_html=True)
            r_cols[2].markdown(name_html, unsafe_allow_html=True)
            r_cols[3].markdown(get_colored_text(diff, f"{row['價格']:,.2f}", is_bold=True), unsafe_allow_html=True)
            r_cols[4].markdown(get_colored_text(diff, f"{diff:+,.2f}"), unsafe_allow_html=True)
            r_cols[5].markdown(get_colored_text(diff, f"{row['漲幅%']:+,.2f}%"), unsafe_allow_html=True)
            r_cols[6].markdown(f"{row['K']:.2f}")
            r_cols[7].markdown(f"{row['D']:.2f}")
            st.write('<div style="margin:-5px 0;"></div>', unsafe_allow_html=True) # 微調縮小行距
    else:
        st.info("💡 目前庫存股為空。")

# === 右側：電視新聞直播 ===
with top_col2:
    st.subheader("📺 財經新聞直播設定")
    video_id = st.text_input("請輸入最新 YouTube 直播 ID (11碼):", value="1I2iq41Akmo", key="yt_video_id")
    st.video(f"https://www.youtube.com/watch?v={video_id}")


# === 下半部：💼 自選明細完整儀表板 (原生排版) ===
st.divider()
with st.container():
    st.subheader("💼 自選明細完整儀表板")
    
    df_watchlist = df_all[df_all["代號"].isin(final_watchlist_list)].copy()
    
    if not df_watchlist.empty:
        # 表頭配置
        w_cols = st.columns([0.5, 1.0, 1.5, 1.0, 1.0, 1.0, 0.8, 0.8, 1.0, 1.0, 1.0, 1.2, 2.5])
        w_cols[0].markdown("**操作**")
        w_cols[1].markdown("**代號**")
        w_cols[2].markdown("**名稱**")
        w_cols[3].markdown("**價格**")
        w_cols[4].markdown("**漲跌**")
        w_cols[5].markdown("**漲幅%**")
        w_cols[6].markdown("**K**")
        w_cols[7].markdown("**D**")
        w_cols[8].markdown("**MA5**")
        w_cols[9].markdown("**MA10**")
        w_cols[10].markdown("**MA20**")
        w_cols[11].markdown("**均線狀態**")
        w_cols[12].markdown("**訊號**")
        st.divider()
        
        for idx, row in df_watchlist.iterrows():
            sid = row["代號"]
            diff = row["漲跌"]
            price = row["價格"]
            
            id_html, name_html = make_html_link(sid, row["名稱"], str(sid).startswith("00"))
            if sid == "^TWII":
                name_html = "加權指數"
            
            r_cols = st.columns([0.5, 1.0, 1.5, 1.0, 1.0, 1.0, 0.8, 0.8, 1.0, 1.0, 1.0, 1.2, 2.5])
            
            # 💡 核心刪除自選：原生按鈕點擊，秒殺下架
            if r_cols[0].button("❌", key=f"del_w_{sid}", help=f"刪除 {sid}", use_container_width=True):
                st.session_state.stored_watchlist.remove(sid)
                st.rerun()
                
            r_cols[1].markdown(id_html, unsafe_allow_html=True)
            r_cols[2].markdown(name_html, unsafe_allow_html=True)
            r_cols[3].markdown(get_colored_text(diff, f"{price:,.2f}", is_bold=True), unsafe_allow_html=True)
            r_cols[4].markdown(get_colored_text(diff, f"{diff:+,.2f}"), unsafe_allow_html=True)
            r_cols[5].markdown(get_colored_text(diff, f"{row['漲幅%']:+,.2f}%"), unsafe_allow_html=True)
            r_cols[6].markdown(f"{row['K']:.2f}")
            r_cols[7].markdown(f"{row['D']:.2f}")
            
            # 均線顏色標記
            r_cols[8].markdown(get_ma_color_text(row["MA5"], price), unsafe_allow_html=True)
            r_cols[9].markdown(get_ma_color_text(row["MA10"], price), unsafe_allow_html=True)
            r_cols[10].markdown(get_ma_color_text(row["MA20"], price), unsafe_allow_html=True)
            
            r_cols[11].markdown(f"{row['均線狀態']}")
            r_cols[12].markdown(f"{row['訊號']}")
            st.write('<div style="margin:-5px 0;"></div>', unsafe_allow_html=True)
    else:
        st.info("💡 目前自選股為空。")

# ===== 5. 自動循環刷新 =====
time.sleep(30)
st.rerun()
