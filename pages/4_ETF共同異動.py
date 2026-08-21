from glob import glob
import os

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="ETF共同異動",
    layout="wide"
)

st.title("ETF共同異動")

files = sorted(
    glob(
        "etf_holdings/*common_daily_changes_summary.xlsx"
    ),
    reverse=True
)

if not files:
    st.warning("找不到共同異動 Summary 檔案")
    st.stop()

latest_file = files[0]

update_time = os.path.getmtime(
    latest_file
)

st.info(
    f"最新檔案：{os.path.basename(latest_file)}"
)

df = pd.read_excel(
    latest_file,
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
