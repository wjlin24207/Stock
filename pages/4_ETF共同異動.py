from glob import glob
import os
import requests
import pandas as pd
import streamlit as st


if st.button("🔄 更新ETF資料"):

    token = st.secrets["GITHUB_TOKEN"]

    url = (
        "https://api.github.com/repos/"
        "wjlin24207/Stock/actions/workflows/"
        "etf_update.yml/dispatches"
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json"
    }

    payload = {
        "ref": "main"
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload
    )

    if response.status_code == 204:
        st.success("已送出 ETF 更新工作")
    else:
        st.error(
            f"送出失敗：{response.status_code}"
        )

st.set_page_config(
    page_title="ETF共同異動",
    layout="wide"
)

st.title("ETF共同異動")

last_update = "未知"

try:

    with open(
        "etf_holdings/last_update.txt",
        "r",
        encoding="utf-8"
    ) as f:

        last_update = f.read().strip()

except Exception:
    pass

st.success(
    f"✅ 最後更新時間：{last_update}"
)

def get_latest_file(pattern):
    files = sorted(
        glob(pattern),
        reverse=True
    )

    if not files:
        return None

    return files[0]


# =========================
# 找最新檔案
# =========================

summary_file = get_latest_file(
    "etf_holdings/*common_daily_changes_summary.xlsx"
)

daily_file = get_latest_file(
    "etf_holdings/*daily_changes_changed_only.xlsx"
)

holding_file = get_latest_file(
    "etf_holdings/*common_holdings_all*.xlsx"
)


tab1, tab2, tab3 = st.tabs(
    [
        "共同異動 Summary",
        "每日異動",
        "共同持股"
    ]
)


# =========================
# Tab1 Summary
# =========================

with tab1:

    if summary_file:

        st.info(
            f"最新檔案：{os.path.basename(summary_file)}"
        )

        df = pd.read_excel(
            summary_file,
            engine="openpyxl"
        )

        col1, col2, col3 = st.columns(3)

        col1.metric(
            "共同異動股票數",
            len(df)
        )

        col2.metric(
            "全部加碼",
            (df["共同方向"] == "全部加碼").sum()
        )

        col3.metric(
            "全部減碼",
            (df["共同方向"] == "全部減碼").sum()
        )

        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True
        )

    else:
        st.warning("找不到共同異動 Summary 檔案")


# =========================
# Tab2 每日異動
# =========================

with tab2:

    if daily_file:

        st.info(
            f"最新檔案：{os.path.basename(daily_file)}"
        )

        daily_df = pd.read_excel(
            daily_file,
            engine="openpyxl"
        )

        # 每日異動頁面不顯示的欄位
        daily_hidden_columns = [
            "股票名稱_昨日",
            "權重_昨日",
            "股數_昨日",
        ]

        daily_df = daily_df.drop(
            columns=daily_hidden_columns,
            errors="ignore"
        )

        st.dataframe(
            daily_df,
            use_container_width=True,
            hide_index=True
        )

    else:
        st.warning("找不到每日異動檔案")


# =========================
# Tab3 共同持股
# =========================

with tab3:

    if holding_file:

        st.info(
            f"最新檔案：{os.path.basename(holding_file)}"
        )

        holding_df = pd.read_excel(
            holding_file,
            engine="openpyxl",
            dtype={
                "股票代碼": str,
            }
        )

        # 隱藏各 ETF 的股票名稱與股數欄位
        # 保留「顯示股票名稱」及各 ETF 的權重
        hidden[

 col in holding_df.columns
 (
.ol
            for col in holding_df.columns
            if (
                col.endswith("_股票名稱")
                or col.endswith("_股數")
            )
        ]

        holding_df = holding_df.drop(
            columns=hidden_holding_columns,
            errors="ignore"
        )

        # 將「共同持有ETF」移到最後一欄
        if "共同持有ETF" in holding_df.columns:
            other[

 col in holding_df.columns
 (
.               for col in holding_df.columns
                if col != "共同持有ETF"
            ]

            holding_df = holding_df[
                other[
_columns + 共同持有ETF"]
            ]

        st.dataframe(
            holding_df,
            use_container_width=True,
            hide_index=True
        )

    else:
        st.warning("找不到共同持股檔案")
