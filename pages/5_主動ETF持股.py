from pathlib import Path
import os
import re
import subprocess
import sys

import pandas as pd
import streamlit as st

import etf_utils

st.set_page_config(page_title="主動ETF持股", layout="wide")
st.title("主動ETF持股")

BASE_DIR = Path(__file__).resolve().parent.parent
ETF_HOLDINGS_DIR = BASE_DIR / "etf_holdings"
LAST_UPDATE_FILE = ETF_HOLDINGS_DIR / "last_update.txt"
UPDATE_SCRIPT = BASE_DIR / "run_etf_update.py"
NOTIFY_SCRIPT = BASE_DIR / "etf_line_notify_local.py"
ETF_CODES = list(etf_utils.ETFS)


def run_etf_update_with_progress():
    if not UPDATE_SCRIPT.exists():
        st.error(f"找不到更新程式：{UPDATE_SCRIPT}")
        return
    if not (BASE_DIR / "etf_utils.py").exists():
        st.error(f"找不到爬蟲模組：{BASE_DIR / 'etf_utils.py'}")
        return

    progress = st.progress(0, text="準備啟動 ETF 更新...")
    current = st.empty()
    log_area = st.empty()
    logs = []
    completed = set()

    with st.status("正在抓取 ETF 持股資料...", expanded=True) as status:
        update_env = os.environ.copy()
        update_env["PYTHONIOENCODING"] = "utf-8"
        update_env["PYTHONUTF8"] = "1"

        process = subprocess.Popen(
            [sys.executable, "-X", "utf8", "-u", str(UPDATE_SCRIPT)],
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=update_env,
        )

        if process.stdout:
            for raw_line in process.stdout:
                line = raw_line.rstrip()
                if not line:
                    continue
                logs.append(line)
                log_area.code("\n".join(logs[-15:]), language="text")

                for etf_code in ETF_CODES:
                    if f"開始抓取完整持股: {etf_code}" in line:
                        etf_index = ETF_CODES.index(etf_code) + 1
                        progress.progress(
                            int((etf_index - 1) / len(ETF_CODES) * 85),
                            text=(
                                f"正在抓取 {etf_code}，"
                                f"第 {etf_index}/{len(ETF_CODES)} 檔"
                            ),
                        )
                        current.info(f"目前處理：{etf_code}")
                        break
                    if f"{etf_code} 完整抓取完成" in line:
                        completed.add(etf_code)
                        progress.progress(
                            int(len(completed) / len(ETF_CODES) * 85),
                            text=f"已完成 {len(completed)}/{len(ETF_CODES)} 檔 ETF",
                        )
                        break

                if "合併完整持股檔已儲存" in line:
                    progress.progress(90, text="正在產生合併持股與每日異動 Excel...")
                elif "共同每日異動 Summary 已儲存" in line:
                    progress.progress(95, text="共同異動 Summary 已完成...")
                elif "最後更新時間已儲存" in line:
                    progress.progress(98, text="正在完成最後整理...")

        return_code = process.wait()
        if return_code == 0:
            progress.progress(100, text="ETF 資料更新完成")
            current.success(f"更新完成，成功抓取 {len(completed)}/{len(ETF_CODES)} 檔 ETF。")
            status.update(label="ETF資料更新完成", state="complete", expanded=False)
            st.success("最新 Excel 已儲存至 etf_holdings。")
            st.cache_data.clear()
            st.rerun()
        else:
            status.update(label="ETF資料更新失敗", state="error", expanded=True)
            st.error(f"更新程式結束碼：{return_code}")


def send_line_notification():
    if not NOTIFY_SCRIPT.exists():
        st.error(f"找不到 LINE 通知程式：{NOTIFY_SCRIPT}")
        return
    line_env = os.environ.copy()
    line_env["PYTHONIOENCODING"] = "utf-8"

    with st.spinner("正在發送 LINE 通知..."):
        result = subprocess.run(
            [sys.executable, "-u", str(NOTIFY_SCRIPT)],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=line_env,
        )
    if result.returncode == 0:
        st.success("LINE 通知已發送。")
    else:
        st.error(f"LINE 通知發送失敗，結束碼：{result.returncode}")
        output = "\n".join(x for x in [result.stdout.strip(), result.stderr.strip()] if x)
        if output:
            st.code(output[-12000:], language="text")


