import os
import requests

from fund_utils import FUNDS, fetch_moneydj_fund

# ==========================================
# LINE 設定
# ==========================================

LINE_TOKEN = os.environ["LINE_TOKEN"]
USER_ID = os.environ["LINE_USER_ID"]


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

        icon = "🟢" if "-" in change else "🔴"

        lines.append(
            f"{icon} {item['基金名稱']}\n"
            f"💰 淨值：{item['最新淨值']}\n"
            f"📊 漲跌：{item['漲跌幅']}\n"
            f"📅 日期：{item['淨值日期']}\n"
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

    print("Status:", response.status_code)
    print("Response:", response.text)


# ==========================================
# 主程式
# ==========================================

def main():

    data_list = []

    for name, url in FUNDS.items():

        print(f"抓取中: {name}")

        info = fetch_moneydj_fund(name, url)

        print(info)

        data_list.append(info)

    message = build_message(data_list)

    print(message)

    send_line_message(message)


if __name__ == "__main__":
    main()
