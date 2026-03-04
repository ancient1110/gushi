#!/usr/bin/env python3
"""本地股市行情自动采集 + 简易分析 + 报告生成工具。"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import schedule
import yaml
import yfinance as yf


def setup_logger(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def load_config(config_path: Path) -> dict:
    if not config_path.exists():
        raise FileNotFoundError(f"找不到配置文件: {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    required_keys = ["schedule_times", "history_period", "symbols", "output"]
    for key in required_keys:
        if key not in cfg:
            raise ValueError(f"配置缺少关键字段: {key}")

    return cfg


def fetch_symbol_history(symbol: str, period: str) -> pd.DataFrame:
    logging.debug("拉取数据: %s", symbol)
    df = yf.Ticker(symbol).history(period=period, interval="1d", auto_adjust=True)
    if df.empty:
        raise ValueError(f"{symbol} 无可用数据")

    keep_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    df = df[keep_cols].copy()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def calc_metrics(df: pd.DataFrame) -> Dict[str, float]:
    close = df["Close"].dropna()
    if len(close) < 21:
        raise ValueError("数据不足，至少需要 21 个交易日")

    ret_1d = close.pct_change().iloc[-1]
    ret_5d = close.iloc[-1] / close.iloc[-6] - 1 if len(close) >= 6 else np.nan
    ma20 = close.rolling(20).mean().iloc[-1]
    ma_bias = close.iloc[-1] / ma20 - 1
    volatility_20d = close.pct_change().rolling(20).std().iloc[-1] * np.sqrt(252)

    return {
        "last_close": float(close.iloc[-1]),
        "ret_1d": float(ret_1d),
        "ret_5d": float(ret_5d),
        "ma20": float(ma20),
        "ma20_bias": float(ma_bias),
        "volatility_20d": float(volatility_20d),
    }


def generate_signal(metrics: Dict[str, float]) -> str:
    score = 0
    if metrics["ret_5d"] > 0:
        score += 1
    if metrics["ma20_bias"] > 0:
        score += 1
    if metrics["volatility_20d"] < 0.30:
        score += 1

    if score >= 3:
        return "偏强"
    if score == 2:
        return "中性偏强"
    if score == 1:
        return "中性偏弱"
    return "偏弱"


def build_summary(symbol: str, metrics: Dict[str, float]) -> Dict[str, object]:
    return {
        "symbol": symbol,
        "last_close": round(metrics["last_close"], 4),
        "ret_1d(%)": round(metrics["ret_1d"] * 100, 2),
        "ret_5d(%)": round(metrics["ret_5d"] * 100, 2),
        "ma20": round(metrics["ma20"], 4),
        "ma20_bias(%)": round(metrics["ma20_bias"] * 100, 2),
        "volatility_20d(%)": round(metrics["volatility_20d"] * 100, 2),
        "signal": generate_signal(metrics),
    }


def run_once(config: dict) -> Tuple[Path, Path]:
    now = dt.datetime.now()
    date_tag = now.strftime("%Y%m%d_%H%M%S")

    data_dir = Path(config["output"].get("data_dir", "data"))
    report_dir = Path(config["output"].get("report_dir", "reports"))
    data_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    summaries: List[Dict[str, object]] = []
    errors: List[str] = []

    for symbol in config["symbols"]:
        try:
            hist = fetch_symbol_history(symbol, config["history_period"])
            hist.to_csv(data_dir / f"{symbol.replace('^', 'IDX_')}_{date_tag}.csv")
            summaries.append(build_summary(symbol, calc_metrics(hist)))
            logging.info("完成: %s", symbol)
        except Exception as e:  # noqa: BLE001
            msg = f"{symbol}: {e}"
            errors.append(msg)
            logging.warning("失败: %s", msg)

    summary_df = pd.DataFrame(summaries).sort_values(by="ret_1d(%)", ascending=False)
    summary_path = data_dir / f"summary_{date_tag}.csv"
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")

    report_path = report_dir / f"report_{date_tag}.md"
    write_markdown_report(report_path, summary_df, errors)

    logging.info("输出汇总: %s", summary_path)
    logging.info("输出报告: %s", report_path)

    return summary_path, report_path


def write_markdown_report(path: Path, summary_df: pd.DataFrame, errors: List[str]) -> None:
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        f"# 行情自动分析报告 ({ts})",
        "",
        "## 总览",
        f"- 成功采集标的数量: **{len(summary_df)}**",
        f"- 失败标的数量: **{len(errors)}**",
        "",
    ]

    if not summary_df.empty:
        best = summary_df.iloc[0]
        worst = summary_df.iloc[-1]
        lines.extend(
            [
                "## 亮点与风险",
                f"- 当日最强: **{best['symbol']}** (1日涨跌: {best['ret_1d(%)']}%)",
                f"- 当日最弱: **{worst['symbol']}** (1日涨跌: {worst['ret_1d(%)']}%)",
                "",
                "## 明细表",
                summary_df.to_markdown(index=False),
                "",
            ]
        )

    if errors:
        lines.append("## 失败列表")
        lines.extend([f"- {e}" for e in errors])

    path.write_text("\n".join(lines), encoding="utf-8")


def schedule_jobs(config: dict) -> None:
    times = config["schedule_times"]
    for t in times:
        schedule.every().day.at(t).do(run_once, config)
        logging.info("已注册定时任务: 每天 %s", t)

    logging.info("调度器启动，按 Ctrl+C 退出")
    while True:
        schedule.run_pending()
        # 这里不用 time.sleep 会导致空转占用 CPU
        import time

        time.sleep(30)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="本地股市行情自动采集与分析")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--once", action="store_true", help="立即执行一次后退出")
    parser.add_argument("--verbose", action="store_true", help="输出更详细日志")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logger(args.verbose)

    config = load_config(Path(args.config))

    if args.once:
        run_once(config)
    else:
        schedule_jobs(config)


if __name__ == "__main__":
    main()
