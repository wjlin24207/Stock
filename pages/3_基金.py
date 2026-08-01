import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd

# 頁面設定 (適合手機版，移除 wide layout)
st.set_page_config(page_title="自選基金追蹤", layout="centered")

st.markdown("## ⭐ 自選基金即時監控快照")

FUNDS = {
    "安聯收益成長": "https://www.moneydj.com/funddj/ya/yp010001.djhtm?a=tlz64",
    "貝萊德世界科技A10": "https://www.moneydj.com/funddj/ya/yp010001.djhtm?a=shzv9",
    "富坦穩定月收益": "https://www.moneydj.com/funddj/ya/yp010001.djhtm?a=flz92",
    "野村優質": "https://www.moneydj.com/funddj/ya/yp010000.djhtm?a=acic01",
    "安聯台灣科技": "https://www.moneydj.com/funddj/ya/yp010000.djhtm?a=acdd04",
    "統一奔騰": "https://www.moneydj.com/funddj/ya/yp010000.djhtm?a=acps10"
}

@st.cache_data(ttl=600, show_spinner=False)
def fetch_moneydj_fund(name, url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.moneydj.com/"
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=20, verify=False)
        resp.raise_for_status() 
        soup = BeautifulSoup(resp.content, "html.parser")
        
        price, change, date = "N/A", "N/A", "N/A"
        
        def is_price(v): return any(c.isdigit() for c in v) and '/' not in v
        def is_change(v): return any(c.isdigit() for c in v) and '/' not in v
        def is_date(v): return ('/' in v or '-' in v) and any(c.isdigit() for c in v)

        price_lbls = ["最新淨值", "最新報價", "淨值(報價)", "淨值"]
        change_lbls = ["漲跌幅", "日漲跌幅", "漲跌", "漲跌(%)", "漲跌幅(%)", "每日變化"]
        date_lbls = ["淨值日期", "報價日期", "日期"]

        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            for r_idx, row in enumerate(rows):
                cells = row.find_all(['th', 'td'])
                texts = [c.get_text(strip=True) for c in cells]
                
                if any(l in texts for l in price_lbls):
                    if r_idx + 1 < len(rows):
                        next_cells = rows[r_idx + 1].find_all(['th', 'td'])
                        next_texts = [c.get_text(strip=True) for c in next_cells]
                        
                        for c_idx, lbl in enumerate(texts):
                            if c_idx < len(next_texts):
                                val = next_texts[c_idx]
                                if lbl in price_lbls and price == "N/A" and is_price(val): 
                                    price = val
                                elif lbl in date_lbls and date == "N/A" and is_date(val): 
                                    date = val
                                elif lbl in change_lbls and is_change(val):
                                    if change == "N/A":
                                        change = val
                                        if c_idx + 1 < len(next_texts):
                                            next_val = next_texts[c_idx+1]
                                            if '%' in next_val and is_change(next_val):
                                                change = f"{val} ({next_val})"
                                    elif '%' not in change and '%' in val:
                                        change = f"{change} ({val})"

        for row in soup.find_all("tr"):
            cells = row.find_all(['th', 'td'])
            for i in range(len(cells) - 1):
                lbl = cells[i].get_text(strip=True)
                
                if lbl in price_lbls or lbl in change_lbls or lbl in date_lbls:
                    vals = []
                    for j in range(i+1, min(i+4, len(cells))):
                        v = cells[j].get_text(strip=True)
                        if v: vals.append(v)
                    
                    if not vals: continue
                    val = vals[0]

                    if lbl in price_lbls and price == "N/A" and is_price(val): 
                        price = val
                    elif lbl in date_lbls and date == "N/A" and is_date(val): 
                        date = val
                    elif lbl in change_lbls and is_change(val):
                        if change == "N/A":
                            change = val
                            if len(vals) > 1:
                                next_val = vals[1]
                                if '%' in next_val and is_change(next_val):
                                    change = f"{val} ({next_val})"
                        elif '%' not in change and '%' in val:
                            change = f"{change} ({val})"

        return {
            "基金名稱": name,
            "最新淨值": price,
            "漲跌幅": change,
            "淨值日期": date,
            "資料連結": url
        }
    except Exception as e:
        return {"基金名稱": name, "最新淨值": "N/A", "漲跌幅": "N/A", "淨值日期": "N/A", "資料連結": url}

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
<div style="color: {color}; font-size: 28px; font-weight: bold; font-family: monospace;">{arrow} {display_change}</div>
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
