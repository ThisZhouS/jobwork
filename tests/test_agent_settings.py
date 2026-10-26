"""agent 配置层（config/agents.json）的读写与生效测试。"""
from __future__ import annotations

import json

import pytest

from boss_crawler.agents import settings as agent_settings


@pytest.fixture()
def cfg(tmp_path):
    """每个测试用独立配置文件，绝不碰仓库里的真配置。"""
    return tmp_path / "agents.json"


# ---------------------------------------------------------------- 读写
def test_missing_file_means_defaults(cfg):
    assert agent_settings.load(cfg) == {}
    assert agent_settings.is_enabled("zhihu", cfg) is True


def test_set_config_writes_file(cfg):
    conf = agent_settings.set_config("zhihu", enabled=False, path=cfg)
    assert conf.enabled is False
    assert cfg.exists()
    saved = json.loads(cfg.read_text(encoding="utf-8"))
    assert saved["agents"]["zhihu"]["enabled"] is False


def test_set_config_none_fields_keep_previous(cfg):
    agent_settings.set_config("zhihu", enabled=False, path=cfg)
    conf = agent_settings.set_config("zhihu", options={"depth": 2}, path=cfg)
    assert conf.enabled is False          # enabled 没被 None 覆盖成 True
    assert conf.options == {"depth": 2}


def test_string_false_disables_agent(cfg):
    cfg.write_text(json.dumps({"agents": {"zhihu": {"enabled": "false"}}}),
                   encoding="utf-8")
    assert agent_settings.load(cfg)["zhihu"].enabled is False


def test_corrupt_config_warns_instead_of_silently_resetting(cfg):
    cfg.write_text("{not json", encoding="utf-8")
    with pytest.warns(RuntimeWarning):
        assert agent_settings.load(cfg) == {}


def test_reset_removes_override(cfg):
    agent_settings.set_config("zhihu", enabled=False, path=cfg)
    agent_settings.reset_config("zhihu", cfg)
    assert agent_settings.load(cfg) == {}
    assert agent_settings.is_enabled("zhihu", cfg) is True


def test_save_is_atomic_no_tmp_left(cfg):
    agent_settings.set_config("zhihu", enabled=False, path=cfg)
    leftovers = list(cfg.parent.glob("*.tmp"))
    assert leftovers == []


def test_corrupt_file_does_not_raise(cfg):
    cfg.write_text("{ 这不是 JSON", encoding="utf-8")
    with pytest.warns(RuntimeWarning):
        assert agent_settings.load(cfg) == {}


def test_noop_write_does_not_persist_entry(cfg):
    """写成"和默认一样"时不留条目，避免配置文件堆满无意义的 enabled:true。"""
    agent_settings.set_config("zhihu", enabled=True, path=cfg)
    assert agent_settings.load(cfg) == {}
    assert "zhihu" not in cfg.read_text(encoding="utf-8")


# ---------------------------------------------------------------- 校验
def test_unknown_agent_rejected(cfg):
    with pytest.raises(ValueError):
        agent_settings.set_config("不存在的agent", enabled=False, path=cfg)


def test_unknown_model_spec_rejected(cfg):
    with pytest.raises(ValueError):
        agent_settings.set_config("zhihu", model={"chat": "不存在的模型"}, path=cfg)


def test_unknown_model_kind_rejected(cfg):
    with pytest.raises(ValueError):
        agent_settings.set_config("zhihu", model={"不存在的类型": "chat.doubao"}, path=cfg)


def test_valid_model_accepted(cfg):
    conf = agent_settings.set_config("resume_tailor", model={"chat": "chat.doubao"}, path=cfg)
    assert conf.model == {"chat": "chat.doubao"}


def test_clear_one_model_keeps_options_and_enabled(cfg):
    agent_settings.set_config("resume_tailor", model={"chat": "chat.doubao"},
                              options={"max_questions": 2}, path=cfg)
    conf = agent_settings.set_config("resume_tailor", clear_models=["chat"], path=cfg)
    assert conf.model == {}
    assert conf.options == {"max_questions": 2}
    assert conf.enabled is True
    # 选项还在，所以条目不能被当成"与默认一致"删掉
    assert agent_settings.load(cfg)["resume_tailor"].options == {"max_questions": 2}


