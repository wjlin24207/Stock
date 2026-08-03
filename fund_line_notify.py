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
