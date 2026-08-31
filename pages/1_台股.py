import time
import json
import re
import requests
import urllib3
import yfinance as yf
import pandas as pd
import streamlit as st

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(
    page_title="自選股 KD 均線監控儀表板（含大盤）",
    layout="wide",
)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
})


def parse_number(value, default=None):
    if value is None:
        return default
    text = str(value).strip()
    if text in ("", "-", "--"):
        return default
    try:
        cleaned = text.replace(",", "").replace("%", "").strip()
        return float(cleaned)
    except (TypeError, ValueError):
        return default


def get_all_live_prices(stock_list):
    ex_ch_list = []
    for sid in stock_list:
        if sid == "^TWII":
            ex_ch_list.append("tse_t00.tw")
        else:
            ex_ch_list.extend([f"tse_{sid}.tw", f"otc_{sid}.tw"])

    url = (
        "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
        f"?ex_ch={'|'.join(ex_ch_list)}&json=1&delay=0"
    )

    try:
        response = session.get(url, timeout=10, verify=False)
        response.raise_for_status()
        data = response.json()
        price_map = {}
        for info in data.get("msgArray", []):
            key = info.get("c")
            if key == "t00":
                key = "^TWII"
            if key:
                price_map[key] = info
        return price_map
    except Exception as error:
        print(f"證交所即時報價抓取失敗：{error}")
        return {}



def get_twse_etf_inav():
    """抓取證交所官方 ETF 預估淨值及折溢價。"""
    page_url = (
        "https://mis.twse.com.tw/stock/various-areas/etf-price/"
        "indicator-disclosure-etf?lang=zhHant"
    )
    data_url = f"https://mis.twse.com.tw/stock/data/all_etf.txt?_={int(time.time() * 1000)}"
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Referer": page_url,
        "User-Agent": session.headers.get("User-Agent", "Mozilla/5.0"),
        "Cache-Control": "no-cache",
    }

    def find_etf_records(obj):
        found = []
        if isinstance(obj, dict):
            # 真正資料列具有 ETF 代號 a，並通常具有 e/f/g 欄位。
            if "a" in obj and any(key in obj for key in ("e", "f", "g")):
                found.append(obj)
            for value in obj.values():
                found.extend(find_etf_records(value))
        elif isinstance(obj, list):
            for value in obj:
                found.extend(find_etf_records(value))
        return found

    try:
        session.get(page_url, headers=headers, timeout=15, verify=False)
        response = session.get(data_url, headers=headers, timeout=15, verify=False)
        response.raise_for_status()

        text = response.text.lstrip("\ufeff").strip()
        try:
            payload = response.json()
        except Exception:
            payload = json.loads(text)

        records = find_etf_records(payload)
        inav_map = {}

        for item in records:
            sid = str(item.get("a", "")).strip()
            if not sid:
                continue

            market_price = parse_number(item.get("e"))
            inav = parse_number(item.get("f"))
            official_rate = parse_number(item.get("g"))

            if official_rate is None and market_price is not None and inav is not None and inav > 0:
                official_rate = (market_price - inav) / inav * 100

            inav_map[sid] = {
                "iNAV": inav,
                "溢折價率%": official_rate,
                "資料日期": str(item.get("i", "")).strip(),
                "資料時間": str(item.get("j", "")).strip(),
            }

        return inav_map, None

    except Exception as error:
        return {}, str(error)

def get_all_yahoo_hist(stock_list):
    tickers = [f"{sid}.TW" if not sid.startswith("^") else sid for sid in stock_list]
    try:
        return yf.download(
            tickers,
            period="6mo",
            interval="1d",
            progress=False,
            group_by="ticker",
            auto_adjust=True,
        )
    except Exception as error:
        print(f"Yahoo 歷史資料抓取失敗：{error}")
        return pd.DataFrame()


