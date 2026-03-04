#!/usr/bin/env python3
"""本地股市行情自动采集 + 简易分析 + 报告生成工具。"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import importlib
import logging
import re
import time
import urllib.parse
import urllib.request
from functools import lru_cache
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



def _load_akshare_module():
    spec = importlib.util.find_spec("akshare")
    if spec is None:
        return None
    return importlib.import_module("akshare")


def is_akshare_available() -> bool:
    return _load_akshare_module() is not None


def _to_yfinance_cn_symbol(code: str) -> str:
    if code.startswith(("600", "601", "603", "605", "688", "689", "900")):
        return f"{code}.SS"
    if code.startswith(("000", "001", "002", "003", "300", "301", "200")):
        return f"{code}.SZ"
    if code.startswith(("430", "831", "832", "833", "834", "835", "836", "837", "838", "839", "870", "871", "872", "873", "920")):
        return f"{code}.BJ"
    return code


def _to_prefixed_cn_symbol(code: str) -> str:
    if code.startswith(("600", "601", "603", "605", "688", "689", "900")):
        return f"sh{code}"
    if code.startswith(("000", "001", "002", "003", "300", "301", "200")):
        return f"sz{code}"
    if code.startswith(("430", "831", "832", "833", "834", "835", "836", "837", "838", "839", "870", "871", "872", "873", "920")):
        return f"bj{code}"
    return code


@lru_cache(maxsize=1)
def _get_akshare_spot_cache() -> pd.DataFrame:
    ak = _load_akshare_module()
    if ak is None:
        return pd.DataFrame()

    # 优先实时全量快照，失败时回退到代码名称表
    try:
        spot = ak.stock_zh_a_spot_em()
        if spot is not None and not spot.empty and {"代码", "名称"}.issubset(spot.columns):
            return spot[["代码", "名称"]].copy()
    except Exception:  # noqa: BLE001
        pass

    try:
        code_name = ak.stock_info_a_code_name()
        if code_name is not None and not code_name.empty:
            rename_map = {"code": "代码", "name": "名称"}
            normalized = code_name.rename(columns=rename_map)
            if {"代码", "名称"}.issubset(normalized.columns):
                return normalized[["代码", "名称"]].copy()
    except Exception:  # noqa: BLE001
        pass

    return pd.DataFrame()


def _find_cn_symbol_by_akshare(query: str) -> dict | None:
    if _load_akshare_module() is None:
        return None

    spot = _get_akshare_spot_cache()
    if spot is None or spot.empty or "代码" not in spot.columns or "名称" not in spot.columns:
        return None

    term = query.strip().lower()
    exact = spot[(spot["代码"].astype(str).str.lower() == term) | (spot["名称"].astype(str).str.lower() == term)]
    if exact.empty:
        fuzzy = spot[
            spot["代码"].astype(str).str.lower().str.contains(term, regex=False)
            | spot["名称"].astype(str).str.lower().str.contains(term, regex=False)
        ]
        if fuzzy.empty:
            return None
        row = fuzzy.iloc[0]
    else:
        row = exact.iloc[0]

    code = str(row["代码"]).zfill(6)
    name = str(row["名称"])
    return {
        "name": name,
        "symbol": code,
        "cn_code": code,
        "yfinance": _to_yfinance_cn_symbol(code),
    }




def _find_cn_symbol_by_sina_suggest(query: str) -> dict | None:
    """使用新浪 suggest 接口动态解析 A 股名称/代码，降低对手工映射依赖。"""
    term = query.strip()
    if not term:
        return None

    url = (
        "https://suggest3.sinajs.cn/suggest/type=11,12,13,14,15&key="
        + urllib.parse.quote(term)
    )

    try:
        with urllib.request.urlopen(url, timeout=6) as response:  # noqa: S310
            raw = response.read()
        text = raw.decode("gbk", errors="ignore")
    except Exception:  # noqa: BLE001
        return None

    # 示例：var suggestvalue="11,600938,中国海油,600938,中国海油,0;...";
    payload = text.split('"')
    if len(payload) < 2 or not payload[1].strip():
        return None

    for item in payload[1].split(";"):
        parts = item.split(",")
        if len(parts) < 3:
            continue
        code = parts[1].strip()
        name = parts[2].strip()
        if re.fullmatch(r"\d{6}", code):
            return {
                "name": name or f"A股{code}",
                "symbol": code,
                "cn_code": code,
                "yfinance": _to_yfinance_cn_symbol(code),
            }
    return None

def _find_cn_symbol_offline(query: str) -> dict | None:
    """仅保留 6 位纯代码直通，避免离线名称池覆盖在线检索结果。"""
    term = query.strip().lower()
    if re.fullmatch(r"\d{6}", term):
        return {
            "name": f"A股{term}",
            "symbol": term,
            "cn_code": term,
            "yfinance": _to_yfinance_cn_symbol(term),
        }
    return None


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
    """按名称/代码查找标的，优先在线检索。"""
    if not query or not query.strip():
        raise ValueError("请输入名称或代码")

    term = query.strip()
    term_lower = term.lower()

    # 直通：常见国际代码（例如 AAPL, QQQ, ^GSPC）
    if re.fullmatch(r"\^?[A-Za-z][A-Za-z0-9._-]{0,14}", term):
        return {"name": term.upper(), "symbol": term.upper(), "yfinance": term.upper()}

    # 回退 1：6 位 A 股代码直通
    offline_cn = _find_cn_symbol_offline(term)
    if offline_cn is not None:
        return offline_cn

    # 回退 2：在线名称检索（不依赖 akshare）
    sina_symbol = _find_cn_symbol_by_sina_suggest(term)
    if sina_symbol is not None:
        return sina_symbol

    # 回退 3：尝试实时 A 股库（akshare）
    cn_symbol = _find_cn_symbol_by_akshare(term)
    if cn_symbol is not None:
        return cn_symbol

    if not is_akshare_available():
        raise ValueError(
            f"未找到匹配标的: {term_lower}。已尝试在线检索；如需更高成功率建议安装 akshare: pip install akshare"
        )
    raise ValueError(f"未找到匹配标的: {term_lower}（已尝试在线检索和 akshare）")


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
    cutoff = dt.datetime.now() - dt.timedelta(hours=72)

    try:
        df = yf.Ticker(query_symbol).history(period="5d", interval="15m", auto_adjust=True)
        if not df.empty:
            normalized = _normalize_columns(df)
            normalized = normalized[normalized.index >= cutoff]
            if not normalized.empty:
                return display, _calc_intraday_indicators(normalized)
    except Exception:  # noqa: BLE001
        logging.info("yfinance 72h 分时失败，尝试 A 股数据源回退: %s", display)

    ak = _load_akshare_module()
    cn_code = None
    if isinstance(raw_symbol, dict):
        cn_code = raw_symbol.get("cn_code") or raw_symbol.get("symbol")
        if cn_code and re.fullmatch(r"\d{6}", str(cn_code)):
            cn_code = str(cn_code)
        else:
            cn_code = None
    if ak is None or not cn_code:
        raise ValueError(f"{display} 72h 分时无可用数据（建议安装 akshare 或检查标的代码）")

    start = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    end = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    detail: pd.DataFrame | None = None
    em_error: Exception | None = None
    try:
        detail = ak.stock_zh_a_hist_min_em(
            symbol=cn_code,
            period="15",
            adjust="qfq",
            start_date=start,
            end_date=end,
        )
    except Exception as exc:  # noqa: BLE001
        em_error = exc
        logging.warning("akshare 东财分时接口失败（%s）: %s", display, exc)

    if detail is None or detail.empty:
        # 回退：Sina 分时接口（通常不受东财 SSL 波动影响）
        minute_symbols = [cn_code, _to_prefixed_cn_symbol(cn_code)]
        for minute_symbol in minute_symbols:
            try:
                if hasattr(ak, "stock_zh_a_minute"):
                    detail = ak.stock_zh_a_minute(symbol=minute_symbol, period="15", adjust="qfq")
                    if detail is not None and not detail.empty:
                        break
            except Exception as exc:  # noqa: BLE001
                logging.warning("akshare 新浪分时接口失败（%s/%s）: %s", display, minute_symbol, exc)
                if em_error is None:
                    em_error = exc

    if detail is None or detail.empty:
        if em_error is not None:
            raise ValueError(f"{display} 72h 分时拉取失败（数据源连接不稳定，请稍后重试）") from em_error
        raise ValueError(f"{display} 72h 分时无可用数据")

    rename_map = {
        "时间": "Datetime",
        "day": "Datetime",
        "date": "Datetime",
        "开盘": "Open",
        "open": "Open",
        "收盘": "Close",
        "close": "Close",
        "最高": "High",
        "high": "High",
        "最低": "Low",
        "low": "Low",
        "成交量": "Volume",
        "volume": "Volume",
    }
    detail = detail.rename(columns=rename_map)
    required = ["Datetime", "Open", "High", "Low", "Close", "Volume"]
    missing = [c for c in required if c not in detail.columns]
    if missing:
        raise ValueError(f"{display} 分时字段缺失: {missing}")

    detail = detail[required].copy()
    detail["Datetime"] = pd.to_datetime(detail["Datetime"], errors="coerce")
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        detail[col] = pd.to_numeric(detail[col], errors="coerce")

    detail = detail.dropna(subset=["Datetime", "Open", "High", "Low", "Close"])
    detail["Volume"] = detail["Volume"].fillna(0.0)
    detail = detail.set_index("Datetime").sort_index()
    detail = detail[detail.index >= cutoff]
    if detail.empty:
        raise ValueError(f"{display} 72h 分时无可用数据")
    return display, _calc_intraday_indicators(detail)


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
