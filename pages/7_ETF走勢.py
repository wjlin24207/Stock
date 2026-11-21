import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(page_title="ETF K 線與 KD 觀測站", page_icon="📊", layout="wide")

@st.cache_data
def load_etf_list():
    return pd.DataFrame({
        "股票代號": ["0056.TW", "00878.TW", "00919.TW", "0050.TW", "009816.TW", "00981A.TW", "00400A.TW"],
        "股票名稱": ["元大高股息", "國泰永續高股息", "群益台灣精選高息", "元大台灣50", "凱基台灣TOP50", "主動統一台股增長", "國泰動能高息"],
    })

etf_df = load_etf_list()
etf_records = etf_df.to_dict("records")
tab_labels = [item["股票代號"].split(".")[0] for item in etf_records]

st.markdown("### ⚙️ 圖表指標設定")
indicator_choice = st.radio(
    label="請選擇要疊加在 K 線圖上的指標：",
    options=("無", "均線（5日、月線、季線）", "布林通道"),
    horizontal=True,
    label_visibility="collapsed",
)

@st.cache_data(ttl=3600, show_spinner=False)
def load_stock_data(ticker_symbol):
    df = yf.Ticker(ticker_symbol).history(period="6mo", auto_adjust=False, actions=False)
    if df.empty:
        return df, df
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)
    for column in ["Open", "High", "Low", "Close", "Volume"]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    if df.empty:
        return df, df

    low_min = df["Low"].rolling(window=9, min_periods=1).min()
    high_max = df["High"].rolling(window=9, min_periods=1).max()
    price_range = high_max - low_min
    df["RSV"] = 100 * (df["Close"] - low_min) / price_range.replace(0, pd.NA)
    k_values, d_values = [], []
    k, d = 50.0, 50.0
    for rsv in df["RSV"].fillna(50):
        k = (2 / 3) * k + (1 / 3) * float(rsv)
        d = (2 / 3) * d + (1 / 3) * k
        k_values.append(k)
        d_values.append(d)
    df["K"], df["D"] = k_values, d_values

    df["MA5"] = df["Close"].rolling(5).mean()
    df["MA20"] = df["Close"].rolling(20).mean()
    df["MA60"] = df["Close"].rolling(60).mean()
    df["BB_Mid"] = df["MA20"]
    std_20 = df["Close"].rolling(20).std()
    df["BB_Upper"] = df["BB_Mid"] + 2 * std_20
    df["BB_Lower"] = df["BB_Mid"] - 2 * std_20
    # Yahoo Finance 的 Volume 單位是「股」。台股 1 張通常為 1,000 股，
    # 因此除以 1,000，轉換為成交張數。保留小數可涵蓋零股交易。
    df["Volume_Lots"] = df["Volume"] / 1000

    df["Volume_Color"] = df.apply(
        lambda row: "#EF5350" if row["Close"] >= row["Open"] else "#26A69A", axis=1
    )
    # 這裡改成回傳最後 90 筆給主要圖表使用
    return df.copy(), df.tail(90).copy()


def create_candlestick_chart(df, indicator):
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.04,
        row_heights=[0.60, 0.17, 0.23], subplot_titles=("日 K 線", "成交量（張）", "KD 指標")
    )
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        name="日 K", increasing=dict(line=dict(color="#E53935"), fillcolor="#E53935"),
        decreasing=dict(line=dict(color="#00A65A"), fillcolor="#00A65A")
    ), row=1, col=1)

    if indicator == "均線（5日、月線、季線）":
        for col, name, color in [("MA5", "MA5", "#FF9800"), ("MA20", "MA20", "#2196F3"), ("MA60", "MA60", "#9C27B0")]:
            fig.add_trace(go.Scatter(x=df.index, y=df[col], mode="lines", name=name,
                                     line=dict(color=color, width=1.8)), row=1, col=1)
    elif indicator == "布林通道":
        fig.add_trace(go.Scatter(x=df.index, y=df["BB_Upper"], mode="lines", name="布林上軌",
                                 line=dict(color="#FF9800", width=1.5)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df["BB_Mid"], mode="lines", name="布林中軌",
                                 line=dict(color="#2196F3", width=1.5)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df["BB_Lower"], mode="lines", name="布林下軌",
                                 line=dict(color="#FF9800", width=1.5), fill="tonexty",
                                 fillcolor="rgba(255,152,0,0.08)"), row=1, col=1)

    fig.add_trace(go.Bar(x=df.index, y=df["Volume_Lots"], name="成交量（張）",
                         hovertemplate="日期：%{x|%Y-%m-%d}<br>成交量：%{y:,.1f} 張<extra></extra>",
                         marker_color=df["Volume_Color"]), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["K"], mode="lines", name="K 值",
                             line=dict(color="#FF9800", width=2)), row=3, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["D"], mode="lines", name="D 值",
                             line=dict(color="#2196F3", width=2)), row=3, col=1)
    fig.add_hline(y=80, line_width=1, line_dash="dash", line_color="#E53935", row=3, col=1)
    fig.add_hline(y=20, line_width=1, line_dash="dash", line_color="#00A65A", row=3, col=1)

    all_dates = pd.date_range(df.index.min(), df.index.max(), freq="D")
    missing_dates = all_dates.difference(pd.DatetimeIndex(df.index))
    fig.update_xaxes(rangebreaks=[dict(values=missing_dates)])
    # 使用明確的巢狀設定，避免部分 Plotly 版本不支援
    # xaxis_rangeslider_visible 這種 magic underscore 寫法。
    fig.update_layout(
        height=850,
        margin=dict(l=20, r=20, t=55, b=20),
        hovermode="x unified",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
        ),
        bargap=0.15,
    )

    # K 線位於第一個 X 軸，關閉 Plotly 預設的縮放滑桿。
    fig.update_xaxes(rangeslider=dict(visible=False), row=1, col=1)
    fig.update_yaxes(title_text="股價", row=1, col=1)
    fig.update_yaxes(title_text="成交量（張）", rangemode="tozero", row=2, col=1)
    fig.update_yaxes(title_text="KD", range=[0, 100], row=3, col=1)
    fig.update_xaxes(title_text="日期", row=3, col=1)
    return fig


