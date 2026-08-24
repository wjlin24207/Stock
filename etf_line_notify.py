import os
from glob import glob

import pandas as pd
import requests


# ==========================================
# 基本設定
# ==========================================

OUTPUT_DIR = "etf_holdings"

SUMMARY_PATTERN = os.path.join(
    OUTPUT_DIR,
    "*_common_daily_changes_summary.xlsx"
)

LAST_UPDATE_FILE = os.path.join(
    OUTPUT_DIR,
    "last_update.txt"
)

# 可在 GitHub Secrets 設定 STREAMLIT_DASHBOARD_URL
# 若沒有設定，請把下方預設網址改成你實際的 Streamlit 網址
DASHBOARD_URL = os.environ.get(
    "STREAMLIT_DASHBOARD_URL",
    "https://wjlinstock.streamlit.app/"
)


# ==========================================
# LINE 設定
# ==========================================

LINE_TOKEN = os.environ["LINE_TOKEN"]
LINE_USER_ID = os.environ["LINE_USER_ID"]


# ==========================================
# 找到最新的 Summary Excel
# ==========================================

def get_latest_summary_file() -> str:
    files = sorted(
        glob(SUMMARY_PATTERN),
        reverse=True
    )

    if not files:
        raise FileNotFoundError(
            "找不到共同異動 Summary Excel："
            f"{SUMMARY_PATTERN}"
        )

    return files[0]


# ==========================================
# 讀取最後更新時間
# ==========================================

def get_last_update_time() -> str:
    if not os.path.exists(LAST_UPDATE_FILE):
        return "未知"

    with open(
        LAST_UPDATE_FILE,
        "r",
        encoding="utf-8"
    ) as file:
        update_time = file.read().strip()

    return update_time or "未知"


# ==========================================
# 清理股票代碼
# ==========================================

def normalize_display_stock_code(value) -> str:
    if pd.isna(value):
        return ""

    text = str(value).strip()

    if text.endswith(".0"):
        text[0=========
讀取最後更新時間
=========

_last_update_time() ->======================
# 清理股票名稱
# ==========================================

def normalize_display_stock_name(value) -> str:
    if pd.isna(value):
        return ""

    text = str(value).strip()

    if text.lower() == "nan":
        return ""

    return text


# ==========================================
# 建立單一分類的股票清單
# ==========================================

def append_stock_section(
    lines[:-2


=========
理股票名稱
=========

_on: str,
    group_df: pd.DataFrame
):
    lines.append(
        f"{icon} {title}（{len(group_df)}）"
    )

    if group_df.empty:
        lines.append("無")
        return

    for _, row in group_df.iterrows():
        stock_code = normalize_display_stock_code(
            row.get("股票代碼", "")
        )

        stock_name = normalize_display_stock_name(
            row.get("股票名稱", "")
        )

        display_text = " ".join(
            item
            for item in [stock_code, stock_name]
            if item
        )

        if display_text:
            lines.append(display_text)


# ==========================================
# 建立 LINE 訊息
# ==========================================

def build_etf_message(
    summary_df: pd.DataFrame,
    update_time: str,
    dashboard_url: str
) -> str:
    required_columns = {
        "股票代碼",
        "股票名稱",
        "共同方向",
    }

    missing_columns = (
        required_columns - set(summary_df.columns)
    )

    if missing_columns:
        raise RuntimeError(
            "Summary Excel 缺少必要欄位："
            + ", ".join(sorted(missing_columns))
        )

    add_df = summary_df[
        summary_df["共同方向"] == "全部加碼"
    ].copy()

    reduce_df = summary_df[
        summary_df["共同方向"] == "全部減碼"
    ].copy()

    mixed_df = summary_df[
        summary_df["共同方向"] == "混合"
    ].copy()

    lines = [
        "ETF共同異動",
        "",
        "📅 更新時間",
        update_time,
        "",
        "📊 共同異動股票",
        f"{len(summary_df)}檔",
        "",
    ]

    append_stock_section(
        lines=lines,
        title="全部加碼",
        icon="🟢",
        group_df=add_df
    )

    lines.append("")

    append_stock_section(
        lines=lines,
        title="全部減碼",
        icon="🔴",
        group_df=reduce_df
    )

    lines.append("")

    append_stock_section(
        lines=lines,
        title="混合",
        icon="🟡",
        group_df=mixed_df
    )

    lines.extend([
        "",
        "🔗 Streamlit Dashboard",
        dashboard_url,
    ])

    message = "\n".join(lines)

    # LINE 單一文字訊息上限為 5,000 字元
    return message[:5000]


# ==========================================
# 發送 LINE
# ==========================================

def send_line_message(message: str):
    url = "https://api.line.me/v2/bot/message/push"

    headers = {
        "Authorization": f"Bearer {LINE_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "to": LINE_USER_ID,
        "messages": [
            {
                "type": "text",
                "text": message,
            }
        ],
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=30
    )

    print("LINE Status:", response.status_code)
    print("LINE Response:", response.text)

    if not response.ok:
        raise RuntimeError(
            "LINE 訊息發送失敗："
            f"{response.status_code} {response.text}"
        )


# ==========================================
# 主程式
# ==========================================

def main():
    summary_file = get_latest_summary_file()

    print(f"讀取 Summary：{summary_file}")

    summary_df = pd.read_excel(
        summary_file,
        engine="openpyxl",
        dtype={
            "股票代碼": str,
        }
    )

    update_time = get_last_update_time()

    message = build_etf_message(
        summary_df=summary_df,
        update_time=update_time,
        dashboard_url=DASHBOARD_URL
    )

    print("=" * 50)
    print(message)
    print("=" * 50)

    send_line_message(message)


if __name__ == "__main__":
    main()
