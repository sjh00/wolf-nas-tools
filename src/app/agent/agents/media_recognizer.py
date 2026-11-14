"""媒体文件名识别 Agent"""

import re
import time
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

# 模型可能用来标注条目序号的键名
_INDEX_KEYS = ("index", "idx", "i", "no")

# 片名分隔符：模型把多条片名拼进一个字段时用它们连接
_TITLE_SPLIT_RE = re.compile(r"\s*[/／|｜]\s*")

# 分隔后段数达到该值才判定为「串味」。取 3 而不是 2，避免把
# 合法片名（如 Face/Off、Spider-Man/蜘蛛侠 这类双语片名）误切。
_MULTI_TITLE_THRESHOLD = 3

# 调用异常（限流/欠费/网络）连续达到该次数后进入冷却期。
# 冷却期内不再发起请求，直接由调用方回落到本地规则解析器 —— 否则一批几百条
# 文件会逐条撞同一个 429，既刷屏又拖慢整个入库流程。
_FAILURE_THRESHOLD = 3

# 冷却时长（秒）。额度类故障通常以小时计，但这里不宜设太长：
# 偶发网络抖动也会计数，冷却结束后重新试探一次即可自愈。
_COOLDOWN_SECONDS = 120.0


def _normalize_for_match(text: str) -> str:
    """归一化用于「片名是否出现在文件名里」的比对。"""
    return re.sub(r"[\W_]+", "", str(text or "").lower())


def _pick_primary_title(value: str | None, filename: str) -> str | None:
    """从可能被拼接的片名字段里挑出属于当前文件名的那一个。

    模型有时会把多个作品的片名塞进同一个 title_cn（形如
    `cn=作品A / 作品B / 作品C`），下游拿去查 TMDB 必然失败，且会把整条记录
    识别成错误作品。这里在片名段数明显过多时按「与文件名的字符重合度」挑一段，
    重合度全为 0（例如中文片名配英文文件名）时保留第一段。
    """
    if not value:
        return value
    segments = [seg.strip() for seg in _TITLE_SPLIT_RE.split(str(value)) if seg.strip()]
    if len(segments) < _MULTI_TITLE_THRESHOLD:
        return value
    haystack = _normalize_for_match(filename)
    best = segments[0]
    best_score = -1
    for seg in segments:
        needle = _normalize_for_match(seg)
        score = 0
        if needle and haystack:
            # 用片段的最长可匹配子串长度衡量重合度，避免整名不匹配时全为 0
            for size in range(len(needle), 1, -1):
                if any(needle[i : i + size] in haystack for i in range(len(needle) - size + 1)):
                    score = size
                    break
        if score > best_score:
            best, best_score = seg, score
    log.warn(f"[MediaRecognizer]片名疑似拼接，已归一：{value[:60]} -> {best[:40]}")
    return best


