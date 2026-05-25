# Meme Onchain Explorer

**独立长期项目** — Solana meme 链上信号 + paper trading 模拟盘 + 策略迭代。

- 不依赖海豚桌面仓库、`h-agent-mcp` 或其它本地文件夹
- 仅需本仓库 + 系统安装的 `onchainos` CLI
- 仓库：[okx-wallet-H/cursor-onchain-meme](https://github.com/okx-wallet-H/cursor-onchain-meme) · 说明见 [docs/REPO_SETUP.md](docs/REPO_SETUP.md)

## 目标

- 每小时扫描一次 Solana meme 信号
- 组合聪明钱/鲸鱼买入信号、持有人、集中度、卖出比例等字段
- 模拟买入，不触碰真实 swap / approve / broadcast
- 自动检查止盈止损
- 记录仓位、现金、权益、PnL、交易日志、踩坑和新发现

## 运行

```bash
python3 scripts/meme_sim_trader.py scan
python3 scripts/meme_sim_trader.py check
python3 scripts/meme_sim_trader.py tick
python3 scripts/meme_sim_trader.py report
python3 scripts/meme_sim_trader.py export
python3 scripts/meme_sim_trader.py dashboard   # 生成 dashboard/snapshot.json
```

## 数据面板 (HTML)

**推荐（稳定）**：用 GitHub 仓库同步，浏览器打开固定地址，不依赖本机 8765 服务。

| 用途 | 地址 |
|------|------|
| **稳定面板（推荐）** | https://okx-wallet-H.github.io/cursor-onchain-meme/ |
| 仓库内 JSON | https://raw.githubusercontent.com/okx-wallet-H/cursor-onchain-meme/main/dashboard/snapshot.json |

每小时 `tick` 结束后会自动执行 `scripts/publish_dashboard.sh`，把 `dashboard/snapshot.json` 推到 `main`，GitHub Actions 再部署 Pages。

手动刷新并推送：

```bash
chmod +x scripts/publish_dashboard.sh
./scripts/publish_dashboard.sh
```

**本机备用**（可选）：`./scripts/install_dashboard_service.sh` → http://127.0.0.1:8765/dashboard/

**离线**：双击 `dashboard/index.html`（读同目录 `data.js`）。

- `dashboard/index.html`：面板页面（优先从 GitHub raw / Pages 拉数据）
- `dashboard/snapshot.json` + `dashboard/data.js`：提交到仓库，供 Pages 与离线使用

核对仓位优先看 `data/positions.csv`，字段包括：trade_id、开平仓价、信号价、止盈止损价、仓位金额、浮盈浮亏、聪明钱地址数、触发钱包列表等。

持续每小时运行：

```bash
python3 scripts/meme_sim_trader.py loop
```

## 目录

- `config/config.json`：策略和风控边界
- `data/state.json`：模拟钱包状态
- `data/trade_log.jsonl`：交易事件日志（扁平字段，含 trade_id）
- `data/positions.csv`：持仓核对表（开仓/平仓一行，可用 Excel 打开）
- `data/position_snapshots.jsonl`：每轮持仓市值快照
- `data/observations.jsonl`：每轮信号和过滤原因
- `memory/lessons.md`：过程中新发现和踩坑记录
- `reports/`：报告输出

## 当前策略假设

Meme 不按普通估值交易，本项目只做短周期事件交易：

1. 发现资金同步进入
2. 过滤明显高风险信号
3. 小仓位模拟建仓
4. 严格 TP/SL
5. 冷却和黑名单防止复买陷阱

金额由配置控制，策略只提供风险边界和自动化框架。

## 策略优化

```bash
python3 scripts/meme_sim_trader.py analyze    # 按钱包类型/分数/sold_ratio 分桶统计
python3 scripts/meme_sim_trader.py optimize # 生成 strategy_recommendation.json
python3 scripts/meme_sim_trader.py optimize --apply  # 写入 config.json（已应用 v3）
```

当前策略版本见 `config/config.json` 的 `strategy_version`（**v3-whale-strict**：仅 Whale、更高分数门槛、更严 sold_ratio、更快止损）。

## 轮次说明

- **`round`**：按 `scan_interval_seconds`（默认 1 小时）才 +1；同一小时内的多次 `tick` / `report` 只检查止盈止损，不重复扫信号、不增轮次。
- **`scan_count`**：每次真正执行信号扫描时 +1（含手动 `scan`）。
- **`strategy_version`**：当前策略版本；每轮 `analyze` 输出 `reports/strategy_analysis.json` 供迭代。
- 手动开启新轮：`python3 scripts/meme_sim_trader.py tick --force-round`
- 策略复盘：`python3 scripts/meme_sim_trader.py analyze`
