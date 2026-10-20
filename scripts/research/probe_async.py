import asyncio
from boss_crawler.providers import run_due_diligence_async

class FakeDB:
    def __init__(self): self.p={};self.r={};self.k={}
    def save_tyc_profile(self,k,p,**kw): self.p[k]=p
    def replace_tyc_relations(self,k,rows): self.r[k]=rows
    def replace_tyc_risks(self,k,rows): self.k[k]=rows
    def commit(self): print("commit ok")

async def main():
    db=FakeDB()
    res = await run_due_diligence_async(
        db, [{"company_key":"baidu","company_name":"百度","legal_name":"北京百度网讯科技有限公司"}],
        token="invalid-probe-token", concurrency=2, retry_times=1, log_level="warn")
    print("retried:", res.stats["request_retried"], "failed:", res.stats["response_failed"])
    print("profiles written:", len(db.p), "| spent:", res.spent)
    print("skipped:", res.skipped)

asyncio.run(main())