def test_set_one_model_keeps_other_capabilities(cfg):
    agent_settings.set_config("resume_tailor", model={"chat": "chat.doubao"}, path=cfg)
    conf = agent_settings.set_config("resume_tailor",
                                     model={"embedding": "embedding.doubao"}, path=cfg)
    assert conf.model == {"chat": "chat.doubao", "embedding": "embedding.doubao"}


def test_clear_unknown_capability_rejected(cfg):
    with pytest.raises(ValueError, match="未知模型能力"):
        agent_settings.set_config("resume_tailor", clear_models=["vision"], path=cfg)


def test_set_and_clear_same_capability_rejected(cfg):
    with pytest.raises(ValueError, match="不能同时"):
        agent_settings.set_config("resume_tailor", model={"chat": "chat.doubao"},
                                  clear_models=["chat"], path=cfg)


# ---------------------------------------------------------------- 生效
def test_effective_merges_code_and_config(cfg):
    agent_settings.set_config("zhihu", enabled=False, path=cfg)
    rows = agent_settings.effective(cfg)
    by_name = {row["name"]: row for row in rows}
    assert by_name["zhihu"]["enabled"] is False
    assert by_name["zhihu"]["configured"] is True
    assert by_name["weibo"]["enabled"] is True
    assert by_name["weibo"]["configured"] is False


def test_effective_rows_carry_module_metadata(cfg):
    rows = {row["name"]: row for row in agent_settings.effective(cfg)}
    assert rows["resume_tailor"]["requires_models"] == ["chat"]
    assert rows["company_score"]["requires_models"] == []
    assert rows["zhihu"]["description"]
    assert "zhihu_search" in rows["zhihu"]["tools"]
    assert rows["zhihu"]["produces"] == ["findings"]


def test_describe_reports_disabled(cfg):
    agent_settings.set_config("weibo", enabled=False, path=cfg)
    payload = agent_settings.describe(cfg)
    assert "weibo" in payload["disabled"]
    assert payload["total"] == len(payload["agents"])


def test_scope_context_injects_model_override(cfg):
    from boss_crawler.agents.base import AgentContext

    agent_settings.set_config("resume_tailor", model={"chat": "chat.doubao"}, path=cfg)
    ctx = AgentContext()
    scoped = agent_settings.scope_context(ctx, "resume_tailor", cfg)
    assert scoped.option("model_overrides") == {"chat": "chat.doubao"}
    # 原上下文不被污染
    assert ctx.option("model_overrides") is None


def test_scope_context_passes_agent_options(cfg):
    from boss_crawler.agents.base import AgentContext

    agent_settings.set_config("resume_tailor", options={"max_questions": 2}, path=cfg)
    scoped = agent_settings.scope_context(AgentContext(), "resume_tailor", cfg)
    assert scoped.option("max_questions") == 2


def test_scope_context_does_not_mutate_shared_nested_options(cfg):
    from boss_crawler.agents.base import AgentContext

    shared: dict = {}
    ctx = AgentContext(options={"agent_options": shared})
    agent_settings.set_config("resume_tailor", options={"max_questions": 2}, path=cfg)
    agent_settings.scope_context(ctx, "resume_tailor", cfg)
    assert shared == {}
    assert ctx.option("max_questions") is None


def test_scope_context_returns_same_when_no_config(cfg):
    from boss_crawler.agents.base import AgentContext

    ctx = AgentContext()
    assert agent_settings.scope_context(ctx, "zhihu", cfg) is ctx


# ---------------------------------------------------------------- 流水线
async def test_pipeline_skips_disabled_agent(monkeypatch):
    from boss_crawler.agents.base import AgentContext, AgentRequest
    from boss_crawler.agents.registry import Pipeline

    monkeypatch.setattr(agent_settings, "is_enabled", lambda name, path=None: name != "zhihu")
    monkeypatch.setattr(agent_settings, "scope_context", lambda ctx, name, path=None: ctx)

    results = await Pipeline(["zhihu", "weibo"]).run(
        AgentRequest(company_name="测试公司"), AgentContext())
    assert [r.agent for r in results] == ["weibo"]
