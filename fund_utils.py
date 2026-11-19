# -*- coding: utf-8 -*-
"""MoneyDJ 基金資料工具：以表格方式呈現 6 檔基金最新淨值。"""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests
import streamlit as st
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 請保留純網址，不要貼入 <a href="...">...</a> HTML 標籤。
FUNDS = {
    "安聯收益成長": "https://www.moneydj.com/funddj/ya/yp010001.djhtm?a=tlz64",
    "貝萊德世界科技A10": "https://www.moneydj.com/funddj/ya/yp010001.djhtm?a=shzv9",
    "富坦穩定月收益": "https://www.moneydj.com/funddj/ya/yp010001.djhtm?a=flz92",
    "野村優質": "https://www.moneydj.com/funddj/ya/yp010000.djhtm?a=acic01",
    "安聯台灣科技": "https://www.moneydj.com/funddj/ya/yp010000.djhtm?a=acdd04",
    "統一奔騰": "https://www.moneydj.com/funddj/ya/yp010000.djhtm?a=acps10",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.moneydj.com/",
}


def _clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _is_price(value):
    value = _clean_text(value)
    return bool(re.search(r"\d", value)) and "/" not in value and "%" not in value


def _is_change(value):
    value = _clean_text(value)
    return bool(re.search(r"\d", value)) and "/" not in value


def _is_date(value):
    value = _clean_text(value)
    return bool(re.search(r"\d", value)) and ("/" in value or "-" in value)


def _change_number(value):
    """從漲跌文字取出第一個數字，僅供表格正負顏色判斷。"""
    if not value or value == "N/A":
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", value.replace(",", ""))
    if not match:
        return None
    number = float(match.group())
    if any(mark in value for mark in ("▼", "▽")) and number > 0:
        number = -number
    return number


def _normalize_change(value):
    """將 MoneyDJ 的方向符號轉成數值正負號。"""
    value = _clean_text(value)
    if not value or value == "N/A":
        return "N/A"

    is_down = any(mark in value for mark in ("▼", "▽", "下跌"))
    is_up = any(mark in value for mark in ("▲", "△", "上漲"))

    cleaned = value
    for mark in ("▼", "▽", "▲", "△", "下跌", "上漲"):
        cleaned = cleaned.replace(mark, "")
    cleaned = _clean_text(cleaned)

    # 同時處理漲跌值及括號內百分比。
    def replace_number(match):
        number_text = match.group(0)
        try:
            number = float(number_text)
        except ValueError:
            return number_text

        if is_down:
            return f"-{number_text.lstrip('+-')}" if number != 0 else number_text.lstrip('+-')
        if is_up:
            return number_text.lstrip('+-')
        return number_text

    return re.sub(r"(?<![\d.])[+-]?\d+(?:\.\d+)?", replace_number, cleaned)


def fetch_moneydj_fund(name, url):
    """取得單檔基金的最新淨值、漲跌和淨值日期。"""
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=20,
            verify=False,
        )
        response.raise_for_status()
        response.encoding = response.apparent_encoding or "utf-8"
        soup = BeautifulSoup(response.text, "html.parser")

        price, change, date = "N/A", "N/A", "N/A"

        price_labels = ["最新淨值", "最新報價", "淨值(報價)", "淨值"]
        change_labels = ["漲跌幅", "日漲跌幅", "漲跌", "漲跌(%)", "漲跌幅(%)", "每日變化"]
        date_labels = ["淨值日期", "報價日期", "日期"]

        # MoneyDJ 常見格式：表頭在上一列，資料在下一列。
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            for row_index, row in enumerate(rows):
                cells = row.find_all(["th", "td"])
                texts = [_clean_text(cell.get_text(" ", strip=True)) for cell in cells]

                if not any(label in texts for label in price_labels):
                    continue
                if row_index + 1 >= len(rows):
                    continue

                next_cells = rows[row_index + 1].find_all(["th", "td"])
                next_texts = [_clean_text(cell.get_text(" ", strip=True)) for cell in next_cells]

                for cell_index, label in enumerate(texts):
                    if cell_index >= len(next_texts):
                        continue
                    value = next_texts[cell_index]

                    if label in price_labels and price == "N/A" and _is_price(value):
                        price = value
                    elif label in date_labels and date == "N/A" and _is_date(value):
                        date = value
                    elif label in change_labels and _is_change(value):
                        if change == "N/A":
                            change = value
                            if cell_index + 1 < len(next_texts):
                                percentage = next_texts[cell_index + 1]
                                if "%" in percentage and _is_change(percentage):
                                    change = f"{value} ({percentage})"
                        elif "%" not in change and "%" in value:
                            change = f"{change} ({value})"

        # 備援格式：標籤和值位於同一列的相鄰儲存格。
        for row in soup.find_all("tr"):
            cells = row.find_all(["th", "td"])
            for index in range(len(cells) - 1):
                label = _clean_text(cells[index].get_text(" ", strip=True))
                if label not in price_labels + change_labels + date_labels:
                    continue

                values = []
                for next_index in range(index + 1, min(index + 4, len(cells))):
                    value = _clean_text(cells[next_index].get_text(" ", strip=True))
                    if value:
                        values.append(value)

                if not values:
                    continue
                value = values[0]

                if label in price_labels and price == "N/A" and _is_price(value):
                    price = value
                elif label in date_labels and date == "N/A" and _is_date(value):
                    date = value
                elif label in change_labels and _is_change(value):
                    if change == "N/A":
                        change = value
                        if len(values) > 1 and "%" in values[1] and _is_change(values[1]):
                            change = f"{value} ({values[1]})"
                    elif "%" not in change and "%" in value:
                        change = f"{change} ({value})"

        change = _normalize_change(change)

        return {
            "基金名稱": name,
            "最新淨值": price,
            "漲跌幅": change,
            "淨值日期": date,
            "資料連結": url,
            "_漲跌數值": _change_number(change),
        }

    except Exception as error:
        return {
            "基金名稱": name,
            "最新淨值": "N/A",
            "漲跌幅": "N/A",
            "淨值日期": "N/A",
            "資料連結": url,
            "_漲跌數值": None,
        }


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_all_funds():
    """平行讀取全部基金，回傳 DataFrame，快取 30 分鐘。"""
    results_by_name = {}

    with ThreadPoolExecutor(max_workers=min(6, len(FUNDS))) as executor:
        futures = {
            executor.submit(fetch_moneydj_fund, name, url): name
            for name, url in FUNDS.items()
        }
        for future in as_completed(futures):
            name = futures[future]
            results_by_name[name] = future.result()

    # 維持 FUNDS 原始排序。
    rows = [results_by_name[name] for name in FUNDS]
    return pd.DataFrame(rows)


