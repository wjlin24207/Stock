from datetime import date, timedelta
import time

import altair as alt
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="台股融資融券查詢", page_icon="📊", layout="wide")

TWSE_API_URL = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
T86_API_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
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


def find_t86_row(data, stock_id):
    if not data:
        return None, None
    for table in data.get("tables", []):
        fields = table.get("fields", [])
        for row in table.get("data", []):
            if row and str(row[0]).strip() == stock_id:
                return fields, row
    fields = data.get("fields", [])
    for row in data.get("data", []):
        if row and str(row[0]).strip() == stock_id:
            return fields, row
    return None, None


def parse_t86_row(fields, row):
    if not fields or not row:
        return 0, 0, 0, 0

    def get_val(col_name):
        for i, f in enumerate(fields):
            if f.strip() == col_name and i < len(row):
                return to_int(row[i])
        return None

    # 外資：加總外陸資與外資自營商
    f1 = get_val("外陸資買賣超股數(不含外資自營商)")
    f2 = get_val("外資自營商買賣超股數")
    if f1 is not None:
        foreign = f1 + (f2 if f2 is not None else 0)
    else:
        foreign = 0
        for i, f in enumerate(fields):
            if "外" in f and "買賣超" in f and i < len(row):
                foreign = to_int(row[i])
                break

    # 投信
    trust = get_val("投信買賣超股數")
    if trust is None:
        for i, f in enumerate(fields):
            if "投信" in f and "買賣超" in f and i < len(row):
                trust = to_int(row[i])
                break
    if trust is None:
        trust = 0

    # 自營商
    dealer = get_val("自營商買賣超股數")
    if dealer is None:
        d1 = get_val("自營商買賣超股數(自行買賣)")
        d2 = get_val("自營商買賣超股數(避險)")
        if d1 is not None or d2 is not None:
            dealer = (d1 or 0) + (d2 or 0)
        else:
            dealer = 0

    # 三大法人合計
    total = get_val("三大法人買賣超股數")
    if total is None:
        for i, f in enumerate(fields):
            if "三大法人" in f and "買賣超" in f and i < len(row):
                total = to_int(row[i])
                break
    if total is None:
        total = foreign + trust + dealer

    # 換算為「張」（1 張 = 1000 股）
    return (
        int(round(foreign / 1000)),
        int(round(trust / 1000)),
        int(round(dealer / 1000)),
        int(round(total / 1000)),
    )


def _fetch_institutional_api(stock_id, query_date):
    params = {"date": query_date, "selectType": "ALL", "response": "json"}
    try:
        response = requests.get(T86_API_URL, params=params, headers=HEADERS, timeout=15)
        response.raise_for_status()
        fields, row = find_t86_row(response.json(), stock_id)
        if row:
            foreign, trust, dealer, total = parse_t86_row(fields, row)
            return {
                "外資買賣超": foreign,
                "投信買賣超": trust,
                "自營商買賣超": dealer,
                "三大法人買賣超": total,
            }
    except (requests.RequestException, ValueError):
        pass
    return None


@st.cache_data(ttl=43200, show_spinner=False)
def _fetch_institutional_cached(stock_id, query_date):
    return _fetch_institutional_api(stock_id, query_date)


def fetch_institutional_one_day(stock_id, query_date):
    # 若為今天，不走快取，直接抓最新數據
    if query_date == date.today().strftime("%Y%m%d"):
        return _fetch_institutional_api(stock_id, query_date)
    return _fetch_institutional_cached(stock_id, query_date)


def _fetch_one_day_api(stock_id, query_date):
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


@st.cache_data(ttl=43200, show_spinner=False)
def _fetch_one_day_cached(stock_id, query_date):
    return _fetch_one_day_api(stock_id, query_date)


def fetch_one_day(stock_id, query_date):
    # 若為今天，不走快取，直接抓最新數據
    if query_date == date.today().strftime("%Y%m%d"):
        return _fetch_one_day_api(stock_id, query_date)
    return _fetch_one_day_cached(stock_id, query_date)


