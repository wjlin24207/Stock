from datetime import date, timedelta
import time

import altair as alt
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="台股融資融券查詢", page_icon="📊", layout="wide")

TWSE_API_URL = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
T86_API_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
STOCK_DAY_API_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.twse.com.tw/",
}


def to_int(value):
    if value is None:
        return 0
    text = str(value).strip().replace(",", "").replace(" ", "")
    if text in {"", "--", "-", "N/A", "nan", "None"}:
        return 0
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return 0


def weekdays(start_date, end_date):
    result, current = [], start_date
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
    for row in data.get("data", []):
        if row and str(row[0]).strip() == stock_id:
            return data.get("fields", []), row
    return None, None


def parse_t86_row(fields, row):
    if not fields or not row:
        return 0, 0, 0, 0

    def get_val(name):
        for i, field in enumerate(fields):
            if field.strip() == name and i < len(row):
                return to_int(row[i])
        return None

    f1 = get_val("外陸資買賣超股數(不含外資自營商)")
    f2 = get_val("外資自營商買賣超股數")
    if f1 is not None:
        foreign = f1 + (f2 or 0)
    else:
        foreign = next(
            (to_int(row[i]) for i, field in enumerate(fields)
             if "外" in field and "買賣超" in field and i < len(row)), 0
        )

    trust = get_val("投信買賣超股數")
    if trust is None:
        trust = next(
            (to_int(row[i]) for i, field in enumerate(fields)
             if "投信" in field and "買賣超" in field and i < len(row)), 0
        )

    dealer = get_val("自營商買賣超股數")
    if dealer is None:
        dealer = (get_val("自營商買賣超股數(自行買賣)") or 0) + (
            get_val("自營商買賣超股數(避險)") or 0
        )

    total = get_val("三大法人買賣超股數")
    if total is None:
        total = next(
            (to_int(row[i]) for i, field in enumerate(fields)
             if "三大法人" in field and "買賣超" in field and i < len(row)),
            foreign + trust + dealer,
        )

    return tuple(int(round(value / 1000)) for value in (foreign, trust, dealer, total))


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
    margin_previous, margin_balance = to_int(row[5]), to_int(row[6])
    short_previous, short_balance = to_int(row[11]), to_int(row[12])
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
    if query_date == date.today().strftime("%Y%m%d"):
        return _fetch_one_day_api(stock_id, query_date)
    return _fetch_one_day_cached(stock_id, query_date)


