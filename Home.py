import streamlit as st

st.set_page_config(
    page_title="R&S FSW Tool",
    layout="wide"
)

st.title("R&S FSW Tool")

st.write("請從左側選單選擇要執行的功能。")

st.markdown(
    """
    ## 功能選單

    左側 Pages 會顯示：

    - FSW Screenshot
    - FSW CSE Measurement

    選擇後就會直接執行對應的 Streamlit 程式。
    """
)