def fetch_history(stock_id, start_date, end_date):
    dates = weekdays(start_date, end_date)
    results = []
    progress = st.progress(0)
    message = st.empty()

    for index, day in enumerate(dates):
        d_str = day.strftime("%Y%m%d")
        message.text(f"正在查詢 {day:%Y-%m-%d}...")
        item = fetch_one_day(stock_id, d_str)
        inst = fetch_institutional_one_day(stock_id, d_str)
        if item:
            if inst:
                item.update(inst)
            else:
                item.update({
                    "外資買賣超": 0,
                    "投信買賣超": 0,
                    "自營商買賣超": 0,
                    "三大法人買賣超": 0,
                })
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
    """將民國日期轉成 pandas 日期。"""
    try:
        year, month, day = str(text).strip().split("/")
        return pd.Timestamp(int(year) + 1911, int(month), int(day))
    except (ValueError, TypeError):
        return pd.NaT


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_stock_price(stock_id, start_date, end_date):
    """逐月取得 TWSE 個股每日收盤價與高低價，計算均線及 KD 指標。"""
    fetch_start = pd.Timestamp(start_date) - pd.Timedelta(days=60)
    month_starts = pd.date_range(
        start=fetch_start.replace(day=1),
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
            high_index = fields.index("最高價")
            low_index = fields.index("最低價")
        except ValueError:
            continue

        for row in payload.get("data", []):
            if len(row) <= max(date_index, close_index, high_index, low_index):
                continue
            trade_date = roc_date_to_datetime(row[date_index])
            close_price = pd.to_numeric(
                str(row[close_index]).replace(",", "").replace("--", ""),
                errors="coerce",
            )
            high_price = pd.to_numeric(
                str(row[high_index]).replace(",", "").replace("--", ""),
                errors="coerce",
            )
            low_price = pd.to_numeric(
                str(row[low_index]).replace(",", "").replace("--", ""),
                errors="coerce",
            )
            if pd.notna(trade_date) and pd.notna(close_price) and pd.notna(high_price) and pd.notna(low_price):
                records.append({
                    "日期": trade_date,
                    "收盤價": float(close_price),
                    "最高價": float(high_price),
                    "最低價": float(low_price),
                })

    if not records:
        return pd.DataFrame(columns=["日期", "收盤價", "MA5", "MA10", "MA20", "K", "D"])

    price_df = pd.DataFrame(records).drop_duplicates("日期").sort_values("日期").reset_index(drop=True)

    # 計算均線
    price_df["MA5"] = price_df["收盤價"].rolling(window=5).mean()
    price_df["MA10"] = price_df["收盤價"].rolling(window=10).mean()
    price_df["MA20"] = price_df["收盤價"].rolling(window=20).mean()

    # 計算 KD 指標 (9, 3, 3)
    low9 = price_df["最低價"].rolling(window=9).min()
    high9 = price_df["最高價"].rolling(window=9).max()
    denom = high9 - low9
    rsv = ((price_df["收盤價"] - low9) / denom.replace(0, pd.NA) * 100).fillna(50)

    k_list, d_list = [], []
    k_val, d_val = 50.0, 50.0
    for r in rsv:
        k_val = (2 / 3) * k_val + (1 / 3) * float(r)
        d_val = (2 / 3) * d_val + (1 / 3) * k_val
        k_list.append(k_val)
        d_list.append(d_val)

    price_df["K"] = k_list
    price_df["D"] = d_list

    mask = (
        (price_df["日期"] >= pd.Timestamp(start_date))
        & (price_df["日期"] <= pd.Timestamp(end_date))
    )
    return price_df.loc[mask].reset_index(drop=True)


def price_chart(detail_df):
    """顯示股價走勢與均線，並在各資料點下方標示參考指數。"""
    chart_df = detail_df.copy()
    chart_df = chart_df.dropna(subset=["收盤價"])
    chart_df["圖表標籤"] = chart_df["參考指數"].replace(
        {"資料不足": "", "持平，未分類": "持平"}
    )

    base = alt.Chart(chart_df).encode(
        x=alt.X(
            "日期:O",
            title="日期",
            timeUnit="yearmonthdate",
            axis=alt.Axis(format="%m/%d", labelAngle=-45, labelOverlap=True),
        )
    )

    line_close = base.mark_line(
        point=alt.OverlayMarkDef(filled=True, size=55),
        color="#F2B134",
        strokeWidth=2.5,
    ).encode(
        y=alt.Y(
            "收盤價:Q",
            title="收盤價（元）",
            scale=alt.Scale(zero=False, nice=True, padding=35),
            axis=alt.Axis(format=",.2f"),
        ),
        tooltip=[
            alt.Tooltip("日期:T", title="日期", format="%Y-%m-%d"),
            alt.Tooltip("收盤價:Q", title="收盤價", format=",.2f"),
            alt.Tooltip("MA5:Q", title="5日線 (MA5)", format=",.2f"),
            alt.Tooltip("MA10:Q", title="10日線 (MA10)", format=",.2f"),
            alt.Tooltip("MA20:Q", title="20日線 (MA20)", format=",.2f"),
            alt.Tooltip("參考指數:N", title="參考指數"),
        ],
    )

    line_ma5 = base.mark_line(color="#2CA02C", strokeWidth=1.5).encode(
        y=alt.Y("MA5:Q")
    )
    line_ma10 = base.mark_line(color="#1F77B4", strokeWidth=1.5).encode(
        y=alt.Y("MA10:Q")
    )
    line_ma20 = base.mark_line(color="#9467BD", strokeWidth=1.5).encode(
        y=alt.Y("MA20:Q")
    )

    labels = base.mark_text(
        dy=18,
        baseline="top",
        color="#FF6B6B",
        fontSize=12,
        fontWeight="bold",
    ).encode(
        y=alt.Y("收盤價:Q"),
        text=alt.Text("圖表標籤:N"),
    )

    chart = alt.layer(line_close, line_ma5, line_ma10, line_ma20, labels).properties(height=380)
    st.altair_chart(chart, use_container_width=True)


def kd_chart(detail_df):
    """顯示 KD 指標走勢 (9, 3, 3)。"""
    chart_df = detail_df.dropna(subset=["K", "D"]).copy()
    if chart_df.empty:
        return

    base = alt.Chart(chart_df).encode(
        x=alt.X(
            "日期:O",
            title="日期",
            timeUnit="yearmonthdate",
            axis=alt.Axis(format="%m/%d", labelAngle=-45, labelOverlap=True),
        )
    )

    line_k = base.mark_line(
        point=alt.OverlayMarkDef(filled=True, size=40),
        color="#E15759",
        strokeWidth=2,
    ).encode(
        y=alt.Y(
            "K:Q",
            title="KD 指標",
            scale=alt.Scale(domain=[-5, 105]),
            axis=alt.Axis(format=",.0f"),
        ),
        tooltip=[
            alt.Tooltip("日期:T", title="日期", format="%Y-%m-%d"),
            alt.Tooltip("K:Q", title="K 值", format=",.2f"),
            alt.Tooltip("D:Q", title="D 值", format=",.2f"),
        ],
    )

    line_d = base.mark_line(
        point=alt.OverlayMarkDef(filled=True, size=40),
        color="#4E79A7",
        strokeWidth=2,
    ).encode(
        y=alt.Y("D:Q"),
        tooltip=[
            alt.Tooltip("日期:T", title="日期", format="%Y-%m-%d"),
            alt.Tooltip("K:Q", title="K 值", format=",.2f"),
            alt.Tooltip("D:Q", title="D 值", format=",.2f"),
        ],
    )

    k_labels = base.mark_text(
        dy=-8,
        baseline="bottom",
        color="#E15759",
        size=10,
        fontWeight="bold",
    ).encode(
        y=alt.Y("K:Q"),
        text=alt.Text("K:Q", format=",.1f"),
    )

    rule_80 = alt.Chart(pd.DataFrame({"y": [80]})).mark_rule(
        strokeDash=[4, 4], color="#888888", strokeWidth=1
    ).encode(y="y:Q")

    rule_20 = alt.Chart(pd.DataFrame({"y": [20]})).mark_rule(
        strokeDash=[4, 4], color="#888888", strokeWidth=1
    ).encode(y="y:Q")

    chart = alt.layer(rule_80, rule_20, line_k, line_d, k_labels).properties(height=200)
    st.altair_chart(chart, use_container_width=True)


def institutional_chart(df, field, title, height=250):
    """繪製法人買賣超柱狀圖（紅買綠賣）。"""
    data = df[["日期", field]].copy()
    data["方向"] = data[field].apply(lambda x: "買超" if x >= 0 else "賣超")
    chart = alt.Chart(data).mark_bar().encode(
        x=alt.X(
            "日期:O",
            title="日期",
            timeUnit="yearmonthdate",
            axis=alt.Axis(format="%m/%d", labelAngle=-45, labelOverlap=True),
        ),
        y=alt.Y(f"{field}:Q", title="買賣超（張）", axis=alt.Axis(format=",.0f")),
        color=alt.Color(
            "方向:N",
            title="方向",
            scale=alt.Scale(domain=["買超", "賣超"], range=["#E15759", "#59A14F"]),
        ),
        tooltip=[
            alt.Tooltip("日期:T", title="日期", format="%Y-%m-%d"),
            alt.Tooltip(f"{field}:Q", title=field, format=","),
        ],
    ).properties(title=title, height=height)
    st.altair_chart(chart, use_container_width=True)


def balance_chart(df):
    base = alt.Chart(df).encode(
        x=alt.X(
            "日期:O",
            title="日期",
            timeUnit="yearmonthdate",
            axis=alt.Axis(format="%m/%d", labelAngle=-45, labelOverlap=True),
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
    """合併收盤價、均線與 KD，並依前一交易日的價、資、券變化產生參考指數。"""
    merge_cols = [c for c in ["日期", "收盤價", "MA5", "MA10", "MA20", "K", "D"] if c in price_df.columns]
    result = margin_df.merge(price_df[merge_cols], on="日期", how="left")
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
            axis=alt.Axis(format="%m/%d", labelAngle=-45, labelOverlap=True),
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

# 提供「開始查詢」與「清除快取」按鈕
btn_col1, btn_col2 = st.columns([3, 1])
with btn_col1:
    submit = st.button("開始查詢", type="primary", use_container_width=True)
with btn_col2:
    if st.button("🔄 清除快取", use_container_width=True):
        st.cache_data.clear()
        st.toast("已清除所有快取！正在重新取得證交所最新資料...")
        st.rerun()

st.caption("目前版本：上市股票 ｜ 資料單位：張／交易單位")
st.divider()

if submit:
    if not stock_id or not stock_id.isdigit():
        st.warning("請輸入數字股票代號，例如 2330。")
        st.stop()

    with st.spinner("正在取得證交所融資融券、三大法人與股價資料..."):
        df = fetch_history(stock_id, start_date, end_date)
        price_df = fetch_stock_price(stock_id, start_date, end_date)

    if df.empty:
        st.error("找不到資料。請確認股票代號為上市股票，且查詢期間內有交易資料。")
        st.stop()

    detail_df = add_reference_signal(df, price_df)
    latest = df.iloc[-1]
    st.subheader(f"{stock_id} {latest['股票名稱']}")
    st.caption(f"最新資料日期：{latest['日期']:%Y-%m-%d}")

    # 若今天為平日且最新日期不是今天，給出貼心提醒
    if latest['日期'].date() < date.today() and date.today().weekday() < 5:
        st.info(f"💡 提醒：若今日為交易日，證交所融資融券通常於 21:00～21:30 公布。若已超過公布時間仍未顯示，請點擊上方「🔄 清除快取」重新取得最新資料。")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("融資餘額", f"{latest['融資餘額']:,.0f} 張")
    c2.metric("融資變化", f"{latest['融資變化']:+,.0f} 張")
    c3.metric("融券餘額", f"{latest['融券餘額']:,.0f} 張")
    c4.metric("融券變化", f"{latest['融券變化']:+,.0f} 張")

    st.divider()

    st.markdown("### 股價走勢")
    st.caption("🟡 黃線：收盤價 ｜ 🟢 綠線：5日線 (MA5) ｜ 🔵 藍線：10日線 (MA10) ｜ 🟣 紫線：20日線 (MA20)")
    if price_df.empty:
        st.warning("此查詢期間找不到股價資料。")
    else:
        price_chart(detail_df)

    st.markdown("### KD 指標 (9, 3, 3)")
    st.caption("🔴 紅線：K 值（附數值） ｜ 🔵 藍線：D 值 ｜ 灰虛線：80 超買線、20 超賣線")
    if not price_df.empty:
        kd_chart(detail_df)

    # --- 三大法人買賣超 ---
    st.markdown("### 三大法人買賣超")
    st.caption("最新法人籌碼動向與每日買賣超走勢（單位：張，紅買綠賣）。")

    i1, i2, i3, i4 = st.columns(4)
    i1.metric("外資買賣超", f"{latest['外資買賣超']:+,.0f} 張")
    i2.metric("投信買賣超", f"{latest['投信買賣超']:+,.0f} 張")
    i3.metric("自營商買賣超", f"{latest['自營商買賣超']:+,.0f} 張")
    i4.metric("三大法人合計", f"{latest['三大法人買賣超']:+,.0f} 張")

    institutional_chart(df, "三大法人買賣超", "三大法人合計買賣超", height=260)

    f_col, t_col, d_col = st.columns(3)
    with f_col:
        institutional_chart(df, "外資買賣超", "外資每日買賣超", height=220)
    with t_col:
        institutional_chart(df, "投信買賣超", "投信每日買賣超", height=220)
    with d_col:
        institutional_chart(df, "自營商買賣超", "自營商每日買賣超", height=220)

    # --- 融資與融券每日變化 ---
    st.markdown("### 融資與融券每日變化")
    left, right = st.columns(2)
    with left:
        change_chart(df, "融資變化", "融資每日變化")
    with right:
        change_chart(df, "融券變化", "融券每日變化")

    # --- 融資與融券餘額走勢 ---
    st.markdown("### 融資與融券餘額走勢")
    st.caption("紅線：左側 Y 軸融資餘額；藍線：右側 Y 軸融券餘額。")
    balance_chart(df)

    with st.expander("查看每日明細與下載 CSV"):
        display = detail_df.copy()
        display["日期"] = display["日期"].dt.strftime("%Y-%m-%d")
        display = display[
            [
                "日期", "股票代號", "股票名稱", "收盤價", "MA5", "MA10", "MA20", "K", "D", "股價變化",
                "外資買賣超", "投信買賣超", "自營商買賣超", "三大法人買賣超",
                "融資餘額", "融資變化", "融券餘額", "融券變化", "參考指數"
            ]
        ].sort_values("日期", ascending=False)
        st.dataframe(
            display,
            use_container_width=True,
            hide_index=True,
            column_config={
                "收盤價": st.column_config.NumberColumn("收盤價", format="%.2f"),
                "MA5": st.column_config.NumberColumn("5日線", format="%.2f"),
                "MA10": st.column_config.NumberColumn("10日線", format="%.2f"),
                "MA20": st.column_config.NumberColumn("20日線", format="%.2f"),
                "K": st.column_config.NumberColumn("K 值", format="%.2f"),
                "D": st.column_config.NumberColumn("D 值", format="%.2f"),
                "股價變化": st.column_config.NumberColumn("股價變化", format="%+.2f"),
                "外資買賣超": st.column_config.NumberColumn("外資買賣超", format="%+d"),
                "投信買賣超": st.column_config.NumberColumn("投信買賣超", format="%+d"),
                "自營商買賣超": st.column_config.NumberColumn("自營商買賣超", format="%+d"),
                "三大法人買賣超": st.column_config.NumberColumn("三大法人合計", format="%+d"),
                "融資餘額": st.column_config.NumberColumn("融資餘額", format="%d"),
                "融資變化": st.column_config.NumberColumn("融資變化", format="%+d"),
                "融券餘額": st.column_config.NumberColumn("融券餘額", format="%d"),
                "融券變化": st.column_config.NumberColumn("融券變化", format="%+d"),
                "參考指數": st.column_config.TextColumn("參考指數"),
            },
        )
        csv_data = display.to_csv(index=False, encoding="utf-8-sig")
        st.download_button(
            "下載 CSV", csv_data, f"{stock_id}_融資融券與三大法人資料.csv", "text/csv"
        )

    st.info("今日餘額與法人數據後續可能因調帳而修正，本工具僅供資料整理參考。")
else:
    st.info("請在上方輸入股票代號並按下「開始查詢」。")