c1, c2, _ = st.columns([1, 1, 3])
with c1:
    update_clicked = st.button("🔄 更新ETF資料", type="primary", use_container_width=True)
with c2:
    notify_clicked = st.button("📨 LINE通知", use_container_width=True)
if update_clicked:
    run_etf_update_with_progress()
if notify_clicked:
    send_line_notification()

st.caption("更新時會顯示目前 ETF、完成檔數、進度與最近 15 行紀錄。LINE 按鈕會發送最新 Summary。")

try:
    last_update = LAST_UPDATE_FILE.read_text(encoding="utf-8").strip() or "未知"
except FileNotFoundError:
    last_update = "找不到 last_update.txt"
except OSError as error:
    last_update = f"讀取失敗：{error}"
st.success(f"✅ 最後更新時間：{last_update}")


def get_latest_file(pattern: str):
    files = list(ETF_HOLDINGS_DIR.glob(pattern))
    return max(files, key=lambda path: path.stat().st_mtime) if files else None


def get_latest_etf_files():
    latest = {}
    for path in ETF_HOLDINGS_DIR.glob("*_full_holdings.xlsx"):
        match = re.match(
            r"^(\d{4}-\d{2}-\d{2})_([A-Za-z0-9]+)_full_holdings\.xlsx$",
            path.name,
        )
        if not match:
            continue
        date, code = match.group(1), match.group(2).upper()
        if code not in latest or date > latest[code]["date"]:
            latest[code] = {"date": date, "path": path}
    return latest


def clean_code(series):
    return series.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)


summary_file = get_latest_file("*common_daily_changes_summary.xlsx")
daily_file = get_latest_file("*daily_changes_changed_only.xlsx")
holding_file = get_latest_file("*_common_holdings_all.xlsx")
etf_files = get_latest_etf_files()

tab1, tab2, tab3, tab4 = st.tabs(["共同異動 Summary", "每日異動", "共同持股", "ETF詳細持股"])

with tab1:
    if not summary_file:
        st.warning("找不到共同異動 Summary 檔案")
    else:
        st.info(f"最新檔案：{summary_file.name}")
        try:
            df = pd.read_excel(summary_file, engine="openpyxl")
            if "共同方向" not in df.columns:
                st.error("Summary Excel 找不到『共同方向』欄位")
            else:
                inc = df["共同方向"].isin(["全部加碼", "全數加碼"]).sum()
                dec = df["共同方向"].isin(["全部減碼", "全數減碼"]).sum()
                df["共同方向"] = df["共同方向"].replace({
                    "全部加碼": "🔴 全部加碼", "全數加碼": "🔴 全數加碼",
                    "全部減碼": "🟢 全部減碼", "全數減碼": "🟢 全數減碼", "混合": "🟡 混合",
                })
                metric_col1, metric_col2, metric_col3 = st.columns(3)
                metric_col1.metric("共同異動股票數", len(df))
                metric_col2.metric("🔴 全部加碼", int(inc))
                metric_col3.metric("🟢 全部減碼", int(dec))
                st.dataframe(df, use_container_width=True, hide_index=True)
        except Exception as error:
            st.error(f"讀取共同異動 Summary 失敗：{error}")

