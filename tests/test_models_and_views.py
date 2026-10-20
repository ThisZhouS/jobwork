"""模型 API 层、劳务派遣字段、前端视图契约的离线测试。

模型测试**不发真实请求**：只用假规格与假 key 验证"能不能用/怎么降级"。
"""
from __future__ import annotations

import json

import pytest

from boss_crawler.agents import AgentContext, AgentRequest
from boss_crawler.agents.models import (
    ModelBox,
    ModelSpec,
    ModelUnavailable,
    apply_overrides,
    describe_models,
    get_model,
    model_names,
    models_for,
    register_model,
    unregister_model,
)
from boss_crawler.agents.scoring.company_score import detect_labor_dispatch
from boss_crawler.agents.scoring.framework import ScoreContext


# ---------------------------------------------------------------- 规格
def test_spec_rejects_bad_kind():
    with pytest.raises(ValueError):
        ModelSpec(name="x", kind="不存在的类型", provider="ark", model_id="m")


def test_spec_rejects_empty_name():
    with pytest.raises(ValueError):
        ModelSpec(name="", kind="chat", provider="ark", model_id="m")


def test_describe_never_exposes_key(monkeypatch):
    monkeypatch.setenv("TEST_MODEL_KEY", "super-secret-value")
    spec = ModelSpec(name="t.key", kind="chat", provider="ark", model_id="m",
                     api_key_env="TEST_MODEL_KEY")
    described = spec.describe()
    assert described["has_key"] is True
    assert "secret" not in json.dumps(described)
    assert "super-secret-value" not in json.dumps(described)


def test_builtin_embedding_is_available_and_chat_is_disabled():
    names = model_names()
    assert "embedding.doubao" in names
    assert "chat.doubao" in names
    assert get_model("embedding.doubao").dimension == 2048
    # 对话模型默认停用（当前密钥只有嵌入权限）
    assert get_model("chat.doubao").enabled is False
    assert models_for("chat") == []


def test_duplicate_spec_rejected():
    with pytest.raises(ValueError):
        register_model(ModelSpec(name="embedding.doubao", kind="embedding",
                                 provider="ark", model_id="dup"))


def test_unknown_spec_raises():
    with pytest.raises(KeyError):
        get_model("不存在")


def test_catalog_shape():
    payload = describe_models()
    assert set(payload["by_kind"]) == {"chat", "embedding", "rerank"}
    for spec in payload["models"]:
        assert spec["name"] and spec["kind"]
        assert "has_key" in spec


# ---------------------------------------------------------------- 覆盖配置
def test_apply_overrides_from_file(tmp_path):
    path = tmp_path / "models.json"
    path.write_text(json.dumps({
        "overrides": {"chat.doubao": {"enabled": True, "model_id": "改过的模型"}},
        "extra": [{"name": "chat.test", "kind": "chat", "provider": "ark",
                   "model_id": "t", "enabled": True}],
    }), encoding="utf-8")
    try:
        result = apply_overrides(path)
        assert result["applied"] == 1
        assert result["added"] == 1
        assert get_model("chat.doubao").model_id == "改过的模型"
        assert get_model("chat.doubao").enabled is True
        assert "chat.test" in model_names()
    finally:
        unregister_model("chat.test")
        # 还原内置状态，避免污染其他测试
        apply_overrides(_reset_file(tmp_path))


def _reset_file(tmp_path):
    path = tmp_path / "reset.json"
    path.write_text(json.dumps({
        "overrides": {"chat.doubao": {"enabled": False}}}), encoding="utf-8")
    return path


# ---------------------------------------------------------------- 调用器
def test_box_global_switch_off():
    box = ModelBox(AgentContext(options={"models_enabled": False}))
    assert box.available("embedding") is False


async def test_box_returns_failure_not_exception_when_off():
    box = ModelBox(AgentContext(options={"models_enabled": False}))
    result = await box.embed(["文本"])
    assert result.ok is False
    assert result.code == "models_off"
    assert result.usable is False


async def test_box_no_spec_for_chat_kind():
    box = ModelBox(AgentContext())
    assert box.available("chat") is False
    result = await box.chat([{"role": "user", "content": "hi"}])
    assert result.ok is False
    assert result.code == "no_spec"


async def test_box_dry_run_does_not_call():
    box = ModelBox(AgentContext(options={"model_dry_run": True}))
    result = await box.embed(["文本"])
    assert result.code == "dry_run"
    assert result.vectors == []


