# clashpilot

简体中文 | [English](README.en.md)

一个**独立运行**的 Clash/Mihomo 客户端，自动挑选**最快**的代理节点，并在当前节点掉线的瞬间**自动切换**到下一个最佳节点 —— **静默在后台运行**，让 Cursor 等 AI agent 永不掉线。

给它一个订阅链接，剩下的全部交给它：自动为你的平台下载 [mihomo](https://github.com/MetaCubeX/mihomo) 内核、生成配置、启动内核、设置系统代理，然后持续地用你真正访问的目标（默认是 Cursor + Anthropic）去探测每个节点，切换到最快的那个，并在所在节点掉线时立刻跳到下一个最优节点。

**不需要 Clash Verge，不需要图形界面，也不用额外装任何东西** —— mihomo 内核由它自动拉取并管理。**零第三方 Python 依赖** —— 纯标准库实现。**全程静默运行** —— 没有控制台窗口、没有托盘图标、不用点任何东西，它只负责让你一直在线。

> 它仍然可以挂接到一个已有的 Clash Verge Rev / Mihomo 实例上（见[传统模式](#传统模式挂接已有内核)）。

## 安装

直接从 GitHub 安装 —— 无需 PyPI。

```bash
# 不安装直接运行（需要 uv + git）
uvx --from git+https://github.com/JamesChoeng/clashpilot clashpilot status

# 或作为全局命令安装（需要 pipx + git）
pipx install git+https://github.com/JamesChoeng/clashpilot.git

# 普通 pip 也可以
pip install git+https://github.com/JamesChoeng/clashpilot.git
```

后续更新：`pipx upgrade clashpilot`（或重新执行安装命令）。

需要 Python 3.8+ 和 git。mihomo 内核会在首次运行时自动下载。

> 国内网络下载 GitHub 资源可能受阻，可设置 `CLASHPILOT_GH_PROXY` 使用镜像加速（见[配置](#配置)）。

## 快速开始

```bash
clashpilot up   # 内核 + 配置 + 系统代理 + 自动切换（前台阻塞运行）
```

就这么简单 —— **开箱即用，装好即可上网**。即使没有设置订阅，clashpilot 也会使用一个内置默认源（一个公开的、自动更新的免费节点列表），所以安装完就能联网。流量会走最快的可用节点，并具备自动故障切换。

想用你自己的（更快、更稳定的）节点，把订阅链接指给它即可 —— 它的优先级高于默认源：

```bash
clashpilot set-sub "https://your-provider.example/sub?token=..."   # 你的 Clash/Mihomo 订阅
clashpilot update                                                   # 根据订阅重建配置
```

> 内置默认源使用的是免费、由志愿者维护的公共节点 —— 用来临时上网没问题，但它们不稳定，而且能看到你的所有流量。涉及敏感数据时请使用你自己的订阅。

用 Ctrl-C 停止（会同时移除系统代理并停止内核），或者让它在后台运行：

```bash
clashpilot ensure   # 在后台启动整套服务
clashpilot down     # 停止内核 + 移除系统代理 + 停止后台守护进程
```

## 让 Cursor 等 AI agent 不掉线

clashpilot 从设计之初就是为了**静默运行**，让长时间的 agent 会话（Cursor、Claude Code 等）在请求进行到一半时也不会掉线：

- **静默无感** —— 后台守护进程启动时没有控制台窗口（Windows 下使用 `pythonw`）、没有图形界面、没有托盘图标。装一次就可以彻底忘掉它的存在。
- **保护进行中请求的故障切换** —— 默认探测的就是 agent 实际访问的端点（`api2.cursor.sh`、`api.anthropic.com`）；当存在进行中的 Cursor/Anthropic 连接时，**优化型**切换会被延后，以免打断正在生成的回复。而当节点**已经掉线**时，仍然会立即切换。
- **Cursor sessionStart 钩子** —— `hook` 子命令会幂等地拉起整套服务并输出 `{}`，因此可以作为一个即插即用的 [Cursor hook](https://docs.cursor.com/)，保证每次会话开始的那一刻代理一定是就绪的：

```jsonc
// ~/.cursor/hooks.json
{
  "version": 1,
  "hooks": {
    "sessionStart": [
      { "command": "clashpilot hook" }
    ]
  }
}
```

再配合[开机自启](#开机自启)，你的 agent 就能在节点故障中始终保持连接，而你完全不用动手。

## 用法

```bash
clashpilot set-sub URL # 保存你的 Clash/Mihomo 订阅 URL
clashpilot up          # 独立模式：内核 + 配置 + 系统代理 + 循环（前台阻塞）
clashpilot ensure      # 在后台启动整套独立服务
clashpilot down        # 停止内核 + 移除系统代理 + 停止守护进程
clashpilot update      # 重新拉取订阅 + 重建配置 + 热重载内核
clashpilot core        # 下载/更新 mihomo 内核二进制
clashpilot status      # 内核 / 控制器 / 当前节点 / 守护进程 状态
clashpilot scan        # 按延迟给所有节点排名（不切换）
clashpilot switch HK   # 手动切换到某个节点（名称或子串匹配）
clashpilot log         # 查看守护进程日志
clashpilot stop        # 停止后台守护进程（内核继续运行）
```

## 开机自启

一条命令搞定，路径自动填好 —— 无需手工编辑服务文件：

```bash
clashpilot install-service     # macOS launchd / Linux systemd --user / Windows 计划任务
clashpilot uninstall-service
```

每种方式都会在登录时执行 `clashpilot up`（内核 + 系统代理 + 自动切换）。

- **macOS** —— 安装一个 `launchd` LaunchAgent（`~/Library/LaunchAgents`），登录时启动，崩溃后自动重启。
- **Linux** —— 安装一个 `systemd --user` 单元，并 `enable --now`。在无头服务器上你可能需要 `loginctl enable-linger $USER`。
- **Windows** —— 注册一个登录时运行的计划任务（通过 `pythonw` 无窗口运行）。

## 工作原理

- **自带内核** —— `mihomo` 会根据你的操作系统/架构从 GitHub Releases 下载（amd64 使用 `compatible` 版本以兼容最广泛的 CPU），缓存在你的状态目录下，并作为子进程启动，指向我们根据你的订阅生成的配置 —— 其中注入了我们自己的 `external-controller`、`secret` 和 `mixed-port`。
- **打分** —— 对每个节点逐一探测所有目标并取平均延迟；无法访问的目标会加上惩罚分，使得只能部分工作的节点排在完全可用的节点之后。
- **故障切换** —— 一个短周期的存活检测循环盯着当前节点，连续多次失败后会立即切换（绕过优化切换的冷却时间）。
- **抗抖动** —— 优化切换会遵守冷却时间和切换容差，并且在存在进行中的 Cursor/Anthropic 连接时延后执行（最多延后若干次），以免打断正在进行的请求。
- **订阅刷新** —— 独立模式下会定期重新拉取订阅并热重载内核。

## 传统模式：挂接已有内核

如果你更愿意自己继续运行 Clash Verge Rev / Mihomo，原本的「仅控制器」模式仍然可用 —— 它会自动从 Clash Verge 的 `config.yaml` 中发现控制器端点和 secret：

```bash
clashpilot run     # 仅循环；与你已经运行的内核/Verge 通信
```

## 配置

所有项都有合理的默认值。可通过环境变量覆盖：

| 环境变量 | 默认值 | 含义 |
|---|---|---|
| `CLASHPILOT_SUBSCRIPTION` | 内置默认 | 订阅 URL（覆盖 `set-sub`；其次回退到内置免费默认源，再次回退到打包的离线节点列表） |
| `CLASHPILOT_GH_PROXY` | 无 | GitHub 下载的前缀，例如 `https://ghproxy.com`（国内有用） |
| `CLASHPILOT_CORE_VERSION` | latest | 锁定特定 mihomo 版本（例如 `v1.19.24`） |
| `CLASHPILOT_MIXED_PORT` | `7890` | 本地 HTTP+SOCKS 代理端口 |
| `CLASHPILOT_CONTROLLER_PORT` | `9090` | 受管内核的 external-controller 端口 |
| `CLASHPILOT_SUB_REFRESH_INTERVAL` | `21600` | 订阅刷新间隔（秒，`0` = 关闭） |
| `CLASH_CONTROLLER` | 自动 | external-controller 的 `host:port`（传统模式/覆盖用） |
| `CLASH_SECRET` | 自动 | 控制器 secret（传统模式/覆盖用） |
| `CLASHPILOT_TARGETS` | Cursor + Anthropic | 逗号分隔的探测 URL |
| `CLASHPILOT_STATE_DIR` | 每用户状态目录 | 内核/配置/pid/日志文件存放位置 |
| `CLASHPILOT_FULL_SCAN_INTERVAL` | `180` | 全量重新排名扫描的间隔（秒） |
| `CLASHPILOT_HEALTH_INTERVAL` | `15` | 存活检测的间隔（秒） |
| `CLASHPILOT_HEALTH_FAIL_THRESHOLD` | `3` | 触发故障切换前的失败次数 |
| `CLASHPILOT_SWITCH_TOLERANCE_MS` | `150` | 值得切换所需的最小延迟收益 |
| `CLASHPILOT_SWITCH_COOLDOWN` | `60` | 两次优化切换之间的最小间隔（秒） |
| `CLASHPILOT_DELAY_TIMEOUT_MS` | `4000` | 打分时单次探测的超时时间 |

状态文件（下载的内核、受管配置、pid + 滚动日志）存放在每用户目录下：
`%LOCALAPPDATA%\clashpilot`（Windows）、`~/Library/Application Support/clashpilot`（macOS）、`~/.local/state/clashpilot`（Linux）。

## 说明与限制

- 系统代理被设置为 mihomo 的 mixed-port（HTTP + SOCKS）。未配置 TUN/全局抓包模式（它需要管理员权限/驱动）。
- 在 Linux 上，自动系统代理设置依赖 GNOME 的 `gsettings`；其他桌面环境下请自行导出 `http_proxy`/`https_proxy`（代理依然在 mixed-port 上运行）。
- 代理协议本身由 mihomo 二进制处理；本项目不重新实现这些协议。

## 许可证

MIT
