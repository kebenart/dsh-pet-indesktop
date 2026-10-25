"""气泡朗读（``pet/bubble_voice.py``）的行为守卫。

覆盖七件事：

1. 开关关着时 ``submit`` 纯早退（不建队列、不碰通道）；
2. 太短 / 纯标点的碎片不念；
3. 去重窗口：同一段文本重复上屏只念一次，过了窗口再念；
4. 气泡口径上限：最多 3 句 / 120 字；
5. 滴灌：通道忙时排队、空闲时送下一句，第一句之后不把整段一次倒进去；
6. 汇合点开关：``show_text(voice=False)`` 不提交（调用方自己念过），
   默认 ``voice=None`` 才提交；
7. 已经自带朗读的链路（歌词 / 报时 / 节日 / 抽签 / 待办 / 点击台词）在源码里
   显式带 ``voice=False``——它们与气泡朗读共用同一条通道，漏一处就是念两遍。
"""

from __future__ import annotations

from pathlib import Path

from pet import bubble_voice
from pet.bubble_voice import (
    MAX_SENTENCES,
    BubbleVoice,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


class FakeSpeaker:
    """假通道：``idle`` 手动翻，``heard`` 记录被念出来的句子。"""

    def __init__(self, *, idle: bool = True) -> None:
        self.idle = idle
        self.heard: list[str] = []

    def speak(self, sentence: str) -> bool:
        assert self.idle, "通道忙的时候不该被塞新句子（必须先问 channel_idle）"
        self.heard.append(sentence)
        self.idle = False
        return True

    def channel_idle(self) -> bool:
        return self.idle

    def finish(self) -> None:
        """模拟一句播完（通道空出来）。"""
        self.idle = True


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeScheduler:
    """假定时器：记下待跑的 pump 回调，测试用 ``run_pending`` 推进。"""

    def __init__(self) -> None:
        self.pending: list = []

    def __call__(self, ms: int, fn) -> None:
        self.pending.append(fn)

    def run_pending(self) -> None:
        pending, self.pending = self.pending, []
        for fn in pending:
            fn()


def _reader(speaker: FakeSpeaker, *, enabled: bool = True, clock=None, scheduler=None):
    state = {"enabled": enabled}
    voice = BubbleVoice(
        speak=speaker.speak,
        channel_idle=speaker.channel_idle,
        enabled=lambda: state["enabled"],
        schedule=scheduler or FakeScheduler(),
        clock=clock or FakeClock(),
    )
    return voice, state


# ------------------------------------------------------------------ 开关 / 碎片
def test_disabled_submit_is_a_no_op():
    speaker = FakeSpeaker()
    voice, _state = _reader(speaker, enabled=False)
    assert voice.submit("主人早上好，今天也要加油哦") is False
    assert speaker.heard == []
    assert voice.pending == 0


def test_too_short_or_punctuation_only_is_skipped():
    speaker = FakeSpeaker()
    voice, _state = _reader(speaker)
    assert voice.submit("嗯") is False          # 1 个字：不值得合成
    assert voice.submit("。。。") is False      # 纯标点：切句层也会丢
    assert speaker.heard == []


def test_plain_sentence_is_spoken_once():
    speaker = FakeSpeaker()
    voice, _state = _reader(speaker)
    assert voice.submit("主人，喝口水吧。") is True
    assert speaker.heard == ["主人，喝口水吧。"]


# ------------------------------------------------------------------ 去重
def test_same_text_within_window_is_deduped():
    speaker = FakeSpeaker()
    clock = FakeClock()
    voice, _state = _reader(speaker, clock=clock)
    assert voice.submit("让我看看…") is True
    speaker.finish()
    assert voice.submit("让我看看…") is False
    assert speaker.heard == ["让我看看…"]


def test_same_text_after_window_is_spoken_again():
    speaker = FakeSpeaker()
    clock = FakeClock()
    voice, _state = _reader(speaker, clock=clock)
    assert voice.submit("让我看看…") is True
    clock.advance(bubble_voice.DEDUPE_SECONDS + 1.0)
    speaker.finish()
    assert voice.submit("让我看看…") is True
    assert speaker.heard == ["让我看看…", "让我看看…"]
    assert voice.recent_count == 1  # 过期条目被清掉，表不会一直长


# ------------------------------------------------------------------ 上限
def test_long_text_is_capped_to_three_sentences():
    speaker = FakeSpeaker()
    voice, _state = _reader(speaker)
    text = "第一句话在这里。第二句话也在这里。第三句话仍然在。第四句话不该被念到。"
    assert voice.submit(text) is True
    assert voice.pending == MAX_SENTENCES - 1  # 第一句已送出，队列里剩两句上限
    assert "第四句" not in "".join(speaker.heard)


def test_markdown_is_cleaned_before_speaking():
    speaker = FakeSpeaker()
    voice, _state = _reader(speaker)
    assert voice.submit("## 余额\n\n**还有** 12.5 元") is True
    assert "#" not in speaker.heard[0]
    assert "**" not in speaker.heard[0]


# ------------------------------------------------------------------ 滴灌
def test_busy_channel_defers_and_then_drips():
    speaker = FakeSpeaker()
    speaker.idle = False                       # 通道正忙（报时刚起播）
    scheduler = FakeScheduler()
    voice, _state = _reader(speaker, scheduler=scheduler)
    assert voice.submit("第一句。第二句。") is True
    assert speaker.heard == []                 # 忙：一句都不许塞
    assert scheduler.pending, "通道忙时必须排一次重试"

    speaker.finish()
    scheduler.run_pending()
    assert speaker.heard == ["第一句。"]        # 先送第一句，不是整段
    assert voice.pending == 1
    assert scheduler.pending

    speaker.finish()
    scheduler.run_pending()
    assert speaker.heard == ["第一句。", "第二句。"]


# ------------------------------------------------------------------ 汇合点（Qt）
def _bubble():
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QApplication

    from pet.speech_bubble import PetSpeechBubble

    QApplication.instance() or QApplication([])
    bubble = PetSpeechBubble()
    return bubble, QRect(0, 0, 120, 120)


def test_show_text_reports_unless_muted():
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QApplication

    from pet.speech_bubble import PetSpeechBubble

    QApplication.instance() or QApplication([])
    bubble = PetSpeechBubble()
    rect = QRect(0, 0, 120, 120)
    speaker = FakeSpeaker()
    voice, _state = _reader(speaker)
    bubble_voice.install(voice)
    try:
        bubble.show_text("默认要念的一句。", rect)
        assert speaker.heard == ["默认要念的一句。"]

        speaker.finish()
        with bubble_voice.muted():
            bubble.show_text("这条自己念过了。", rect)
        assert speaker.heard == ["默认要念的一句。"], "让位区间里不许再提交"
        assert bubble_voice.muted_now() is False, "退出区间必须复位"

        speaker.finish()
        bubble.show_text("正文在这里。", rect, subtitle="标题在这里")
        # 副标题（标题）先念，正文在后——"标题 + 正文"结构里标题是这句的主语。
        assert speaker.heard[-1] == "标题在这里。"
    finally:
        bubble_voice.uninstall(voice)
        bubble.deleteLater()


def test_nested_mute_unwinds_to_the_right_depth():
    speaker = FakeSpeaker()
    voice, _state = _reader(speaker)
    bubble_voice.install(voice)
    try:
        with bubble_voice.muted():
            with bubble_voice.muted():
                assert bubble_voice.report("里层也要静音。") is False
            assert bubble_voice.report("外层仍在静音。") is False
        assert bubble_voice.report("出来后恢复。") is True
        assert speaker.heard == ["出来后恢复。"]
    finally:
        bubble_voice.uninstall(voice)


def test_report_without_router_is_a_no_op():
    bubble_voice.uninstall()
    assert bubble_voice.report("没有任何朗读器时装着的那条。") is False


def test_install_and_uninstall_detach_the_router():
    speaker = FakeSpeaker()
    voice, _state = _reader(speaker)
    bubble_voice.install(voice)
    try:
        assert bubble_voice.active_router() is voice
        assert bubble_voice.report("装上了就会念。") is True
    finally:
        bubble_voice.uninstall(voice)
    assert bubble_voice.active_router() is None
    assert bubble_voice.report("卸下之后不再念。") is False


# ------------------------------------------------------------------ 接线（设置 → 壳）
def test_settings_save_keeps_the_channel_and_installs_the_router(tmp_path):
    """设置页保存 → 壳留住音频通道并装上汇合点；漏接 ``_chime_wanted`` 就是死开关。"""
    from PySide6.QtWidgets import QApplication

    from pet.app import AppShell
    from pet.config import Config
    from pet.modern_settings_dialog import ModernSettingsDialog, SettingRow

    qapp = QApplication.instance() or QApplication([])
    cfg_root = tmp_path / "appdata"
    dialog = ModernSettingsDialog(Config(cfg_root), include_ai=False)
    try:
        row = dialog.findChild(SettingRow, "settingRow_bubble_voice_enabled")
        assert row is not None, "「语音」组必须有「气泡朗读」一行"
        assert row.control.isChecked() is False, "出厂默认必须是关"
        assert "免打扰" in row.control.accessibleDescription(), "说明必须写明免打扰期间不出声"
        row.control.setChecked(True)
        assert dialog._write_config() is True
    finally:
        dialog.deleteLater()

    shell = AppShell(qapp, Config(cfg_root), enable_chat=False)
    try:
        assert shell.config.get("bubble_voice_enabled") is True
        assert shell._chime_wanted() is True, "开了气泡朗读就必须留住音频通道"
        assert bubble_voice.active_router() is not None, "开着的壳必须把朗读器装到汇合点上"
        shell.config.set("bubble_voice_enabled", False)
        shell._sync_chime_service()
        assert shell._chime_wanted() is False, "关掉后不再无谓常驻一条通道"
        assert bubble_voice.active_router() is None, "关掉后必须摘掉汇合点"
    finally:
        shell._release_bubble_voice()
        bubble_voice.uninstall()


# ------------------------------------------------------------------ 防念两遍
def test_self_spoken_paths_declare_mute():
    """已经自带朗读的链路必须显式让位，否则同一句会被念两遍。"""
    expectations = {
        "pet/voice/chime_service.py": "bubble_voice.muted()",
        "pet/music/lyric_controller.py": "bubble_voice.muted()",
        "pet/festival/service.py": "bubble_voice.muted()",
        "pet/divination/service.py": "bubble_voice.muted()",
        "pet/todo/reminder.py": "bubble_voice.muted()",
        "pet/window_alerts.py": "bubble_voice.muted()",
    }
    for relative, needle in expectations.items():
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert needle in source, f"{relative} 缺了让位标记：{needle}"
