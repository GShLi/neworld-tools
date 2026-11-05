"""真实浏览器 + 本地路由替身，不访问或操作真实账户。"""
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright
from neworld_checkin import AutomationError, checkin, login


LOGIN = """<input id=email><input id=passwd type=password><input id=totp-code>
<button id=login-dashboard>登入</button><script>
visitorId = 'fixture-fingerprint';
document.querySelector('#login-dashboard').onclick = async () => {
  const r = await fetch('/auth/login', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({email:document.querySelector('#email').value,
      passwd:document.querySelector('#passwd').value,
      code:document.querySelector('#totp-code').value, fingerprint:visitorId})});
  if ((await r.json()).ret === 1) location.href='/user';
};
document.querySelector('#totp-code').oninput = () => {
  if (document.querySelector('#totp-code').value.length === 6)
    setTimeout(() => document.querySelector('#login-dashboard').click(), 30);
};</script>"""

USER = """<input type=radio name=checkin_type value=traffic checked>
<input type=radio name=checkin_type value=time>
<button id=check-in>签到</button><button id=check-in-done style="display:none">已签到</button>
<div id=captcha-dialog style="display:none;position:fixed;inset:0;background:white;z-index:9">
<button id=captcha-submit disabled>确认签到</button></div><script>
async function submit(captcha) {
  const body = new URLSearchParams({checkin_type:document.querySelector('input:checked').value});
  if(captcha) body.set('cf-turnstile-response','fixture-token');
  const r = await fetch('/user/checkin', {method:'POST',body});
  const data = await r.json();
  if(data.ret === 2) {
    document.querySelector('#captcha-dialog').style.display='block';
    setTimeout(() => document.querySelector('#captcha-submit').disabled=false, 30);
  }
  if(data.ret === 1) {
    document.querySelector('#check-in').style.display='none';
    document.querySelector('#check-in-done').style.display='block';
  }
}
document.querySelector('#check-in').onclick=()=>submit(false);
document.querySelector('#captcha-submit').onclick=()=>submit(true);
</script>"""


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.context = self.browser.new_context(service_workers="block")
        self.page = self.context.new_page()
        self.page.set_default_timeout(1500)
        self.authenticated = True
        self.login_result = {"ret":1}
        self.login_requests = []
        self.checkin_requests = []
        self.results = [{"ret": 1, "msg": "ok"}]
        self.abort_checkin = False
        self.context.route("**/*", self.route)

    def tearDown(self):
        self.context.close()

    def route(self, route):
        request = route.request
        path = urlsplit(request.url).path
        if path == "/auth/login" and request.method == "POST":
            self.login_requests.append(request.post_data_json)
            self.authenticated = self.login_result["ret"] == 1
            route.fulfill(json=self.login_result)
        elif path == "/user/checkin":
            self.checkin_requests.append(parse_qs(request.post_data))
            if self.abort_checkin:
                route.abort("connectionreset")
                return
            result = self.results.pop(0)
            route.fulfill(json=result)
        elif path == "/user" and not self.authenticated:
            # Route handlers see only the first request in an HTTP redirect chain.
            # A document navigation keeps the subsequent login request intercepted.
            route.fulfill(content_type="text/html",
                          body="<script>location.replace('/auth/login')</script>")
        elif path in ("/user", "/auth/login"):
            route.fulfill(content_type="text/html", body=LOGIN if path == "/auth/login" else USER)
        else:
            route.abort()

    def test_login(self):
        self.authenticated = False
        login(self.page, {"username":"test@example.com", "password":"test-password", "totp_code":""},
              wait_ms=3000)
        self.assertEqual(self.page.url, "https://neworld.cloud/user")
        self.assertEqual(self.login_requests, [{"email":"test@example.com", "passwd":"test-password",
                                              "code":"", "fingerprint":"fixture-fingerprint"}])
        self.assertEqual(self.checkin_requests, [])

    def test_totp_does_not_submit_twice(self):
        self.authenticated = False
        login(self.page, {"username":"test@example.com", "password":"test-password", "totp_code":"123456"},
              wait_ms=3000)
        self.assertEqual(len(self.login_requests), 1)
        self.assertEqual(self.login_requests[0]["code"], "123456")

    def test_reuse_session(self):
        login(self.page, {"username":"test@example.com", "password":"test-password", "totp_code":""}, wait_ms=3000)
        self.assertEqual(self.login_requests, [])

    def test_login_failure_exits_without_checkin(self):
        self.authenticated = False
        self.login_result = {"ret":0, "msg":"invalid credentials"}
        with self.assertRaises(AutomationError):
            login(self.page, {"username":"test@example.com", "password":"wrong", "totp_code":""},
                  wait_ms=1500)
        self.assertEqual(len(self.login_requests), 1)
        self.assertEqual(self.checkin_requests, [])

    def test_both_rewards(self):
        for reward in ("traffic", "time"):
            self.page.goto("https://neworld.cloud/user")
            self.results = [{"ret":1}]
            with patch("neworld_checkin.choose_reward", return_value=reward):
                self.assertEqual(checkin(self.page), "success")
            self.assertEqual(self.checkin_requests[-1], {"checkin_type":[reward]})

    def test_skip_done_and_dry_run(self):
        self.page.goto("https://neworld.cloud/user")
        self.assertEqual(checkin(self.page, dry_run=True), "dry_run")
        self.page.locator("#check-in-done").evaluate("el => el.style.display='block'")
        self.assertEqual(checkin(self.page), "already_done")
        self.assertEqual(self.checkin_requests, [])

    def test_captcha_reselects_after_midnight(self):
        self.page.goto("https://neworld.cloud/user")
        self.results = [{"ret":2}, {"ret":1}]
        with patch("neworld_checkin.choose_reward", side_effect=["traffic", "time"]):
            self.assertEqual(checkin(self.page, wait_ms=1500), "success")
        self.assertEqual(self.checkin_requests, [
            {"checkin_type":["traffic"]},
            {"checkin_type":["time"], "cf-turnstile-response":["fixture-token"]},
        ])

    def test_rejection_is_not_success_or_retried(self):
        self.page.goto("https://neworld.cloud/user")
        self.results = [{"ret":0, "msg":"denied"}]
        with self.assertRaises(AutomationError):
            checkin(self.page)
        self.assertEqual(len(self.checkin_requests), 1)

    def test_notice_countdowns_and_pages_are_completed_before_checkin(self):
        self.page.goto("https://neworld.cloud/user")
        self.page.evaluate("""() => {
            const modal = document.createElement('div');
            modal.id = 'short-msg-dialog';
            modal.style = 'position:fixed;inset:0;background:white;z-index:1000';
            modal.innerHTML = '<button data-next disabled>下一条</button>' +
                              '<button class="btn-close" disabled>关闭</button>';
            document.body.appendChild(modal);
            window.noticeActions = [];
            const next = modal.querySelector('[data-next]');
            const close = modal.querySelector('.btn-close');
            setTimeout(() => next.disabled = false, 80);
            next.onclick = () => {
                window.noticeActions.push('next');
                next.disabled = true;
                setTimeout(() => close.disabled = false, 80);
            };
            close.onclick = () => {
                window.noticeActions.push('close');
                modal.style.display = 'none';
            };
        }""")
        self.assertEqual(checkin(self.page, wait_ms=1500), "success")
        self.assertEqual(self.page.evaluate("noticeActions"), ["next", "close"])
        self.assertEqual(len(self.checkin_requests), 1)

    def test_notice_timeout_is_specific_and_does_not_submit(self):
        self.page.goto("https://neworld.cloud/user")
        self.page.evaluate("""() => {
            const modal = document.createElement('div');
            modal.id = 'short-msg-dialog';
            modal.style = 'position:fixed;inset:0;background:white;z-index:1000';
            modal.innerHTML = '<button data-next disabled>下一条</button>' +
                              '<button class="btn-close" disabled>关闭</button>';
            document.body.appendChild(modal);
        }""")
        with self.assertRaisesRegex(AutomationError, "公告"):
            checkin(self.page, wait_ms=150)
        self.assertEqual(self.checkin_requests, [])

    def test_missing_click_handler_reports_no_request(self):
        self.page.goto("https://neworld.cloud/user")
        self.page.locator('#check-in').evaluate('el => el.onclick = null')
        with self.assertRaisesRegex(AutomationError, "未观察到签到请求"):
            checkin(self.page, wait_ms=150)
        self.assertEqual(self.checkin_requests, [])

    def test_request_failure_reports_uncertain_result_and_no_retry(self):
        self.page.goto("https://neworld.cloud/user")
        self.abort_checkin = True
        with self.assertRaisesRegex(AutomationError, "已发出签到请求"):
            checkin(self.page, wait_ms=150)
        self.assertEqual(len(self.checkin_requests), 1)


if __name__ == "__main__":
    unittest.main()
