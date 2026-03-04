#!/usr/bin/env python3
"""Streamlit 图形界面：按名称快速查询 + 细看 72h 分时指标。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

from market_bot import (
    build_quickstart_config,
    fetch_intraday_detail_72h,
    find_symbol_by_name,
    is_akshare_available,
    run_once,
    validate_config,
)

st.set_page_config(page_title="行情采集助手", layout="wide")
st.title("📈 行情采集助手")
st.caption("输入名称/代码即可查询；支持 72h 分时细看（价格 + MACD/KDJ/RSI）。")

if is_akshare_available():
    st.success("已检测到 akshare：A 股名称检索和分时回退可用")
else:
    st.warning("未检测到 akshare。若要更稳地查询 A 股（如中国海油），请先执行：pip install akshare")

query = st.text_input("输入标的名称或代码", placeholder="例如：标普500 / AAPL / QQQ")

col1, col2, col3 = st.columns([1, 1, 1])
with col1:
    if st.button("快捷查询（日线摘要）", type="primary", width="stretch"):
        try:
            symbol = find_symbol_by_name(query)
            cfg = build_quickstart_config()
            cfg["symbols"] = [symbol]
            summary_path, report_path = run_once(cfg)

            st.success(f"查询完成：{symbol['name']}")
            st.write(f"汇总文件：`{summary_path}`")
            st.write(f"报告文件：`{report_path}`")

            df = pd.read_csv(summary_path)
            if not df.empty:
                st.dataframe(df, width="stretch")
        except Exception as exc:  # noqa: BLE001
            st.error(f"查询失败: {exc}")

with col2:
    if st.button("细看（近72h分时）", width="stretch"):
        try:
            symbol = find_symbol_by_name(query)
            display_name, intraday = fetch_intraday_detail_72h(symbol)
            st.success(f"已获取 {display_name} 近72h分时")

            latest = intraday.iloc[-1]
            metric1, metric2, metric3, metric4 = st.columns(4)
            metric1.metric("最新价格", f"{latest['Close']:.4f}")
            metric2.metric("MACD(HIST)", f"{latest['MACD_HIST']:.4f}")
            metric3.metric("KDJ(J)", f"{latest['J']:.2f}")
            metric4.metric("RSI14", f"{latest['RSI14']:.2f}")

            st.line_chart(intraday[["Close", "MACD_DIF", "MACD_DEA"]], height=260, width="stretch")
            st.line_chart(intraday[["K", "D", "J", "RSI14"]], height=260, width="stretch")
            st.dataframe(intraday.tail(120), width="stretch")
        except Exception as exc:  # noqa: BLE001
            st.error(f"细看失败: {exc}")

with col3:
    if st.button("全市场一键验证", width="stretch"):
        try:
            cfg = build_quickstart_config()
            summary_path, report_path = run_once(cfg)
            st.success("默认配置采集完成（全市场概览）")
            st.write(f"汇总文件：`{summary_path}`")
            st.write(f"报告文件：`{report_path}`")
            df = pd.read_csv(summary_path)
            if not df.empty:
                st.dataframe(df, width="stretch")
        except Exception as exc:  # noqa: BLE001
            st.error(f"运行失败: {exc}")

st.divider()
st.caption("高级模式：如需完整批量配置，可手动编辑 config.yaml 后在终端运行。")
if st.checkbox("显示高级配置预览（只读）"):
    config_path = Path("config.yaml")
    if config_path.exists():
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        cfg = validate_config(cfg)
        st.code(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), language="yaml")
    else:
        st.info("未找到 config.yaml")
