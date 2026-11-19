# -*- coding: utf-8 -*-
"""自選基金追蹤頁面。請與 fund_utils.py 放在同一個資料夾。"""

import streamlit as st
from fund_utils import render_fund_table


st.set_page_config(
    page_title="自選基金追蹤",
    layout="centered",
)

st.markdown("## ⭐ 自選基金")

if st.button("🔄 重新整理資料", type="primary"):
    st.cache_data.clear()
    st.rerun()

render_fund_table()
