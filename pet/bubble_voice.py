# -*- coding: utf-8 -*-
"""气泡朗读：把**屏幕上正在显示的气泡文本**送进进程内唯一音频通道。

与「助手回复朗读」（``chat_reply_voice``）的分工：

* 那个只接 ``ChatService.register_global_finished``（聊天窗回答）；
* 本模块接的是**气泡本身**——自言自语、看看屏幕、余额、天气、网络、更新提示、
  审批/提问、主动识屏、文件解读……全都经 ``PetSpeechBubble.show_text`` 展示，
  所以朗读只在那一处报一次，不按功能逐个接线（否则每加一个功能就得再补一次，
  漏一处就是"某个功能只有字没有声"）。

设计取舍：

* **复用 ``ChatReplyReader`` 的滴灌链路**：音频通道待播槽深度 1 且新覆盖旧，
  一次把三句 ``speak()`` 进去只剩最后一句；本模块继承它的队列/忙等/世代作废，
  只在 ``_split`` 里加了"气泡口径"的上限（最多 3 句 / 120 字）。
  **新气泡覆盖旧队列**是刻意的：旧气泡在屏上已经被盖掉了，接着念它等于念一段
  用户看不到的内容。
* **默认关**（``bubble_voice_enabled``）：每个气泡一次合成 = 一次网络往返 +
  一次计费，主动打扰型能力必须由用户自己打开；关着时 ``report()`` 是纯早退，
  不建对象、不建队列。
* **去重**：粘滞气泡恢复、免打扰汇总重挂、同一句连发（"让我看看…"）都会让同
  一段文本在几秒内再次上屏；窗口内重复不再念第二遍。
* **跳过**由调用方声明：已经自己念过的链路（报时 / 节日 / 抽签 / 待办 / 点击
  台词 / 歌词）在上游包一层 :func:`muted`，气泡照显示但不再交给朗读——绝不再念
  第二遍。用上下文而不是给 ``show_text`` 加 kwarg 的理由见 ``_mute_depth``。
* 模块顶层不 import Qt：``ChatReplyReader`` 的 ``schedule`` 是注入的，测试可以
  给假时钟；只有默认实现（``QTimer.singleShot``）才惰性取 Qt。
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Callable

from .chat_reply_voice import ChatReplyReader, clean_for_speech

logger = logging.getLogger(__name__)

#: 少于这么多个可见字符不念（"嗯。"、"…"这类碎片没有朗读价值，还白花一次合成）。
MIN_CHARS = 2

#: 一个气泡最多念几句 / 多少字：气泡是短句，识屏结果与审批文案可能很长。
MAX_SENTENCES = 3
MAX_CHARS = 120

#: 同一段文本在这个窗口内重复上屏不再念（粘滞恢复 / 汇总重挂 / 连发同句）。
DEDUPE_SECONDS = 8.0

#: 通道忙时的重试间隔（与助手回复朗读同口径：250ms，追上就续，不空转）。
PUMP_INTERVAL_MS = 250


def _speakable(text: str) -> bool:
    """这段文本值不值得念：够长，且至少有一个字母/数字/汉字。"""
    if len(text) < MIN_CHARS:
        return False
    return any(ch.isalnum() for ch in text)


def _cap_sentences(sentences: list[str]) -> list[str]:
    """气泡口径的句子上限：最多 :data:`MAX_SENTENCES` 句、总长 :data:`MAX_CHARS`。"""
    out: list[str] = []
    total = 0
    for sentence in sentences:
        if len(out) >= MAX_SENTENCES:
            break
        if total + len(sentence) > MAX_CHARS and out:
            break
        if len(sentence) > MAX_CHARS:
            sentence = sentence[:MAX_CHARS]
        out.append(sentence)
        total += len(sentence)
    return out


class BubbleVoice(ChatReplyReader):
    """气泡朗读器（进程级单例；由 ``PetApp`` 懒建/释放）。

    依赖全部注入，测试不建 Qt 通道也能验证"该不该念 / 念几句 / 忙等 / 去重"：

    * ``speak(sentence) -> bool``：送一句进通道（实现走 ``VoiceChimeService.speak``）；
    * ``channel_idle() -> bool``：通道是否真空闲（``VoiceChimeService.channel_idle``）；
    * ``enabled() -> bool``：每次现读配置（热开关，不必重建对象）；
    * ``schedule(ms, fn)``：延迟回调，默认 ``QTimer.singleShot``，测试注入假时钟；
    * ``clock()``：去重窗口用的时钟，测试注入假时钟。
    """

    def __init__(
        self,
        *,
        speak: Callable[[str], bool],
        channel_idle: Callable[[], bool],
        enabled: Callable[[], bool],
        schedule: Callable[[int, Callable[[], None]], None] | None = None,
        interval_ms: int = PUMP_INTERVAL_MS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(
            speak=speak,
            channel_idle=channel_idle,
            enabled=enabled,
            schedule=schedule,
            interval_ms=interval_ms,
            max_chars=MAX_CHARS,
        )
        self._clock = clock
        self._recent: dict[str, float] = {}

    # ------------------------------------------------------------ 对外
    def submit(self, text: str, *, subtitle: str = "", owner=None) -> bool:
        """提交一条**刚上屏**的气泡文本；返回是否真的送进了朗读队列。

        ``owner`` 只用于日志定位（哪只宠物/哪条链路），不参与判据——音色目前是
        全局的（与报时共用一套后端参数）。
        """
        if not self.enabled:
            return False
        raw = str(text or "").strip()
        if not raw:
            return False
        subtitle = str(subtitle or "").strip()
        # 副标题是"标题 + 正文"结构里的标题（歌词的歌名、提醒的标题），先念标题更自然。
        cleaned = clean_for_speech(f"{subtitle}。{raw}" if subtitle else raw)
        if not _speakable(cleaned):
            return False
        now = self._clock()
        self._expire_recent(now)
        if cleaned in self._recent:
            logger.debug("气泡朗读去重（%.0fs 内重发）：%s", DEDUPE_SECONDS, cleaned[:20])
            return False
        self._recent[cleaned] = now
        self.feed(cleaned)
        logger.info("气泡朗读：%s（来源 %s）", cleaned[:24], owner if owner is not None else "-")
        return True

    @property
    def recent_count(self) -> int:
        """去重表里还有多少条（测试与探针用）。"""
        return len(self._recent)

    # ------------------------------------------------------------ 内部
    def _split(self, text: str) -> list[str]:
        """继承链路的切句 + 气泡口径上限（最多 3 句 / 120 字）。"""
        return _cap_sentences(super()._split(text))

    def _expire_recent(self, now: float) -> None:
        if not self._recent:
            return
        cutoff = now - DEDUPE_SECONDS
        stale = [key for key, at in self._recent.items() if at < cutoff]
        for key in stale:
            self._recent.pop(key, None)


# ---------------------------------------------------------------- 汇合点
# 气泡控件（``speech_bubble.PetSpeechBubble.show_text``）只认这两个函数：
# 装/卸由 ``PetApp`` 管（懒建、随配置保存同步），控件侧不需要知道 app 的存在。
_router: BubbleVoice | None = None

#: 让位深度：>0 时 ``report()`` 什么都不做。用上下文管理器而不是给每个
#: ``show_bubble`` / ``show_text`` 加一个 kwarg——那要改三层宿主面（legacy 窗口、
#: overlay 壳、sprite 跟随器）以及所有测试替身，漏一层就是"某个链路照样念两遍"。
#: 全部调用都在 GUI 线程且同步完成，故一个进程级计数器足够精确。
_mute_depth = 0


@contextmanager
def muted():
    """在这段调用里让位：气泡照show，但不交给朗读（调用方自己已经念过）。

    例（报时）：语音由 ``_fire`` 念，气泡只是同屏展示；不包这一层就会出现
    "一次报时两声、且文本口径不同"（气泡是阿拉伯数字，语音是中文数字）。
    """
    global _mute_depth
    _mute_depth += 1
    try:
        yield
    finally:
        _mute_depth -= 1


def muted_now() -> bool:
    """当前是否处于让位区间（测试与探针用）。"""
    return _mute_depth > 0


def install(router: BubbleVoice) -> None:
    """装上当前生效的朗读器（app 懒建时调用；重复装 = 覆盖）。"""
    global _router
    if _router is not None and _router is not router:
        _router.stop()
    _router = router


def uninstall(router: BubbleVoice | None = None) -> None:
    """卸下朗读器；传了 ``router`` 就只卸它自己（避免卸掉后来装上的那只）。"""
    global _router
    if router is not None and _router is not router:
        return
    current = _router
    _router = None
    if current is not None:
        current.stop()


def active_router() -> BubbleVoice | None:
    return _router


def report(text: str, *, subtitle: str = "", owner=None) -> bool:
    """气泡上屏时调用：没有朗读器（默认关 / 语音模块停用）或正在让位 = 什么都不做。"""
    if _mute_depth:
        return False
    router = _router
    if router is None:
        return False
    try:
        return router.submit(text, subtitle=subtitle, owner=owner)
    except Exception:
        logger.exception("气泡朗读提交失败，已跳过这一条")
        return False
