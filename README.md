# 新界自动签到

Python + Playwright 无界面脚本，自动登录 [新界](https://neworld.cloud/user)，按北京时间选择当天奖励：

| 日期 | 领取内容 |
| --- | --- |
| 周一 | 流量 |
| 周二至周日 | 时长 |

当天已经签到时自动跳过。可以在本地执行，也可以 Fork 后通过 GitHub Actions 每天自动执行。

## 本地执行

### 1. 下载项目并安装依赖

```bash
git clone https://github.com/GShLi/neworld-tools.git
cd neworld-tools
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install --only-shell chromium
```

Linux 如果缺少浏览器系统依赖，执行：

```bash
.venv/bin/python -m playwright install --with-deps --only-shell chromium
```

只安装 Chromium 无界面组件，首次使用需要下载，后续运行复用本地安装。

### 2. 设置账号密码

账号密码只从环境变量读取，用户名填写网站注册邮箱。下面的命令适用于 macOS 默认 zsh，密码输入不回显：

```zsh
read 'NEWORLD_USERNAME?登录邮箱: '
read -s 'NEWORLD_PASSWORD?登录密码: '
echo
export NEWORLD_USERNAME NEWORLD_PASSWORD
```

如果使用 Bash：

```bash
read -r -p '登录邮箱: ' NEWORLD_USERNAME
read -r -s -p '登录密码: ' NEWORLD_PASSWORD
echo
export NEWORLD_USERNAME NEWORLD_PASSWORD
```

### 3. 执行签到

在设置环境变量的同一个终端中运行：

```bash
.venv/bin/python neworld_checkin.py
```

每次运行只处理当天签到，完成后退出。其他可用命令：

```bash
# 只登录并保存本地会话，不签到
.venv/bin/python neworld_checkin.py --login-only

# 登录并检查签到状态，不提交签到
.venv/bin/python neworld_checkin.py --dry-run

# 离线预览指定日期的领取规则
.venv/bin/python neworld_checkin.py --plan --date 2026-11-02

# 将登录和自动验证的等待上限设为 60 秒
.venv/bin/python neworld_checkin.py --wait-seconds 60
```

本地会话按账号保存在 `.state/`，不要分享或提交该目录。脚本不自动读取 `.env` 文件。若账号开启两步验证，可额外设置 `NEWORLD_TOTP_CODE` 为当前 6 位验证码；过期后需更新。

## GitHub Actions 自动执行

**请先将本仓库 Fork 到自己的 GitHub 账号下，再在自己的仓库中配置。** 不需要本地安装 Python 或浏览器。

### 1. Fork 仓库

打开 [GShLi/neworld-tools](https://github.com/GShLi/neworld-tools)，点击右上角 **Fork → Create fork**。

### 2. 添加账号 Secrets

在你 Fork 的仓库中，打开 **Settings → Secrets and variables → Actions → New repository secret**，分别添加：

| Secret 名称 | 内容 |
| --- | --- |
| `USERNAME` | 新界注册邮箱 |
| `PASSWORD` | 新界登录密码 |

Secret 名称不区分大小写，GitHub 会保存为大写；工作流中的 `secrets.username`、`secrets.password` 可以正常读取。参见 [GitHub Secrets 文档](https://docs.github.com/en/actions/reference/security/secrets#naming-your-secrets)。

### 3. 启用 Actions 和定时工作流

打开自己仓库的 **Actions** 页面，按页面提示启用工作流，然后选择 **Neworld daily check-in**。如果显示 **Enable workflow**，点击启用。

Fork 的定时工作流默认禁用，需要确认该工作流已启用。参见 [GitHub 启用工作流说明](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows)。

### 4. 手动验证一次

在 **Actions → Neworld daily check-in → Run workflow** 中选择默认分支并运行。打开运行记录，查看 **Sign in and claim today's reward** 步骤的日志。

### 5. 每天自动签到

启用后，工作流每天北京时间 **08:10** 自动执行，周一领取流量，周二至周日领取时长。无需电脑保持开机。

定时配置位于 [`.github/workflows/checkin.yml`](.github/workflows/checkin.yml)：

```yaml
schedule:
  - cron: '10 0 * * *' # UTC 00:10，即北京时间 08:10
```

工作流会将 `USERNAME`、`PASSWORD` Secrets 注入 `NEWORLD_USERNAME`、`NEWORLD_PASSWORD` 环境变量。无界面浏览器组件自动安装并缓存，缓存命中时复用；账号会话不上传或缓存，每次任务重新登录。

GitHub 定时任务可能延迟，且只在默认分支运行；公共仓库连续 60 天无活动时，定时工作流可能被自动禁用，需要重新启用。参见 [GitHub 定时任务说明](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。

如果网站要求人工验证码，或账号需要两步验证码但未提供，任务会失败。本项目仅支持无界面运行，不提供人工验证或验证码绕过功能。
