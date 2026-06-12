import requests
import yfinance as yf
import pandas as pd
import urllib3
import time
from datetime import datetime, timedelta
import streamlit as st
import streamlit.components.v1 as components

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
# ==================== 1. 頁面基本設定 ====================
st.set_page_config(page_title="KD監控儀表板", layout="wide")
st.title("📊 策略監控儀表板（專業版）")

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
            "訊號": " | ".join(signal)
        }

    except:
        return None


# ===== 2. 資料準備與計算 =====
# 這裡包含所有要追蹤的股票
target_stocks = ["^TWII", "0056", "00878", "00919", "0050", "00981A", "00988A", "00631L", "3711"]

# 頂部控制列（更新時間與手動刷新按鈕並排）
time_col1, time_col2 = st.columns([8, 2])
with time_col1:
    taiwan_time = datetime.utcnow() + timedelta(hours=8)
    st.write("⏱️ 更新時間：", taiwan_time.strftime("%Y-%m-%d %H:%M:%S"))
with time_col2:
    if st.button("🔄 手動刷新", use_container_width=True):
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

df = df.rename(columns={
    "代號": "代號/K線",
    "名稱": "名稱/成份股"
})


# 建立超連結處理
df["代號_raw"] = df["代號/K線"]

def make_id_link(row):
    sid = row["代號_raw"]
    if sid == "^TWII":
        url = "https://tw.stock.yahoo.com/tw-market"
    else:
        url = f"https://tw.stock.yahoo.com/quote/{sid}/technical-analysis"
    return f'<a href="{url}" target="_blank">{sid}</a>'

def make_name_link(row):
    sid = row["代跑_raw"] if "代跑_raw" in row else row["代號_raw"]
    name = row["名稱/成份股"]
    url = None
    if str(sid).startswith("00"):
        url = f"https://www.moneydj.com/ETF/X/Basic/Basic0007.xdjhtm?etfid={sid}.TW"
    if url:
        return f'<a href="{url}" target="_blank">{name}</a>'
    return name

df["名稱/成份股"] = df.apply(make_name_link, axis=1)
df["代號/K線"] = df.apply(make_id_link, axis=1)
df = df.drop(columns=["代號_raw"])




# ==================== 3. 畫面排版渲染 (核心修改區) ====================

# 定義全域表格 CSS 樣式
st.markdown("""
<style>
table { width: 100% !important; table-layout: auto; }
td, th { white-space: nowrap; font-size: 14px; padding: 6px 10px !important; }
div[data-testid="stMarkdownContainer"] { overflow-x: auto; }
</style>
""", unsafe_allow_html=True)

if df.empty:
    st.error("❌ 抓不到資料")
else:
    # 統一樣式美化設定
    styled = df.style.format({
        "價格": "{:,.2f}",
        "漲跌": "{:+,.2f}",
        "漲幅%": "{:+,.2f}%",
        "K": "{:.2f}",
        "D": "{:.2f}",
        "MA5": "{:.2f}",
        "MA10": "{:.2f}",
        "MA20": "{:.2f}"
    })

    def color(val):
        return "color:red" if val > 0 else "color:green" if val < 0 else ""
    styled = styled.map(color, subset=["漲跌", "漲幅%"])

    def apply_price(row):
        diff = df.loc[row.name, "漲跌"]
        return ["color:red; font-weight:bold"] if diff > 0 else ["color:green; font-weight:bold"] if diff < 0 else [""]
    styled = styled.apply(apply_price, subset=["價格"], axis=1)

    def color_ma(val, price):
        return "color:red" if val < price else "color:green" if val > price else ""

    def apply_ma(row):
        price = df.loc[row.name, "價格"]
        return [
            color_ma(row["MA5"], price),
            color_ma(row["MA10"], price),
            color_ma(row["MA20"], price)
        ]
    styled = styled.apply(apply_ma, subset=["MA5", "MA10", "MA20"], axis=1)
    
    # 將 Styler 轉換為 HTML 字串
    html_table = styled.to_html(escape=False)

    # ------------------ 畫面上半部：左右分欄 ------------------
    # 分配權重：自選股 65%, YouTube 直播 35%
    top_col1, top_col2 = st.columns([6, 4])

# === 左側：自選股監控 (簡化版) ===
    with top_col1:
       st.subheader("📌 自選股監控")
       # 1. 排除大盤，複製一份自選股資料
       df_watchlist = df[df["代號/K線"].str.contains("TWII") == False].copy()
       # 2. 移除自選股不需要的欄位
       drop_cols = ["MA5", "MA10", "MA20", "均線狀態", "訊號"]
       existing_drop_cols = [c for c in drop_cols if c in df_watchlist.columns]
       df_watchlist = df_watchlist.drop(columns=existing_drop_cols)
       # 3. 重新建立簡化版表格的樣式
       watch_styled = df_watchlist.style.format({
           "價格": "{:,.2f}", "漲跌": "{:+,.2f}", "漲幅%": "{:+,.2f}%", "K": "{:.2f}", "D": "{:.2f}"
       }).map(color, subset=["漲跌", "漲幅%"])
       watch_styled = watch_styled.apply(apply_price, subset=["價格"], axis=1)
       # 4. 渲染自選股
       st.markdown(watch_styled.to_html(escape=False), unsafe_allow_html=True)
   # === 右側：東森財經新聞直播 (含 ID 輸入欄位) ===
    with top_col2:
       st.subheader("📺 財經新聞直播設定")
       # 💡 【重新加回】：畫面上的直播 ID 輸入框，預設放您能用的 ID
       video_id = st.text_input(
           "請輸入最新 YouTube 直播 ID (11碼):",
           value="1I2iq41Akmo",
           key="yt_video_id"
       )
       # 串接輸入的 ID 並用標準播放器播放
       live_url = f"https://www.youtube.com/watch?v={video_id}"
       st.video(live_url)

    # ------------------ 畫面下半部：全寬獨占 ------------------
    st.divider()
    col_bottom = st.container()
    
    with col_bottom:
        st.subheader("💼 庫存明細 (範例)")
        # 這裡可以放你的庫存 DataFrame。目前先拿大盤「加權指數」當作下方的庫存示範範例
        df_inventory = df[df["代號/K線"].str.contains("TWII|00981A") == True]
        
        if not df_inventory.empty:
            # 這裡簡單呈現大盤在下方，你也可以直接換成 st.dataframe(你的真實庫存)
            st.info("💡 這裡可以放置您獨立的庫存資產表格，目前下方暫時獨立顯示大盤。")
            
            # 重新為庫存建立獨立樣式或直接渲染
            inv_styled = df_inventory.style.format({
                "價格": "{:,.2f}", "漲跌": "{:+,.2f}", "漲幅%": "{:+,.2f}%",
                "K": "{:.2f}", "D": "{:.2f}", "MA5": "{:.2f}", "MA10": "{:.2f}", "MA20": "{:.2f}"
            }).map(color, subset=["漲跌", "漲幅%"])
            
            st.markdown(inv_styled.to_html(escape=False), unsafe_allow_html=True)

# ===== 4. 自動循環刷新 =====
time.sleep(30)
st.rerun()