def process_kd_logic(stock_id, live_info, hists_all):
    try:
        key = f"{stock_id}.TW" if not stock_id.startswith("^") else stock_id

        if isinstance(hists_all.columns, pd.MultiIndex):
            available = hists_all.columns.get_level_values(0)
            if key not in available:
                return None
            hist = hists_all[key].dropna().copy()
        else:
            hist = hists_all.dropna().copy()

        if hist.empty:
            return None

        hist.columns = [str(c).lower() for c in hist.columns]
        if not all(c in hist.columns for c in ("high", "low", "close")):
            return None

        last_price = parse_number(live_info.get("z"))
        best_bid_text = str(live_info.get("b", "-")).split("_")[0]
        best_bid = parse_number(best_bid_text)
        yesterday_price = parse_number(live_info.get("y"), 0)

        live_price = last_price if last_price is not None else best_bid
        if live_price is None:
            live_price = yesterday_price
        if live_price is None or live_price <= 0:
            return None
        if yesterday_price is None or yesterday_price <= 0:
            yesterday_price = live_price

        temp = hist.astype(float).copy()
        temp.iloc[-1, temp.columns.get_loc("close")] = live_price
        temp["9h"] = temp["high"].rolling(9).max()
        temp["9l"] = temp["low"].rolling(9).min()
        temp["rsv"] = (
            100 * (temp["close"] - temp["9l"])
            / (temp["9h"] - temp["9l"] + 1e-9)
        ).fillna(50)

        k, d = 50.0, 50.0
        for rsv in temp["rsv"]:
            k = k * (2 / 3) + rsv * (1 / 3)
            d = d * (2 / 3) + k * (1 / 3)

        # MA5、MA10保留背景運算，僅不顯示在表格。
        ma5 = temp["close"].rolling(5).mean()
        ma10 = temp["close"].rolling(10).mean()
        ma20 = temp["close"].rolling(20).mean()
        ma5_t, ma10_t, ma20_t = ma5.iloc[-1], ma10.iloc[-1], ma20.iloc[-1]
        ma5_y, ma10_y = ma5.iloc[-2], ma10.iloc[-2]

        diff = live_price - yesterday_price
        percent = diff / yesterday_price * 100 if yesterday_price > 0 else 0

        signal = ["📈多" if k > d else "📉空"]
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

        name = "加權指數" if stock_id == "^TWII" else live_info.get("n", stock_id)

        return {
            "代號": stock_id,
            "名稱": name,
            "價格": round(live_price, 2),
            "漲跌": round(diff, 2),
            "漲幅%": round(percent, 2),
            "K": round(k, 2),
            "D": round(d, 2),
            "iNAV": None,
            "溢折價率%": None,
            "MA20": round(ma20_t, 2),
            "均線狀態": ma_status,
            "訊號": " ".join(signal),
        }
    except Exception as error:
        print(f"{stock_id} 資料處理失敗：{error}")
        return None


# ===== 4. 上方卡片與下方表格使用獨立清單 =====
# 只想顯示在上方卡片的股票，加入 card_watchlist。
card_watchlist = [
    "^TWII",
    "0056",
    "00878",
    "00919",
    "0050",
    "00981A",
]

# 只想顯示在下方表格的股票，加入 table_watchlist。
table_watchlist = [
    "^TWII",
    "0056",
    "00878",
    "00919",
    "0050",
    "00981A",
    "009816",
    "00685L",
    "2330",
    "3711",
]

# 合併後統一抓取資料，dict.fromkeys 可去除重複代號並保留原本順序。
all_watchlist = list(dict.fromkeys(card_watchlist + table_watchlist))

prices = get_all_live_prices(all_watchlist)
etf_inav_map, etf_inav_error = get_twse_etf_inav()
hists = get_all_yahoo_hist(all_watchlist)

st.title("📊 策略監控儀表板（精簡專業版）")
st.markdown("---")
refresh_seconds = st.number_input(
    "⏱️ 自動刷新秒數", min_value=5, max_value=3600, value=30, step=5
)

# 分別建立上方卡片資料與下方表格資料。
# 計算結果先放入 result_map，同一檔股票只處理一次。
result_map = {}

for sid in all_watchlist:
    live = prices.get(sid)
    if not live or hists.empty:
        continue

    result = process_kd_logic(sid, live, hists)
    if not result:
        continue

    etf_info = etf_inav_map.get(sid, {})
    result["iNAV"] = etf_info.get("iNAV")
    result["溢折價率%"] = etf_info.get("溢折價率%")
    result_map[sid] = result

# 依照各自清單的排列順序建立畫面資料。
card_rows = [result_map[sid].copy() for sid in card_watchlist if sid in result_map]
table_rows = [result_map[sid].copy() for sid in table_watchlist if sid in result_map]

if card_rows:
    st.subheader("⭐ 自選股即時監控快照")
    cards_per_row = 5
    for i in range(0, len(card_rows), cards_per_row):
        cols = st.columns(cards_per_row)
        for idx, item in enumerate(card_rows[i:i + cards_per_row]):
            with cols[idx]:
                sid = item["代號"]
                name = item["名稱"]
                price = item["價格"]
                change = item["漲跌"]
                pct = item["漲幅%"]

                if change > 0:
                    color, icon, sign = "#FF4B4B", "▲", "+"
                elif change < 0:
                    color, icon, sign = "#00B050", "▼", ""
                else:
                    color, icon, sign = "#888888", "—", ""

                target_url = (
                    "https://tw.stock.yahoo.com/tw-market"
                    if sid == "^TWII"
                    else f"https://tw.stock.yahoo.com/quote/{sid}/technical-analysis"
                )

                card_html = f'''
                <a href="{target_url}" target="_blank" style="text-decoration:none;color:inherit;">
                    <div style="background-color:#1E222D;padding:14px;border-radius:10px;
                                border-left:6px solid {color};margin-bottom:12px;
                                box-shadow:0 4px 6px rgba(0,0,0,0.1);cursor:pointer;">
                        <div style="color:#AEB3B7;font-size:22px;font-weight:500;
                                    white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                            {name} ({sid}) ↗
                        </div>
                        <div style="color:#FFFFFF;font-size:18px;font-weight:700;font-family:monospace;">
                            {price:,.2f}
                        </div>
                        <div style="color:{color};font-size:24px;font-weight:600;font-family:monospace;">
                            {icon} {sign}{change:,.2f} ({sign}{pct:.2f}%)
                        </div>
                    </div>
                </a>
                '''
                st.markdown(card_html, unsafe_allow_html=True)
    st.markdown("---")

