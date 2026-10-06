from datetime import date, timedelta
import time

import altair as alt
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="台股融資融券查詢", page_icon="📊", layout="wide")

TWSE_API_URL = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.twse.com.tw/",
}


def to_int(value):
    text = str(value).strip().replace(",", "").replace(" ", "")
    if value is None or text in {"", "--", "-", "N/A", "nan", "None"}:
        return 0
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return 0


def weekdays(start_date, end_date):
    current = start_date
    result = []
    while current <= end_date:
        if current.weekday() < 5:
            result.append(current)
        current += timedelta(days=1)
    return result


def find_stock_row(data, stock_id):
    for table in data.get("tables", []):
        for row in table.get("data", []):
            if row and str(row[0]).strip() == stock_id:
                return row
    return None


@st.cache_data(ttl=43200, show_spinner=False)
def fetch_one_day(stock_id, query_date):
    params = {"date": query_date, "selectType": "ALL", "response": "json"}
    try:
        response = requests.get(TWSE_API_URL, params=params, headers=HEADERS, timeout=15)
        response.raise_for_status()
        row = find_stock_row(response.json(), stock_id)
    except (requests.RequestException, ValueError):
        return None

    if row is None or len(row) < 13:
        return None

    margin_previous = to_int(row[5])
    margin_balance = to_int(row[6])
    short_previous = to_int(row[11])
    short_balance = to_int(row[12])

    return {
        "日期": pd.to_datetime(query_date, format="%Y%m%d"),
        "股票代號": str(row[0]).strip(),
        "股票名稱": str(row[1]).strip(),
        "融資餘額": margin_balance,
        "融資變化": margin_balance - margin_previous,
        "融券餘額": short_balance,
        "融券變化": short_balance - short_previous,
    }


def fetch_history(stock_id, start_date, end_date):
    dates = weekdays(start_date, end_date)
    results = []
    progress = st.progress(0)
    message = st.empty()

    for index, day in enumerate(dates):
        message.text(f"正在查詢 {day:%Y-%m-%d}...")
        item = fetch_one_day(stock_id, day.strftime("%Y%m%d"))
        if item:
            results.append(item)
        progress.progress((index + 1) / len(dates))
        if index < len(dates) - 1:
            time.sleep(0.08)

    progress.empty()
    message.empty()
    if not results:
        return pd.DataFrame()
    return pd.DataFrame(results).drop_duplicates("日期").sort_values("日期").reset_index(drop=True)


def roc_date_to_datetime(text):
    """將民國日期，例如 115/10/06，轉成 pandas 日期。"""
    try:
        year, month, day = str(text).strip().split("/")
        return pd.Timestamp(int(year) + 1911, int(month), int(day))
    except (ValueError, TypeError):
        return pd.NaT


