# 本地股市行情自动采集与分析脚本

这个项目提供一个可本地运行的自动化脚本，支持：
- 每天定时采集多个股指/股票行情（支持 `yfinance` + `stooq` 自动切换）
- 自动计算基础指标（1日/5日涨跌、20日均线偏离、20日年化波动）
- 自动生成 CSV 汇总和 Markdown 报告
- 可选图形界面（Streamlit），一键运行、可视化查看结果

## 1) 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell 请改用：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 2) 配置

先复制配置模板：

```bash
cp config.yaml.example config.yaml
```

Windows PowerShell 可用：

```powershell
Copy-Item config.yaml.example config.yaml
```

然后修改：
- `schedule_times`: 每天执行时间（可多个）
- `history_period`: 拉取历史窗口（如 `3mo`、`6mo`）
- `source_priority`: 数据源优先级（建议 `yfinance -> stooq`）
- `symbols`: 要追踪的指数/股票代码（推荐用“按数据源分别配置”的写法）

## 3) 使用方式

### 先手动跑一次（建议）

```bash
python market_bot.py --config config.yaml --once
```

输出：
- `data/summary_*.csv`（汇总结果）
- `reports/report_*.md`（可直接阅读的报告）

### 开启定时常驻

```bash
python market_bot.py --config config.yaml
```

## 4) 图形化界面（更省事）

如果你觉得命令行安装和使用太麻烦，可直接用图形界面：

```bash
streamlit run app.py
```

页面里可以：
- 载入/编辑/保存 `config.yaml`
- 一键执行采集
- 直接预览汇总表和报告

## 5) 推荐本地定时方式（更稳）

你也可以不让 Python 常驻，改用系统 `cron` 每天触发一次：

```cron
10 18 * * * cd /你的路径/gushi && /你的路径/gushi/.venv/bin/python market_bot.py --config config.yaml --once >> cron.log 2>&1
```

## 6) 注意事项

- 公开行情接口可能波动，脚本会按 `source_priority` 自动切换数据源。
- 如果出现 `Too Many Requests`，可提高 `request_pause_seconds`、`request_backoff_seconds`，或减少单次追踪标的数量。
- `stooq` 与 `yfinance` 代码有时不一致，建议在 `symbols` 中分别配置。
- 即使本次全部标的都失败，脚本也会照常输出报告（含失败列表），不会因为汇总排序报错而中断。
- 该脚本仅做信息汇总与量化观察，不构成投资建议。
