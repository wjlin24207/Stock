import requests
import yfinance as yf
import pandas as pd
import urllib3
import time
from datetime import datetime, timedelta
import streamlit as st

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="KD監控儀表板", layout="wide")
st.title("📊 策略監控儀表板")

session = requests.Session()
session.headers.update({'User-Agent': 'Mozilla/5.0'})


# ===== 取得即時價格 =====
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


# ===== Yahoo 歷史資料 =====
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


# ===== KD + 策略 =====
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

        signal.append("📈 KD多方" if k > d else "📉 KD空方")

        if k < 30:
            signal.append("⚠️ KD超賣")
        elif k > 80:
            signal.append("🔥 KD超買")

        if ma5_y <= ma10_y and ma5_t > ma10_t:
            signal.append("✨ 均線黃金交叉")
        elif ma5_y >= ma10_y and ma5_t < ma10_t:
            signal.append("❌ 均線死亡交叉")

        ma_values = [ma5_t, ma10_t, ma20_t]
        ma_max = max(ma_values)
        ma_min = min(ma_values)

        if live_price > 0 and (ma_max - ma_min) / live_price < 0.02:
            signal.append("🟡 均線糾結")

        if live_price > ma5_t > ma10_t > ma20_t:
            ma_status = "🚀 均線多頭"
        elif live_price < ma5_t < ma10_t < ma20_t:
            ma_status = "💥 均線空頭"
        else:
            ma_status = "➖ 均線盤整"

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
            "KD訊號": " | ".join(signal)
        }

    except:
        return None


# ===== 顏色函數（重要）=====
def color(val):
    if val > 0:
        return "color:red"
    elif val < 0:
        return "color:green"
    return ""

def color_ma(val, price):
    if val < price:
        return "color:red"
    elif val > price:
        return "color:green"
    return ""


# ===== 主程式 =====
target_stocks = ["^TWII", "0056", "00878", "00919", "0050", "00981A", "00988A", "2330", "00631L"]

taiwan_time = datetime.utcnow() + timedelta(hours=8)
st.write("更新時間：", taiwan_time.strftime("%Y-%m-%d %H:%M:%S"))

if st.button("🔄 手動刷新"):
    st.rerun()

prices = get_all_live_prices(target_stocks)
hists = get_all_yahoo_hist(target_stocks)

rows = []

for sid in target_stocks:
    live = prices.get(sid)
    key = f"{sid}.TW" if not sid.startswith("^") else sid

    hist = None
    if isinstance(hists.columns, pd.MultiIndex):
        if key in hists.columns.levels[0]:
            hist = hists[key]
    else:
        hist = hists

    if live and hist is not None:
        result = process_kd_logic(sid, live, hist)
        if result:
            rows.append(result)

df = pd.DataFrame(rows)


if df.empty:
    st.error("❌ 抓不到資料")
else:
    styled = df.style.format({
        "價格": "{:,.2f}",
        "漲跌": "{:+,.2f}",
        "漲幅%": "{:+.2f}%",
        "K": "{:.2f}",
        "D": "{:.2f}",
        "MA5": "{:.2f}",
        "MA10": "{:.2f}",
        "MA20": "{:.2f}"
    })

    # ===== 漲跌顏色 =====
    def color(val):
        if val > 0:
            return "color:red"
        elif val < 0:
            return "color:green"
        return ""

    styled = styled.map(color, subset=["漲跌", "漲幅%"])

    # ===== ✅ 價格顏色（跟漲跌走）=====
    def apply_price(row):
        diff = df.loc[row.name, "漲跌"]

        if diff > 0:
            return ["color:red; font-weight:bold"]
        elif diff < 0:
            return ["color:green; font-weight:bold"]
        return [""]

    styled = styled.apply(
        apply_price,
        subset=["價格"],
        axis=1
    )

    # ===== ✅ 均線顏色 =====
    def color_ma(val, price):
        if val < price:
            return "color:red"
        elif val > price:
            return "color:green"
        return ""

    def apply_ma(row):
        price = df.loc[row.name, "價格"]

        return [
            color_ma(row["MA5"], price),
            color_ma(row["MA10"], price),
            color_ma(row["MA20"], price),
        ]

    styled = styled.apply(
        apply_ma,
        subset=["MA5", "MA10", "MA20"],
        axis=1
    )

    # ===== 顯示 =====
    st.dataframe(styled, use_container_width=True)


time.sleep(30)
st.rerun()