async def test_text_of_returns_none_when_unavailable():
    box = ModelBox(AgentContext())
    assert await box.text_of([{"role": "user", "content": "写一句"}]) is None


def test_box_override_to_unknown_spec_raises():
    box = ModelBox(AgentContext(options={"model_overrides": {"chat": "不存在"}}))
    with pytest.raises(KeyError):
        box.resolve("chat")


async def test_unavailable_model_is_recorded():
    """模型不可用要留痕（可观察），但不抛给业务。"""
    recorded: list[dict] = []
    box = ModelBox(AgentContext(options={"models_enabled": False}),
                   log=recorded.append)
    await box.embed(["x"])
    assert recorded and recorded[0]["code"] == "models_off"


async def test_chat_call_returns_failure_result_not_exception():
    box = ModelBox(AgentContext())
    result = await box.chat([{"role": "user", "content": "hi"}])
    assert result.ok is False
    assert result.code in ("no_spec", "no_key", "unsupported")


# ---------------------------------------------------------------- agent 声明
def test_agent_declares_model_capabilities():
    from boss_crawler.agents.registry import catalog, get

    for row in catalog():
        agent = get(row["name"])()
        assert isinstance(agent.requires_models, tuple)
        if agent.requires_models:
            # 声明了就要能用 require_model 检查（不可用则 MissingInput）
            assert all(kind in ("chat", "embedding", "rerank")
                       for kind in agent.requires_models)


def test_resume_agent_needs_chat_but_degrades():
    from boss_crawler.agents.registry import get

    agent = get("resume_tailor")()
    assert "chat" in agent.requires_models
    ctx = AgentContext()
    # 对话模型不可用时应抛 MissingInput，由 execute 转成"输入不足"
    from boss_crawler.agents.base import MissingInput

    with pytest.raises(MissingInput):
        ctx.require_model("chat")


# ---------------------------------------------------------------- 劳务派遣
def _ctx(name: str, scope: str = "") -> ScoreContext:
    ctx = ScoreContext.build(AgentRequest(company_name=name))
    ctx.profile = {"name": name, "business_scope": scope}
    return ctx


@pytest.mark.parametrize("name,scope,expected", [
    ("成都某劳务派遣有限公司", "劳务派遣服务", True),
    ("某科技", "人力资源外包服务", True),
    ("某科技", "软件开发；技术服务", False),
    ("某科技", "软件开发；劳务咨询", None),        # 单个弱词 -> 不敢下结论
    ("某科技", "", None),                          # 无信息 -> 不知道
])
def test_labor_dispatch_detection(name, scope, expected):
    info = detect_labor_dispatch(_ctx(name, scope))
    assert info["is_labor_dispatch"] is expected
    assert info["labor_dispatch_reason"]


async def test_labor_dispatch_lands_in_agent_meta():
    from boss_crawler.agents.registry import get

    ctx = AgentContext()
    request = AgentRequest(company_name="某劳务派遣公司",
                           metrics={"profile": {"business_scope": "劳务派遣"}})
    result = await get("company_score")().execute(request, ctx)
    assert result.meta["is_labor_dispatch"] is True
    assert any("劳务派遣" in advice for advice in result.score.advice)


async def test_labor_dispatch_absent_is_none_not_false():
    from boss_crawler.agents.registry import get

    result = await get("company_score")().execute(
        AgentRequest(company_name="某公司"), AgentContext())
    assert result.meta["is_labor_dispatch"] is None


# ---------------------------------------------------------------- 前端视图
def test_filter_options_mirror_boss_filters():
    from boss_crawler.app.views import filter_options

    payload = filter_options()
    fields = {item["field"] for item in payload["fields"]}
    assert {"salary", "experience", "degree", "industry"} <= fields
    for item in payload["fields"]:
        assert item["label"] and item["options"]
        for option in item["options"]:
            assert option["value"] and option["label"] and option["code"]
    assert any(item["field"] == "query" and item["required"] for item in payload["text"])
    assert payload["toggles"]


def test_filter_options_include_all_boss_platforms():
    from boss_crawler.app.views import filter_options

    platforms = next(item for item in filter_options()["toggles"]
                     if item["field"] == "platforms")
    assert set(platforms["options"]) == {"tianyancha", "tianyan_ai", "zhihu",
                                         "weibo", "tieba"}
