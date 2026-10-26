"""测试全局隔离：不要让本机的真实密钥触发外部模型调用。"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_live_model_keys(monkeypatch, tmp_path):
    """隔离所有模型密钥：测试绝不能拿本机真实密钥去请求外网。

    需要验证密钥读取逻辑的测试应显式 monkeypatch 回来。
    """
    from boss_crawler import config

    for env in ("DEEPSEEK_API_KEY", "ARK_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr(config, "DEEPSEEK_KEY_FILE", tmp_path / "no-deepseek-key.txt")
    monkeypatch.setattr(config, "ARK_KEY_FILE", tmp_path / "no-ark-key.txt")
