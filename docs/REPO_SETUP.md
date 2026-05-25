# 独立仓库接入说明

本项目为**长期独立仓库**，不依赖海豚桌面目录、`h-agent-mcp` 或其它工作区文件夹。

## 官方仓库

https://github.com/okx-wallet-H/cursor-onchain-meme

```bash
git clone https://github.com/okx-wallet-H/cursor-onchain-meme.git
cd cursor-onchain-meme
cp config/config.example.json config/config.json   # 首次本地配置
./scripts/install_scheduler.sh
./scripts/install_dashboard_service.sh
```

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

克隆到新路径后**必须重装** launchd，路径会写入当前目录：

```bash
./scripts/install_scheduler.sh
./scripts/install_dashboard_service.sh
```

## Cursor 工作区

在 Cursor 中 **Open Folder** 只打开本仓库根目录即可。不要与 `h-agent-mcp`、海豚 `dolphin` 放在同一 workspace 里混用。
