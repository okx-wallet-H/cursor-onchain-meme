# 独立仓库接入说明

本项目为**长期独立仓库**，不依赖海豚桌面目录、`h-agent-mcp` 或其它工作区文件夹。

## 官方仓库

https://github.com/okx-wallet-H/cursor-onchain-meme

```bash
git clone https://github.com/okx-wallet-H/cursor-onchain-meme.git
cd cursor-onchain-meme
cp config/config.example.json config/config.json   # 首次本地配置
./scripts/install_scheduler.sh
chmod +x scripts/publish_dashboard.sh
# 稳定面板: https://okx-wallet-H.github.io/cursor-onchain-meme/
```

首次若面板空白，执行 `./scripts/publish_dashboard.sh`；Pages 约 1–2 分钟生效。

## 首次推送（维护者）

```bash
git remote add origin https://github.com/okx-wallet-H/cursor-onchain-meme.git
git push -u origin main
```

运行时数据（`data/`、`logs/`、`reports/` 生成物）已在 `.gitignore` 中排除，每台机器本地积累。

## 环境依赖

- Python 3.10+
- [onchainos CLI](https://github.com/okx/onchainos-skills)（读信号与价格，**不**需要把本仓库放进海豚项目）

```bash
# 安装后验证
onchainos signal list --chain solana --limit 3
```

## 本机服务（可选）

克隆到新路径后**必须重装** 定时 tick（路径写入 launchd）：

```bash
./scripts/install_scheduler.sh
```

数据面板默认走 **GitHub Pages**（`publish_dashboard.sh` 随 tick 推送）。仅在本机调试时再装：

```bash
./scripts/install_dashboard_service.sh
```

## Cursor 工作区

在 Cursor 中 **Open Folder** 只打开本仓库根目录即可。不要与 `h-agent-mcp`、海豚 `dolphin` 放在同一 workspace 里混用。
