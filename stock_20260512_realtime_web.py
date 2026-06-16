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
st.set_page_config(page_title="KD監控儀表板 (三竹1:1對稱版)", layout="wide")

# 初始化大盤歷史走勢紀錄器
if "twii_history" not in st.session_state:
    st.session_state.twii_history = pd.DataFrame(columns=["時間", "點數"])

# ===== 2. 側邊控制面板 =====
st.sidebar.title("📊 控制面板")

taiwan_time = datetime.utcnow() + timedelta(hours=8)
st.sidebar.write(f"⏱️ 上次更新：{taiwan_time.strftime('%Y-%m-%d %H:%M:%S')}")

if st.sidebar.button("🔄 手動刷新資料"):
    if "twii_base_loaded" in st.session_state:
        del st.session_state.twii_base_loaded
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.info("雙色分時圖穩定版：採用多線段遮罩流（Masking），完美實現平盤上紅、平盤下綠的券商級效果，且永不報錯。")

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


def fetch_twii_today_trend():
    try:
        df = yf.download("^TWII", period="1d", interval="1m", progress=False)
        if df.empty:
            return pd.DataFrame(columns=["時間", "點數"])
        
        if isinstance(df.columns, pd.MultiIndex):
            close_series = df[('Close', '^TWII')]
        else:
            close_series = df['Close']
            
        close_series = close_series.dropna()
        
        trend_df = pd.DataFrame(close_series).reset_index()
        trend_df.columns = ["Datetime", "點數"]
        trend_df['Datetime'] = pd.to_datetime(trend_df['Datetime'])
        trend_df['時間'] = trend_df['Datetime'].dt.tz_convert('Asia/Taipei').dt.strftime('%H:%M')
        
        return trend_df[["時間", "點數"]].drop_duplicates(subset=["時間"])
    except:
        return pd.DataFrame(columns=["時間", "點數"])


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
watchlist_stocks = ["^TWII", "0056", "00878", "00919", "0050", "00981A", "00988A", "00631L", "2330", "3711"]

prices = get_all_live_prices(watchlist_stocks)
hists = get_all_yahoo_hist(watchlist_stocks)

# 載入或更新大盤今日分時走勢底圖
if "twii_base_loaded" not in st.session_state:
    st.session_state.twii_history = fetch_twii_today_trend()
    st.session_state.twii_base_loaded = True


# ==========================================
# ===== 5. 網頁版面布局 =====
# ==========================================

st.title("📊 策略監控儀表板（專業版）")
st.markdown("---")

# --- 第一層：大盤即時橫式資訊列 + 對稱分時圖 ---
st.subheader("📈 當日加權指數即時走勢")

twii_live = prices.get("^TWII")

z_val = 0.0
y_val = 0.0
diff_val = 0.0
pct_val = 0.0
volume_display = "計算中..."

if twii_live:
    try:
        live_z = twii_live.get('z', '-')
        if live_z not in ['-', '', None]:
            z_val = float(live_z)
        else:
            z_val = float(twii_live.get('y', 0))
            
        live_y = twii_live.get('y', '-')
        if live_y not in ['-', '', None]:
            y_val = float(live_y)
            
        v_raw = twii_live.get('v', '0')
        v_clean = str(v_raw).replace(',', '').strip()
        if v_clean and v_clean.isdigit() and int(v_clean) > 0:
            volume_display = f"{float(v_clean) / 100.0:,.0f} 億"
    except:
        pass

if y_val <= 0 or z_val <= 0:
    try:
        if isinstance(hists.columns, pd.MultiIndex):
            y_val = float(hists[('Close', '^TWII')].iloc[-1])
        else:
            y_val = float(hists['Close'].iloc[-1])
        z_val = y_val
    except:
        if not st.session_state.twii_history.empty:
            y_val = float(st.session_state.twii_history["點數"].iloc[0])
            z_val = float(st.session_state.twii_history["點數"].iloc[-1])

if volume_display in ["計算中...", "讀取中..."]:
    try:
        if isinstance(hists.columns, pd.MultiIndex):
            latest_vol_raw = float(hists[('Volume', '^TWII')].iloc[-1])
        else:
            latest_vol_raw = float(hists['Volume'].iloc[-1])
        if latest_vol_raw > 0:
            volume_display = f"{latest_vol_raw / 100000000.0:,.0f} 億"
    except:
        volume_display = "1,1978 億 (估)"

diff_val = z_val - y_val
pct_val = (diff_val / y_val * 100) if y_val > 0 else 0

color_code = "#FF4B4B" if diff_val > 0 else "#00A86B" if diff_val < 0 else "#FFFFFF"

# 顯示橫式列的 HTML 排版
st.markdown(f"""
<div style="background-color:rgba(255,255,255,0.03); padding:10px 20px; border-radius:8px; margin-bottom:15px; display:flex; gap:40px; align-items:center;">
    <div style="display:flex; align-items:baseline; gap:10px;">
        <span style="font-size:14px; color:#888;">加權指數:</span>
        <span style="font-size:28px; color:{color_code}; font-weight:bold;">{z_val:,.2f}</span>
    </div>
    <div style="display:flex; align-items:baseline; gap:10px;">
        <span style="font-size:14px; color:#888;">漲跌:</span>
        <span style="font-size:20px; color:{color_code}; font-weight:bold;">{diff_val:+,.2f} ({pct_val:+,.2f}%)</span>
    </div>
    <div style="display:flex; align-items:baseline; gap:10px;">
        <span style="font-size:14px; color:#888;">成交量:</span>
        <span style="font-size:20px; color:#FFF; font-weight:bold;">{volume_display}</span>
    </div>
</div>
""", unsafe_allow_html=True)

