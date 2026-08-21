import os
import pandas as pd
import streamlit as st

st.title("ETF共同異動")

file_path = (
    "etf_holdings/"
    "2026-08-21_common_daily_changes_summary.xlsx"
)

if os.path.exists(file_path):

    df = pd.read_excel(
        file_path,
        engine="openpyxl"
    )

    st.dataframe(
        df,
        use_container_width=True
    )

else:
    st.warning("找不到 Summary 檔")
