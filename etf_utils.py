import os
import re
import asyncio
import logging
import pandas as pd

from io import StringIO
from datetime import datetime
from zoneinfo import ZoneInfo
from playwright.async_api import async_playwright


# =========================
# 基本設定
# =========================

ETFS = {
    "00981A": {
        "url": "https://www.etfinfo.tw/etf/00981A/holdings",
        "expected_min_rows": 45,
    },
    "00991A": {
        "url": "https://www.etfinfo.tw/etf/00991A/holdings",
        "expected_min_rows": 45,
    },
    "00980A": {
        "url": "https://www.etfinfo.tw/etf/00980A/holdings",
        "expected_min_rows": 45,
    },
    "00982A": {
        "url": "https://www.etfinfo.tw/etf/00982A/holdings",
        "expected_min_rows": 45,
    },
    "00403A": {
        "url": "https://www.etfinfo.tw/etf/00403A/holdings",
        "expected_min_rows": 45,
    },
    "00985A": {
        "url": "https://www.etfinfo.tw/etf/00985A/holdings",
        "expected_min_rows": 45,
    },
}

TARGET_COMMON_ETFS = [
    "00981A",
    "00991A",
    "00980A",
    "00982A",
    "00403A",
    "00985A",
]

# 共同每日異動門檻：
# 2 代表同一股票至少有 2 檔 ETF 同日異動才輸出
# 3 代表至少 3 檔 ETF 同日異動才輸出
MIN_COMMON_CHANGE_ETF_COUNT = 2

OUTPUT_DIR = "etf_holdings"
TIMEZONE = "Asia/Taipei"

MAX_PAGES_PER_ETF = 10
PAGE_WAIT_MS = 1200


# =========================
# Log 設定
# =========================

def setup_logging():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    log_path = os.path.join(OUTPUT_DIR, "fetch_full_holdings.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler()
        ],
        force=True
    )


# =========================
# 時間工具
# =========================

def now_taipei() -> datetime:
    return datetime.now(ZoneInfo(TIMEZONE))


def today_string() -> str:
    return now_taipei().strftime("%Y-%m-%d")


# =========================
# Edge 啟動工具
# =========================

async def launch_edge_browser(playwright):
    launch_options = {
        "headless": True,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ],
    }

    try:
        logging.info("嘗試使用 channel='msedge' 啟動 Microsoft Edge")
        return await playwright.chromium.launch(
            channel="msedge",
            **launch_options
        )
    except Exception as e:
        logging.warning(f"使用 channel='msedge' 啟動失敗: {e}")

    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(
            r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"
        ),
    ]

    for edge_path in edge_paths:
        if os.path.exists(edge_path):
            logging.info(f"改用 Edge 路徑啟動: {edge_path}")
            return await playwright.chromium.launch(
                executable_path=edge_path,
                **launch_options
            )

    raise RuntimeError(
        "找不到 Microsoft Edge 執行檔。請確認 Edge 已安裝，"
        "或手動修改 edge_paths 裡的 msedge.exe 路徑。"
    )


# =========================
# 欄位與資料清理工具
# =========================

def make_unique_columns(columns) -> list:
    seen = {}
    new_columns = []

    for col in columns:
        base = str(col).strip().replace("\n", "").replace("\r", "")

        if base not in seen:
            seen[base] = 1
            new_columns.append(base)
        else:
            seen[base] += 1
            new_columns.append(f"{base}_{seen[base]}")

    return new_columns


def flatten_multiindex_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [
            "_".join([str(x) for x in col if str(x) != "nan"]).strip()
            for col in df.columns
        ]

    return df


def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = make_unique_columns(df.columns)
    return df


def normalize_stock_code(value) -> str:
    """
    從欄位內容抽出股票代碼。

    支援：
    2330
    2330 台積電
    2330台積電
    """

    if pd.isna(value):
        return ""

    text = str(value).strip()

    if text == "" or text.lower() == "nan":
        return ""

    if text.endswith(".0"):
        text = text[:-2]

    match = re.match(r"^(\d{4})", text)

    if match:
        return match.group(1)

    return ""


def extract_stock_name(value) -> str:
    """
    從欄位內容抽出股票名稱。

    支援：
    2330 台積電 -> 台積電
    2330台積電 -> 台積電
    """

    if pd.isna(value):
        return ""

    text = str(value).strip()

    if text == "" or text.lower() == "nan":
        return ""

    text = re.sub(r"^\d{4}\s*", "", text).strip()

    bad_values = [
        "登入查看",
        "登入",
        "查看",
        "--",
        "-",
        "nan",
    ]

    if text in bad_values:
        return ""

    if "登入" in text or "查看" in text:
        return ""

    return text


def build_stock_name_series(
    df: pd.DataFrame,
    code_col: str,
    name_col: str | None
) -> pd.Series:
    """
    建立股票名稱欄位。

    優先從 code_col 抽名稱：
    2330 台積電 -> 台積電

    若 code_col 只有 2330，才改用 name_col。
    並排除登入查看這類非股票名稱。
    """

    name_from_code = df[code_col].apply(extract_stock_name)

    if name_col and name_col in df.columns and name_col != code_col:
        name_from_name_col = df[name_col].astype(str).str.strip()

        invalid_name = (
            name_from_name_col.eq("")
            | name_from_name_col.str.lower().eq("nan")
            | name_from_name_col.str.contains("登入|查看", na=False)
        )

        name_from_name_col = name_from_name_col.mask(invalid_name, "")

        return name_from_code.mask(
            name_from_code.astype(str).str.strip() == "",
            name_from_name_col
        )

    return name_from_code


