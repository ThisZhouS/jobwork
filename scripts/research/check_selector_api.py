from scrapling.parser import Selector

HTML = (
    '<div class="job-card-box"><a href="/job_detail/abc.html">'
    '<span class="job-name">Python开发</span>'
    '<span class="job-salary">15-25K</span>'
    '<span class="company-name">示例科技</span>'
    '<span class="job-area">成都</span>'
    '<ul class="tag-list"><li>3-5年</li><li>本科</li></ul></a></div>'
)

page = Selector(HTML)
card = page.css(".job-card-box").first
print("card:", card is not None)
print("href:", card.css("a").first.attrib.get("href"))
print("name:", card.css(".job-name").first.get_all_text())
print("tags:", [t.get_all_text().strip() for t in card.css(".tag-list li")])
print("empty first:", card.css(".nope").first)
