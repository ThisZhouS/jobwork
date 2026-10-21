"""模型 API 层：声明式、可替换、可关停、可观察。

```python
from boss_crawler.agents.models import ModelBox, describe_models

box = ModelBox(ctx)
text = await box.text_of([{"role": "user", "content": "写一句概述"}])
if text is None:            # 拿不到就降级，不抛
    ...
```

与 ``agents/tools/`` 的分工：

* **工具**——怎么把数据抓下来（含全部反爬）；
* **模型**——怎么把数据变成文字/向量（含供应商差异、密钥、失败降级）。

两者都不被 agent 直接依赖具体实现：agent 只声明"我要 chat 能力"。
"""
from __future__ import annotations

from .base import (
    KINDS,
    WRITABLE_FIELDS,
    ModelBox,
    ModelResult,
    ModelSpec,
    ModelUnavailable,
    apply_overrides,
    describe_models,
    describe_spec,
    get_model,
    load_errors,
    model_catalog,
    model_names,
    models_for,
    overrides_document,
    overrides_path,
    register_model,
    reset_models,
    reset_override,
    save_override,
    unregister_model,
)

__all__ = [
    "KINDS",
    "WRITABLE_FIELDS",
    "ModelBox",
    "ModelResult",
    "ModelSpec",
    "ModelUnavailable",
    "apply_overrides",
    "describe_models",
    "describe_spec",
    "get_model",
    "load_errors",
    "model_catalog",
    "model_names",
    "models_for",
    "overrides_document",
    "overrides_path",
    "register_model",
    "reset_models",
    "reset_override",
    "save_override",
    "unregister_model",
]
