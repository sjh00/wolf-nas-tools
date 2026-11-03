"""媒体文件名识别 Agent"""

from typing import Any

from pydantic import BaseModel, model_validator

import log
from app.agent.prompts.media import MEDIA_BATCH_PROMPT, MEDIA_RECOGNITION_PROMPT
from app.core.settings import settings

# 单次请求携带的文件名上限。
# 批量识别的输出与文件名数量成正比（每个元素十几个字段），一批放太多会让模型在
# 长数组末尾跑偏或输出被截断；配置了更大的值（如 100）时按此上限收敛。
MAX_BATCH_SIZE = 40

# 模型可能用来装批量结果的键名（除 items 外）
_ITEM_KEY_ALIASES = ("results", "result", "data", "list", "item")


def _sanitize_items(raw: list) -> list:
    """非字典元素降级为 None，保持下标与文件名对齐。"""
    return [item if isinstance(item, dict) else None for item in raw]


class MediaResult(BaseModel):
    """媒体识别结果"""

    title_en: str | None = None
    title_cn: str | None = None
    alternate_titles: list = []
    year: int | None = None
    season: int | None = None
    episode: int | None = None
    end_season: int | None = None
    end_episode: int | None = None
    resolution: str | None = None
    source: str | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    language: list = []
    platform: str | None = None
    release_group: str | None = None
    format: str | None = None
    edition: str | None = None
    type: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _unwrap_single_item_list(cls, value: Any) -> Any:
        """容忍模型把单条结果包成数组：`[{...}]` → `{...}`。

        单条识别时提示词要求返回对象，但部分模型（含 MiniMax 系）在结构化输出
        场景会把顶层包成单元素数组，形状不符会让整条识别被判为失败。
        """
        if isinstance(value, list):
            if len(value) == 1:
                return value[0]
            if not value:
                return None
        return value


class BatchResult(BaseModel):
    """批量识别结果

    顶层固定是 `{"items": [...]}`。真实故障里模型把顶层直接返回成裸数组
    `[{...}, {...}]`，与包装对象形状不一致 → Pydantic 校验失败 →
    `structured_chat` 返回 None → 整批识别结果全丢（日志表现为
    "结构化解析失败: Input should be a valid dictionary or instance of BatchResult"）。
    因此这里在进入校验前统一归一化容器形状，并容忍个别元素异常或为 null。
    """

    items: list[MediaResult | None] = []

    @model_validator(mode="before")
    @classmethod
    def _normalize_container(cls, value: Any) -> Any:
        """把裸数组 / 单键别名包装 / 混杂元素统一成 `{"items": [dict | None]}`。

        - 裸数组 `[{...}, ...]` → `{"items": [...]}`
        - `{"results": [...]}` 之类单键别名 → `{"items": [...]}`
        - 非字典元素降级为 None：批量结果靠下标与文件名一一对应，直接丢弃会错位
        """
        if isinstance(value, list):
            value = {"items": value}
        if not isinstance(value, dict):
            return value
        items = value.get("items")
        if items is None:
            alias_keys = [k for k, v in value.items() if k in _ITEM_KEY_ALIASES and isinstance(v, list)]
            # 只接受「唯一的数组别名键」，多个候选时无法判断，保持原样（交给上层判失败重试）
            if len(alias_keys) == 1:
                return {"items": _sanitize_items(value[alias_keys[0]])}
            return value
        return {**value, "items": _sanitize_items(items) if isinstance(items, list) else items}


