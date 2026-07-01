import requests
import yfinance as yf
import pandas as pd
import urllib3
import time
from datetime import datetime, timedelta
import streamlit as st

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===== 1. 頁面初始化與設定 =====
st.set_page_config(page_title="自選股 KD 均線監控儀表板", layout="wide")

# ===== 2. 側邊控制面板 =====
st.sidebar.title("📊 控制面板")

taiwan_time = datetime.utcnow() + timedelta(hours=8)
st.sidebar.write(f"⏱️ 上次更新：{taiwan_time.strftime('%Y-%m-%d %H:%M:%S')}")

if st.sidebar.button("🔄 手動刷新資料"):
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.info("純淨自選股版：已移除不穩定的大盤 API 區塊，專注於個股與 ETF 的 KD 策略監控。")

# ===== 3. 資料抓取核心邏輯 =====
session = requests.Session()
session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})

def get_all_live_prices(stock_list):
    ex_ch_list = []
    for sid in stock_list:
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
                price_map[key] = info
        return price_map
    except:
        return {}

def get_all_yahoo_hist(stock_list):
    tickers = [f"{sid}.TW" for sid in stock_list]
    try:
        return yf.download(
            tickers,
            period="6mo",
            interval="1d",
            progress=False,
            group_by='ticker',
            auto_adjust=True
        )
    except:
        return pd.DataFrame()

def process_kd_logic(stock_id, live_info, hists_all):
    try:
        key = f"{stock_id}.TW"
        
        if isinstance(hists_all.columns, pd.MultiIndex):
            if key in hists_all.columns.levels[0]:
                hist = hists_all[key].dropna().copy()
            else:
                return None
        else:
            hist = hists_all.dropna().copy()

        if hist.empty:
            return None
            
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
        
        if 'close' in temp.columns:
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
# 已完全移除大盤符號 "^TWII"
watchlist_stocks = ["^TWII", "0056", "00878", "00919", "0050", "00981A", "00988A", "00631L", "2330", "3711"]

prices = get_all_live_prices(watchlist_stocks)
hists = get_all_yahoo_hist(watchlist_stocks)

# ==========================================
# ===== 5. 網頁版面布局 =====
# ==========================================

st.title("📊 策略監控儀表板（精簡專業版）")
st.markdown("---")

st.subheader("⭐ 自選股監控看板")

watch_rows = []
for sid in watchlist_stocks:
    live = prices.get(sid)
    if live and not hists.empty:
        result = process_kd_logic(sid, live, hists)
        if result:
            v_stock = live.get('v', '0')
            try:
                if v_stock not in ['-', '', None] and int(v_stock) > 0:
                    result["成交量(張)"] = f"{int(v_stock):,} 張"
                else:
                    result["成交量(張)"] = "0 張"
            except:
                result["成交量(張)"] = f"{v_stock} 張"
            watch_rows.append(result)

if not watch_rows:
    st.error("❌ 系統暫時無法獲取自選股即時數據，請點擊左側手動刷新重試。")
else:
    df = pd.DataFrame(watch_rows)
    df = df.rename(columns={"代號": "代號/K線", "名稱": "名稱/成份股"})
    
    col_order = ["代號/K線", "名稱/成份股", "價格", "漲跌", "漲幅%", "成交量(張)", "K", "D", "MA5", "MA10", "MA20", "均線狀態", "訊號"]
    df = df[[c for c in col_order if c in df.columns]]
    
    df["代號_raw"] = df["代號/K線"]

    def make_id_link(row):
        sid = row["代號_raw"]
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

    st.markdown("""
    <style>
    table { width: 100% !important; table-layout: auto; }
    td, th { white-space: nowrap; font-size: 14px; padding: 6px 10px !important; }
    div[data-testid="stMarkdownContainer"] { overflow-x: auto; }
    </style>
    """, unsafe_allow_html=True)

    st.markdown(styled.hide(axis='index').to_html(escape=False), unsafe_allow_html=True)

# ===== 6. 倒數計時並自動重整 (30秒) =====
time.sleep(30)
st.rerun()
