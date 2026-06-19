# clashpilot

简体中文 | [English](README.en.md)

一个独立运行的 Clash/Mihomo 客户端：自动选择最快的代理节点，节点掉线时自动切换，全程在后台静默运行。无需 Clash Verge、无需图形界面，[mihomo](https://github.com/MetaCubeX/mihomo) 内核自动下载并管理。

自带一份免费默认节点，安装后即可联网；填入自己的订阅可获得更快、更稳定的连接。

## 安装

需要 [Python 3.8+](https://www.python.org/downloads/) 和 [git](https://git-scm.com/downloads)。推荐使用 `pipx`：

```bash
pipx install git+https://github.com/JamesChoeng/clashpilot.git
```

升级：`pipx upgrade clashpilot`。

<details>
<summary>使用 uvx 或 pip 安装</summary>

```bash
# 不安装直接运行（需要 uv）
uvx --from git+https://github.com/JamesChoeng/clashpilot clashpilot status

# 普通 pip
pip install git+https://github.com/JamesChoeng/clashpilot.git
```

使用 `pip install --user` 时，命令可能安装到不在 PATH 上的目录。首次运行 `clashpilot up` 会自动将其加入 PATH（Windows 上同时使短命令 `clp` 生效），也可手动执行 `clashpilot setup-path`。之后请新开一个终端。

国内下载 GitHub 资源较慢时，可通过 `CLASHPILOT_GH_PROXY` 设置镜像（见[配置](#配置)）。

</details>

## 快速开始

启动（前台运行，`Ctrl-C` 停止）：

```bash
clashpilot up
```

使用自己的订阅：

```bash
clashpilot set-sub "你的订阅链接"
clashpilot update
```

> 所有命令均可使用短命令 `clp` 代替 `clashpilot`，例如 `clp up`。

## 让 Cursor 等 AI 工具保持在线

将以下内容加入 `~/.cursor/hooks.json`，每次会话开始时自动确保代理就绪：

```jsonc
{
  "version": 1,
  "hooks": {
    "sessionStart": [
      { "command": "clashpilot hook" }
    ]
  }
}
```

## 命令

| 命令 | 说明 |
|---|---|
| `clashpilot up` | 启动：内核 + 系统代理 + 自动切换（前台运行） |
| `clashpilot down` | 停止：关闭内核并撤销系统代理 |
| `clashpilot status` | 查看内核、代理、订阅等状态 |
| `clashpilot set-sub URL` | 保存订阅链接 |
| `clashpilot update` | 重新拉取订阅并重建配置 |
| `clashpilot setup-path` | 将命令所在目录加入 PATH |
| `clashpilot hook` | 供 Cursor 钩子调用 |

## 配置

所有项均有合理默认值，可通过环境变量覆盖：

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `CLASHPILOT_SUBSCRIPTION` | 内置默认 | 订阅链接（优先级高于 `set-sub`） |
| `CLASHPILOT_GH_PROXY` | 无 | GitHub 下载镜像前缀，如 `https://ghproxy.com` |
| `CLASHPILOT_CORE_VERSION` | latest | 锁定 mihomo 版本，如 `v1.19.24` |
| `CLASHPILOT_MIXED_PORT` | `7890` | 本地代理端口（HTTP + SOCKS） |
| `CLASHPILOT_CONTROLLER_PORT` | `9090` | 内核控制端口 |
| `CLASHPILOT_TARGETS` | Cursor + Anthropic | 测速目标地址（逗号分隔） |
| `CLASHPILOT_STATE_DIR` | 每用户状态目录 | 内核 / 配置 / 日志存放位置 |
| `CLASH_CONTROLLER` / `CLASH_SECRET` | 自动 | 控制器地址 / 密钥 |

数据文件存放于：`%LOCALAPPDATA%\clashpilot`（Windows）、`~/Library/Application Support/clashpilot`（macOS）、`~/.local/state/clashpilot`（Linux）。

## 说明与限制

- 系统代理使用 mihomo 的本地端口（HTTP + SOCKS），未启用 TUN 模式。
- Linux 上自动设置系统代理依赖 GNOME 的 `gsettings`；其他桌面环境请自行设置 `http_proxy` / `https_proxy`。

## 许可证

MIT
