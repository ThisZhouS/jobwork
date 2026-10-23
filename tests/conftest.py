"""测试全局隔离：不要让本机的真实密钥触发外部模型调用。"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_live_model_keys(monkeypatch, tmp_path):
    """把 DeepSeek 密钥来源指向不存在的临时文件，并清掉环境变量。

    Ark 的既有测试会直接读写 ``config.ARK_KEY_FILE``，所以这里只隔离新加的
    DeepSeek——否则测试会拿真实密钥去请求外网。
    """
    from boss_crawler import config

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(config, "DEEPSEEK_KEY_FILE", tmp_path / "no-deepseek-key.txt")
