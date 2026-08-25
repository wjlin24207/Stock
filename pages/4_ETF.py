from glob import glob
import os
import re
import requests
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="主動ETF持股",
    layout="wide"
)


if st.button("🔄 更新ETF資料"):

    token = st.secrets["GITHUB_TOKEN"]

    url = (
        "https://api.github.com/repos/"
        "wjlin24207/Stock/actions/workflows/"
        "etf_update.yml/dispatches"
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json"
    }

    payload = {
        "ref": "main"
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload
    )

    if response.status_code == 204:
        st.success("已送出 ETF 更新工作")
    else:
        st.error(
            f"送出失敗：{response.status_code}"
        )

st.set_page_config(
    page_title="主動ETF持股",
    layout="wide"
)

st.title("主動ETF持股")

last_update = "未知"

try:

    with open(
        "etf_holdings/last_update.txt",
        "r",
        encoding="utf-8"
    ) as f:

        last_update = f.read().strip()

except Exception:
    pass

st.success(
    f"✅ 最後更新時間：{last_update}"
)

def get_latest_file(pattern):
    files = sorted(
        glob(pattern),
        reverse=True
    )

    if not files:
        return None

    return files[0]

def get_latest_etf_files():
    """
    尋找每一檔 ETF 最新的完整持股檔案。

    檔名格式：
    YYYY-MM-DD_ETF代碼_full_holdings.xlsx

    例如：
    2026-08-25_00981A_full_holdings.xlsx
    """

    files = glob(
        "etf_holdings/*_full_holdings.xlsx"
    )

    latest_etf_files = {}

    for file_path in files:

        file_name = os.path.basename(file_path)

        match = re.match(
            r"^(\d{4}-\d{2}-\d{2})_"
            r"([A-Za-z0-9]+)_"
            r"full_holdings\.xlsx$",
            file_name
        )

        if not match:
            continue

        file_date = match.group(1)
        etf_code = match.group(2).upper()

        # 如果同一檔 ETF 有多個日期，只保留最新日期
        if etf_code not in latest_etf_files:
            latest_etf_files[etf_code] = {
                "date": file_date,
                "path": file_path
            }

        elif file_date > latest_etf_files[etf_code]["date"]:
            latest_etf_files[etf_code] = {
                "date": file_date,
                "path": file_path
            }

    return latest_etf_files

# =========================
# 找最新檔案
# =========================

summary_file = get_latest_file(
    "etf_holdings/*common_daily_changes_summary.xlsx"
)

daily_file = get_latest_file(
    "etf_holdings/*daily_changes_changed_only.xlsx"
)

holding_file = get_latest_file(
    "etf_holdings/*common_holdings_all*.xlsx"
)

# 每一檔 ETF 最新的詳細持股檔
etf_files = get_latest_etf_files()


tab1, tab2, tab3, tab4 = st.tabs(
    [
        "共同異動 Summary",
        "每日異動",
        "共同持股",
        "ETF詳細持股"
    ]
)


# =========================
# Tab1 Summary
# =========================