def _sanitize_items(raw: list) -> list:
    """非字典元素降级为 None；带序号的条目按序号归位，并按序号补齐空位。

    批量结果靠下标与文件名一一对应。模型偶尔会漏掉某个条目，若照顺序硬对应，
    后面所有结果都会错位（A 的标题被记到 B 上）。提示词要求回传 index，
    这里据此把它们放回原位；缺失的位置留 None，由上层单条补识别。
    全部缺 index 时才退回原顺序。
    """
    cleaned: list = [item if isinstance(item, dict) else None for item in raw]
    if not cleaned:
        return []
    indexed: list[tuple[int, Any]] = []
    for item in cleaned:
        if item is None:
            indexed.append((-1, None))
            continue
        raw_index = next((item.get(k) for k in _INDEX_KEYS if k in item), None)
        try:
            idx = int(raw_index)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return cleaned
        if idx < 0:
            return cleaned
        indexed.append((idx, item))
    if any(idx < 0 for idx, _ in indexed):
        return cleaned
    placed: list[Any] = [None] * (max(idx for idx, _ in indexed) + 1)
    for idx, item in indexed:
        placed[idx] = item
    return placed


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
    # 模型自评的置信度（0-1）。低于阈值的结果不采纳，避免把猜测当成识别结果。
    confidence: float | None = None

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
        - 带 index 的条目按 index 重排，避免漏条导致整体错位
        - 非字典元素降级为 None，保持下标对齐
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
        self._failure_streak = 0
        self._cooldown_until = 0.0

    @property
    def ready(self) -> bool:
        """是否可发起识别请求。

        除了 provider 配置就绪，还要看是否处于故障冷却期：连续调用异常
        （限流/欠费/网络）后短时间内不再尝试，交由调用方回落到本地规则解析。
        """
        if self._cooldown_until and time.monotonic() < self._cooldown_until:
            return False
        return self._svc.ready

    @property
    def in_cooldown(self) -> bool:
        """是否处于故障冷却期（供调用方解释回落原因）。"""
        return self._cooldown_until > 0 and time.monotonic() < self._cooldown_until

    def _note_failure(self, error: object) -> None:
        """记录一次调用异常；连续达到阈值后进入冷却期。"""
        self._failure_streak += 1
        if self._failure_streak < _FAILURE_THRESHOLD:
            return
        self._cooldown_until = time.monotonic() + _COOLDOWN_SECONDS
        self._failure_streak = 0
        log.warn(
            f"[MediaRecognizer]LLM 连续 {_FAILURE_THRESHOLD} 次调用失败，"
            f"暂停 {int(_COOLDOWN_SECONDS)}s 并改用本地规则解析: {error}"
        )

    def _note_success(self) -> None:
        if self._failure_streak or self._cooldown_until:
            self._failure_streak = 0
            self._cooldown_until = 0.0

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
                # 抽取类任务用 0 温度：降低同一条文件名两次识别结果不一致、以及
                # 模型顺手「引用」上文其它片名（串味）的概率
                temperature=0.0,
            )
        except Exception as e:
            # 识别失败（如限流/网络）不应中断整批转移：降级为未识别，由后续逻辑兜底
            self._note_failure(e)
            log.warn(f"[MediaRecognizer]识别失败，降级为未识别: {e}")
            return None
        if result:
            result = self._sanitize(result, filename)
        if result and (result.title_en or result.title_cn):
            self._note_success()
            log.info(f"[MediaRecognizer]识别成功: cn={result.title_cn}, en={result.title_en}, type={result.type}")
        else:
            log.warn("[MediaRecognizer]识别失败或返回空结果")
        return result

    @staticmethod
    def _sanitize(result: MediaResult, filename: str) -> MediaResult:
        """清洗单条识别结果：拆开被拼接的多片名、去掉重复的中英同名。

        模型在批量/长上下文场景下容易把多条作品名合并进一个字段
        （形如 `cn=作品A / 作品B / 作品C`），这类结果拿去查 TMDB 必然错配，
        必须在进入下游前收敛。
        """
        result.title_cn = _pick_primary_title(result.title_cn, filename)
        result.title_en = _pick_primary_title(result.title_en, filename)
        if result.title_cn and result.title_en:
            if _normalize_for_match(result.title_cn) == _normalize_for_match(result.title_en):
                # 中英同名字段填了同一串（多为模型把片名同时写进两个字段）
                result.title_en = None
        return result

    def recognize_batch(self, filenames: list[str], batch_size: int = 0) -> list[MediaResult | None]:
        """批量识别文件名，返回与入参等长、按顺序对齐的结果列表"""
        if not filenames:
            return []
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
        # 同一条文件名在批量里可能重复出现（目录同步重叠、同片多规格同名等）。
        # 直接去重后再展开，能省下重复的 LLM 调用与费用。
        unique_names: list[str] = []
        index_of: dict[str, int] = {}
        for name in filenames:
            if name not in index_of:
                index_of[name] = len(unique_names)
                unique_names.append(name)

        log.info(f"[MediaRecognizer]批量识别开始: {total} 条（去重后 {len(unique_names)} 条）, batch_size={batch_size}")
        unique_results: list[MediaResult | None] = []
        for i in range(0, len(unique_names), batch_size):
            chunk = unique_names[i : i + batch_size]
            unique_results.extend(self._recognize_chunk(chunk))

        success_count = sum(1 for r in unique_results if r and (r.title_en or r.title_cn))
        log.info(f"[MediaRecognizer]批量识别完成: {success_count}/{len(unique_names)} 成功（原始 {total} 条）")
        return [unique_results[index_of[name]] for name in filenames]

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
            return self._fill_gaps(filenames, aligned)

        mid = len(filenames) // 2
        log.warn(f"[MediaRecognizer]Batch 拆分重试: {len(filenames)} -> {mid}+{len(filenames) - mid}")
        return self._recognize_chunk(filenames[:mid]) + self._recognize_chunk(filenames[mid:])

    def _fill_gaps(self, filenames: list[str], aligned: list[MediaResult | None]) -> list[MediaResult | None]:
        """批量结果里缺失的条目按单条补识别，避免整批成功却被少数缺口拖累。

        缺口通常来自模型漏条或返回 null；比起整批拆半重试，只补缺口更省调用。
        """
        missing = [i for i, item in enumerate(aligned) if item is None]
        if not missing:
            return aligned
        log.info(f"[MediaRecognizer]Batch 结果缺失 {len(missing)}/{len(filenames)} 条，按单条补齐")
        result = list(aligned)
        for idx in missing:
            result[idx] = self.recognize(filenames[idx])
        return result

    def _request_batch(self, filenames: list[str]) -> list[MediaResult | None] | None:
        """发起一次批量请求；失败返回 None（区别于「成功但结果为空」）"""
        texts = "\n".join(f"[{j}] {f}" for j, f in enumerate(filenames))
        prompt = (
            f"识别以下 {len(filenames)} 个文件名，按原始顺序放进 JSON 对象的 items 数组。\n"
            f'返回格式：{{"items": [ ... ]}}，每个元素必须带 "index" 且等于文件名前的序号 [n]，'
            f"items 长度必须等于 {len(filenames)}。\n\n{texts}"
        )
        try:
            result = self._svc.structured_chat(
                messages=[{"role": "user", "content": prompt}],
                system_prompt=MEDIA_BATCH_PROMPT,
                response_model=BatchResult,
                temperature=0.0,
                # 提示词已逐字段列出结构，再追加完整 JSON Schema 只是重复消耗输入 token
                append_schema=False,
            )
        except Exception as e:  # noqa: BLE001
            self._note_failure(e)
            log.warn(f"[MediaRecognizer]Batch 请求失败（{len(filenames)} 条）: {e}")
            return None

        items = list(result.items) if result and result.items else []
        if not items:
            log.warn(f"[MediaRecognizer]Batch 结构化结果为空（{len(filenames)} 条）")
            return None
        self._note_success()
        if len(items) < len(filenames):
            # 数量缺口过大通常是输出被截断；交给拆分重试，避免大批量条目被判成未识别
            log.warn(f"[MediaRecognizer]Batch 结果数量不足: {len(items)}/{len(filenames)}")
            if len(items) * 2 < len(filenames):
                return None
        aligned: list[MediaResult | None] = []
        for j in range(len(filenames)):
            item = items[j] if j < len(items) else None
            aligned.append(self._sanitize(item, filenames[j]) if item else None)
        return aligned
