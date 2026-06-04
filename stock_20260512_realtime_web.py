import requests
import yfinance as yf
import pandas as pd
import urllib3
import time
from datetime import datetime
import streamlit as st

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="KD監控儀表板", layout="wide")
st.title("📊 策略監控儀表板（專業版）")

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

        live_high = float(live_info.get('h', live_price) or live_price)
        live_low = float(live_info.get('l', live_price) or live_price)
        y_price = float(y)

        temp = hist.astype(float).copy()

        temp.iloc[-1, temp.columns.get_loc('close')] = live_price
        temp.iloc[-1, temp.columns.get_loc('high')] = live_high
        temp.iloc[-1, temp.columns.get_loc('low')] = live_low

        temp['9h'] = temp['high'].rolling(9).max()
        temp['9l'] = temp['low'].rolling(9).min()

        temp['rsv'] = 100 * (temp['close'] - temp['9l']) / (temp['9h'] - temp['9l'] + 1e-9)
        temp['rsv'] = temp['rsv'].fillna(50)

        k, d = 50, 50
        for rsv in temp['rsv']:
            k = k * (2/3) + rsv * (1/3)
            d = d * (2/3) + k * (1/3)

        diff = live_price - y_price
        percent = (diff / y_price * 100) if y_price > 0 else 0

        signal = []
        if k < 30:
            signal.append("⚠️ 超賣")
        elif k > 80:
            signal.append("🔥 超買")

        signal.append("📈 多方" if k > d else "📉 空方")

        name = live_info.get('n', stock_id)
        if stock_id == "^TWII":
            name = "加權指數"

        return {
            "代號": stock_id,
            "名稱": name,
            "價格": live_price,
            "漲跌": diff,
            "漲幅%": percent,
            "K": k,
            "D": d,
            "訊號": " | ".join(signal)
        }

    except:
        return None


# ===== 主程式 =====
target_stocks = ["^TWII", "0056", "00878", "00919", "0050", "00981A", "00988A", "2330", "00631L"]


from datetime import datetime, timedelta

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
        "D": "{:.2f}"
    })

    def color(val):
        return "color:red" if val > 0 else "color:green" if val < 0 else ""

    try:
        styled = styled.map(color, subset=["漲跌", "漲幅%"])
        st.dataframe(styled)
    except:
        st.dataframe(df)

time.sleep(30)
st.rerun()