class MediaRecognizer:
    """媒体文件名识别器 — 基于 LLM"""

    def __init__(self, svc):

        self._svc = svc

    @property
    def ready(self) -> bool:
        return self._svc.ready

    def recognize(self, filename: str) -> MediaResult | None:
        """识别单个文件名"""
        if not self.ready:
            return None
        log.info(f"[MediaRecognizer]识别单个文件名: {filename[:80]}...")
        try:
            result = self._svc.structured_chat(
                messages=[{"role": "user", "content": filename}],
                system_prompt=MEDIA_RECOGNITION_PROMPT,
                response_model=MediaResult,
            )
        except Exception as e:
            # 识别失败（如限流/网络）不应中断整批转移：降级为未识别，由后续逻辑兜底
            log.warn(f"[MediaRecognizer]识别失败，降级为未识别: {e}")
            return None
        if result and (result.title_en or result.title_cn):
            log.info(f"[MediaRecognizer]识别成功: cn={result.title_cn}, en={result.title_en}, type={result.type}")
        else:
            log.warn("[MediaRecognizer]识别失败或返回空结果")
        return result

    def recognize_batch(self, filenames: list[str], batch_size: int = 0) -> list[MediaResult | None]:
        """批量识别文件名，返回与入参等长、按顺序对齐的结果列表"""
        if not self.ready:
            log.warn("[MediaRecognizer]批量识别失败：Provider 未就绪")
            return [None] * len(filenames)

        if batch_size <= 0:
            batch_size = (settings.get("agent") or {}).get("batch_size", MAX_BATCH_SIZE)
        try:
            batch_size = int(batch_size)
        except (TypeError, ValueError):
            batch_size = MAX_BATCH_SIZE
        if batch_size > MAX_BATCH_SIZE:
            log.info(f"[MediaRecognizer]batch_size={batch_size} 超出上限，按 {MAX_BATCH_SIZE} 分批")
            batch_size = MAX_BATCH_SIZE
        batch_size = max(1, batch_size)

        total = len(filenames)
        log.info(f"[MediaRecognizer]批量识别开始: {total} 条, batch_size={batch_size}")
        results: list[MediaResult | None] = []
        success_count = 0
        for i in range(0, total, batch_size):
            chunk = filenames[i : i + batch_size]
            chunk_results = self._recognize_chunk(chunk)
            results.extend(chunk_results)
            success_count += sum(1 for r in chunk_results if r and (r.title_en or r.title_cn))
        log.info(f"[MediaRecognizer]批量识别完成: {success_count}/{total} 成功")
        return results

    def _recognize_chunk(self, filenames: list[str]) -> list[MediaResult | None]:
        """识别一批并在失败时拆分重试，直到单条识别为止。

        早期实现是「一次请求失败 → 整批按单条再跑」。问题是 `structured_chat`
        解析失败时返回 None（不抛异常），调用方拿到的只是空列表，异常分支根本
        不会进入，整批结果就这样被静默丢弃。现在改为：整批失败先拆半重试，
        长数组跑偏/截断往往拆小即可成功，也不必一次性退化成 N 次单条请求。
        """
        if not filenames:
            return []

        # 单条不值得再包一层批量请求：直接走单条结构化识别
        if len(filenames) == 1:
            return [self.recognize(filenames[0])]

        aligned = self._request_batch(filenames)
        if aligned is not None:
            return aligned

        mid = len(filenames) // 2
        log.warn(f"[MediaRecognizer]Batch 拆分重试: {len(filenames)} -> {mid}+{len(filenames) - mid}")
        return self._recognize_chunk(filenames[:mid]) + self._recognize_chunk(filenames[mid:])

    def _request_batch(self, filenames: list[str]) -> list[MediaResult | None] | None:
        """发起一次批量请求；失败返回 None（区别于「成功但结果为空」）"""
        texts = "\n".join(f"[{j}] {f}" for j, f in enumerate(filenames))
        prompt = (
            f"识别以下 {len(filenames)} 个文件名，按原始顺序放进 JSON 对象的 items 数组。\n"
            f'返回格式：{{"items": [ ... ]}}，items 长度必须等于 {len(filenames)}。\n\n{texts}'
        )
        try:
            result = self._svc.structured_chat(
                messages=[{"role": "user", "content": prompt}],
                system_prompt=MEDIA_BATCH_PROMPT,
                response_model=BatchResult,
            )
        except Exception as e:  # noqa: BLE001
            log.warn(f"[MediaRecognizer]Batch 请求失败（{len(filenames)} 条）: {e}")
            return None

        items = list(result.items) if result and result.items else []
        if not items:
            log.warn(f"[MediaRecognizer]Batch 结构化结果为空（{len(filenames)} 条）")
            return None
        if len(items) < len(filenames):
            # 数量缺口过大通常是输出被截断；交给拆分重试，避免大批量条目被判成未识别
            log.warn(f"[MediaRecognizer]Batch 结果数量不足: {len(items)}/{len(filenames)}")
            if len(items) * 2 < len(filenames):
                return None
        return [items[j] if j < len(items) else None for j in range(len(filenames))]
