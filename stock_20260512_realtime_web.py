import yfinance as yf
import pandas as pd
import time
from datetime import datetime, timedelta
import streamlit as st

# ==================== 1. 頁面基本設定 ====================
st.set_page_config(page_title="KD監控儀表板", layout="wide")
st.title("📊 策略監控儀表板（Yahoo 穩定版）")

# ===== Yahoo資料 =====
def get_all_yahoo_hist(stock_list):
    tickers = [f"{sid}.TW" if not sid.startswith("^") else sid for sid in stock_list]

    for i in range(3):
        try:
            df = yf.download(
                tickers,
                period="6mo",
                interval="1d",
                progress=False,
                group_by='ticker',
                auto_adjust=True
            )
            return df
        except Exception as e:
            print(f"Yahoo retry {i+1}: {e}")
            time.sleep(2)

    return pd.DataFrame()


def process_kd_logic(stock_id, hist_df):
    try:
        if hist_df is None or hist_df.empty:
            return None

        hist = hist_df.dropna().copy()
        hist.columns = [c.lower() for c in hist.columns]

        # ✅ 直接用最新收盤當「即時價」
        live_price = float(hist['close'].iloc[-1])
        y_price = float(hist['close'].iloc[-2])

        temp = hist.astype(float).copy()

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
        signal.append("📈 KD多方" if k > d else "📉 KD空方")

        if k < 30:
            signal.append("⚠️ KD超賣")
        elif k > 80:
            signal.append("🔥 KD超買")

        if ma5_y <= ma10_y and ma5_t > ma10_t:
            signal.append("✨ 均線黃金交叉")
        elif ma5_y >= ma10_y and ma5_t < ma10_t:
            signal.append("❌ 均線死亡交叉")

        if live_price > ma5_t > ma10_t > ma20_t:
            ma_status = "🚀 均線多頭"
        elif live_price < ma5_t < ma10_t < ma20_t:
            ma_status = "💥 均線空頭"
        else:
            ma_status = "➖ 均線盤整"

        name = stock_id if stock_id != "^TWII" else "加權指數"

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
            "訊號": " | ".join(signal)
        }

    except Exception as e:
        print(f"process error {stock_id}: {e}")
        return None


# ===== 股票清單 =====
target_stocks = ["^TWII", "0056", "00878", "00919", "0050", "00981A", "00988A", "00631L", "2330", "3711"]

# ===== 顯示時間 =====
col1, col2 = st.columns([8, 2])
with col1:
    taiwan_time = datetime.utcnow() + timedelta(hours=8)
    st.write("⏱️ 更新時間：", taiwan_time.strftime("%Y-%m-%d %H:%M:%S"))

with col2:
    if st.button("🔄 手動刷新"):
        st.rerun()

# ===== 抓資料 =====
hists = get_all_yahoo_hist(target_stocks)

rows = []
for sid in target_stocks:
    key = f"{sid}.TW" if not sid.startswith("^") else sid

    hist = None
    if isinstance(hists.columns, pd.MultiIndex):
        if key in hists.columns.levels[0]:
            hist = hists[key]
    else:
        hist = hists

    result = process_kd_logic(sid, hist)
    if result:
        rows.append(result)

df = pd.DataFrame(rows)

if df.empty:
    st.error("❌ Yahoo 沒抓到資料")
    st.stop()

df = df.rename(columns={
    "代號": "代號/K線",
    "名稱": "名稱/成份股"
})

# ===== 表格顯示 =====
st.dataframe(df, use_container_width=True)

# ===== 自動刷新 =====
time.sleep(30)
st.rerun()
