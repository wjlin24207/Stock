import streamlit as st

st.set_page_config(
    page_title="WJLin_Stock_Tracking",
    layout="wide"
)

st.title("股票系統")

st.write("請從左側選單選擇要執行的功能。")

st.markdown(
    """
    ## 功能選單

    左側 Pages 會顯示：

    - 台股
    - 美股
    - 基金
    - 主動ETF持股
    
    選擇後就會直接執行對應的 Streamlit 程式。
    """
)
