#!/usr/bin/env python3
"""新界自动登录与签到：北京时间周一流量，其余日期时长。"""

import argparse
from contextlib import contextmanager
from datetime import date, datetime
import hashlib
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

BASE_URL = "https://neworld.cloud"
ROOT = Path(__file__).resolve().parent
BEIJING = ZoneInfo("Asia/Shanghai")
LABELS = {"traffic": "流量", "time": "时长"}


class AutomationError(Exception):
    pass


def choose_reward(now=None):
    now = now or datetime.now(BEIJING)
    if now.tzinfo is None:
        raise ValueError("日期必须包含时区")
    return "traffic" if now.astimezone(BEIJING).weekday() == 0 else "time"


def response_state(data):
    if not isinstance(data, dict) or type(data.get("ret")) is not int:
        raise AutomationError("签到接口返回了无法识别的数据，停止操作。")
    if data["ret"] == 1:
        return "success"
    if data["ret"] == 2:
        return "captcha"
    raise AutomationError("网站拒绝签到，请检查账号状态或今天是否已签到。")


def log(message):
    print(f"[{datetime.now(BEIJING):%Y-%m-%d %H:%M:%S} +08:00] {message}", flush=True)


def load_credentials():
    credentials = {name: os.environ.get(f"NEWORLD_{name.upper()}", "")
                   for name in ("username", "password", "totp_code")}
    if not credentials["username"] or not credentials["password"]:
        raise AutomationError("请设置 NEWORLD_USERNAME 和 NEWORLD_PASSWORD 环境变量。")
    return credentials


def profile_path(state_dir, username):
    account_id = hashlib.sha256(username.encode("utf-8")).hexdigest()
    return state_dir / f"browser-{account_id}"


