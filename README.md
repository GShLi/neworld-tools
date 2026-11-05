# 新界自动登录与签到

Python + Playwright **仅无界面运行**的脚本，访问 `https://neworld.cloud/user`。每次运行按**北京时间（Asia/Shanghai）**选择领取类型：

| 日期 | 领取内容 | 提交值 |
| --- | --- | --- |
| 周一 | 流量 | `traffic` |
| 周二至周日 | 时长 | `time` |

一次运行只处理当天签到，完成后退出。每天自动执行可使用下方的定时任务。

## 截图和代码分析

- 提供的截图显示每日奖励为 512 MB 流量或 4 小时时长，每日零点重置；2026-11-05 已领取时长。奖励额度由网站决定，脚本不硬编码额度。
- 保存的 HTML 中两个单选框均名为 `checkin_type`，取值分别是 `traffic` 和 `time`。默认选中流量，因此脚本每次必须明确设置目标选项。
- 同目录 `新界_files/user-indexi-checkin_Y_9A.js` 显示：点击 `#check-in` 后向 `/user/checkin` 发送 POST；`ret=1` 成功，`ret=2` 需要验证码，其余结果为失败。`#check-in-done` 可见表示当天已签到。
- [在线登录页](https://neworld.cloud/auth/login) 使用 `#email`、`#passwd`、`#totp-code` 和 `#login-dashboard`，向 `/auth/login` 提交邮箱、密码、两步验证码和浏览器指纹。脚本通过网页控件完成登录，保留网站自己的指纹及验证流程。
- 签到可能触发 Turnstile 或 hCaptcha。脚本等待网站自动验证通过后提交确认；若必须人工操作，则等待超时后失败退出，不打开窗口或绕过验证。**因此无法保证每天签到成功**。

原始 HTML 含个人账户数据，没有复制到本项目。

## 安装

要求 Python 3.9+，支持 macOS/Linux。

```bash
cd /Users/double/Desktop/Gits/Github/neworld-tools
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install --only-shell chromium
```

账号密码**只从环境变量读取**：

| 环境变量 | 内容 |
| --- | --- |
| `NEWORLD_USERNAME` | 登录用户名，即网站注册邮箱 |
| `NEWORLD_PASSWORD` | 登录密码 |
| `NEWORLD_TOTP_CODE` | 可选，当前 6 位两步验证码 |

本地可在终端安全输入（下面命令适用于 macOS 默认 zsh）：

```zsh
read 'NEWORLD_USERNAME?登录邮箱: '
read -s 'NEWORLD_PASSWORD?登录密码: '
echo
export NEWORLD_USERNAME NEWORLD_PASSWORD
```

脚本不读取账号配置文件，不自动加载 `.env`，也不打印凭据。缺少用户名或密码时直接报错退出。`.state/` 按用户名隔离保存浏览器会话，已加入 `.gitignore`，请不要分享；其上级目录权限设为仅当前用户可访问。

## 使用

```bash
# 无界面自动登录、选择当天奖励并签到
.venv/bin/python neworld_checkin.py

# 只自动登录并保存会话，不签到（仍需设置环境变量）
.venv/bin/python neworld_checkin.py --login-only

# 登录并检查当天状态，不提交签到
.venv/bin/python neworld_checkin.py --dry-run

# 完全离线预览规则，不需要配置账户或安装浏览器
python3 neworld_checkin.py --plan --date 2026-11-02
# 2026-11-02 Asia/Shanghai：领取流量 (traffic)

python3 neworld_checkin.py --plan --date 2026-11-03
# 2026-11-03 Asia/Shanghai：领取时长 (time)
```

其他参数：

| 参数 | 用途 |
| --- | --- |
| `--wait-seconds 300` | 等待登录或自动验证，默认 180 秒 |
| `--state-dir /path/state` | 指定独立会话目录，默认脚本目录下 `.state/` |

`--date` 仅用于 `--plan`，不能改变实际签到日期。等待验证码期间如果跨越午夜，提交前会重新计算领取类型。当天已经签到时直接跳过，不能改领另一种奖励。同一状态目录不允许多个脚本同时运行。

开启两步验证的账户可通过 `NEWORLD_TOTP_CODE` 提供当前 6 位验证码；验证码会过期，不适合固定写入每日定时任务。会话过期后，若账号仍需要两步验证，需要提供新的验证码；不支持手动登录。

## GitHub Actions 每天自动执行

已提供 [`.github/workflows/checkin.yml`](.github/workflows/checkin.yml)。

1. 将项目推送到 GitHub 仓库的默认分支。
2. 打开仓库 **Settings → Secrets and variables → Actions → New repository secret**，添加：

   | Secret 名称 | 值 | 映射到环境变量 |
   | --- | --- | --- |
   | `username` | 注册邮箱 | `NEWORLD_USERNAME` |
   | `password` | 登录密码 | `NEWORLD_PASSWORD` |

3. 在 **Actions → Neworld daily check-in → Run workflow** 手动运行一次，查看日志。

之后每天北京时间 **08:10** 自动执行（cron `10 0 * * *`，UTC），在运行当天自动决定周一流量、其余日期时长。工作流安装 Python 与 Chromium Headless Shell（不安装完整 Chromium）、运行本地模拟测试，然后将两个 Secrets 注入签到步骤的环境变量。

无界面浏览器组件按系统、架构和固定的 Playwright 版本缓存。首次运行或缓存失效时下载，之后恢复缓存并检查安装；Linux 系统依赖仍会安装。只缓存浏览器程序，不缓存账户会话。缓存恢复仍需传输数据，不保证总耗时比直接下载更短，参见 [Playwright 缓存说明](https://playwright.dev/python/docs/ci#caching-browsers)。

GitHub 定时任务仅从默认分支执行，高负载时可能延迟；公共仓库长时间无活动可能停用定时任务。参见 [GitHub schedule 文档](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。

GitHub runner 每次是新环境，不持久化或上传浏览器登录状态。若网站要求人工验证码或两步验证，任务会失败；本地 `--login-only` 的会话不会传到 GitHub。浏览器安装方式参考 [Playwright CI 文档](https://playwright.dev/python/docs/ci-intro)。

成功或当天已签到返回退出码 `0`；登录失败、验证超时、网络异常、页面结构变化等返回 `1`；手动中断返回 `130`。若服务端已接收请求但客户端超时，脚本不会盲目重复提交，下一次运行会重新检查当天状态。

## 验证

```bash
.venv/bin/python -m unittest discover -s tests -v
```

测试覆盖整周规则、北京时间午夜边界、登录及两步验证提交、复用会话、两种领取参数、验证码后跨日切换、重复签到跳过、只读预览及服务端拒绝。浏览器测试使用本地模拟响应，不操作真实账户；真实站点会话、指纹风控和验证码仍需用户配置账户后验证。