def is_stock_code_like(value) -> bool:
    code = normalize_stock_code(value)
    return bool(re.fullmatch(r"\d{4}", code))


def score_as_stock_code_column(series: pd.Series) -> float:
    values = series.dropna().astype(str).str.strip()

    if values.empty:
        return 0.0

    sample = values.head(100)
    hit_count = sample.apply(is_stock_code_like).sum()

    return hit_count / len(sample)


def score_as_name_column(series: pd.Series) -> float:
    values = series.dropna().astype(str).str.strip()

    if values.empty:
        return 0.0

    sample = values.head(100)

    bad_values = [
        "登入查看",
        "登入",
        "查看",
        "--",
        "-",
        "nan",
    ]

    def is_name_like(x: str) -> bool:
        x = str(x).strip()

        if not x or x.lower() == "nan":
            return False

        if x in bad_values:
            return False

        if "登入" in x or "查看" in x:
            return False

        if is_stock_code_like(x):
            return False

        return bool(re.search(r"[\u4e00-\u9fffA-Za-z]", x))

    hit_count = sample.apply(is_name_like).sum()

    return hit_count / len(sample)


def score_as_weight_column(series: pd.Series) -> float:
    values = series.dropna().astype(str).str.strip()

    if values.empty:
        return 0.0

    sample = values.head(100)

    def is_weight_like(x: str) -> bool:
        x = x.replace(",", "").replace("%", "").strip()

        try:
            val = float(x)
            return 0 <= val <= 100
        except ValueError:
            return False

    hit_count = sample.apply(is_weight_like).sum()

    return hit_count / len(sample)


def score_as_share_column(series: pd.Series) -> float:
    values = series.dropna().astype(str).str.strip()

    if values.empty:
        return 0.0

    sample = values.head(100)

    def is_share_like(x: str) -> bool:
        x = x.replace(",", "").strip()

        if not re.fullmatch(r"\d+(\.0)?", x):
            return False

        try:
            val = float(x)
            return val >= 1000
        except ValueError:
            return False

    hit_count = sample.apply(is_share_like).sum()

    return hit_count / len(sample)


def parse_weight_to_number(value) -> float | None:
    if pd.isna(value):
        return None

    text = str(value).strip().replace("%", "").replace(",", "")

    if text == "" or text.lower() == "nan":
        return None

    try:
        return float(text)
    except ValueError:
        return None


def parse_share_to_number(value) -> float | None:
    if pd.isna(value):
        return None

    text = str(value).strip().replace(",", "")

    if text == "" or text.lower() == "nan":
        return None

    try:
        return float(text)
    except ValueError:
        return None


def pick_common_columns(df: pd.DataFrame) -> dict:
    df = df.copy()
    df.columns = make_unique_columns(df.columns)

    exclude_cols = {
        "ETF",
        "抓取時間",
        "資料來源",
        "來源頁次",
        "共同持有ETF",
    }

    bad_code_keywords = [
        "股數",
        "權重",
        "收盤價",
        "漲跌幅",
        "貢獻度",
        "持股變化",
        "價格",
        "報酬",
    ]

    bad_name_keywords = [
        "持股變化",
        "貢獻度",
        "漲跌幅",
        "收盤價",
        "權重",
        "股數",
        "來源",
        "頁次",
    ]

    candidate_cols = [
        col for col in df.columns
        if str(col) not in exclude_cols
    ]

    code_scores = []

    for col in candidate_cols:
        col_text = str(col)

        if any(keyword in col_text for keyword in bad_code_keywords):
            continue

        score = score_as_stock_code_column(df[col])

        if "代號" in col_text:
            score += 0.3

        code_scores.append((col, score))

    code_scores = sorted(code_scores, key=lambda x: x[1], reverse=True)
    code_col = code_scores[0][0] if code_scores and code_scores[0][1] > 0.5 else None

    name_scores = []

    for col in candidate_cols:
        if col == code_col:
            continue

        col_text = str(col)

        if any(keyword in col_text for keyword in bad_name_keywords):
            continue

        score = score_as_name_column(df[col])

        if "名稱" in col_text:
            score += 0.5

        name_scores.append((col, score))

    name_scores = sorted(name_scores, key=lambda x: x[1], reverse=True)
    name_col = name_scores[0][0] if name_scores and name_scores[0][1] > 0.5 else None

    weight_scores = []

    for col in candidate_cols:
        if col in [code_col, name_col]:
            continue

        score = score_as_weight_column(df[col])

        col_text = str(col)

        if "權重" in col_text:
            score += 0.3

        if "股數" in col_text:
            score -= 0.4

        weight_scores.append((col, score))

    weight_scores = sorted(weight_scores, key=lambda x: x[1], reverse=True)
    weight_col = weight_scores[0][0] if weight_scores and weight_scores[0][1] > 0.5 else None

    share_scores = []

    for col in candidate_cols:
        if col in [code_col, name_col, weight_col]:
            continue

        score = score_as_share_column(df[col])

        col_text = str(col)

        if "股數" in col_text:
            score += 0.3

        if "權重" in col_text:
            score -= 0.4

        share_scores.append((col, score))

    share_scores = sorted(share_scores, key=lambda x: x[1], reverse=True)
    share_col = share_scores[0][0] if share_scores and share_scores[0][1] > 0.5 else None

    logging.info(
        f"欄位判斷結果：股票代碼欄={code_col}, "
        f"股票名稱欄={name_col}, 權重欄={weight_col}, 股數欄={share_col}"
    )

    return {
        "code_col": code_col,
        "name_col": name_col,
        "weight_col": weight_col,
        "share_col": share_col,
    }


