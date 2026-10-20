"""探测：公司行业筛选的真实编码（点击后抓 POST body 里的 industry=）。"""
import time
import urllib.parse

from boss_crawler.session import BossBrowser

BODIES: list[str] = []


def on_request(request):
    if "joblist.json" in request.url and request.post_data:
        BODIES.append(request.post_data)


with BossBrowser(headless=False) as browser:
    page = browser.page()
    page.on("request", on_request)
    browser.goto(page, "https://www.zhipin.com/web/geek/jobs?query=Python&city=101270100")
    time.sleep(4)

    opened = page.evaluate(
        """() => {
            const nodes = Array.from(document.querySelectorAll('.filter-condition .current-select'))
                .filter(el => el.innerText && el.innerText.trim() === '公司行业');
            if (!nodes.length) return false;
            nodes[0].closest('.current-select').click();
            return true;
        }"""
    )
    print("opened industry dropdown:", opened)
    time.sleep(1.5)

    options = page.evaluate(
        """() => Array.from(document.querySelectorAll('.filter-select-dropdown li'))
            .filter(li => li.offsetParent !== null)
            .map(li => ({ txt: li.innerText.trim(), ka: li.getAttribute('ka') || '' }))
            .slice(0, 12)"""
    )
    print("options:", options)

    picked = page.evaluate(
        """() => {
            const li = Array.from(document.querySelectorAll('.filter-select-dropdown li'))
                .find(el => el.innerText.trim() === '计算机软件');
            if (!li) return false;
            li.click();
            return true;
        }"""
    )
    print("picked 计算机软件:", picked)
    time.sleep(4)

    print("\njoblist POST bodies:")
    for body in BODIES[-3:]:
        print("  ", urllib.parse.unquote(body)[:400])
    print("\nfilter text:", page.evaluate("() => document.querySelector('.filter-condition').innerText.replace(/\\n+/g,' | ')")[:300])