def render_fund_table():
    """在 Streamlit 頁面顯示基金表格，基金名稱可直接點擊 MoneyDJ。"""
    import html

    with st.spinner("正在更新基金淨值…"):
        dataframe = fetch_all_funds()

    rows_html = []
    for _, row in dataframe.iterrows():
        name = html.escape(str(row["基金名稱"]))
        url = html.escape(str(row["資料連結"]), quote=True)
        date = html.escape(str(row["淨值日期"]))
        price = html.escape(str(row["最新淨值"]))
        change = html.escape(str(row["漲跌幅"]))
        change_number = row.get("_漲跌數值")

        if pd.isna(change_number) if change_number is not None else True:
            color_class = "fund-change-flat"
        elif float(change_number) < 0:
            color_class = "fund-change-down"
        elif float(change_number) > 0:
            color_class = "fund-change-up"
        else:
            color_class = "fund-change-flat"

        rows_html.append(
            f"""
            <tr>
                <td><a href="{url}" target="_blank" rel="noopener noreferrer">{name}</a></td>
                <td>{date}</td>
                <td>{price}</td>
                <td class="{color_class}">{change}</td>
            </tr>
            """
        )

    table_html = f"""
    <style>
        .fund-table-wrap {{
            width: 100%;
            overflow-x: auto;
            border: 1px solid rgba(128, 128, 128, 0.35);
            border-radius: 10px;
        }}
        .fund-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 16px;
        }}
        .fund-table th {{
            text-align: left;
            padding: 12px 14px;
            background: rgba(128, 128, 128, 0.14);
            border-bottom: 1px solid rgba(128, 128, 128, 0.35);
            white-space: nowrap;
        }}
        .fund-table td {{
            padding: 12px 14px;
            border-bottom: 1px solid rgba(128, 128, 128, 0.22);
            white-space: nowrap;
        }}
        .fund-table tr:last-child td {{ border-bottom: none; }}
        .fund-table a {{
            color: #2f80ed;
            font-weight: 600;
            text-decoration: none;
        }}
        .fund-table a:hover {{ text-decoration: underline; }}
        .fund-change-up {{ color: #e53935; font-weight: 600; }}
        .fund-change-down {{ color: #16a34a; font-weight: 600; }}
        .fund-change-flat {{ color: inherit; }}
    </style>
    <div class="fund-table-wrap">
        <table class="fund-table">
            <thead>
                <tr>
                    <th>基金名稱</th>
                    <th>淨值日期</th>
                    <th>最新淨值</th>
                    <th>漲跌／漲跌幅</th>
                </tr>
            </thead>
            <tbody>{''.join(rows_html)}</tbody>
        </table>
    </div>
    """

    # 壓縮成單行 HTML，避免動態產生的 <tr> 縮排被 Markdown 當成程式碼區塊。
    compact_html = re.sub(r">\s+<", "><", table_html).strip()
    st.markdown(compact_html, unsafe_allow_html=True)
    return dataframe


# 可直接執行本檔測試：streamlit run fund_utils.py
if __name__ == "__main__":
    st.set_page_config(page_title="基金淨值", page_icon="💰", layout="wide")
    st.title("基金最新淨值")

    if st.button("🔄 重新整理資料", type="primary"):
        st.cache_data.clear()
        st.rerun()

    render_fund_table()