with tab2:
    if not daily_file:
        st.warning("找不到每日異動檔案")
    else:
        st.info(f"最新檔案：{daily_file.name}")
        try:
            df = pd.read_excel(daily_file, engine="openpyxl", dtype=str).dropna(how="all").dropna(axis=1, how="all")
            df.columns = [str(x).strip() for x in df.columns]
            today, previous = "股票名稱_今日", "股票名稱_昨日"
            def names(col):
                if col not in df.columns:
                    return pd.Series(pd.NA, index=df.index, dtype="string")
                s = df[col].astype("string").str.strip()
                return s.mask(s.str.upper().isin(["", "NAN", "NONE", "<NA>"]))
            df["股票名稱"] = names(today).fillna(names(previous)) if today in df.columns or previous in df.columns else ""
            etf_col = next((x for x in df.columns if str(x).strip() in ["ETF", "ETF代碼", "基金代碼"]), None)
            if not etf_col:
                st.error("每日異動 Excel 找不到 ETF 代碼欄位")
            else:
                df[etf_col] = df[etf_col].astype(str).str.strip().str.upper()
                df = df[~df[etf_col].isin(["", "NAN", "NONE", "<NA>"])]
                options = sorted(df[etf_col].dropna().unique())
                selected = st.selectbox("請選擇 ETF", options, key="selected_daily_etf")
                show = df[df[etf_col] == selected].copy().drop(columns=[previous, today, "權重_昨日", "股數_昨日"], errors="ignore")
                if "調整方向" in show.columns:
                    show["調整方向"] = show["調整方向"].replace({"加碼":"🔴 加碼", "減碼":"🟢 減碼", "新納入":"🔴 新納入", "全數賣出":"🟢 全數賣出"})
                code_col = next((x for x in show.columns if "股票代碼" in str(x)), None)
                if code_col:
                    show[code_col] = clean_code(show[code_col])

                metric_col1, metric_col2 = st.columns(2)
                metric_col1.metric("ETF代碼", selected)
                metric_col2.metric("異動股票數", f"{len(show):,}")
                st.dataframe(show, use_container_width=True, hide_index=True)
        except Exception as error:
            st.error(f"讀取每日異動檔案失敗：{error}")

with tab3:
    if not holding_file:
        st.warning("找不到共同持股檔案")
    else:
        st.info(f"最新檔案：{holding_file.name}")
        try:
            df = pd.read_excel(holding_file, engine="openpyxl", dtype={"股票代碼": str})
            hidden = [x for x in df.columns if x.endswith("_股票名稱") or x.endswith("_股數")]
            df = df.drop(columns=hidden, errors="ignore")
            if "共同持有ETF" in df.columns:
                df = df[[x for x in df.columns if x != "共同持有ETF"] + ["共同持有ETF"]]
            st.dataframe(df, use_container_width=True, hide_index=True)
        except Exception as error:
            st.error(f"讀取共同持股檔案失敗：{error}")

with tab4:
    if not etf_files:
        st.warning("找不到各 ETF 的完整持股檔案")
        st.caption("檔案名稱應為：YYYY-MM-DD_ETF代碼_full_holdings.xlsx")
    else:
        selected = st.selectbox("請選擇 ETF", sorted(etf_files), key="selected_etf_detail")
        path, date = etf_files[selected]["path"], etf_files[selected]["date"]
        st.info(f"最新檔案：{path.name}")
        try:
            df = pd.read_excel(path, engine="openpyxl", dtype={"股票代碼": str}).dropna(how="all").dropna(axis=1, how="all")
            df.columns = [str(x).strip() for x in df.columns]
            if "股票代碼" in df.columns:
                df["股票代碼"] = clean_code(df["股票代碼"])
            remove = [x for x in df.columns if str(x).strip() in ["資料來源", "來源頁次", "持股變化", "00XXXA_股數"] or ("漲跌幅" in str(x) and "收盤價" in str(x)) or ("權重" in str(x) and "股數" in str(x))]
            df = df.drop(columns=remove, errors="ignore")
            capture = next((x for x in df.columns if "抓取時間" in str(x)), None)
            if capture:
                df = df[[x for x in df.columns if x != capture] + [capture]]

            metric_col1, metric_col2, metric_col3 = st.columns(3)
            metric_col1.metric("ETF代碼", selected)
            metric_col2.metric("持股檔數", f"{len(df):,}")
            metric_col3.metric("資料日期", date)
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.download_button(f"下載 {selected} 詳細持股", df.to_csv(index=False).encode("utf-8-sig"), f"{date}_{selected}_holdings.csv", "text/csv", key="download_etf_detail")
        except Exception as error:
            st.error(f"讀取 {selected} 持股檔失敗：{error}")
