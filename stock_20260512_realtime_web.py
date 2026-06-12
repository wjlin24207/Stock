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


# ===== 即時價格 =====
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


# ===== Yahoo資料 =====
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


# ===== KD =====
def process_kd_logic(stock_id, live_info, hist_df):
    try:
        if hist_df is None or hist_df.empty:
            return None

        hist = hist_df.dropna().copy()
        hist.columns = [c.lower() for c in hist.columns]

        z = live_info.get('z', '-')
        y = live_info.get('y', '0')

        live_price = float(z) if z not in ['-', ''] else float(y)
        y_price = float(y)

        temp = hist.astype(float).copy()
        temp.iloc[-1, temp.columns.get_loc('close')] = live_price

        temp['9h'] = temp['high'].rolling(9).max()
        temp['9l'] = temp['low'].rolling(9).min()
        temp['rsv'] = 100 * (temp['close'] - temp['9l']) / (temp['9h'] - temp['9l'] + 1e-9)

        k, d = 50, 50
        for rsv in temp['rsv'].fillna(50):
            k = k*2/3 + rsv/3
            d = d*2/3 + k/3

        ma5 = temp['close'].rolling(5).mean().iloc[-1]
        ma10 = temp['close'].rolling(10).mean().iloc[-1]
        ma20 = temp['close'].rolling(20).mean().iloc[-1]

        return {
            "代號": stock_id,
            "名稱": "加權指數" if stock_id == "^TWII" else stock_id,
            "價格": round(live_price, 2),
            "漲跌": round(live_price - y_price, 2),
            "漲幅%": round((live_price - y_price)/y_price*100, 2) if y_price else 0,
            "K": round(k, 2),
            "D": round(d, 2),
            "MA5": round(ma5, 2),
            "MA10": round(ma10, 2),
            "MA20": round(ma20, 2)
        }
    except:
        return None


# ==================== 股票清單 ====================
target_stocks = ["^TWII", "0056", "00878", "00919", "0050", "00981A", "00988A", "00631L", "2330", "3711"]
inventory_stocks = ["^TWII", "2454", "2317"]

# ✅ 正確保留順序（不使用 set）
all_stocks = target_stocks + [s for s in inventory_stocks if s not in target_stocks]


# ===== UI =====
col1, col2 = st.columns([8,2])
with col1:
    tw_time = datetime.utcnow() + timedelta(hours=8)
    st.write("⏱️ 更新時間：", tw_time.strftime("%Y-%m-%d %H:%M:%S"))
with col2:
    if st.button("🔄 手動刷新"):
        st.rerun()


# ===== 抓資料 =====
prices = get_all_live_prices(all_stocks)
hists = get_all_yahoo_hist(all_stocks)

rows = []
for sid in all_stocks:
    live = prices.get(sid)
    key = f"{sid}.TW" if not sid.startswith("^") else sid

    hist = None
    if isinstance(hists.columns, pd.MultiIndex):
        if key in hists.columns.levels[0]:
            hist = hists[key]
    else:
        hist = hists

    if live and hist is not None:
        r = process_kd_logic(sid, live, hist)
        if r:
            rows.append(r)

df = pd.DataFrame(rows)

if df.empty:
    st.error("❌ 抓不到資料")
    st.stop()

# ✅ 加 raw
df["代號_raw"] = df["代號"]


# ==================== 畫面 ====================
top_col1, top_col2 = st.columns([6,4])

# 左：自選股
with top_col1:
    st.subheader("📌 自選股監控")
    df_watch = df[df["代號_raw"].isin(target_stocks)].copy()
    df_watch = df_watch.drop(columns=["代號_raw"])
    st.dataframe(df_watch, use_container_width=True)

# 右：YouTube
with top_col2:
    st.subheader("📺 財經新聞直播")
    video_id = st.text_input("輸入YouTube ID", value="1I2iq41Akmo")
    st.video(f"https://www.youtube.com/watch?v={video_id}")

# 下：庫存
st.divider()
st.subheader("💼 庫存明細")

df_inventory = df[df["代號_raw"].isin(inventory_stocks)].copy()
df_inventory = df_inventory.drop(columns=["代號_raw"])

st.dataframe(df_inventory, use_container_width=True)


# ===== 自動刷新 =====
time.sleep(30)
st.rerun()
