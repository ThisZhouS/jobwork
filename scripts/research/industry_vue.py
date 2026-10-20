"""探测：从 Vue 3 组件实例上取 industry 列表（label -> code）。"""
import json
import time

from boss_crawler.session import BossBrowser

with BossBrowser(headless=False) as browser:
    page = browser.page()
    browser.goto(page, "https://www.zhipin.com/web/geek/jobs?query=Python&city=101270100")
    time.sleep(3)

    page.get_by_text("公司行业", exact=True).click()
    time.sleep(1.5)

    data = page.evaluate(
        """() => {
            const out = { found: false };
            const all = Array.from(document.querySelectorAll('*'));
            for (const el of all) {
                const comp = el.__vueParentComponent;
                if (!comp) continue;
                const props = comp.props || {};
                const text = JSON.stringify(props);
                if (text && text.includes('计算机软件')) {
                    out.found = true;
                    out.propsKeys = Object.keys(props);
                    out.sample = text.slice(0, 1500);
                    break;
                }
            }
            return out;
        }"""
    )
    print(json.dumps(data, ensure_ascii=False)[:2000])

    # 兜底：全局搜索页面里含 code 的行业数组
    data2 = page.evaluate(
        """() => {
            const res = [];
            const walk = (obj, depth) => {
                if (!obj || depth > 3 || typeof obj !== 'object') return;
                if (Array.isArray(obj)) {
                    const probe = JSON.stringify(obj).slice(0, 300);
                    if (probe.includes('计算机软件')) res.push(probe);
                    obj.slice(0, 5).forEach(x => walk(x, depth + 1));
                } else {
                    for (const k of Object.keys(obj)) {
                        if (/industry/i.test(k)) {
                            res.push(k + '=' + JSON.stringify(obj[k]).slice(0, 300));
                        }
                        walk(obj[k], depth + 1);
                    }
                }
            };
            const app = document.querySelector('#app');
            if (app && app.__vue_app__) walk(app.__vue_app__._instance?.proxy || {}, 0);
            return res.slice(0, 5);
        }"""
    )
    print(json.dumps(data2, ensure_ascii=False)[:1500])
