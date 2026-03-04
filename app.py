#!/usr/bin/env python3
"""Streamlit 图形界面：一键运行行情采集。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

from market_bot import load_config, run_once

st.set_page_config(page_title="行情采集助手", layout="wide")
st.title("📈 行情采集助手")
st.caption("支持多数据源自动切换：yfinance 失败会自动回退到 stooq。")

config_path_str = st.text_input("配置文件路径", value="config.yaml")
config_path = Path(config_path_str)

col1, col2 = st.columns([1, 1])
with col1:
    if st.button("加载配置", use_container_width=True):
        try:
            cfg = load_config(config_path)
            st.session_state["cfg_text"] = yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True)
            st.success("配置已加载")
        except Exception as exc:  # noqa: BLE001
            st.error(f"加载失败: {exc}")

if "cfg_text" not in st.session_state and config_path.exists():
    st.session_state["cfg_text"] = config_path.read_text(encoding="utf-8")

cfg_text = st.text_area("配置内容（可直接编辑）", value=st.session_state.get("cfg_text", ""), height=340)

with col2:
    if st.button("保存配置", use_container_width=True):
        config_path.write_text(cfg_text, encoding="utf-8")
        st.success(f"已保存到 {config_path}")

st.divider()
if st.button("立即执行一次采集", type="primary", use_container_width=True):
    try:
        cfg = yaml.safe_load(cfg_text)
        summary_path, report_path = run_once(cfg)

        st.success("采集完成")
        st.write(f"汇总文件：`{summary_path}`")
        st.write(f"报告文件：`{report_path}`")

        df = pd.read_csv(summary_path)
        if not df.empty:
            st.dataframe(df, use_container_width=True)
        else:
            st.warning("本次没有成功采集到数据，请查看报告中的失败列表。")

        report_text = Path(report_path).read_text(encoding="utf-8")
        st.markdown("### 报告预览")
        st.markdown(report_text)
    except Exception as exc:  # noqa: BLE001
        st.error(f"运行失败: {exc}")