# =========================
# 表格解析工具
# =========================

def looks_like_holding_table(df: pd.DataFrame) -> bool:
    if df.empty:
        return False

    columns_text = "".join(map(str, df.columns))
    sample_text = df.head(10).astype(str).to_string()
    text = columns_text + sample_text

    keywords = [
        "代號",
        "名稱",
        "權重",
        "股數",
        "持股",
        "成分股",
        "貢獻度",
    ]

    hit_count = sum(keyword in text for keyword in keywords)

    return len(df) >= 5 and hit_count >= 2


def extract_best_table_from_html(html: str) -> pd.DataFrame | None:
    try:
        tables = pd.read_html(StringIO(html))
    except ValueError:
        return None

    candidates = []

    for table in tables:
        table = flatten_multiindex_columns(table)
        table = clean_columns(table)

        if looks_like_holding_table(table):
            candidates.append(table)

    if not candidates:
        return None

    return max(candidates, key=len)


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df = df.dropna(how="all")

    if df.empty:
        return df

    first_col = df.columns[0]

    df = df[df[first_col].astype(str) != str(first_col)]

    joined = df.astype(str).agg(" ".join, axis=1)

    df = df[
        ~joined.str.contains(
            r"上一頁|下一頁|^\s*\d+\s*/\s*\d+\s*$",
            regex=True,
            na=False
        )
    ]

    return df.reset_index(drop=True)


def add_metadata(
    df: pd.DataFrame,
    etf_code: str,
    source_url: str,
    page_no: int
) -> pd.DataFrame:

    df = df.copy()

    fetch_time = now_taipei().strftime("%Y-%m-%d %H:%M:%S")

    df.insert(0, "ETF", etf_code)
    df.insert(1, "抓取時間", fetch_time)
    df.insert(2, "資料來源", source_url)
    df.insert(3, "來源頁次", page_no)

    return df


def remove_duplicate_holdings(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = make_unique_columns(df.columns)

    col_map = pick_common_columns(df)
    code_col = col_map["code_col"]

    if code_col:
        df["_股票代碼"] = df[code_col].apply(normalize_stock_code)
        df = df[df["_股票代碼"] != ""]
        df = df.drop_duplicates(subset=["ETF", "_股票代碼"], keep="first")
        df = df.drop(columns=["_股票代碼"])
    else:
        logging.warning("找不到股票代碼欄，改用整列去重。")
        df = df.drop_duplicates(keep="first")

    return df.reset_index(drop=True)


# =========================
# 翻頁工具
# =========================

async def make_page_signature(page) -> str:
    try:
        text = await page.locator("body").inner_text(timeout=5000)
        return text[:3000]
    except Exception:
        return ""


async def click_next_page_if_possible(page) -> bool:
    next_locators = [
        page.get_by_text("下一頁", exact=True),
        page.locator("a:has-text('下一頁')"),
        page.locator("button:has-text('下一頁')"),
        page.locator("text=下一頁"),
        page.locator("a:has-text('»')"),
        page.locator("button:has-text('»')"),
    ]

    before_signature = await make_page_signature(page)

    for locator in next_locators:
        try:
            count = await locator.count()

            if count == 0:
                continue

            item = locator.last

            if not await item.is_visible(timeout=2000):
                continue

            try:
                if not await item.is_enabled(timeout=2000):
                    continue
            except Exception:
                pass

            await item.click(timeout=5000)

            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

            await page.wait_for_timeout(PAGE_WAIT_MS)

            after_signature = await make_page_signature(page)

            if after_signature and after_signature != before_signature:
                return True

        except Exception:
            continue

    return False


# =========================
# 抓取單一 ETF
# =========================

async def fetch_one_etf_full_holdings(
    browser,
    etf_code: str,
    url: str
) -> pd.DataFrame:

    logging.info(f"開始抓取完整持股: {etf_code} {url}")

    page = await browser.new_page(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36 Edg/124.0"
        ),
        locale="zh-TW",
        viewport={
            "width": 1440,
            "height": 1200,
        }
    )

    await page.goto(url, wait_until="networkidle", timeout=60000)
    await page.wait_for_timeout(PAGE_WAIT_MS)

    page_tables = []
    seen_signatures = set()

    for page_no in range(1, MAX_PAGES_PER_ETF + 1):
        signature = await make_page_signature(page)

        if signature in seen_signatures:
            logging.warning(f"{etf_code} 偵測到頁面重複，停止翻頁")
            break

        seen_signatures.add(signature)

        html = await page.content()
        table = extract_best_table_from_html(html)

        if table is None:
            logging.warning(f"{etf_code} 第 {page_no} 頁找不到持股表")
        else:
            table = clean_dataframe(table)

            if not table.empty:
                table = add_metadata(
                    table,
                    etf_code=etf_code,
                    source_url=url,
                    page_no=page_no
                )

                page_tables.append(table)

                logging.info(
                    f"{etf_code} 第 {page_no} 頁抓到 {len(table)} 筆"
                )
            else:
                logging.warning(f"{etf_code} 第 {page_no} 頁表格為空")

        has_next = await click_next_page_if_possible(page)

        if not has_next:
            logging.info(f"{etf_code} 沒有下一頁，翻頁結束")
            break

    await page.close()

    if not page_tables:
        raise RuntimeError(f"{etf_code} 未抓到任何持股資料")

    result = pd.concat(page_tables, ignore_index=True)
    result = remove_duplicate_holdings(result)

    logging.info(f"{etf_code} 完整抓取完成，去重後共 {len(result)} 筆")

    return result