@contextmanager
def profile_lock(state_dir):
    # macOS/Linux: OS releases this lock even when the process crashes.
    import fcntl

    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_dir.chmod(0o700)
    with (state_dir / "run.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AutomationError("已有脚本使用此登录状态目录，跳过本次运行。") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def is_site_url(url, path):
    parsed = urlsplit(url)
    return (parsed.scheme == "https" and parsed.netloc == "neworld.cloud"
            and parsed.path.rstrip("/") == path)


def is_user_page(page):
    return (is_site_url(page.url, "/user")
            and page.locator("#check-in-done, #check-in").count() > 0)


def read_response(response):
    if response.status != 200:
        raise AutomationError(f"网站返回 HTTP {response.status}，停止操作。")
    try:
        return response.json()
    except (ValueError, UnicodeError) as exc:
        raise AutomationError("网站未返回 JSON，可能是登录已过期或触发了验证。") from exc


def login(page, credentials, *, wait_ms):
    page.goto(BASE_URL + "/user", wait_until="domcontentloaded")
    page.wait_for_function(
        "() => document.querySelector('#email, #check-in, #check-in-done')",
        timeout=wait_ms,
    )
    if is_user_page(page):
        log("已复用登录状态。")
        return
    if not is_site_url(page.url, "/auth/login"):
        raise AutomationError("当前页面不是本站登录页，停止填写凭据。")

    email, password = credentials["username"], credentials["password"]
    if not email or not password:
        raise AutomationError("请设置 NEWORLD_USERNAME 和 NEWORLD_PASSWORD 环境变量。")
    page.locator("#email").fill(email)
    page.locator("#passwd").fill(password)
    # The real page uses this variable when sending /auth/login.
    page.wait_for_function("() => typeof visitorId !== 'undefined' && !!visitorId",
                           timeout=wait_ms)
    with page.expect_response(
        lambda r: is_site_url(r.url, "/auth/login") and r.request.method == "POST",
        timeout=wait_ms,
    ) as pending:
        if credentials["totp_code"]:
            # The site's input handler submits six-digit codes automatically.
            if not (credentials["totp_code"].isascii()
                    and credentials["totp_code"].isdigit()
                    and len(credentials["totp_code"]) == 6):
                raise AutomationError("两步验证码必须为 6 位数字。")
            page.locator("#totp-code").fill(credentials["totp_code"])
        else:
            page.locator("#login-dashboard").click()
    result = read_response(pending.value)
    if not isinstance(result, dict) or str(result.get("ret")) != "1":
        raise AutomationError("登录失败，请检查邮箱、密码和两步验证设置。")

    page.wait_for_url(lambda url: is_site_url(url, "/user"), timeout=wait_ms)
    page.locator("#check-in").wait_for(state="attached", timeout=wait_ms)
    if not is_user_page(page):
        raise AutomationError("登录后没有找到签到页面。")
    log("登录成功。")


def submit_checkin(page, button):
    # Recalculate immediately before EVERY submission (including after a CAPTCHA).
    reward = choose_reward()
    radio = page.locator(f'input[name="checkin_type"][value="{reward}"]')
    if radio.count() != 1:
        raise AutomationError(f"页面没有提供领取{LABELS[reward]}选项，停止操作。")
    # A CAPTCHA dialog can cover the radio controls when the date changes.
    # The site's submission handler reads the checked DOM value directly.
    radio.evaluate("""element => {
        element.checked = true;
        element.dispatchEvent(new Event('change', {bubbles: true}));
    }""")
    if not radio.is_checked():
        raise AutomationError("未能选中目标领取类型，停止操作。")
    log(f"按北京时间选择领取{LABELS[reward]}。")
    with page.expect_response(
        lambda r: is_site_url(r.url, "/user/checkin") and r.request.method == "POST",
        timeout=30000,
    ) as pending:
        page.locator(button).click()
    return response_state(read_response(pending.value)), reward


def checkin(page, *, dry_run=False, wait_ms=180000):
    if not is_user_page(page):
        raise AutomationError("未登录或页面结构已变化，停止签到。")
    if page.locator("#check-in-done").is_visible():
        log("今天已签到，跳过；已领取的类型不能在当天更换。")
        return "already_done"
    if dry_run:
        log(f"预览：今天应领取{LABELS[choose_reward()]}，未提交签到。")
        return "dry_run"
    if not page.locator("#check-in").is_visible():
        raise AutomationError("签到按钮不可用，停止操作。")

    state, reward = submit_checkin(page, "#check-in")
    if state == "captcha":
        log("网站要求安全验证，等待自动验证结果；本脚本不支持人工验证。")
        page.wait_for_function("""() => {
            const dialog = document.querySelector('#captcha-dialog');
            const button = document.querySelector('#captcha-submit');
            return dialog && dialog.getClientRects().length && button && !button.disabled;
        }""", timeout=wait_ms)
        state, reward = submit_checkin(page, "#captcha-submit")
    if state != "success":
        raise AutomationError("验证后仍被要求再次验证，停止本次运行。")
    log(f"签到成功：领取{LABELS[reward]}。")
    return "success"


def positive_seconds(value):
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("必须是正整数秒数") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("必须是正整数秒数")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=ROOT / ".state")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--login-only", action="store_true", help="只登录并保存状态")
    mode.add_argument("--dry-run", action="store_true", help="登录并检查状态，不提交签到")
    mode.add_argument("--plan", action="store_true", help="离线查看当天规则，不打开浏览器")
    parser.add_argument("--date", type=date.fromisoformat, help="仅供 --plan 使用，格式 YYYY-MM-DD")
    parser.add_argument("--wait-seconds", type=positive_seconds, default=180,
                        help="等待登录/自动验证的上限，默认 180 秒")
    args = parser.parse_args(argv)
    if args.date and not args.plan:
        parser.error("--date 只能与 --plan 一起使用，不能伪造实际签到日期")
    if args.plan:
        now = datetime.combine(args.date, datetime.min.time(), BEIJING) if args.date else datetime.now(BEIJING)
        print(f"{now:%Y-%m-%d} Asia/Shanghai：领取{LABELS[choose_reward(now)]} ({choose_reward(now)})")
        return 0
    try:
        from playwright.sync_api import Error as PlaywrightError, sync_playwright
    except ImportError:
        print("请先安装依赖：python -m pip install -r requirements.txt", file=sys.stderr)
        return 1
    try:
        credentials = load_credentials()
        with profile_lock(args.state_dir), sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(profile_path(args.state_dir, credentials["username"])), headless=True,
                timezone_id="Asia/Shanghai", locale="zh-CN",
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.set_default_timeout(30000)
                login(page, credentials, wait_ms=args.wait_seconds * 1000)
                if args.login_only:
                    log("登录状态已保存在本地。")
                else:
                    checkin(page, dry_run=args.dry_run, wait_ms=args.wait_seconds * 1000)
            finally:
                context.close()
        return 0
    except AutomationError as exc:
        print(f"失败：{exc}", file=sys.stderr)
        return 1
    except PlaywrightError:
        # Playwright call logs can include filled passwords. Do not print them.
        print("浏览器操作失败或等待超时。请检查网络、浏览器安装及页面验证；"
              "若已提交签到但结果不明，请先检查网站状态。本脚本仅支持无界面运行。",
              file=sys.stderr)
        return 1
    except OSError:
        print("无法访问浏览器或状态目录，请检查路径和权限。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("已取消。", file=sys.stderr)
        raise SystemExit(130)
