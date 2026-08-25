from glob import glob
import os
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

full_holding_file = get_latest_file(
    "etf_holdings/*active_etf_full_holdings_all.xlsx"
)

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

    if full_holding_file:

        st.info(
            f"最新檔案：{os.path.basename(full_holding_file)}"
        )

        try:
            # 讀取 Excel 內的所有工作表
            all_sheets = pd.read_excel(
                full_holding_file,
                sheet_name=None,
                engine="openpyxl"
            )

            # 取得工作表名稱
            sheet_names = list(all_sheets.keys())

            # 優先將像 00981A、00991A 的工作表當成 ETF
            etf_sheet_names = [
                sheet_name
                for sheet_name in sheet_names
                if (
                    str(sheet_name).strip().upper().endswith("A")
                    and any(
                        char.isdigit()
                        for char in str(sheet_name)
                    )
                )
            ]

            # 如果找不到符合格式的工作表，
            # 就暫時顯示全部工作表
            if not etf_sheet_names:
                etf_sheet_names = sheet_names

            if etf_sheet_names:

                selected_etf = st.selectbox(
                    "請選擇 ETF",
                    options=etf_sheet_names,
                    key="selected_etf_detail"
                )

                detail_df = all_sheets[
                    selected_etf
                ].copy()

                # 股票代碼維持文字格式
                if "股票代碼" in detail_df.columns:
                    detail_df["股票代碼"] = (
                        detail_df["股票代碼"]
                        .astype(str)
                        .str.replace(
                            r"\.0$",
                            "",
                            regex=True
                        )
                        .str.zfill(4)
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

                # 不想顯示的欄位
                hidden_detail_columns = [
                    "00XXXA_股數"
                ]

                detail_df = detail_df.drop(
                    columns=hidden_detail_columns,
                    errors="ignore"
                )

                # 顯示資料日期
                file_name = os.path.basename(
                    full_holding_file
                )

                file_date = file_name[:10]

                col1, col2, col3 = st.columns(3)

                col1.metric(
                    "ETF代碼",
                    selected_etf
                )

                col2.metric(
                    "持股檔數",
                    len(detail_df)
                )

                col3.metric(
                    "資料日期",
                    file_date
                )

                # 搜尋股票
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

                st.dataframe(
                    display_df,
                    use_container_width=True,
                    hide_index=True
                )

                # 下載目前選取的 ETF 持股
                csv_data = display_df.to_csv(
                    index=False
                ).encode("utf-8-sig")

                st.download_button(
                    label=(
                        f"下載 {selected_etf} "
                        "詳細持股"
                    ),
                    data=csv_data,
                    file_name=(
                        f"{file_date}_"
                        f"{selected_etf}_holdings.csv"
                    ),
                    mime="text/csv",
                    key="download_etf_detail"
                )

            else:
                st.warning(
                    "完整持股 Excel 內沒有可使用的工作表"
                )

        except Exception as e:
            st.error(
                f"讀取 ETF 完整持股檔案失敗：{e}"
            )

    else:
        st.warning(
            "找不到 ETF 完整持股檔案"
        )