tabs = st.tabs(tab_labels)
for index, tab in enumerate(tabs):
    with tab:
        current_etf = etf_records[index]
        selected_ticker = current_etf["股票代號"]
        selected_name = current_etf["股票名稱"]
        display_code = selected_ticker.split(".")[0]

        # 標題改為 90 日
        st.markdown(f'''<div style="font-size:28px;font-weight:700;margin-top:4px;margin-bottom:14px;">
        📊 {display_code}（{selected_name}）近 90 日 K 線與 KD 指標</div>''', unsafe_allow_html=True)

        with st.spinner(f"正在載入 {display_code} 的股價資料..."):
            full_df, df = load_stock_data(selected_ticker)
        if df.empty:
            st.error(f"無法取得 {display_code} 的股價資料，請稍後再試或確認 Yahoo Finance 是否支援此代號。")
            continue

        latest = df.iloc[-1]
        previous_close = df.iloc[-2]["Close"] if len(df) >= 2 else latest["Close"]
        price_change = latest["Close"] - previous_close
        price_change_percent = price_change / previous_close * 100 if previous_close else 0

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("最新收盤價", f"{latest['Close']:.2f}", f"{price_change:+.2f} ({price_change_percent:+.2f}%)")
        c2.metric("今日開盤", f"{latest['Open']:.2f}")
        c3.metric("今日最高", f"{latest['High']:.2f}")
        c4.metric("今日最低", f"{latest['Low']:.2f}")
        c5.metric("今日成交量（張）", f"{latest['Volume_Lots']:,.1f}")

        st.plotly_chart(create_candlestick_chart(df, indicator_choice),
                        use_container_width=True, key=f"chart_{display_code}")

        st.markdown("### 📋 近 30 個交易日收盤價")
        # 加上 .tail(30) 讓表格只抓取最後 30 天的資料
        table_df = df.tail(30).sort_index(ascending=False).copy()
        table_df.index = table_df.index.strftime("%Y-%m-%d")
        dates = table_df.index.tolist()
        closes = [f"{value:.2f}" for value in table_df["Close"].tolist()]
        while len(dates) < 30:
            dates.append("-")
            closes.append("-")
        md_table = "| 日期（D1～D10） | 收盤價 | 日期（D11～D20） | 收盤價 | 日期（D21～D30） | 收盤價 |\n"
        md_table += "|:---:|:---:|:---:|:---:|:---:|:---:|\n"
        for row in range(10):
            md_table += (f"| {dates[row]} | {closes[row]} | {dates[row+10]} | {closes[row+10]} "
                         f"| {dates[row+20]} | {closes[row+20]} |\n")
        st.markdown(md_table)

        with st.expander("查看最新技術指標", expanded=False):
            t1, t2, t3 = st.columns(3)
            fmt = lambda x: f"{x:.2f}" if pd.notna(x) else "-"
            t1.write(f"**移動平均線**\n\n- MA5：{fmt(latest['MA5'])}\n- MA20：{fmt(latest['MA20'])}\n- MA60：{fmt(latest['MA60'])}")
            t2.write(f"**KD 指標**\n\n- K 值：{latest['K']:.2f}\n- D 值：{latest['D']:.2f}")
            if latest["K"] >= 80 and latest["D"] >= 80:
                kd_status = "高檔區"
            elif latest["K"] <= 20 and latest["D"] <= 20:
                kd_status = "低檔區"
            elif latest["K"] > latest["D"]:
                kd_status = "K 值高於 D 值"
            elif latest["K"] < latest["D"]:
                kd_status = "K 值低於 D 值"
            else:
                kd_status = "中性"
            t3.write(f"**目前狀態**\n\n- KD 狀態：{kd_status}\n- 最新交易日：{df.index[-1].strftime('%Y-%m-%d')}")