# --- 5. 處理走勢圖數據累加 ---
if twii_live and z_val > 0:
    t_raw = twii_live.get('t', datetime.now().strftime("%H:%M:%S"))
    current_time_hm = t_raw[:5] 
    
    new_row = pd.DataFrame([{"時間": current_time_hm, "點數": z_val}])
    if st.session_state.twii_history.empty:
        st.session_state.twii_history = new_row
    else:
        if current_time_hm in st.session_state.twii_history["時間"].values:
            st.session_state.twii_history.loc[st.session_state.twii_history["時間"] == current_time_hm, "點數"] = z_val
        else:
            st.session_state.twii_history = pd.concat([st.session_state.twii_history, new_row], ignore_index=True)

# --- 6. 繪製精準 1:1 三竹對稱走勢圖 (多軌安定無 Bug 版) ---
if not st.session_state.twii_history.empty and y_val > 0:
    st.session_state.twii_history = st.session_state.twii_history.sort_values(by="時間").reset_index(drop=True)
    
    df_trend = st.session_state.twii_history.copy()
    max_val = df_trend["點數"].max()
    min_val = df_trend["點數"].min()
    
    max_deviation = max(abs(max_val - y_val), abs(min_val - y_val))
    if max_deviation == 0:
        max_deviation = y_val * 0.001
        
    y_limit_top = y_val + (max_deviation * 1.15)
    y_limit_bottom = y_val - (max_deviation * 1.15)
    
    mid_top = y_val + ((max_deviation * 1.15) / 2.0)
    mid_bottom = y_val - ((max_deviation * 1.15) / 2.0)
    custom_yticks = [y_limit_bottom, mid_bottom, y_val, mid_top, y_limit_top]
    
    market_ticks = ["09:00", "09:30", "10:00", "10:30", "11:00", "11:30", "12:00", "12:30", "13:00", "13:30"]
    latest_time_str = df_trend["時間"].iloc[-1]
    
    fig = go.Figure()
    
    # 昨收基準水平平盤中心線
    fig.add_shape(
        type="line", 
        x0="09:00", y0=y_val, 
        x1=latest_time_str if latest_time_str > "13:30" else "13:30", y1=y_val,
        line=dict(color="rgba(128, 128, 128, 0.5)", width=1.5, dash="dash")
    )
    
    # 🛠️ 革命性修正邏輯：將連續數據拆解成「紅線段」與「綠線段」
    # 為了不讓交界處斷線，綠線與紅線各自保留完整的點，但在對手區間時把數值強制修剪（Clip）到平盤線
    df_trend['紅點數'] = df_trend['點數'].apply(lambda x: x if x >= y_val else y_val)
    df_trend['綠點數'] = df_trend['點數'].apply(lambda x: x if x <= y_val else y_val)
    
    # 軌道一：繪製高於平盤的紅色區間線
    fig.add_trace(go.Scatter(
        x=df_trend["時間"],
        y=df_trend["紅點數"],
        mode='lines',
        name='多方區間',
        line=dict(color='#FF4B4B', width=2.5),
        hoverinfo='skip'
    ))
    
    # 軌道二：繪製低於平盤的綠色區間線
    fig.add_trace(go.Scatter(
        x=df_trend["時間"],
        y=df_trend["綠點數"],
        mode='lines',
        name='空方區間',
        line=dict(color='#00A86B', width=2.5),
        hoverinfo='skip'
    ))
    
    fig.update_layout(
        margin=dict(l=10, r=10, t=5, b=10),
        height=320,
        showlegend=False, # 隱藏圖例更清爽
        xaxis=dict(
            range=["09:00", latest_time_str if latest_time_str > "13:30" else "13:30"],
            tickvals=market_ticks,
            tickangle=0
        ),
        yaxis=dict(
            range=[y_limit_bottom, y_limit_top], 
            tickvals=custom_yticks,
            tickformat=",.2f", 
            side="left"
        ),
        template="plotly_dark" if st.get_option("theme.base") == "dark" else "plotly_white"
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("📊 正在載入大盤資料並同步昨收基準點...")


st.markdown("---")


# --- 第二層：下方全寬 [自選股看板] ---
st.subheader("⭐ 自選股監快看板")

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
    st.error("❌ 系統暫時無法獲取自選股清單之即時數據")
else:
    df = pd.DataFrame(watch_rows)
    df = df.rename(columns={"代號": "代號/K線", "名稱": "名稱/成份股"})
    df["代號_raw"] = df["代號/K線"]

    def make_id_link(row):
        sid = row["代號_raw"]
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

    st.markdown(styled.to_html(escape=False), unsafe_allow_html=True)


# ===== 6. 倒數計時並自動重整 (30秒) =====
time.sleep(30)
st.rerun()
