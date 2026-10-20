"""探测：用真实鼠标点击「公司行业 → 计算机软件」，抓取 industry 编码。"""
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
    time.sleep(3)

    page.get_by_text("公司行业", exact=True).click()
    time.sleep(1.5)

    visible = page.locator(".filter-select-dropdown:visible")
    print("visible dropdowns:", visible.count())
    labels = visible.locator("li").all_inner_texts()
    print("options:", [x.strip() for x in labels][:14])

    # Vue 组件里通常挂着 industry 列表
    vue = page.evaluate(
        """() => {
            const el = document.querySelector('.filter-select-dropdown li');
            let node = el;
            while (node) {
                if (node.__vue__) {
                    const data = node.__vue__.$data || {};
                    const keys = Object.keys(data);
                    const props = Object.keys(node.__vue__.$props || {});
                    return { keys, props, sample: JSON.stringify(data).slice(0, 500) };
                }
                node = node.parentElement;
            }
            return null;
        }"""
    )
    print("vue data:", vue)

    page.locator(".filter-select-dropdown:visible li", has_text="计算机软件").first.click()
    time.sleep(4)
    for body in BODIES[-2:]:
        print("POST:", urllib.parse.unquote(body)[:400])
    print("filter:", page.evaluate("() => document.querySelector('.filter-condition').innerText.replace(/\\n+/g,' | ')")[:250])
