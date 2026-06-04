
st.markdown("""
<style>

/* 表格整體 */
table {
    width: 100% !important;
    table-layout: fixed;
}

/* ✅ 不換行（你要的） */
td, th {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    font-size: 14px;
}

/* ✅ 讓整個表可以橫向滑動（手機關鍵🔥） */
div[data-testid="stMarkdownContainer"] {
    overflow-x: auto;
}

/* ✅ 代號欄固定 */
td:nth-child(1), th:nth-child(1) {
    width: 80px !important;
}

/* ✅ 名稱欄固定（建議加） */
td:nth-child(2), th:nth-child(2) {
    width: 120px !important;
}

/* ✅ 價格欄 */
td:nth-child(3), th:nth-child(3) {
    width: 90px !important;
}

/* ✅ 漲跌 */
td:nth-child(4), th:nth-child(4) {
    width: 90px !important;
}

/* ✅ 漲幅% */
td:nth-child(5), th:nth-child(5) {
    width: 90px !important;
}

</style>
""", unsafe_allow_html=True)