with tab1:

    if summary_file:

        st.info(
            f"最新檔案：{os.path.basename(summary_file)}"
        )

        df = pd.read_excel(
            summary_file,
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

    else:
        st.warning("找不到共同異動 Summary 檔案")


# =========================
# Tab2 每日異動
# =========================

with tab2:

    if daily_file:

        st.info(
            f"最新檔案：{os.path.basename(daily_file)}"
        )

        daily_df = pd.read_excel(
            daily_file,
            engine="openpyxl"
        )

        # 每日異動頁面不顯示的欄位
        daily_hidden_columns = [
            "股票名稱_昨日",
            "權重_昨日",
            "股數_昨日",
        ]

        daily_df = daily_df.drop(
            columns=daily_hidden_columns,
            errors="ignore"
        )

        st.dataframe(
            daily_df,
            use_container_width=True,
            hide_index=True
        )

    else:
        st.warning("找不到每日異動檔案")


# =========================
# Tab3 共同持股
# =========================

with tab3:

    if holding_file:

        st.info(
            f"最新檔案：{os.path.basename(holding_file)}"
        )

        holding_df = pd.read_excel(
            holding_file,
            engine="openpyxl",
            dtype={
                "股票代碼": str,
            }
        )

        # 隱藏各 ETF 的股票名稱與股數欄位
        # 保留「顯示股票名稱」及各 ETF 的權重
        hidden_holding_columns = [
            col
            for col in holding_df.columns
            if (
                col.endswith("_股票名稱")
                or col.endswith("_股數")
            )
        ]

        holding_df = holding_df.drop(
            columns=hidden_holding_columns,
            errors="ignore"
        )

        # 將「共同持有ETF」移到最後一欄
        if "共同持有ETF" in holding_df.columns:
            other_columns = [
                col
                for col in holding_df.columns
                if col != "共同持有ETF"
            ]

            holding_df = holding_df[
                other_columns + ["共同持有ETF"]
            ]

        st.dataframe(
            holding_df,
            use_container_width=True,
            hide_index=True
        )

    else:
        st.warning("找不到共同持股檔案")

# =========================
# Tab4 ETF詳細持股
# =========================

with tab4:

    if etf_files:

        # ETF 代碼排序
        etf_list = sorted(etf_files.keys())

        # ETF 下拉選單
        selected_etf = st.selectbox(
            "請選擇 ETF",
            options=etf_list,
            key="selected_etf_detail"
        )

        # 取得選擇 ETF 的最新檔案與日期
        selected_file = etf_files[selected_etf]["path"]
        selected_date = etf_files[selected_etf]["date"]

        st.info(
            f"最新檔案：{os.path.basename(selected_file)}"
        )

        try:
            # 讀取選擇 ETF 的完整持股檔案
            detail_df = pd.read_excel(
                selected_file,
                engine="openpyxl",
                dtype={
                    "股票代碼": str
                }
            )

            # 移除完全空白的資料列
            detail_df = detail_df.dropna(
                how="all"
            )

            # 移除完全空白的欄位
            detail_df = detail_df.dropna(
                axis=1,
                how="all"
            )

            # 清除欄位名稱前後空白
            detail_df.columns = [
                str(column).strip()
                for column in detail_df.columns
            ]

            # 整理股票代碼格式
            if "股票代碼" in detail_df.columns:
                detail_df["股票代碼"] = (
                    detail_df["股票代碼"]
                    .astype(str)
                    .str.strip()
                    .str.replace(
                        r"\.0$",
                        "",
                        regex=True
                    )
                )

            # =========================
            # 隱藏不需要顯示的欄位
            # =========================

            columns_to_remove = []

            for column in detail_df.columns:
                column_name = str(column).strip()

                # 固定隱藏的欄位
                if column_name in [
                    "資料來源",
                    "來源頁次",
                    "持股變化",
                    "00XXXA_股數",
                ]:
                    columns_to_remove.append(column)
                    continue

                # 隱藏「漲跌幅＋收盤價」合併欄位
                if (
                    "漲跌幅" in column_name
                    and "收盤價" in column_name
                ):
                    columns_to_remove.append(column)
                    continue

                # 隱藏「權重＋股數」合併欄位
                if (
                    "權重" in column_name
                    and "股數" in column_name
                ):
                    columns_to_remove.append(column)

            detail_df = detail_df.drop(
                columns=columns_to_remove,
                errors="ignore"
            )

# =========================
# 將抓取時間移到最後一欄
# =========================

if "抓取時間" in detail_df.columns:
    column_order = [
        column
        for column in detail_df.columns
        if column != "抓取時間"
    ]

    column_order.append("抓取時間")
    detail_df = detail_df[column_order]

            # =========================
            # 顯示 ETF 摘要
            # =========================

            col1, col2, col3 = st.columns(3)

            col1.metric(
                "ETF代碼",
                selected_etf
            )

            col2.metric(
                "持股檔數",
                f"{len(detail_df):,}"
            )

            col3.metric(
                "資料日期",
                selected_date
            )

            # =========================
            # 搜尋持股
            # =========================

            search_keyword = st.text_input(
                "搜尋持股",
                placeholder="輸入股票代碼或股票名稱",
                key="etf_detail_search"
            ).strip()

            display_df = detail_df.copy()

            if search_keyword:
                search_mask = (
                    display_df
                    .astype(str)
                    .apply(
                        lambda column:
                        column.str.contains(
                            search_keyword,
                            case=False,
                            na=False,
                            regex=False
                        )
                    )
                    .any(axis=1)
                )

                display_df = display_df[
                    search_mask
                ]

            st.caption(
                f"目前顯示 {selected_etf}，"
                f"共 {len(display_df):,} 筆資料"
            )

            # =========================
            # 顯示詳細持股表格
            # =========================

            st.dataframe(
                display_df,
                use_container_width=True,
                hide_index=True
            )

            # =========================
            # 下載目前選擇的 ETF 持股
            # =========================

            csv_data = display_df.to_csv(
                index=False
            ).encode("utf-8-sig")

            st.download_button(
                label=f"下載 {selected_etf} 詳細持股",
                data=csv_data,
                file_name=(
                    f"{selected_date}_"
                    f"{selected_etf}_holdings.csv"
                ),
                mime="text/csv",
                key="download_etf_detail"
            )

        except Exception as e:
            st.error(
                f"讀取 {selected_etf} 持股檔失敗：{e}"
            )

    else:
        st.warning(
            "找不到各 ETF 的完整持股檔案"
        )

        st.caption(
            "檔案名稱應為："
            "YYYY-MM-DD_ETF代碼_full_holdings.xlsx"
        )
