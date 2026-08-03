import requests
from bs4 import BeautifulSoup
import urllib3

# 忽略 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# LINE 設定
# ==========================================

LINE_TOKEN = "H3L5JbmWTlvBBmn51kOXKYPAGxBAME90+2AikZ62Z91mQmpIbxPpd08FAyZHf0/aw47WIhHs6So6OZ2hphgxoGYxxEY6GZnRejPmoWru5vcMJiV02JH3AIfc7SrluRaxGBhYOy1k+Jlep1Kuy0NDgwdB04t89/1O/w1cDnyilFU="
USER_ID = "U46b1da0a0dda2bba78d89e807f124fe5"

# ==========================================
# 基金清單
# ==========================================

FUNDS = {
    "安聯收益成長": "https://www.moneydj.com/funddj/ya/yp010001.djhtm?a=tlz64",
    "貝萊德世界科技A10": "https://www.moneydj.com/funddj/ya/yp010001.djhtm?a=shzv9",
    "富坦穩定月收益": "https://www.moneydj.com/funddj/ya/yp010001.djhtm?a=flz92",
    "野村優質": "https://www.moneydj.com/funddj/ya/yp010000.djhtm?a=acic01",
    "安聯台灣科技": "https://www.moneydj.com/funddj/ya/yp010000.djhtm?a=acdd04",
    "統一奔騰": "https://www.moneydj.com/funddj/ya/yp010000.djhtm?a=acps10"
}

# ==========================================
# 抓基金資料
# ==========================================

def fetch_moneydj_fund(name, url):

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.moneydj.com/"
    }

    try:

        resp = requests.get(
            url,
            headers=headers,
            timeout=20,
            verify=False
        )

        resp.raise_for_status()

        soup = BeautifulSoup(
            resp.content,
            "html.parser"
        )

        price = "N/A"
        change = "N/A"
        date = "N/A"

        def is_price(v):
            return any(c.isdigit() for c in v) and "/" not in v

        def is_change(v):
            return any(c.isdigit() for c in v) and "/" not in v

        def is_date(v):
            return (
                ("/" in v or "-" in v)
                and any(c.isdigit() for c in v)
            )

        price_lbls = [
            "最新淨值",
            "最新報價",
            "淨值(報價)",
            "淨值"
        ]

        change_lbls = [
            "漲跌幅",
            "日漲跌幅",
            "漲跌",
            "漲跌(%)",
            "漲跌幅(%)",
            "每日變化"
        ]

        date_lbls = [
            "淨值日期",
            "報價日期",
            "日期"
        ]

        for table in soup.find_all("table"):

            rows = table.find_all("tr")

            for r_idx, row in enumerate(rows):

                cells = row.find_all(["th", "td"])
                texts = [c.get_text(strip=True) for c in cells]

                if any(lbl in texts for lbl in price_lbls):

                    if r_idx + 1 < len(rows):

                        next_cells = rows[r_idx + 1].find_all(
                            ["th", "td"]
                        )

                        next_texts = [
                            c.get_text(strip=True)
                            for c in next_cells
                        ]

                        for c_idx, lbl in enumerate(texts):

                            if c_idx < len(next_texts):

                                val = next_texts[c_idx]

                                if (
                                    lbl in price_lbls
                                    and price == "N/A"
                                    and is_price(val)
                                ):
                                    price = val

                                elif (
                                    lbl in date_lbls
                                    and date == "N/A"
                                    and is_date(val)
                                ):
                                    date = val

                                elif (
                                    lbl in change_lbls
                                    and is_change(val)
                                ):
                                    change = val

        return {
            "基金名稱": name,
            "最新淨值": price,
            "漲跌幅": change,
            "淨值日期": date
        }

    except Exception as e:

        return {
            "基金名稱": name,
            "最新淨值": "N/A",
            "漲跌幅": "N/A",
            "淨值日期": "N/A"
        }

# ==========================================
# 建立 LINE 訊息
# ==========================================

def build_message(data_list):

    lines = []

    lines.append("📈 基金每日追蹤")
    lines.append("")

    for item in data_list:

        if item["最新淨值"] == "N/A":
            continue

        change = item["漲跌幅"]

        if "-" in change:
            icon = "🟢"
        else:
            icon = "🔴"

        lines.append(
            f"{icon} {item['基金名稱']}\n"
            f"淨值：{item['最新淨值']}\n"
            f"漲跌幅：{item['漲跌幅']}\n"
            f"日期：{item['淨值日期']}\n"
        )

    return "\n".join(lines)

# ==========================================
# 發送 LINE
# ==========================================

def send_line_message(message):

    url = "https://api.line.me/v2/bot/message/push"

    headers = {
        "Authorization": f"Bearer {LINE_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "to": USER_ID,
        "messages": [
            {
                "type": "text",
                "text": message[:5000]
            }
        ]
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload
    )

    print(response.status_code)
    print(response.text)

# ==========================================
# 主程式
# ==========================================

def main():

    data_list = []

    for name, url in FUNDS.items():

        print(f"抓取中: {name}")

        info = fetch_moneydj_fund(
            name,
            url
        )

        data_list.append(info)

    message = build_message(data_list)

    print(message)

    send_line_message(message)

if __name__ == "__main__":
    main()
