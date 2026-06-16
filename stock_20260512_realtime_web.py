import requests
import yfinance as yf
import pandas as pd
import urllib3
import time
from datetime import datetime, timedelta
import streamlit as st
import plotly.graph_objects as go

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===== 1. 頁面初始化與設定 =====
st.set_page_config(page_title="KD監控儀表板 (即時走勢版)", layout="wide")

# 初始化大盤歷史走勢紀錄器（用來存當天開盤到現在的即時點數，避免刷新時不見）
if "twii_history" not in st.session_state:
    st.session_state.twii_history = pd.DataFrame(columns=["時間", "點數"])

# ===== 2. 側邊控制面板 =====
st.sidebar.title("📊 控制面板")

taiwan_time = datetime.utcnow() + timedelta(hours=8)
st.sidebar.write(f"⏱️ 上次更新：{taiwan_time.strftime('%Y-%m-%d %H:%M:%S')}")

if st.sidebar.button("🔄 手動刷新資料"):
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.info("本儀表板大盤走勢圖採用動態流線繪製，會隨著每一次自動刷新（預設30秒）實時累加最新點數。")

# ===== 3. 資料抓取核心邏輯 =====
session = requests.Session()
session.headers.update({'User-Agent': 'Mozilla/5.0'})

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
        signal.append("📈多" if k > d else "📉空")

        if k < 30:
            signal.append("⚠️超賣")
        elif k > 80:
            signal.append("🔥超買")

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
            "均線狀態": ma_status,
            "訊號": " ".join(signal)
        }
    except:
        return None


# ===== 4. 主程式資料流準備 =====
# 定義你的庫存股與自選股清單
inventory_stocks = ["2330", "0050", "3711"]
watchlist_stocks = ["^TWII", "0056", "00878", "00919", "00981A", "00988A", "00631L"]
all_target_stocks = list(set(inventory_stocks + watchlist_stocks))

# 抓取即時數據
prices = get_all_live_prices(all_target_stocks)
hists = get_all_yahoo_hist(all_target_stocks)


# ==========================================
# ===== 5. 網頁版面布局 (精準還原圖示) =====
# ==========================================

st.title("📊 策略監控儀表板（專業版）")
st.markdown("---")

# --- 第一層：左右分割 [庫存 | 大盤與指標] ---
main_col_left, main_col_right = st.columns([1, 2])

# 【左上區塊：庫存】
with main_col_left:
    st.subheader("📋 我的庫存")
    inv_rows = []
    for sid in inventory_stocks:
        live = prices.get(sid)
        key = f"{sid}.TW" if not sid.startswith("^") else sid
        
        hist = None
        if isinstance(hists.columns, pd.MultiIndex):
            if key in hists.columns.levels[0]: hist = hists[key]
        else: hist = hists

        if live and hist is not None:
            res = process_kd_logic(sid, live, hist)
            if res: inv_rows.append(res)
            
    if inv_rows:
        inv_df = pd.DataFrame(inv_rows)
        # 庫存區欄位精簡，避免擠壓變形
        st.dataframe(inv_df[["代號", "名稱", "價格", "漲幅%", "訊號"]], use_container_width=True, hide_index=True)
    else:
        st.info("暫無庫存資料")


# 【右上區塊：大盤即時走勢 + 其他指標】
with main_col_right:
    sub_col_chart, sub_col_metric = st.columns(2)
    
    # 1. 真正的即時單日走勢圖
    with sub_col_chart:
        st.subheader("📈 當日加權指數即時走勢")
        twii_live = prices.get("^TWII")
        if twii_live:
            # 獲取當前點數與時間
            current_point = twii_live.get('z', '-')
            if current_point in ['-', '', None]:
                current_point = twii_live.get('y', '0')
            current_point = float(current_point)
            current_time = twii_live.get('t', datetime.now().strftime("%H:%M:%S"))
            
            # 塞入 Session State 歷史紀錄中
            new_data = pd.DataFrame([{"時間": current_time, "點數": current_point}])
            if st.session_state.twii_history.empty or st.session_state.twii_history["時間"].iloc[-1] != current_time:
                st.session_state.twii_history = pd.concat([st.session_state.twii_history, new_data], ignore_index=True)
            
            # 畫出走勢折線圖
            if not st.session_state.twii_history.empty:
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=st.session_state.twii_history["時間"],
                    y=st.session_state.twii_history["點數"],
                    mode='lines',
                    name='大盤即時走勢',
                    line=dict(color='#FF4B4B', width=2.5)
                ))
                y_max = st.session_state.twii_history["點數"].max() * 1.0005
                y_min = st.session_state.twii_history["點數"].min() * 0.9995
                fig.update_layout(
                    margin=dict(l=10, r=10, t=10, b=10),
                    height=260,
                    yaxis=dict(range=[y_min, y_max], tickformat=",.0f"),
                    template="plotly_dark" if st.get_option("theme.base") == "dark" else "plotly_white"
                )
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("正在接收大盤即時數據...")

    # 2. 其他關鍵指標看板
    with sub_col_metric:
        st.subheader("🔍 其他關鍵指標")
        if twii_live:
            z_val = float(twii_live.get('z', twii_live.get('y', 0)))
            y_val = float(twii_live.get('y', 0))
            diff_val = z_val - y_val
            st.metric(label="加權指數最新點數", value=f"{z_val:,.2f}", delta=f"{diff_val:+,.2f}")
        else:
            st.metric(label="加權指數最新點數", value="讀取中...")
        st.metric(label="預估成交量", value="3,850 億")
        st.metric(label="市場信心指標", value="多方控盤")


st.markdown("---")


# --- 第二層：下方全寬 [自選股] ---
st.subheader("⭐ 自選股監控看板")

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

if not watch_rows:
    st.error("❌ 抓不到自選股資料")
else:
    df = pd.DataFrame(watch_rows)
    df = df.rename(columns={"代號": "代號/K線", "名稱": "名稱/成份股"})
    df["代號_raw"] = df["代號/K線"]

    # 點擊連結設定
    def make_id_link(row):
        sid = row["代raw"] if "代raw" in row else row["代號_raw"]
        if sid == "^TWII": return f'<a href="https://tw.stock.yahoo.com/tw-market" target="_blank">{sid}</a>'
        return f'<a href="https://tw.stock.yahoo.com/quote/{sid}/technical-analysis" target="_blank">{sid}</a>'

    def make_name_link(row):
        sid = row["代號_raw"]
        name = row["名稱/成份股"]
        if str(sid).startswith("00"):
            return f'<a href="https://www.moneydj.com/ETF/X/Basic/Basic0007.xdjhtm?etfid={sid}.TW" target="_blank">{name}</a>'
        return name

    df["名稱/成份股"] = df.apply(make_name_link, axis=1)
    df["代號/K線"] = df.apply(make_id_link, axis=1)
    df = df.drop(columns=["代號_raw"])

    # 樣式渲染
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

    # 注入全螢幕響應式 CSS 排版
    st.markdown("""
    <style>
    table { width: 100% !important; table-layout: auto; }
    td, th { white-space: nowrap; font-size: 14px; padding: 6px 10px !important; }
    div[data-testid="stMarkdownContainer"] { overflow-x: auto; }
    </style>
    """, unsafe_allow_html=True)

    st.markdown(styled.to_html(escape=False), unsafe_allow_html=True)


# ===== 6. 倒數計時並自動重整 (30秒) =====
time.sleep(30)
st.rerun()
