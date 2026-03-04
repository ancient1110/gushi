#!/usr/bin/env python3
"""本地股市行情自动采集 + 简易分析 + 报告生成工具。"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import logging
import re
import time
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import schedule
import yaml
import yfinance as yf
from pandas_datareader import data as web


def setup_logger(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


REQUIRED_CONFIG_KEYS = ["schedule_times", "history_period", "symbols", "output"]
MIN_HISTORY_DAYS = 45


DEFAULT_QUICK_SYMBOLS = [
    {"name": "标普500", "yfinance": "^GSPC", "stooq": "^SPX"},
    {"name": "纳斯达克100", "yfinance": "^NDX", "stooq": "^NDQ"},
    {"name": "道琼斯工业", "yfinance": "^DJI", "stooq": "^DJI"},
    {"name": "罗素2000", "yfinance": "^RUT", "stooq": "^RUT"},
    {"name": "VIX恐慌指数", "yfinance": "^VIX", "stooq": "^VIX"},
    {"name": "美国总市场ETF", "yfinance": "VTI", "stooq": "VTI.US"},
    {"name": "标普500ETF", "yfinance": "SPY", "stooq": "SPY.US"},
    {"name": "纳指100ETF", "yfinance": "QQQ", "stooq": "QQQ.US"},
    {"name": "道指ETF", "yfinance": "DIA", "stooq": "DIA.US"},
    {"name": "中概互联网ETF", "yfinance": "KWEB", "stooq": "KWEB.US"},
    {"name": "中国大盘ETF", "yfinance": "FXI", "stooq": "FXI.US"},
    {"name": "黄金ETF", "yfinance": "GLD", "stooq": "GLD.US"},
    {"name": "原油ETF", "yfinance": "USO", "stooq": "USO.US"},
]


def build_quickstart_config() -> dict:
    """返回开箱即用的默认配置，用于 GUI 一键验证。"""
    return {
        "schedule_times": ["18:10"],
        "source_priority": ["yfinance", "stooq"],
        "request_retries": 2,
        "request_backoff_seconds": 3,
        "request_pause_seconds": 0.8,
        "request_timeout_seconds": 15,
        "history_period": "45d",
        "symbols": DEFAULT_QUICK_SYMBOLS,
        "output": {"data_dir": "data", "report_dir": "reports"},
    }


def validate_config(cfg: dict) -> dict:
    if not isinstance(cfg, dict):
        raise ValueError("配置内容必须是 YAML 对象（键值对），不能是空内容。")

    for key in REQUIRED_CONFIG_KEYS:
        if key not in cfg:
            raise ValueError(f"配置缺少关键字段: {key}")

    if not isinstance(cfg["schedule_times"], list) or not cfg["schedule_times"]:
        raise ValueError("配置字段 schedule_times 必须是非空列表。")
    if not isinstance(cfg["symbols"], list) or not cfg["symbols"]:
        raise ValueError("配置字段 symbols 必须是非空列表。")
    if not isinstance(cfg["output"], dict):
        raise ValueError("配置字段 output 必须是对象，例如 output: {data_dir: data, report_dir: reports}。")

    return cfg


def load_config(config_path: Path) -> dict:
    if not config_path.exists():
        raise FileNotFoundError(f"找不到配置文件: {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    return validate_config(cfg)


def _period_to_start(period: str) -> dt.datetime:
    now = dt.datetime.now()
    token = period.strip().lower().replace("mo", "m").replace("yr", "y")
    match = re.match(r"^(\d+)([dwmy])$", token)
    if not match:
        return now - dt.timedelta(days=180)

    amount = int(match.group(1))
    unit = match.group(2)
    if unit == "d":
        return now - dt.timedelta(days=amount)
    if unit == "w":
        return now - dt.timedelta(weeks=amount)
    if unit == "m":
        return now - dt.timedelta(days=amount * 30)
    if unit == "y":
        return now - dt.timedelta(days=amount * 365)
    return now - dt.timedelta(days=180)


def normalize_history_period(period: str) -> str:
    """将历史窗口收敛到满足 20 日指标所需的最小量，避免过度抓取。"""
    text = (period or "").strip().lower().replace("mo", "m").replace("yr", "y")
    match = re.match(r"^(\d+)([dwmy])$", text)
    if not match:
        return f"{MIN_HISTORY_DAYS}d"

    amount = int(match.group(1))
    unit = match.group(2)
    if unit == "d":
        days = amount
    elif unit == "w":
        days = amount * 7
    elif unit == "m":
        days = amount * 30
    else:
        days = amount * 365
    return f"{max(days, MIN_HISTORY_DAYS)}d"


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
        "Open": "Open",
        "High": "High",
        "Low": "Low",
        "Close": "Close",
        "Volume": "Volume",
    }
    df = df.rename(columns=rename_map)
    keep_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    out = df[keep_cols].copy()
    out.index = pd.to_datetime(out.index).tz_localize(None)
    return out.sort_index()


def fetch_symbol_history(source: str, symbol: str, period: str) -> pd.DataFrame:
    logging.debug("拉取数据: %s (%s)", symbol, source)

    if source == "yfinance":
        df = yf.Ticker(symbol).history(period=period, interval="1d", auto_adjust=True)
        if df.empty:
            raise ValueError(f"{symbol} 无可用数据")
        return _normalize_columns(df)

    if source == "stooq":
        start = _period_to_start(period)
        df = web.DataReader(symbol, "stooq", start=start)
        if df.empty:
            raise ValueError(f"{symbol} 无可用数据")
        return _normalize_columns(df)

    raise ValueError(f"不支持的数据源: {source}")


def _resolve_symbol_by_source(raw_symbol: str | dict, source: str) -> tuple[str, str]:
    if isinstance(raw_symbol, str):
        return raw_symbol, raw_symbol

    display = raw_symbol.get("name") or raw_symbol.get("symbol") or "unknown"
    direct_key = raw_symbol.get(source)
    if direct_key:
        return display, direct_key

    fallback = raw_symbol.get("symbol")
    if fallback:
        return display, fallback

    raise ValueError(f"标的缺少可用代码: {raw_symbol}")


def find_symbol_by_name(query: str, symbol_pool: list[dict] | None = None) -> dict:
    """按名称/代码模糊查找默认标的。"""
    if not query or not query.strip():
        raise ValueError("请输入名称或代码")

    term = query.strip().lower()
    pool = symbol_pool or DEFAULT_QUICK_SYMBOLS

    for item in pool:
        candidates = [
            str(item.get("name", "")).lower(),
            str(item.get("yfinance", "")).lower(),
            str(item.get("stooq", "")).lower(),
            str(item.get("symbol", "")).lower(),
        ]
        if any(term == c for c in candidates if c):
            return item

    for item in pool:
        candidates = [
            str(item.get("name", "")).lower(),
            str(item.get("yfinance", "")).lower(),
            str(item.get("stooq", "")).lower(),
            str(item.get("symbol", "")).lower(),
        ]
        if any(term in c for c in candidates if c):
            return item

    raise ValueError(f"未找到匹配标的: {query}")


def _calc_intraday_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    close = out["Close"]

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    out["MACD_DIF"] = ema12 - ema26
    out["MACD_DEA"] = out["MACD_DIF"].ewm(span=9, adjust=False).mean()
    out["MACD_HIST"] = (out["MACD_DIF"] - out["MACD_DEA"]) * 2

    low_n = out["Low"].rolling(9, min_periods=1).min()
    high_n = out["High"].rolling(9, min_periods=1).max()
    rsv = (close - low_n) / (high_n - low_n).replace(0, np.nan) * 100
    out["K"] = rsv.ewm(com=2, adjust=False).mean()
    out["D"] = out["K"].ewm(com=2, adjust=False).mean()
    out["J"] = 3 * out["K"] - 2 * out["D"]

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out["RSI14"] = 100 - (100 / (1 + rs))
    return out


def fetch_intraday_detail_72h(raw_symbol: str | dict) -> tuple[str, pd.DataFrame]:
    """抓取近 72h（以 15m 颗粒度）并计算技术指标。"""
    display, query_symbol = _resolve_symbol_by_source(raw_symbol, "yfinance")
    df = yf.Ticker(query_symbol).history(period="5d", interval="15m", auto_adjust=True)
    if df.empty:
        raise ValueError(f"{display} 72h 分时无可用数据")
    df = _normalize_columns(df)
    cutoff = dt.datetime.now() - dt.timedelta(hours=72)
    df = df[df.index >= cutoff]
    if df.empty:
        raise ValueError(f"{display} 72h 分时无可用数据")
    return display, _calc_intraday_indicators(df)


def fetch_symbol_history_with_retry(
    raw_symbol: str | dict,
    period: str,
    retries: int,
    backoff_seconds: int,
    source_priority: list[str],
    request_timeout_seconds: int,
) -> tuple[str, str, pd.DataFrame]:
    last_error: Exception | None = None

    for source in source_priority:
        display_symbol, query_symbol = _resolve_symbol_by_source(raw_symbol, source)
        for attempt in range(1, retries + 1):
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(fetch_symbol_history, source, query_symbol, period)
                    data = future.result(timeout=request_timeout_seconds)
                return display_symbol, source, data
            except concurrent.futures.TimeoutError:
                last_error = TimeoutError(
                    f"{display_symbol} via {source} 拉取超时（>{request_timeout_seconds}s）"
                )
                logging.warning("%s", last_error)
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                message = str(exc).lower()
                is_rate_limited = "too many requests" in message or "rate limited" in message
                if attempt >= retries:
                    break

                wait_seconds = backoff_seconds * attempt if is_rate_limited else 1
                logging.warning(
                    "拉取失败（%s via %s，第 %s/%s 次），%s 秒后重试: %s",
                    display_symbol,
                    source,
                    attempt,
                    retries,
                    wait_seconds,
                    exc,
                )
                time.sleep(wait_seconds)

        logging.warning("数据源 %s 失败，尝试下一个数据源: %s", source, display_symbol)

    target_label = raw_symbol if isinstance(raw_symbol, str) else raw_symbol.get("name", raw_symbol)
    raise ValueError(f"{target_label} 多数据源拉取失败: {last_error}") from last_error


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


def build_summary(symbol: str, source: str, metrics: Dict[str, float]) -> Dict[str, object]:
    return {
        "symbol": symbol,
        "source": source,
        "last_close": round(metrics["last_close"], 4),
        "ret_1d(%)": round(metrics["ret_1d"] * 100, 2),
        "ret_5d(%)": round(metrics["ret_5d"] * 100, 2),
        "ma20": round(metrics["ma20"], 4),
        "ma20_bias(%)": round(metrics["ma20_bias"] * 100, 2),
        "volatility_20d(%)": round(metrics["volatility_20d"] * 100, 2),
        "signal": generate_signal(metrics),
    }


def run_once(config: dict) -> Tuple[Path, Path]:
    config = validate_config(config)
    now = dt.datetime.now()
    date_tag = now.strftime("%Y%m%d_%H%M%S")

    data_dir = Path(config["output"].get("data_dir", "data"))
    report_dir = Path(config["output"].get("report_dir", "reports"))
    data_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    retries = int(config.get("request_retries", 3))
    backoff_seconds = int(config.get("request_backoff_seconds", 3))
    pause_seconds = float(config.get("request_pause_seconds", 1.5))
    request_timeout_seconds = int(config.get("request_timeout_seconds", 15))
    source_priority = list(config.get("source_priority", ["yfinance", "stooq"]))

    history_period = normalize_history_period(str(config.get("history_period", "45d")))

    for raw_symbol in config["symbols"]:
        try:
            symbol_name, source, hist = fetch_symbol_history_with_retry(
                raw_symbol,
                history_period,
                retries,
                backoff_seconds,
                source_priority,
                request_timeout_seconds,
            )
            safe_name = symbol_name.replace("^", "IDX_").replace("/", "_")
            hist.to_csv(data_dir / f"{safe_name}_{date_tag}.csv")
            summaries.append(build_summary(symbol_name, source, calc_metrics(hist)))
            logging.info("完成: %s (source=%s)", symbol_name, source)
            if source in source_priority and source_priority[0] != source:
                source_priority.remove(source)
                source_priority.insert(0, source)
                logging.info("已更新数据源优先级（后续优先尝试）: %s", " -> ".join(source_priority))
        except Exception as e:  # noqa: BLE001
            msg = f"{raw_symbol}: {e}"
            errors.append(msg)
            logging.warning("失败: %s", msg)

        time.sleep(pause_seconds)

    summary_df = pd.DataFrame(summaries)
    if not summary_df.empty and "ret_1d(%)" in summary_df.columns:
        summary_df = summary_df.sort_values(by="ret_1d(%)", ascending=False)
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
                dataframe_to_markdown(summary_df),
                "",
            ]
        )

    if errors:
        lines.append("## 失败列表")
        lines.extend([f"- {e}" for e in errors])

    path.write_text("\n".join(lines), encoding="utf-8")


def dataframe_to_markdown(df: pd.DataFrame) -> str:
    try:
        return df.to_markdown(index=False)
    except ImportError:
        logging.warning("缺少 tabulate，Markdown 表格降级为纯文本输出。建议安装: pip install tabulate")
        return df.to_string(index=False)


def schedule_jobs(config: dict) -> None:
    times = config["schedule_times"]
    for t in times:
        schedule.every().day.at(t).do(run_once, config)
        logging.info("已注册定时任务: 每天 %s", t)

    logging.info("调度器启动，按 Ctrl+C 退出")
    while True:
        schedule.run_pending()
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