def fetch_history(stock_id, start_date, end_date):
    dates = weekdays(start_date, end_date)
    results = []
    progress, message = st.progress(0), st.empty()
    for index, day in enumerate(dates):
        query_date = day.strftime("%Y%m%d")
        message.text(f"正在查詢 {day:%Y-%m-%d}...")
        item = fetch_one_day(stock_id, query_date)
        inst = fetch_institutional_one_day(stock_id, query_date)
        if item:
            item.update(inst or {
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
    try:
        year, month, day = str(text).strip().split("/")
        return pd.Timestamp(int(year) + 1911, int(month), int(day))
    except (ValueError, TypeError):
        return pd.NaT


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_stock_price(stock_id, start_date, end_date):
    fetch_start = pd.Timestamp(start_date) - pd.Timedelta(days=60)
    months = pd.date_range(fetch_start.replace(day=1), pd.Timestamp(end_date).replace(day=1), freq="MS")
    records = []
    for month in months:
        params = {"response": "json", "date": month.strftime("%Y%m%d"), "stockNo": stock_id}
        try:
            response = requests.get(STOCK_DAY_API_URL, params=params, headers=HEADERS, timeout=15)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            continue
        if payload.get("stat") != "OK":
            continue
        fields = payload.get("fields", [])
        try:
            di, ci, hi, li = map(fields.index, ["日期", "收盤價", "最高價", "最低價"])
        except ValueError:
            continue
        for row in payload.get("data", []):
            if len(row) <= max(di, ci, hi, li):
                continue
            trade_date = roc_date_to_datetime(row[di])
            numbers = [pd.to_numeric(str(row[i]).replace(",", "").replace("--", ""), errors="coerce") for i in (ci, hi, li)]
            if pd.notna(trade_date) and all(pd.notna(v) for v in numbers):
                records.append({"日期": trade_date, "收盤價": float(numbers[0]), "最高價": float(numbers[1]), "最低價": float(numbers[2])})
    if not records:
        return pd.DataFrame(columns=["日期", "收盤價", "MA5", "MA10", "MA20", "K", "D"])

    price_df = pd.DataFrame(records).drop_duplicates("日期").sort_values("日期").reset_index(drop=True)
    for period in (5, 10, 20):
        price_df[f"MA{period}"] = price_df["收盤價"].rolling(period).mean()
    low9, high9 = price_df["最低價"].rolling(9).min(), price_df["最高價"].rolling(9).max()
    rsv = ((price_df["收盤價"] - low9) / (high9 - low9).replace(0, pd.NA) * 100).fillna(50)
    k_values, d_values, k_value, d_value = [], [], 50.0, 50.0
    for value in rsv:
        k_value = (2 / 3) * k_value + (1 / 3) * float(value)
        d_value = (2 / 3) * d_value + (1 / 3) * k_value
        k_values.append(k_value)
        d_values.append(d_value)
    price_df["K"], price_df["D"] = k_values, d_values
    mask = (price_df["日期"] >= pd.Timestamp(start_date)) & (price_df["日期"] <= pd.Timestamp(end_date))
    return price_df.loc[mask].reset_index(drop=True)


def add_reference_signal(margin_df, price_df):
    merge_cols = [c for c in ["日期", "收盤價", "MA5", "MA10", "MA20", "K", "D"] if c in price_df.columns]
    result = margin_df.merge(price_df[merge_cols], on="日期", how="left").sort_values("日期").reset_index(drop=True)
    result["前日收盤價"] = result["收盤價"].shift(1)
    result["股價變化"] = result["收盤價"] - result["前日收盤價"]

    def classify(row):
        values = [row["股價變化"], row["融資變化"], row["融券變化"]]
        if any(pd.isna(value) for value in values):
            return "資料不足"
        if any(value == 0 for value in values):
            return "持平，未分類"
        mapping = {
            (True, True, True): "漲升行情", (True, True, False): "末升行情",
            (True, False, True): "養空行情", (True, False, False): "跌深反彈",
            (False, True, True): "多空大戰", (False, True, False): "頭部特色",
            (False, False, True): "跌勢未期", (False, False, False): "人氣退潮",
        }
        return mapping[(row["股價變化"] > 0, row["融資變化"] > 0, row["融券變化"] > 0)]

    result["參考指數"] = result.apply(classify, axis=1)
    return result


def signed_html(value):
    color = "#ff6b6b" if value > 0 else "#57c785" if value < 0 else "#a0a0a0"
    return f'<span style="color:{color};font-weight:700;white-space:nowrap">{value:+,.0f}</span>'


def render_mobile_summary_tables(latest):
    html = f"""
    <style>
    .summary-grid{{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:10px;width:100%;margin:8px 0 18px}}
    .summary-card{{border:1px solid rgba(128,128,128,.35);border-radius:12px;overflow:hidden;background:rgba(20,24,32,.35);min-width:0}}
    .summary-title{{font-size:18px;font-weight:750;padding:11px 12px 8px}}
    .summary-unit{{color:#9aa0aa;font-size:12px;padding:0 12px 8px}}
    .summary-table{{width:100%;border-collapse:collapse;table-layout:fixed}}
    .summary-table th,.summary-table td{{padding:9px 11px;border-top:1px solid rgba(128,128,128,.22);font-size:15px;line-height:1.25}}
    .summary-table th{{color:#aeb4be;font-size:12px;font-weight:600;text-align:right}}
    .summary-table th:first-child,.summary-table td:first-child{{text-align:left}}
    .summary-table td:not(:first-child){{text-align:right;white-space:nowrap}}
    .summary-total td{{font-weight:750;border-top:2px solid rgba(128,128,128,.5)}}
    @media(max-width:600px){{
      .summary-grid{{gap:6px}} .summary-title{{font-size:14px;padding:9px 7px 5px}}
      .summary-unit{{font-size:10px;padding:0 7px 6px}}
      .summary-table th,.summary-table td{{font-size:12px;padding:7px 5px}}
      .summary-table th{{font-size:10px}}
    }}
    </style>
    <div class="summary-grid">
      <section class="summary-card"><div class="summary-title">三大法人買賣超</div><div class="summary-unit">單位：張｜紅買綠賣</div>
        <table class="summary-table"><thead><tr><th>法人</th><th>今日</th></tr></thead><tbody>
          <tr><td>外資</td><td>{signed_html(latest['外資買賣超'])}</td></tr>
          <tr><td>投信</td><td>{signed_html(latest['投信買賣超'])}</td></tr>
          <tr><td>自營</td><td>{signed_html(latest['自營商買賣超'])}</td></tr>
          <tr class="summary-total"><td>合計</td><td>{signed_html(latest['三大法人買賣超'])}</td></tr>
        </tbody></table></section>
      <section class="summary-card"><div class="summary-title">融資融券</div><div class="summary-unit">單位：張｜紅增綠減</div>
        <table class="summary-table"><thead><tr><th>項目</th><th>餘額</th><th>變化</th></tr></thead><tbody>
          <tr><td>融資</td><td>{latest['融資餘額']:,.0f}</td><td>{signed_html(latest['融資變化'])}</td></tr>
          <tr><td>融券</td><td>{latest['融券餘額']:,.0f}</td><td>{signed_html(latest['融券變化'])}</td></tr>
        </tbody></table></section>
    </div>"""
    st.markdown(html, unsafe_allow_html=True)


def color_trade_value(value):
    if pd.isna(value):
        return ""
    if value > 0:
        return "color: #ff6b6b; font-weight: 700;"
    if value < 0:
        return "color: #57c785; font-weight: 700;"
    return "color: #a0a0a0;"


def price_chart(df):
    data = df.dropna(subset=["收盤價"]).copy()
    data["圖表標籤"] = data["參考指數"].replace({"資料不足": "", "持平，未分類": "持平"})
    base = alt.Chart(data).encode(x=alt.X("日期:O", timeUnit="yearmonthdate", axis=alt.Axis(format="%m/%d", labelAngle=-45)))
    close = base.mark_line(point=True, color="#F2B134", strokeWidth=2.5).encode(y=alt.Y("收盤價:Q", scale=alt.Scale(zero=False, nice=True, padding=35)), tooltip=["日期:T", "收盤價:Q", "參考指數:N"])
    ma5 = base.mark_line(color="#2CA02C").encode(y="MA5:Q")
    ma10 = base.mark_line(color="#1F77B4").encode(y="MA10:Q")
    ma20 = base.mark_line(color="#9467BD").encode(y="MA20:Q")
    labels = base.mark_text(dy=18, color="#FF6B6B", fontSize=12, fontWeight="bold").encode(y="收盤價:Q", text="圖表標籤:N")
    st.altair_chart(alt.layer(close, ma5, ma10, ma20, labels).properties(height=380), use_container_width=True)


def kd_chart(df):
    data = df.dropna(subset=["K", "D"])
    if data.empty:
        return
    base = alt.Chart(data).encode(x=alt.X("日期:O", timeUnit="yearmonthdate", axis=alt.Axis(format="%m/%d", labelAngle=-45)))
    k = base.mark_line(point=True, color="#E15759").encode(y=alt.Y("K:Q", scale=alt.Scale(domain=[-5, 105])), tooltip=["日期:T", "K:Q", "D:Q"])
    d = base.mark_line(point=True, color="#4E79A7").encode(y="D:Q", tooltip=["日期:T", "K:Q", "D:Q"])
    r80 = alt.Chart(pd.DataFrame({"y": [80]})).mark_rule(strokeDash=[4, 4], color="#888").encode(y="y:Q")
    r20 = alt.Chart(pd.DataFrame({"y": [20]})).mark_rule(strokeDash=[4, 4], color="#888").encode(y="y:Q")
    st.altair_chart(alt.layer(r80, r20, k, d).properties(height=200), use_container_width=True)


def bar_chart(df, field, title, positive="買超", negative="賣超", height=240):
    data = df[["日期", field]].copy()
    data["方向"] = data[field].apply(lambda x: positive if x >= 0 else negative)
    chart = alt.Chart(data).mark_bar().encode(
        x=alt.X("日期:O", timeUnit="yearmonthdate", axis=alt.Axis(format="%m/%d", labelAngle=-45)),
        y=alt.Y(f"{field}:Q", axis=alt.Axis(format=",.0f")),
        color=alt.Color("方向:N", scale=alt.Scale(domain=[positive, negative], range=["#E15759", "#59A14F"])),
        tooltip=["日期:T", f"{field}:Q"],
    ).properties(title=title, height=height)
    st.altair_chart(chart, use_container_width=True)


def balance_chart(df):
    base = alt.Chart(df).encode(x=alt.X("日期:O", timeUnit="yearmonthdate", axis=alt.Axis(format="%m/%d", labelAngle=-45)))
    margin = base.mark_line(point=True, color="#E15759").encode(y=alt.Y("融資餘額:Q", scale=alt.Scale(zero=False, nice=True), axis=alt.Axis(titleColor="#E15759")))
    short = base.mark_line(point=True, color="#4E79A7").encode(y=alt.Y("融券餘額:Q", scale=alt.Scale(zero=False, nice=True), axis=alt.Axis(orient="right", titleColor="#4E79A7")))
    st.altair_chart(alt.layer(margin, short).resolve_scale(y="independent").properties(height=420), use_container_width=True)


st.title("📊 台股融資融券查詢")
st.caption("輸入上市股票代號，查看股價、法人與融資融券資料。")
col1, col2, col3 = st.columns(3)
with col1:
    stock_id = st.text_input("股票代號", value="2330", max_chars=6).strip()
with col2:
    period_days = st.selectbox("查詢期間", [10, 20, 30, 60, 90], index=2, format_func=lambda x: f"最近 {x} 個日曆日")
with col3:
    end_date = st.date_input("結束日期", value=date.today(), max_value=date.today())
start_date = end_date - timedelta(days=period_days)
btn1, btn2 = st.columns([3, 1])
with btn1:
    submit = st.button("開始查詢", type="primary", use_container_width=True)
with btn2:
    if st.button("🔄 清除快取", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

if submit:
    if not stock_id.isdigit():
        st.warning("請輸入數字股票代號，例如 2330。")
        st.stop()
    with st.spinner("正在取得資料..."):
        df = fetch_history(stock_id, start_date, end_date)
        price_df = fetch_stock_price(stock_id, start_date, end_date)
    if df.empty:
        st.error("找不到資料。")
        st.stop()

    detail_df = add_reference_signal(df, price_df)
    latest = df.iloc[-1]
    st.subheader(f"{stock_id} {latest['股票名稱']}")
    st.caption(f"最新資料日期：{latest['日期']:%Y-%m-%d}")
    render_mobile_summary_tables(latest)

    st.markdown("### 股價走勢")
    if not price_df.empty:
        price_chart(detail_df)
    st.markdown("### KD 指標")
    if not price_df.empty:
        kd_chart(detail_df)

    st.markdown("### 三大法人買賣超走勢")
    bar_chart(df, "三大法人買賣超", "三大法人合計", height=260)
    c1, c2, c3 = st.columns(3)
    with c1:
        bar_chart(df, "外資買賣超", "外資", height=220)
    with c2:
        bar_chart(df, "投信買賣超", "投信", height=220)
    with c3:
        bar_chart(df, "自營商買賣超", "自營商", height=220)

    st.markdown("### 融資與融券每日變化")
    left, right = st.columns(2)
    with left:
        bar_chart(df, "融資變化", "融資每日變化", "增加", "減少", 300)
    with right:
        bar_chart(df, "融券變化", "融券每日變化", "增加", "減少", 300)

    st.markdown("### 融資與融券餘額走勢")
    balance_chart(df)

    with st.expander("查看每日明細與下載 CSV"):
        display = detail_df.copy()
        display["日期"] = display["日期"].dt.strftime("%Y-%m-%d")
        wanted = [
            "日期", "股票代號", "股票名稱", "收盤價", "MA5", "MA10", "MA20", "K", "D", "股價變化",
            "外資買賣超", "投信買賣超", "自營商買賣超", "三大法人買賣超",
            "融資餘額", "融資變化", "融券餘額", "融券變化", "參考指數",
        ]
        display = display[[c for c in wanted if c in display.columns]].sort_values("日期", ascending=False)

        color_columns = [
            "外資買賣超", "投信買賣超", "自營商買賣超", "三大法人買賣超",
            "融資變化", "融券變化",
        ]
        color_columns = [c for c in color_columns if c in display.columns]
        format_map = {
            "收盤價": "{:,.2f}", "MA5": "{:,.2f}", "MA10": "{:,.2f}", "MA20": "{:,.2f}",
            "K": "{:,.2f}", "D": "{:,.2f}", "股價變化": "{:+,.2f}",
            "外資買賣超": "{:+,.0f}", "投信買賣超": "{:+,.0f}",
            "自營商買賣超": "{:+,.0f}", "三大法人買賣超": "{:+,.0f}",
            "融資餘額": "{:,.0f}", "融資變化": "{:+,.0f}",
            "融券餘額": "{:,.0f}", "融券變化": "{:+,.0f}",
        }
        format_map = {k: v for k, v in format_map.items() if k in display.columns}
        styled_display = display.style.format(format_map, na_rep="-").map(
            color_trade_value, subset=color_columns
        )
        st.dataframe(styled_display, use_container_width=True, hide_index=True)

        csv_data = display.to_csv(index=False, encoding="utf-8-sig")
        st.download_button("下載 CSV", csv_data, f"{stock_id}_融資融券與三大法人資料.csv", "text/csv")
else:
    st.info("請輸入股票代號並按下『開始查詢』。")
