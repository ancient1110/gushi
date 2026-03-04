# 本地股市行情自动采集与分析脚本

这个项目提供一个可本地运行的自动化脚本，支持：
- 每天定时采集多个股指/股票行情（支持 `yfinance` + `stooq` 自动切换）
- 自动计算基础指标（1日/5日涨跌、20日均线偏离、20日年化波动）
- 自动生成 CSV 汇总和 Markdown 报告
- 可选图形界面（Streamlit），支持“输入名称即查”与 72h 分时细看（含 A 股）

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
- `history_period`: 拉取历史窗口（会自动收敛到至少 `45d`，避免为 20 日指标过量抓取）
- `source_priority`: 数据源优先级（建议 `yfinance -> stooq`）
- `request_timeout_seconds`: 单次请求超时秒数，避免个别代码卡住整个流程
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

## 4) 图形化界面（重点：Windows 也能直接用）

### 方式 A（推荐，跨平台）

不依赖 `streamlit` 命令是否在 PATH，直接用 Python 模块方式：

```bash
python launch_gui.py
```

### 方式 B（Windows 双击）

直接双击仓库里的 `run_gui.bat`，它会自动：
1. 创建 `.venv`（若不存在）
2. 安装依赖
3. 启动图形界面

> 这样就不需要你手动敲 `streamlit run app.py`，也能避免“streamlit 未识别”问题。

### 方式 C（你原来的命令）

```powershell
streamlit run app.py
```

如果报错“`streamlit` 不是内部或外部命令”，说明 `streamlit` 没装到当前 Python 环境，或脚本目录不在 PATH。请改用：

```powershell
python -m streamlit run app.py
```

页面里可以：
- 输入名称/代码做**快捷查询（日线摘要）**
- 点击**细看（近72h分时）**查看价格 + MACD/KDJ/RSI
- **全市场一键验证（免配置）**

> 若要查询 A 股（如“中国海油”）并获取更稳定的分时数据，请确保安装 `akshare`（已在 `requirements.txt` 中包含）。
> 即使未安装 `akshare`，系统也内置了部分常见 A 股名称/代码映射（含中国海油）用于快捷查询。
> 新版 GUI 会在未检测到 `akshare` 时给出明确安装提示（`pip install akshare`）。

## 5) 推荐本地定时方式（更稳）

你也可以不让 Python 常驻，改用系统 `cron` 每天触发一次：

```cron
10 18 * * * cd /你的路径/gushi && /你的路径/gushi/.venv/bin/python market_bot.py --config config.yaml --once >> cron.log 2>&1
```

## 6) 常见问题

- **Q: PowerShell 报 `streamlit` 无法识别？**  
  A: 用 `python -m streamlit run app.py` 或 `python launch_gui.py`，不要依赖全局 `streamlit` 命令。
- **Q: 双击 `app.py` 没反应？**  
  A: `app.py` 是 Streamlit 应用，不是普通 GUI 程序。请双击 `run_gui.bat`，或在终端执行 `python launch_gui.py`。
- **Q: 第一次运行 Streamlit 出现“要输入 email”是啥？**  
  A: 这是 Streamlit 的首次欢迎提示，不是本项目在收集邮箱。直接按回车跳过即可，后续不会影响使用。
- **Q: GUI 里报 `配置缺少关键字段: schedule_times` 或 `NoneType is not subscriptable`？**  
  A: 说明配置为空或字段不完整。请确保使用了仓库中的 `config.yaml.example`（先复制为 `config.yaml`），再根据需要修改。新版 GUI 会在配置为空时给出更明确提示。
- **Q: 依赖安装慢/失败？**  
  A: 常见原因是网络或代理问题。可先执行 `python -m pip install -U pip`，然后重试 `pip install -r requirements.txt`。

## 7) 注意事项

- 公开行情接口可能波动，脚本会按 `source_priority` 自动切换数据源。
- 某个数据源一旦成功，后续标的会优先尝试该源（动态提权），减少整体失败率与重试耗时。
- 如果出现 `Too Many Requests`，可提高 `request_pause_seconds`、`request_backoff_seconds`，或减少单次追踪标的数量。
- 如遇到个别标的“查不到/卡住”，可降低 `request_timeout_seconds` 让脚本更快跳到下一个源。
- 为降低数据量，日线计算会把 `history_period` 自动规范为至少 45 天（覆盖 20 日均线/波动所需）。
- `stooq` 与 `yfinance` 代码有时不一致，建议在 `symbols` 中分别配置。
- 即使本次全部标的都失败，脚本也会照常输出报告（含失败列表），不会因为汇总排序报错而中断。
- 该脚本仅做信息汇总与量化观察，不构成投资建议。
