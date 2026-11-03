import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(page_title="ETF 走勢與 KD 觀測站", layout="wide")

# --- 1. 讀取 ETF 清單 ---
@st.cache_data
def load_etf_list():
    return pd.DataFrame({
        '股票代號': ['00878.TW', '0050.TW', '0056.TW', '00919.TW', '006208.TW'],
        '股票名稱': ['國泰永續高股息', '元大台灣50', '元大高股息', '群益台灣精選高息', '富邦台50']
    })

etf_df = load_etf_list()
etf_records = etf_df.to_dict('records') 
tab_labels = [f"{item['股票代號'].split('.')[0]}" for item in etf_records]

# --- 2. 新增指標切換選項 ---
st.markdown("### ⚙️ 圖表指標設定")
indicator_choice = st.radio(
    "請選擇要疊加在走勢圖上的指標：",
    ("無", "均線 (5日, 月線, 季線)", "布林通道"),
    horizontal=True
)

# --- 3. 建立頂部頁籤 (Tabs) ---
tabs = st.tabs(tab_labels)

# --- 4. 抓取資料與計算指標的共用函式 ---
@st.cache_data(ttl=3600)
def load_stock_data(ticker_symbol):
    ticker = yf.Ticker(ticker_symbol)
    df = ticker.history(period="6mo")
    
    if df.empty:
        return df
        
    n = 9
    low_min = df['Low'].rolling(window=n, min_periods=1).min()
    high_max = df['High'].rolling(window=n, min_periods=1).max()
    df['RSV'] = 100 * (df['Close'] - low_min) / (high_max - low_min)
    
    K_list, D_list = [], []
    k, d = 50.0, 50.0
    for rsv in df['RSV'].fillna(50):
        k = (2/3) * k + (1/3) * rsv
        d = (2/3) * d + (1/3) * k
        K_list.append(k)
        D_list.append(d)
        
    df['K'] = K_list
    df['D'] = D_list
    
    df['MA5'] = df['Close'].rolling(window=5).mean()
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA60'] = df['Close'].rolling(window=60).mean()
    
    df['BB_Mid'] = df['MA20']
    std_20 = df['Close'].rolling(window=20).std()
    df['BB_Upper'] = df['BB_Mid'] + 2 * std_20
    df['BB_Lower'] = df['BB_Mid'] - 2 * std_20
    
    df = df.tail(30)
    df.index = df.index.strftime('%Y-%m-%d')
    return df

# --- 5. 遍歷每個頁籤並填入內容 ---
for i, tab in enumerate(tabs):
    with tab:
        current_etf = etf_records[i]
        selected_ticker = current_etf['股票代號']
        selected_name = current_etf['股票名稱']
        display_code = selected_ticker.split('.')[0]
        
        st.title(f"📊 {display_code} ({selected_name}) 近 30 日走勢與 KD 指標")

        with st.spinner(f'{display_code} 資料讀取中...'):
            df = load_stock_data(selected_ticker)
            
        if not df.empty and len(df) == 30:
            fig = make_subplots(
                rows=2, cols=1, 
                shared_xaxes=True, 
                vertical_spacing=0.1,
                row_heights=[0.7, 0.3]
            )

            # --- 上方：收盤價折線 (加入數值顯示) ---
            fig.add_trace(go.Scatter(
                x=df.index, y=df['Close'], 
                mode='lines+markers+text', 
                name='收盤價', 
                text=df['Close'].round(2), 
                textposition='top center',
                textfont=dict(size=10, color='blue'),
                line=dict(color='blue')
            ), row=1, col=1)
            
            if indicator_choice == "均線 (5日, 月線, 季線)":
                fig.add_trace(go.Scatter(x=df.index, y=df['MA5'], mode='lines', name='5日均線', line=dict(color='#f28e2b', width=2)), row=1, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], mode='lines', name='月線(20日)', line=dict(color='#e15759', width=2)), row=1, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['MA60'], mode='lines', name='季線(60日)', line=dict(color='#59a14f', width=2)), row=1, col=1)
            elif indicator_choice == "布林通道":
                fig.add_trace(go.Scatter(x=df.index, y=df['BB_Upper'], mode='lines', name='布林上軌', line=dict(color='rgba(173, 216, 230, 0)'), showlegend=False), row=1, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['BB_Lower'], mode='lines', name='布林區間', line=dict(color='rgba(173, 216, 230, 0)'), fill='tonexty', fillcolor='rgba(173, 216, 230, 0.3)'), row=1, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['BB_Mid'], mode='lines', name='中軌(20MA)', line=dict(color='gray', dash='dash')), row=1, col=1)

            fig.add_trace(go.Scatter(
                x=df.index, y=df['D'], 
                mode='lines+markers', name='D值', line=dict(color='green')
            ), row=2, col=1)
            
            fig.add_trace(go.Scatter(
                x=df.index, y=df['K'], 
                mode='lines+markers+text', name='K值', 
                text=df['K'].round(1), textposition='top center', 
                textfont=dict(size=10, color='orange'), line=dict(color='orange')
            ), row=2, col=1)

            fig.add_hline(y=80, line_dash="dash", line_color="red", row=2, col=1, annotation_text="超買區 (80)")
            fig.add_hline(y=20, line_dash="dash", line_color="green", row=2, col=1, annotation_text="超賣區 (20)")

            fig.update_xaxes(type='category')
            fig.update_layout(height=650, hovermode="x unified", margin=dict(l=20, r=20, t=40, b=20))
            st.plotly_chart(fig, use_container_width=True, key=f"chart_{display_code}")

            # --- 下方表格 (改用 Markdown 語法強制置中) ---
            st.subheader("📋 近 30 個工作日收盤價")
            
            dates = df.index.tolist()
            closes = [f"{x:.2f}" for x in df['Close'].tolist()]
            
            md_table = "| 日期 (D1~D10) | 收盤價 (D1~D10) | 日期 (D11~D20) | 收盤價 (D11~D20) | 日期 (D21~D30) | 收盤價 (D21~D30) |\n"
            md_table += "|:---:|:---:|:---:|:---:|:---:|:---:|\n"
            
            for row in range(10):
                md_table += f"| {dates[row]} | {closes[row]} | {dates[row+10]} | {closes[row+10]} | {dates[row+20]} | {closes[row+20]} |\n"
                
            st.markdown(md_table)
            
        elif len(df) < 30:
            st.warning(f"歷史資料筆數不足 30 筆，無法顯示 {display_code} 的排版表格。")
        else:
            st.warning(f"無法取得 {display_code} 的歷史數據，請確認 YFinance 狀態。")