@st.cache_data(ttl=43200, show_spinner=False)
def fetch_stock_price(stock_id, start_date, end_date):
    """逐月取得 TWSE 個股每日收盤價，並篩選指定日期範圍。"""
    month_starts = pd.date_range(
        start=pd.Timestamp(start_date).replace(day=1),
        end=pd.Timestamp(end_date).replace(day=1),
        freq="MS",
    )
    records = []

    for month_start in month_starts:
        params = {
            "response": "json",
            "date": month_start.strftime("%Y%m%d"),
            "stockNo": stock_id,
        }
        try:
            response = requests.get(
                "https://www.twse.com.tw/exchangeReport/STOCK_DAY",
                params=params,
                headers=HEADERS,
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            continue

        if payload.get("stat") != "OK":
            continue

        fields = payload.get("fields", [])
        try:
            date_index = fields.index("日期")
            close_index = fields.index("收盤價")
        except ValueError:
            continue

        for row in payload.get("data", []):
            if len(row) <= max(date_index, close_index):
                continue
            trade_date = roc_date_to_datetime(row[date_index])
            close_price = pd.to_numeric(
                str(row[close_index]).replace(",", "").replace("--", ""),
                errors="coerce",
            )
            if pd.notna(trade_date) and pd.notna(close_price):
                records.append({"日期": trade_date, "收盤價": float(close_price)})

    if not records:
        return pd.DataFrame(columns=["日期", "收盤價"])

    price_df = pd.DataFrame(records).drop_duplicates("日期").sort_values("日期")
    mask = (
        (price_df["日期"] >= pd.Timestamp(start_date))
        & (price_df["日期"] <= pd.Timestamp(end_date))
    )
    return price_df.loc[mask].reset_index(drop=True)


def price_chart(detail_df):
    """顯示股價走勢，並在各資料點下方標示參考指數。"""
    chart_df = detail_df[["日期", "收盤價", "參考指數"]].copy()
    chart_df = chart_df.dropna(subset=["收盤價"])
    chart_df["圖表標籤"] = chart_df["參考指數"].replace(
        {"資料不足": "", "持平，未分類": "持平"}
    )
    
    # 將重複的連續標籤設為空白，避免畫面上字詞擠在一起
    chart_df["前日標籤"] = chart_df["圖表標籤"].shift(1)
    chart_df.loc[chart_df["圖表標籤"] == chart_df["前日標籤"], "圖表標籤"] = ""

    base = alt.Chart(chart_df).encode(
        x=alt.X(
            "日期:O", 
            title="日期", 
            timeUnit="yearmonthdate", 
            axis=alt.Axis(format="%m/%d", labelAngle=-45, labelOverlap=True)
        ),
        y=alt.Y(
            "收盤價:Q",
            title="收盤價（元）",
            scale=alt.Scale(zero=False, nice=True, padding=35),
            axis=alt.Axis(format=",.2f"),
        ),
    )

    line = base.mark_line(
        point=alt.OverlayMarkDef(filled=True, size=55),
        color="#F2B134",
        strokeWidth=2.5,
    ).encode(
        tooltip=[
            alt.Tooltip("日期:T", title="日期", format="%Y-%m-%d"),
            alt.Tooltip("收盤價:Q", title="收盤價", format=",.2f"),
            alt.Tooltip("參考指數:N", title="參考指數"),
        ]
    )

    labels = base.mark_text(
        dx=5,
        dy=15,
        align="left",
        baseline="middle",
        color="#FF6B6B",
        size=12,
        fontWeight="bold",
    ).encode(
        text=alt.Text("圖表標籤:N"),
        angle=alt.value(315) # 315度即為 -45度，放在 encode 內避免 schema error
    )

    chart = alt.layer(line, labels).properties(height=380)
    st.altair_chart(chart, use_container_width=True)


def balance_chart(df):
    base = alt.Chart(df).encode(
        x=alt.X(
            "日期:O", 
            title="日期", 
            timeUnit="yearmonthdate", 
            axis=alt.Axis(format="%m/%d", labelAngle=-45, labelOverlap=True)
        )
    )

    margin = base.mark_line(point=True, color="#E15759", strokeWidth=2.5).encode(
        y=alt.Y(
            "融資餘額:Q",
            title="融資餘額（張）",
            scale=alt.Scale(zero=False, nice=True),
            axis=alt.Axis(titleColor="#E15759", labelColor="#E15759", format=",.0f"),
        ),
        tooltip=[
            alt.Tooltip("日期:T", title="日期", format="%Y-%m-%d"),
            alt.Tooltip("融資餘額:Q", title="融資餘額", format=","),
        ],
    )

    short = base.mark_line(point=True, color="#4E79A7", strokeWidth=2.5).encode(
        y=alt.Y(
            "融券餘額:Q",
            title="融券餘額（張）",
            scale=alt.Scale(zero=False, nice=True),
            axis=alt.Axis(orient="right", titleColor="#4E79A7", labelColor="#4E79A7", format=",.0f"),
        ),
        tooltip=[
            alt.Tooltip("日期:T", title="日期", format="%Y-%m-%d"),
            alt.Tooltip("融券餘額:Q", title="融券餘額", format=","),
        ],
    )

    chart = alt.layer(margin, short).resolve_scale(y="independent").properties(height=420)
    st.altair_chart(chart, use_container_width=True)


def add_reference_signal(margin_df, price_df):
    """合併收盤價，並依前一交易日的價、資、券變化產生參考指數。"""
    result = margin_df.merge(price_df[["日期", "收盤價"]], on="日期", how="left")
    result = result.sort_values("日期").reset_index(drop=True)
    result["前日收盤價"] = result["收盤價"].shift(1)
    result["股價變化"] = result["收盤價"] - result["前日收盤價"]

    def classify(row):
        values = [row["股價變化"], row["融資變化"], row["融券變化"]]
        if any(pd.isna(value) for value in values):
            return "資料不足"
        if any(value == 0 for value in values):
            return "持平，未分類"

        price_up = row["股價變化"] > 0
        margin_up = row["融資變化"] > 0
        short_up = row["融券變化"] > 0

        mapping = {
            (True, True, True): "漲升行情",
            (True, True, False): "末升行情",
            (True, False, True): "養空行情",
            (True, False, False): "跌深反彈",
            (False, True, True): "多空大戰",
            (False, True, False): "頭部特色",
            (False, False, True): "跌勢未期",
            (False, False, False): "人氣退潮",
        }
        return mapping[(price_up, margin_up, short_up)]

    result["參考指數"] = result.apply(classify, axis=1)
    return result


def change_chart(df, field, title):
    data = df[["日期", field]].copy()
    data["方向"] = data[field].apply(lambda x: "增加" if x >= 0 else "減少")
    chart = alt.Chart(data).mark_bar().encode(
        x=alt.X(
            "日期:O", 
            title="日期", 
            timeUnit="yearmonthdate", 
            axis=alt.Axis(format="%m/%d", labelAngle=-45, labelOverlap=True)
        ),
        y=alt.Y(f"{field}:Q", title="每日變化（張）", axis=alt.Axis(format=",.0f")),
        color=alt.Color(
            "方向:N",
            title="方向",
            scale=alt.Scale(domain=["增加", "減少"], range=["#E15759", "#59A14F"]),
        ),
        tooltip=[
            alt.Tooltip("日期:T", title="日期", format="%Y-%m-%d"),
            alt.Tooltip(f"{field}:Q", title=field, format=","),
        ],
    ).properties(title=title, height=300)
    st.altair_chart(chart, use_container_width=True)


st.title("📊 台股融資融券查詢")
st.caption("輸入上市股票代號，查看融資融券餘額及每日變化。")

st.header("查詢條件")
col1, col2, col3 = st.columns(3)

with col1:
    stock_id = st.text_input("股票代號", value="2330", max_chars=6).strip()
with col2:
    period_days = st.selectbox(
        "查詢期間", [10, 20, 30, 60, 90], index=2,
        format_func=lambda value: f"最近 {value} 個日曆日",
    )
with col3:
    end_date = st.date_input("結束日期", value=date.today(), max_value=date.today())

start_date = end_date - timedelta(days=period_days)
submit = st.button("開始查詢", type="primary", use_container_width=True)

st.caption("目前版本：上市股票 ｜ 資料單位：張／交易單位")
st.divider()

if submit:
    if not stock_id or not stock_id.isdigit():
        st.warning("請輸入數字股票代號，例如 2330。")
        st.stop()

    with st.spinner("正在取得證交所融資融券與股價資料..."):
        df = fetch_history(stock_id, start_date, end_date)
        price_df = fetch_stock_price(stock_id, start_date, end_date)

    if df.empty:
        st.error("找不到資料。請確認股票代號為上市股票，且查詢期間內有交易資料。")
        st.stop()

    detail_df = add_reference_signal(df, price_df)
    latest = df.iloc[-1]
    st.subheader(f"{stock_id} {latest['股票名稱']}")
    st.caption(f"最新資料日期：{latest['日期']:%Y-%m-%d}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("融資餘額", f"{latest['融資餘額']:,.0f} 張")
    c2.metric("融資變化", f"{latest['融資變化']:+,.0f} 張")
    c3.metric("融券餘額", f"{latest['融券餘額']:,.0f} 張")
    c4.metric("融券變化", f"{latest['融券變化']:+,.0f} 張")

    st.divider()

    st.markdown("### 股價走勢")
    if price_df.empty:
        st.warning("此查詢期間找不到股價資料。")
    else:
        price_chart(detail_df)

    st.markdown("### 融資與融券餘額走勢")
    st.caption("紅線：左側 Y 軸融資餘額；藍線：右側 Y 軸融券餘額。")
    balance_chart(df)

    st.markdown("### 融資與融券每日變化")
    left, right = st.columns(2)
    with left:
        change_chart(df, "融資變化", "融資每日變化")
    with right:
        change_chart(df, "融券變化", "融券每日變化")

    with st.expander("查看每日明細與下載 CSV"):
        display = detail_df.copy()
        display["日期"] = display["日期"].dt.strftime("%Y-%m-%d")
        display = display[
            [
                "日期", "股票代號", "股票名稱", "收盤價", "股價變化",
                "融資餘額", "融資變化", "融券餘額", "融券變化", "參考指數"
            ]
        ].sort_values("日期", ascending=False)
        st.dataframe(
            display,
            use_container_width=True,
            hide_index=True,
            column_config={
                "收盤價": st.column_config.NumberColumn("收盤價", format="%.2f"),
                "股價變化": st.column_config.NumberColumn("股價變化", format="%+.2f"),
                "融資餘額": st.column_config.NumberColumn("融資餘額", format="%d"),
                "融資變化": st.column_config.NumberColumn("融資變化", format="%+d"),
                "融券餘額": st.column_config.NumberColumn("融券餘額", format="%d"),
                "融券變化": st.column_config.NumberColumn("融券變化", format="%+d"),
                "參考指數": st.column_config.TextColumn("參考指數"),
            },
        )
        csv_data = display.to_csv(index=False, encoding="utf-8-sig")
        st.download_button(
            "下載 CSV", csv_data, f"{stock_id}_融資融券資料.csv", "text/csv"
        )

    st.info("今日餘額後續可能因調帳而修正，本工具僅供資料整理參考。")
else:
    st.info("請在上方輸入股票代號並按下「開始查詢」。")
