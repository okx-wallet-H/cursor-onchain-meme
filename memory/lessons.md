# Meme Exploration Lessons

## 初始假设

- Meme 币不按常规估值判断，核心是短周期资金事件。
- 策略目标不是预测长期价值，而是发现可试错信号并快速退出。
- 止盈止损、冷却、黑名单比“看好某个币”更重要。
- 金额由用户/配置决定，策略只负责风控边界和执行纪律。

## 待验证问题

- `triggerWalletCount` 到底从多少开始有稳定正期望？
- Whale (`walletType=3`) 是否显著优于 Smart Money (`walletType=1`)？
- `soldRatioPercent` 高到多少时信号已经失效？
- Top10 holder concentration 高于多少后容易砸盘？
- 新迁移币和老币的 1 小时收益分布差异有多大？

## 运行发现

后续由 `scripts/meme_sim_trader.py memory` 或人工复盘追加。

### 2026-05-24T09:03:35.515247+00:00

踩坑：OnchainOS signal list 会返回同一 token 的多条信号；模拟开仓必须按 tokenAddress 去重，只取最高分信号，否则同地址重复扣现金并覆盖仓位，导致权益失真。已修复：best_by_address 去重 + open_position 二次防重。

### 2026-05-24T20:00:00+00:00

第 1–20 轮复盘（v2 策略依据）：
- **Whale 明显优于 SmartMoney**：止盈 TRALALERO/PP420 均为 Whale；止损 HypurrClaw/Bank 均为 SmartMoney。
- **sold_ratio > 75% 的票普遍亏损**；盈利单 sold_ratio 多在 40–48%。
- **score < 70 开仓期望为负**；当前 5 仓全为 SmartMoney 且多数 score 53–76、浮亏合计约 -96U。
- **v2 调整**：仅 Whale(`wallet_types=3`)、`min_signal_score=72`、`max_sold_ratio_pct=75`、`min_trigger_wallet_count=3`、提高 min_holders；评分对 sold_ratio>70 额外扣分。
- 既有持仓不动，新信号按 v2 过滤；继续 hourly tick 累积样本后再 `analyze` 迭代。

### 2026-05-25T06:30:00+00:00

v3 策略（`optimize --apply`）：
- 43 轮样本：已实现胜率约 9%（2 胜 / 21 负），仅 **Whale + score≥72 + sold_ratio≤75** 两笔大止盈（PP420、TRALALERO）。
- v3：**仅 Whale**、`min_signal_score=78`、`max_sold_ratio_pct=65`、`min_trigger=4`、TP 38% / SL -15%、单仓 10%、现金预留 15%。
- 旧仓（SmartMoney 低分）保留至 TP/SL，**新开仓** 一律按 v3；跑 `python3 scripts/meme_sim_trader.py analyze` 看分桶统计。

### 2026-05-25T10:00:00+00:00

**暂停模拟**（47 轮复盘后）：
- `sim_enabled=false` + `./scripts/pause_sim.sh` 停掉 launchd；恢复用 `./scripts/resume_sim.sh`。
- 面板仍可读：https://okx-wallet-h.github.io/cursor-onchain-meme/

**47 轮经验摘要**：
| 维度 | 结论 |
|------|------|
| 钱包类型 | **Whale** 平仓 9 笔胜率 33%、合计 +101U；**SmartMoney** 5 笔全胜负、-136U → 新仓禁止 SmartMoney |
| sold_ratio | **≤50%** 胜率 60%、+137U；**51–75%** 6 笔全负；-108U → v4 上限改为 **50%** |
| 高分陷阱 | score 80+ 胜率仅 29%（样本含早期宽松开仓）；盈利单 sold_ratio 均值 **~44%**，亏损 **~62%** |
| 大赢 | GAPLA（Whale、sold 44%）止盈 +58U；历史 PP420/TRALALERO 同类 |
| 大亏 | 重复开仓同一 ticker（GAPLA 先 SL 再 TP）、Whale 但 sold 55–72% 仍止损（Ask/RETARDATIDE） |
| 工程 | 同 token 去重、按地址防重复扣款；模拟与真钱包严格分离 |

**v4 优化**（`v4-whale-low-sold`，默认仍暂停）：
- `max_sold_ratio_pct=50`、`min_signal_score=80`、`max_positions=3`、单仓 8%、现金预留 20%
- TP **35%** / SL **-12%**；评分对 sold>50 加重扣分
- 恢复模拟前建议：手动审视 3 个未平仓位（含 1 个 SmartMoney 遗留 CATCOIN）

### 2026-05-25T10:34:00+00:00

**V4 全新开局**：
- `reset --force`：1000U 现金、0 仓位、日志清空；`scan_interval_seconds=1800`（30 分钟一轮）。
- 面板 `runtime`：在线时长、持续/断线状态、距上次 tick；超 1.5× 间隔为「可能断线」，超 2× 为「断线 · 未持续」。
- 定时：`install_scheduler.sh` 从 config 读取间隔写入 launchd。
