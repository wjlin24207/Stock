import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd

# 頁面設定 (適合手機版，移除 wide layout)
st.set_page_config(page_title="自選基金追蹤", layout="centered")

st.markdown("## ⭐ 自選基金")


@st.cache_data(ttl=600, show_spinner=False)

data_list = []
with st.spinner("正在從 MoneyDJ 抓取最新報價..."):
    st.cache_data.clear()
    for name, url in FUNDS.items():
        info = fetch_moneydj_fund(name, url)
        data_list.append(info)

# -----------------------------------------------------
# UI 介面生成 
# -----------------------------------------------------
if data_list:
    st.write("") 
    
    for item in data_list:
        if item['最新淨值'] == "N/A":
            st.error(f"{item['基金名稱']} - 抓取失敗")
            continue
            
        is_down = "-" in item['漲跌幅']
        color = "#21c45d" if is_down else "#ff4b4b"
        arrow = "▼" if is_down else "▲"
        display_change = item['漲跌幅'].replace("-", "")

        # 💡 將 HTML 標籤靠左對齊，並移除內部的空行，避免觸發 Markdown 程式碼區塊解析
        card_html = f"""<a href="{item['資料連結']}" target="_blank" style="text-decoration: none; display: block;">
<div style="background-color: #262730; padding: 16px 20px; border-radius: 8px; border-left: 6px solid {color}; margin-bottom: 16px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); cursor: pointer;">
<div style="color: #ffffff; font-size: 22px; font-weight: bold; margin-bottom: 8px;">{item['基金名稱']} <span style="color: #a3a8b8; font-size: 14px; font-weight: normal;">({item['淨值日期']})</span></div>
<div style="color: #a3a8b8; font-size: 18px; margin-bottom: 4px; font-family: monospace;">淨值: {item['最新淨值']}</div>
<div style="color: {color}; font-size: 24px; font-weight: bold; font-family: monospace;">{arrow} {display_change}</div>
</div>
</a>"""
        st.markdown(card_html, unsafe_allow_html=True)

    st.markdown("---")
    with st.expander("📋 查看完整數據表 (建議於電腦版觀看)"):
        df = pd.DataFrame(data_list)
        st.dataframe(
            df,
            column_config={
                "資料連結": st.column_config.LinkColumn("MoneyDJ 連結", display_text="點此查看")
            },
            use_container_width=True,
            hide_index=True
        )