st.subheader("📋 自選股策略數據總覽")
st.caption("iNAV 與溢折價率資料來源：臺灣證券交易所 all_etf.txt；非 ETF 標的顯示 -")
if etf_inav_error:
    st.warning(f"證交所 iNAV 抓取失敗：{etf_inav_error}")
elif not etf_inav_map:
    st.warning("證交所有回應，但未解析到 ETF iNAV 資料。請稍後重新整理。")
else:
    st.caption(f"已讀取 {len(etf_inav_map)} 檔 ETF 的證交所資料")

if not table_rows:
    st.error("❌ 系統暫時無法獲取下方表格資料，請稍後刷新頁面重試。")
else:
    df = pd.DataFrame(table_rows).rename(columns={
        "代號": "代號/K線",
        "名稱": "名稱/成份股",
    })

    col_order = [
        "代號/K線", "名稱/成份股", "價格", "漲跌", "漲幅%",
        "iNAV", "溢折價率%", "K", "D", "MA20", "均線狀態", "訊號",
    ]
    df = df[[c for c in col_order if c in df.columns]]
    df["代號_raw"] = df["代號/K線"]

    def make_id_link(row):
        sid = row["代號_raw"]
        url = (
            "https://tw.stock.yahoo.com/tw-market"
            if sid == "^TWII"
            else f"https://tw.stock.yahoo.com/quote/{sid}/technical-analysis"
        )
        return f'<a href="{url}" target="_blank">{sid}</a>'

    def make_name_link(row):
        sid = row["代號_raw"]
        name = row["名稱/成份股"]
        if str(sid).startswith("00"):
            url = (
                "https://www.moneydj.com/ETF/X/Basic/"
                f"Basic0007.xdjhtm?etfid={sid}.TW"
            )
            return f'<a href="{url}" target="_blank">{name}</a>'
        return name

    df["名稱/成份股"] = df.apply(make_name_link, axis=1)
    df["代號/K線"] = df.apply(make_id_link, axis=1)
    df = df.drop(columns=["代號_raw"])

    styled = df.style.format({
        "價格": "{:,.2f}",
        "漲跌": "{:+,.2f}",
        "漲幅%": "{:+,.2f}%",
        "K": "{:.2f}",
        "D": "{:.2f}",
        "iNAV": lambda value: "-" if pd.isna(value) else f"{value:,.2f}",
        "溢折價率%": lambda value: "-" if pd.isna(value) else f"{value:+,.2f}%",
        "MA20": "{:.2f}",
    })

    def color_change(value):
        if pd.isna(value):
            return ""
        return "color:#FF4B4B" if value > 0 else "color:#00B050" if value < 0 else ""

    styled = styled.map(color_change, subset=["漲跌", "漲幅%"])

    def apply_price(row):
        diff = df.loc[row.name, "漲跌"]
        style = "color:#FF4B4B;font-weight:bold" if diff > 0 else (
            "color:#00B050;font-weight:bold" if diff < 0 else ""
        )
        return [style]

    styled = styled.apply(apply_price, subset=["價格"], axis=1)

    def apply_ma20(row):
        price = df.loc[row.name, "價格"]
        value = row["MA20"]
        style = "color:#FF4B4B" if value < price else "color:#00B050" if value > price else ""
        return [style]

    styled = styled.apply(apply_ma20, subset=["MA20"], axis=1)

    def color_premium(value):
        if pd.isna(value):
            return ""
        return "color:#FF4B4B;font-weight:bold" if value > 0 else (
            "color:#00B050;font-weight:bold" if value < 0 else ""
        )

    styled = styled.map(color_premium, subset=["溢折價率%"])

    st.markdown('''
    <style>
    table { width:100% !important; table-layout:auto; }
    td, th { white-space:nowrap; font-size:14px; padding:6px 10px !important; }
    div[data-testid="stMarkdownContainer"] { overflow-x:auto; }
    </style>
    ''', unsafe_allow_html=True)

    st.markdown(styled.hide(axis="index").to_html(escape=False), unsafe_allow_html=True)

time.sleep(refresh_seconds)
st.rerun()