# =========================
# 標準化持股資料
# =========================

def standardize_holdings_for_compare(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = make_unique_columns(df.columns)

    col_map = pick_common_columns(df)

    code_col = col_map["code_col"]
    name_col = col_map["name_col"]
    weight_col = col_map["weight_col"]
    share_col = col_map["share_col"]

    if not code_col:
        raise RuntimeError(f"找不到股票代碼欄位，目前欄位為：{list(df.columns)}")

    result = pd.DataFrame(index=df.index)

    result["股票代碼"] = df[code_col].apply(normalize_stock_code)
    result = result[result["股票代碼"] != ""].copy()

    name_series = build_stock_name_series(df, code_col, name_col)
    result["股票名稱"] = name_series.loc[result.index]

    if weight_col and weight_col in df.columns:
        result["權重"] = df.loc[result.index, weight_col]
        result["權重數值"] = result["權重"].apply(parse_weight_to_number)
    else:
        result["權重"] = ""
        result["權重數值"] = None

    if share_col and share_col in df.columns:
        result["股數"] = df.loc[result.index, share_col]
        result["股數數值"] = result["股數"].apply(parse_share_to_number)
    else:
        result["股數"] = ""
        result["股數數值"] = None

    result = result.drop_duplicates(subset=["股票代碼"], keep="first")
    result = result.reset_index(drop=True)

    return result


# =========================
# 全部 ETF 共同持股分析
# =========================

def find_common_holdings(
    all_data: list[pd.DataFrame],
    target_etfs: list[str]
) -> pd.DataFrame:
    """
    找出 target_etfs 全部 ETF 都共同持有的股票。
    """

    if not all_data:
        return pd.DataFrame()

    merged = pd.concat(all_data, ignore_index=True)
    merged.columns = make_unique_columns(merged.columns)

    if "ETF" not in merged.columns:
        raise RuntimeError("找不到 ETF 欄位，無法判斷共同持股。")

    col_map = pick_common_columns(merged)

    code_col = col_map["code_col"]
    name_col = col_map["name_col"]
    weight_col = col_map["weight_col"]
    share_col = col_map["share_col"]

    if not code_col:
        raise RuntimeError(
            f"找不到股票代碼欄位，目前欄位為：{list(merged.columns)}"
        )

    merged = merged.copy()

    merged["_股票代碼"] = merged[code_col].apply(normalize_stock_code)
    merged["_股票名稱"] = build_stock_name_series(
        merged,
        code_col,
        name_col
    )

    merged = merged[merged["_股票代碼"] != ""]
    merged = merged[merged["ETF"].isin(target_etfs)]

    if merged.empty:
        return pd.DataFrame()

    etf_count = (
        merged.groupby("_股票代碼")["ETF"]
        .nunique()
        .reset_index(name="出現ETF數")
    )

    common_codes = etf_count[
        etf_count["出現ETF數"] == len(target_etfs)
    ]["_股票代碼"].tolist()

    if not common_codes:
        return pd.DataFrame()

    common_detail = merged[merged["_股票代碼"].isin(common_codes)].copy()

    summary = (
        common_detail[["_股票代碼"]]
        .drop_duplicates()
        .rename(columns={"_股票代碼": "股票代碼"})
        .copy()
    )

    summary = summary.merge(
        etf_count.rename(columns={"_股票代碼": "股票代碼"}),
        on="股票代碼",
        how="left"
    )

    for etf in target_etfs:
        etf_df = common_detail[common_detail["ETF"] == etf].copy()

        keep_cols = ["_股票代碼", "_股票名稱"]

        rename_map = {
            "_股票代碼": "股票代碼",
            "_股票名稱": f"{etf}_股票名稱",
        }

        if weight_col and weight_col in etf_df.columns:
            keep_cols.append(weight_col)
            rename_map[weight_col] = f"{etf}_權重"

        if share_col and share_col in etf_df.columns and share_col != weight_col:
            keep_cols.append(share_col)
            rename_map[share_col] = f"{etf}_股數"

        etf_df = (
            etf_df[keep_cols]
            .drop_duplicates(subset=["_股票代碼"])
            .rename(columns=rename_map)
        )

        summary = summary.merge(
            etf_df,
            on="股票代碼",
            how="left"
        )

    name_cols = [
        f"{etf}_股票名稱"
        for etf in target_etfs
        if f"{etf}_股票名稱" in summary.columns
    ]

    if name_cols:
        summary["顯示股票名稱"] = ""

        for name_col_each in name_cols:
            summary["顯示股票名稱"] = summary["顯示股票名稱"].mask(
                summary["顯示股票名稱"].astype(str).str.strip() == "",
                summary[name_col_each]
            )

        cols = summary.columns.tolist()
        cols.remove("顯示股票名稱")
        insert_pos = cols.index("股票代碼") + 1
        cols.insert(insert_pos, "顯示股票名稱")
        summary = summary[cols]

    weight_output_cols = [
        col for col in summary.columns
        if col.endswith("_權重")
    ]

    weight_numeric_cols = []

    for col in weight_output_cols:
        numeric_col = f"_{col}_數值"
        summary[numeric_col] = summary[col].apply(parse_weight_to_number)
        weight_numeric_cols.append(numeric_col)

    if weight_numeric_cols:
        summary["合計權重"] = summary[weight_numeric_cols].sum(axis=1)
        summary["平均權重"] = summary[weight_numeric_cols].mean(axis=1)

        for col in weight_output_cols:
            summary[col] = summary[col].apply(parse_weight_to_number)
            summary[col] = summary[col].map(
                lambda x: "" if pd.isna(x) else f"{x:.2f}%"
            )

        summary["合計權重"] = summary["合計權重"].map(
            lambda x: "" if pd.isna(x) else f"{x:.2f}%"
        )

        summary["平均權重"] = summary["平均權重"].map(
            lambda x: "" if pd.isna(x) else f"{x:.2f}%"
        )

        summary["_合計權重排序"] = (
            summary["合計權重"]
            .astype(str)
            .str.replace("%", "", regex=False)
        )

        summary["_合計權重排序"] = pd.to_numeric(
            summary["_合計權重排序"],
            errors="coerce"
        )

        summary = summary.drop(columns=weight_numeric_cols)

    summary["_股票代碼排序"] = pd.to_numeric(
        summary["股票代碼"],
        errors="coerce"
    )

    if "_合計權重排序" in summary.columns:
        summary = (
            summary
            .sort_values(
                by=["_合計權重排序", "_股票代碼排序", "股票代碼"],
                ascending=[False, True, True],
                na_position="last"
            )
            .drop(columns=["_合計權重排序", "_股票代碼排序"])
            .reset_index(drop=True)
        )
    else:
        summary = (
            summary
            .sort_values(
                by=["_股票代碼排序", "股票代碼"],
                ascending=[True, True],
                na_position="last"
            )
            .drop(columns=["_股票代碼排序"])
            .reset_index(drop=True)
        )

    summary.insert(
        0,
        "共同持有ETF",
        ",".join(target_etfs)
    )

    return summary


# =========================
# 每日異動分析
# =========================

def get_file_date_from_name(file_name: str) -> str | None:
    base = os.path.basename(file_name)

    if len(base) < 10:
        return None

    date_part = base[:10]

    try:
        datetime.strptime(date_part, "%Y-%m-%d")
        return date_part
    except ValueError:
        return None


def find_previous_etf_file(etf_code: str, current_date: str) -> str | None:
    if not os.path.exists(OUTPUT_DIR):
        return None

    candidates = []

    for file_name in os.listdir(OUTPUT_DIR):
        if not file_name.endswith(f"_{etf_code}_full_holdings.xlsx"):
            continue

        file_date = get_file_date_from_name(file_name)

        if not file_date:
            continue

        if file_date < current_date:
            full_path = os.path.join(OUTPUT_DIR, file_name)
            candidates.append((file_date, full_path))

    if not candidates:
        return None

    candidates = sorted(candidates, key=lambda x: x[0], reverse=True)

    return candidates[0][1]


def format_number_change(value) -> str:
    if pd.isna(value):
        return ""

    if value == 0:
        return "0"

    return f"{value:,.0f}"


def format_weight_change(value) -> str:
    if pd.isna(value):
        return ""

    if value == 0:
        return "0.00%"

    return f"{value:+.2f}%"
def get_action(change_type, share_change):
    if change_type == "新增":
        return "新納入"

    if change_type == "刪除":
        return "全數賣出"

    if pd.isna(share_change):
        return ""

    if share_change > 0:
        return "加碼"

    if share_change < 0:
        return "減碼"

    return ""

def compare_etf_holdings(
    etf_code: str,
    current_df: pd.DataFrame,
    previous_file: str
) -> pd.DataFrame:

    previous_df = pd.read_excel(previous_file, engine="openpyxl")

    current_std = standardize_holdings_for_compare(current_df)
    previous_std = standardize_holdings_for_compare(previous_df)

    merged = previous_std.merge(
        current_std,
        on="股票代碼",
        how="outer",
        suffixes=("_昨日", "_今日"),
        indicator=True
    )

    def get_change_type(row):
        if row["_merge"] == "left_only":
            return "刪除"
        if row["_merge"] == "right_only":
            return "新增"
        return "持續持有"

    merged["異動類型"] = merged.apply(get_change_type, axis=1)

    merged["權重變化數值"] = merged["權重數值_今日"] - merged["權重數值_昨日"]
    merged["股數變化數值"] = merged["股數數值_今日"] - merged["股數數值_昨日"]

    merged["權重變化"] = merged["權重變化數值"].apply(format_weight_change)
    merged["股數變化"] = merged["股數變化數值"].apply(format_number_change)

    merged["調整方向"] = merged.apply(
        lambda row: get_action(
            row["異動類型"],
            row["股數變化數值"]
        ),
        axis=1
    )
    
    merged["ETF"] = etf_code
    merged["比較基準檔案"] = os.path.basename(previous_file)

    share_changed = merged["股數變化數值"].fillna(0) != 0
    added_or_removed = merged["異動類型"].isin(["新增", "刪除"])

    # 僅判斷實際持股變化
    changed_only = merged[
        added_or_removed | share_changed
    ].copy()

    if changed_only.empty:
        return pd.DataFrame()

    output = changed_only[
        [
            "ETF",
            "異動類型",
            "調整方向",
            "股票代碼",
            "股票名稱_昨日",
            "股票名稱_今日",
            "權重_昨日",
            "權重_今日",
            "權重變化",
            "股數_昨日",
            "股數_今日",
            "股數變化",
            "比較基準檔案",
        ]
    ].copy()

    sort_priority = {
        "新增": 1,
        "刪除": 2,
        "持續持有": 3,
    }

    output["_排序"] = output["異動類型"].map(sort_priority).fillna(9)

    output["_股票代碼排序"] = pd.to_numeric(
        output["股票代碼"],
        errors="coerce"
    )

    output = (
        output
        .sort_values(
            by=["_排序", "_股票代碼排序", "股票代碼"],
            ascending=[True, True, True],
            na_position="last"
        )
        .drop(columns=["_排序", "_股票代碼排序"])
        .reset_index(drop=True)
    )

    return output


# =========================
# 共同每日異動分析
# =========================

def clean_change_stock_name(value) -> str:
    if pd.isna(value):
        return ""

    text = str(value).strip()

    if text == "" or text.lower() == "nan":
        return ""

    if "登入" in text or "查看" in text:
        return ""

    return text


def choose_display_name_from_change_group(group: pd.DataFrame) -> str:
    for col in ["股票名稱_今日", "股票名稱_昨日"]:
        if col not in group.columns:
            continue

        for value in group[col].tolist():
            name = clean_change_stock_name(value)

            if name:
                return name

    return ""


def find_common_daily_changes(
    change_dfs: list[pd.DataFrame],
    target_etfs: list[str],
    min_etf_count: int = 2
) -> pd.DataFrame:
    """
    從每日異動資料中，找出同一股票有多檔 ETF 同時異動的清單。

    條件：
    - 同一股票代碼
    - 出現在至少 min_etf_count 檔 ETF 的每日異動裡
    """

    non_empty_changes = [
        df for df in change_dfs
        if df is not None and not df.empty
    ]

    if not non_empty_changes:
        return pd.DataFrame()

    all_changes = pd.concat(non_empty_changes, ignore_index=True)

    if "ETF" not in all_changes.columns or "股票代碼" not in all_changes.columns:
        raise RuntimeError(
            f"每日異動資料缺少必要欄位，目前欄位為：{list(all_changes.columns)}"
        )

    all_changes = all_changes.copy()

    all_changes["股票代碼"] = all_changes["股票代碼"].apply(normalize_stock_code)
    all_changes = all_changes[all_changes["股票代碼"] != ""]
    all_changes = all_changes[all_changes["ETF"].isin(target_etfs)]

    if all_changes.empty:
        return pd.DataFrame()

    change_count = (
        all_changes.groupby("股票代碼")["ETF"]
        .nunique()
        .reset_index(name="異動ETF數")
    )

    common_change_codes = change_count[
        change_count["異動ETF數"] >= min_etf_count
    ]["股票代碼"].tolist()

    if not common_change_codes:
        return pd.DataFrame()

    common_changes = all_changes[
        all_changes["股票代碼"].isin(common_change_codes)
    ].copy()

    summary = (
        common_changes[["股票代碼"]]
        .drop_duplicates()
        .copy()
    )

    summary = summary.merge(
        change_count,
        on="股票代碼",
        how="left"
    )

    display_names = (
        common_changes
        .groupby("股票代碼")
        .apply(choose_display_name_from_change_group)
        .reset_index(name="顯示股票名稱")
    )

    summary = summary.merge(
        display_names,
        on="股票代碼",
        how="left"
    )

    etf_list_df = (
        common_changes
        .groupby("股票代碼")["ETF"]
        .apply(lambda x: ",".join(sorted(x.dropna().astype(str).unique().tolist())))
        .reset_index(name="異動ETF清單")
    )

    summary = summary.merge(
        etf_list_df,
        on="股票代碼",
        how="left"
    )

    detail_cols = [
        "異動類型",
        "調整方向",
        "股票名稱_昨日",
        "股票名稱_今日",
        "權重_昨日",
        "權重_今日",
        "權重變化",
        "股數_昨日",
        "股數_今日",
        "股數變化",
    ]

    for etf in target_etfs:
        etf_df = common_changes[common_changes["ETF"] == etf].copy()

        if etf_df.empty:
            continue

        keep_cols = ["股票代碼"] + [
            col for col in detail_cols
            if col in etf_df.columns
        ]

        etf_df = etf_df[keep_cols].drop_duplicates(subset=["股票代碼"])

        rename_map = {
            col: f"{etf}_{col}"
            for col in keep_cols
            if col != "股票代碼"
        }

        etf_df = etf_df.rename(columns=rename_map)

        summary = summary.merge(
            etf_df,
            on="股票代碼",
            how="left"
        )

    summary["_股票代碼排序"] = pd.to_numeric(
        summary["股票代碼"],
        errors="coerce"
    )

    summary = (
        summary
        .sort_values(
            by=["異動ETF數", "_股票代碼排序", "股票代碼"],
            ascending=[False, True, True],
            na_position="last"
        )
        .drop(columns=["_股票代碼排序"])
        .reset_index(drop=True)
    )

    first_cols = [
        "股票代碼",
        "顯示股票名稱",
        "異動ETF數",
        "異動ETF清單",
    ]

    other_cols = [
        col for col in summary.columns
        if col not in first_cols
    ]

    summary = summary[first_cols + other_cols]

    return summary

def build_common_daily_change_summary(
    common_change_df: pd.DataFrame,
    target_etfs: list[str]
) -> pd.DataFrame:

    if common_change_df.empty:
        return pd.DataFrame()

    rows = []

    for _, row in common_change_df.iterrows():

        add_list = []
        reduce_list = []
        directions = []

        for etf in target_etfs:

            direction_col = f"{etf}_調整方向"
            share_change_col = f"{etf}_股數變化"

            if direction_col not in common_change_df.columns:
                continue

            direction = row.get(direction_col)

            if pd.isna(direction) or direction == "":
                continue

            directions.append(direction)

            share_change = row.get(share_change_col)

            if pd.isna(share_change):
                share_change = ""
            
            share_change = str(share_change).strip()
            
            if share_change:
                info = f"{etf}({share_change})"
            
            else:
            
                if direction == "全數賣出":
                    info = f"{etf}(全數賣出)"
            
                elif direction == "新納入":
                    info = f"{etf}(新納入)"
            
                else:
                    info = etf

            if direction in ["加碼", "新納入"]:
                add_list.append(info)

            elif direction in ["減碼", "全數賣出"]:
                reduce_list.append(info)

        bullish = {"加碼", "新納入"}
        bearish = {"減碼", "全數賣出"}

        if directions and all(d in bullish for d in directions):
            common_direction = "全部加碼"

        elif directions and all(d in bearish for d in directions):
            common_direction = "全部減碼"

        else:
            common_direction = "混合"

        rows.append({
            "股票代碼": row["股票代碼"],
            "股票名稱": row["顯示股票名稱"],
            "異動ETF數": row["異動ETF數"],
            "共同方向": common_direction,
            "加碼ETF": "、".join(add_list) if add_list else "-",
            "減碼ETF": "、".join(reduce_list) if reduce_list else "-"
        })

    result = pd.DataFrame(rows)

    result = result.sort_values(
        by=["異動ETF數", "股票代碼"],
        ascending=[False, True]
    )

    return result.reset_index(drop=True)

# =========================
# 儲存檔案，只輸出 xlsx
# =========================

def save_one_etf(etf_code: str, df: pd.DataFrame) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    date_str = today_string()

    xlsx_path = os.path.join(
        OUTPUT_DIR,
        f"{date_str}_{etf_code}_full_holdings.xlsx"
    )

    df.to_excel(xlsx_path, index=False, engine="openpyxl")

    return xlsx_path


def save_merged(all_data: list[pd.DataFrame]) -> str | None:
    if not all_data:
        return None

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    date_str = today_string()

    merged = pd.concat(all_data, ignore_index=True)
    merged.columns = make_unique_columns(merged.columns)

    merged_path = os.path.join(
        OUTPUT_DIR,
        f"{date_str}_active_etf_full_holdings_all.xlsx"
    )

    merged.to_excel(merged_path, index=False, engine="openpyxl")

    return merged_path


def save_common_holdings(
    common_df: pd.DataFrame,
    target_etfs: list[str]
) -> str | None:

    if common_df.empty:
        return None

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    date_str = today_string()
    etf_name_part = "_".join(target_etfs)

    xlsx_path = os.path.join(
        OUTPUT_DIR,
        f"{date_str}_common_holdings_all_{etf_name_part}.xlsx"
    )

    common_df.to_excel(xlsx_path, index=False, engine="openpyxl")

    return xlsx_path


def save_daily_changes(change_dfs: list[pd.DataFrame]) -> str | None:
    non_empty_changes = [
        df for df in change_dfs
        if df is not None and not df.empty
    ]

    if not non_empty_changes:
        return None

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    date_str = today_string()

    all_changes = pd.concat(non_empty_changes, ignore_index=True)

    xlsx_path = os.path.join(
        OUTPUT_DIR,
        f"{date_str}_daily_changes_changed_only.xlsx"
    )

    all_changes.to_excel(xlsx_path, index=False, engine="openpyxl")

    return xlsx_path


def save_common_daily_changes(
    common_change_df: pd.DataFrame,
    target_etfs: list[str],
    min_etf_count: int = 2
) -> str | None:

    if common_change_df.empty:
        return None

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    date_str = today_string()
    etf_name_part = "_".join(target_etfs)

    xlsx_path = os.path.join(
        OUTPUT_DIR,
        f"{date_str}_common_daily_changes_min{min_etf_count}_{etf_name_part}.xlsx"
    )

    common_change_df.to_excel(
        xlsx_path,
        index=False,
        engine="openpyxl"
    )

    return xlsx_path

def save_common_daily_change_summary(
    summary_df: pd.DataFrame
) -> str | None:

    if summary_df.empty:
        return None

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    date_str = today_string()

    xlsx_path = os.path.join(
        OUTPUT_DIR,
        f"{date_str}_common_daily_changes_summary.xlsx"
    )

    summary_df.to_excel(
        xlsx_path,
        index=False,
        engine="openpyxl"
    )

    return xlsx_path


def save_errors(errors: list[dict]):
    if not errors:
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    date_str = today_string()

    error_path = os.path.join(
        OUTPUT_DIR,
        f"{date_str}_errors.xlsx"
    )

    pd.DataFrame(errors).to_excel(
        error_path,
        index=False,
        engine="openpyxl"
    )

    logging.warning(f"錯誤報告已儲存: {error_path}")


# =========================
# 主程式
# =========================

async def main_async():
    setup_logging()

    logging.info("開始抓取主動式 ETF 完整持股明細")

    all_data = []
    errors = []
    change_dfs = []

    async with async_playwright() as p:
        browser = await launch_edge_browser(p)

        for etf_code, config in ETFS.items():
            url = config["url"]
            expected_min_rows = config["expected_min_rows"]

            try:
                df = await fetch_one_etf_full_holdings(
                    browser=browser,
                    etf_code=etf_code,
                    url=url
                )

                if len(df) < expected_min_rows:
                    logging.warning(
                        f"{etf_code} 抓到 {len(df)} 筆，"
                        f"低於預期至少 {expected_min_rows} 筆，"
                        "可能仍未抓完整，請檢查網站是否改版、需要登入，"
                        "或分頁按鈕結構有變。"
                    )

                xlsx_path = save_one_etf(etf_code, df)

                logging.info(f"{etf_code} Excel 已儲存: {xlsx_path}")

                all_data.append(df)

                current_date = today_string()
                previous_file = find_previous_etf_file(etf_code, current_date)

                if previous_file:
                    try:
                        change_df = compare_etf_holdings(
                            etf_code=etf_code,
                            current_df=df,
                            previous_file=previous_file
                        )

                        if change_df is not None and not change_df.empty:
                            change_dfs.append(change_df)

                            logging.info(
                                f"{etf_code} 已完成每日異動比較，"
                                f"有異動 {len(change_df)} 筆，"
                                f"基準檔案：{previous_file}"
                            )
                        else:
                            logging.info(
                                f"{etf_code} 已完成每日異動比較，沒有異動，"
                                f"基準檔案：{previous_file}"
                            )

                    except Exception as e:
                        logging.error(f"{etf_code} 每日異動比較失敗: {e}")
                else:
                    logging.warning(
                        f"{etf_code} 找不到前一份持股檔案，略過每日異動比較。"
                    )

            except Exception as e:
                error_msg = str(e)

                logging.error(f"{etf_code} 抓取失敗: {error_msg}")

                errors.append({
                    "ETF": etf_code,
                    "URL": url,
                    "抓取時間": now_taipei().strftime("%Y-%m-%d %H:%M:%S"),
                    "錯誤訊息": error_msg,
                })

        await browser.close()

    merged_path = save_merged(all_data)

    if merged_path:
        logging.info(f"合併完整持股檔已儲存: {merged_path}")
    else:
        logging.warning("沒有任何 ETF 成功抓取，未產生合併檔案")

    daily_change_xlsx_path = save_daily_changes(change_dfs)

    if daily_change_xlsx_path:
        logging.info(f"每日異動 Excel 已儲存: {daily_change_xlsx_path}")
    else:
        logging.warning("沒有產生每日異動檔案，代表沒有異動或找不到前一份持股檔。")

    try:
        common_change_df = find_common_daily_changes(
            change_dfs=change_dfs,
            target_etfs=TARGET_COMMON_ETFS,
            min_etf_count=MIN_COMMON_CHANGE_ETF_COUNT
        )

        if common_change_df.empty:
            logging.warning(
                f"沒有找到至少 {MIN_COMMON_CHANGE_ETF_COUNT} 檔 ETF 同時異動的股票。"
            )
        else:
            common_change_xlsx_path = save_common_daily_changes(
                common_change_df=common_change_df,
                target_etfs=TARGET_COMMON_ETFS,
                min_etf_count=MIN_COMMON_CHANGE_ETF_COUNT
            )

            if common_change_xlsx_path:

                summary_df = build_common_daily_change_summary(
                    common_change_df=common_change_df,
                    target_etfs=TARGET_COMMON_ETFS
                )

                summary_path = save_common_daily_change_summary(
                    summary_df
                )
            
                logging.info(
                    f"共同每日異動股票共 {len(common_change_df)} 檔"
                )
            
                logging.info(
                    f"共同每日異動 Excel 已儲存: {common_change_xlsx_path}"
                )
            
                if summary_path:
                    logging.info(
                        f"共同每日異動 Summary 已儲存: {summary_path}"
                    )

    except Exception as e:
        logging.error(f"產生共同每日異動清單失敗: {e}")

    try:
        common_df = find_common_holdings(
            all_data=all_data,
            target_etfs=TARGET_COMMON_ETFS
        )

        if common_df.empty:
            logging.warning("指定 ETF 沒有找到全部共同持股。")
        else:
            common_xlsx_path = save_common_holdings(
                common_df=common_df,
                target_etfs=TARGET_COMMON_ETFS
            )

            if common_xlsx_path:
                logging.info(
                    f"全部 ETF 共同持股共 {len(common_df)} 檔"
                )
                logging.info(
                    f"全部共同持股 Excel 已儲存: {common_xlsx_path}"
                )

    except Exception as e:
        logging.error(f"產生共同持股清單失敗: {e}")

    save_errors(errors)

    logging.info("程式結束")


