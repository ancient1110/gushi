# 本地股市行情自动采集与分析脚本

这个项目提供一个可本地运行的自动化脚本，支持：
- 每天定时采集多个股指/股票行情（公开数据，`yfinance`）
- 自动计算基础指标（1日/5日涨跌、20日均线偏离、20日年化波动）
- 自动生成 CSV 汇总和 Markdown 报告

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
- `symbols`: 要追踪的指数/股票代码

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

## 4) 推荐本地定时方式（更稳）

你也可以不让 Python 常驻，改用系统 `cron` 每天触发一次：

```cron
10 18 * * * cd /你的路径/gushi && /你的路径/gushi/.venv/bin/python market_bot.py --config config.yaml --once >> cron.log 2>&1
```

## 5) 注意事项

- 数据来自公开行情接口，偶尔可能出现延迟或个别代码无数据。
- 如果出现 `Too Many Requests`，可提高 `request_pause_seconds`、`request_backoff_seconds`，或减少单次追踪标的数量。
- 即使本次全部标的都失败，脚本也会照常输出报告（含失败列表），不会因为汇总排序报错而中断。
- 该脚本仅做信息汇总与量化观察，不构成投资建议。
- 若你后续想加：微信/邮件推送、更多技术指标、回测模块，可以在此基础上扩展。
