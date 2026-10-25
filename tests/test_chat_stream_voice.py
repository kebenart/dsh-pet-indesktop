"""流式边收边念（``pet/chat_reply_voice.py`` 的增量通道）行为守卫。

覆盖七件事：

1. 纯函数：只切"已经成句"的部分、半句留在尾巴、代码围栏整段不念；
2. 增量按句开口：第一个句号一到就念，不等整段回复；
3. 整轮只念一次：``finished`` 只补尾巴，绝不把整段重念一遍；
4. 非流式后端（没来过增量）仍按整段念——与加流式之前逐字一致；
5. 新一轮回复覆盖上一轮：旧缓冲与旧队列一起丢掉；
6. 开关关着时零动作；
7. 长无标点文本有上限，不会等到结尾才开口。

用注入的假通道 + 假时钟，不建真 ``VoiceChimeService``、不跑 Qt 事件循环。
"""

from __future__ import annotations

from pet.chat_reply_voice import (
    STREAM_MAX_BUFFER,
    ChatReplyReader,
    take_stream_sentences,
)


class FakeChannel:
    def __init__(self, *, idle: bool = True) -> None:
        self.idle = idle
        self.heard: list[str] = []

    def speak(self, sentence: str) -> bool:
        assert self.idle, "通道忙时不该被塞新句子（必须先问 channel_idle）"
        self.heard.append(sentence)
        self.idle = False
        return True

    def channel_idle(self) -> bool:
        return self.idle

    def finish(self) -> None:
        self.idle = True


class FakeScheduler:
    def __init__(self) -> None:
        self.pending: list = []

    def __call__(self, ms: int, fn) -> None:
        self.pending.append(fn)

    def run_pending(self) -> None:
        pending, self.pending = self.pending, []
        for fn in pending:
            fn()


def _reader(channel: FakeChannel, *, enabled: bool = True):
    state = {"enabled": enabled}
    scheduler = FakeScheduler()
    reader = ChatReplyReader(
        speak=channel.speak,
        channel_idle=channel.channel_idle,
        enabled=lambda: state["enabled"],
        schedule=scheduler,
    )
    return reader, scheduler


# ------------------------------------------------------------------ 纯函数
def test_take_stream_sentences_only_returns_finished_sentences():
    assert take_stream_sentences("你好呀。今天也不错") == (["你好呀。"], "今天也不错")
    assert take_stream_sentences("还没说完") == ([], "还没说完")
    assert take_stream_sentences("") == ([], "")


def test_take_stream_sentences_skips_fenced_code():
    buffer = "下面这段代码：\n```python\nprint(1)\n```\n就这些。"
    sentences, remainder = take_stream_sentences(buffer)
    assert "print" not in "".join(sentences)
    assert "下面这段代码" in sentences[0] or "下面这段代码" == sentences[0].strip()
    assert "就这些。" in sentences
    assert remainder == ""


def test_take_stream_sentences_swallows_an_open_fence():
    """半截围栏也要按"在代码里"处理：不把围栏里的符号念出来。"""
    sentences, remainder = take_stream_sentences("看这里：\n```python\nfor i in range")
    assert sentences == ["看这里："], "围栏前的引言要念"
    assert remainder == "", "围栏里的内容不许留到下一轮当正文"


def test_take_stream_sentences_caps_a_runaway_buffer():
    long_line = "这是一段没有句号的文字" * 20
    sentences, remainder = take_stream_sentences(long_line)
    assert sentences, "超过上限必须硬切开口，不能一直等句号"
    assert len(remainder) <= STREAM_MAX_BUFFER


# ------------------------------------------------------------------ 增量
def test_delta_speaks_at_the_first_sentence_boundary():
    channel = FakeChannel()
    reader, _ = _reader(channel)
    reader.on_delta("r1", "第一句。第二")
    assert channel.heard == ["第一句。"], "句号一到就该开口"
    assert reader.pending == 0, "半句不许入队"

    channel.finish()
    reader.on_delta("r1", "句也到了。")
    assert channel.heard == ["第一句。", "第二句也到了。"]


def test_finished_flushes_the_tail_exactly_once():
    channel = FakeChannel()
    reader, _ = _reader(channel)
    reader.on_delta("r1", "开头一句。尾巴没有句号")
    assert channel.heard == ["开头一句。"]

    channel.finish()
    reader.on_finished("开头一句。尾巴没有句号")
    assert channel.heard == ["开头一句。", "尾巴没有句号"], "尾巴只补一次"


def test_finished_never_replays_the_whole_reply():
    channel = FakeChannel()
    reader, _ = _reader(channel)
    channel.finish()
    reader.on_delta("r1", "甲。乙。")
    assert channel.heard == ["甲。"]  # 乙在队列里等通道空出来
    channel.finish()
    reader.on_finished("甲。乙。")
    scheduler = FakeScheduler()
    # finished 之后通道空闲：队列继续滴灌，但整段不许再进来一遍
    reader._schedule_impl = scheduler
    channel.finish()
    reader.pump()
    assert channel.heard == ["甲。", "乙。"]
    assert reader.pending == 0


# ------------------------------------------------------------------ 非流式
def test_finished_without_deltas_reads_the_whole_reply():
    channel = FakeChannel()
    reader, _ = _reader(channel)
    reader.on_finished("甲。乙。")
    assert channel.heard == ["甲。"]
    channel.finish()
    reader.pump()
    assert channel.heard == ["甲。", "乙。"]


# ------------------------------------------------------------------ 新一轮 / 开关
def test_new_request_id_drops_the_previous_stream():
    channel = FakeChannel()
    reader, _ = _reader(channel)
    reader.on_delta("r1", "旧的句子。旧的尾巴")
    channel.finish()
    reader.on_delta("r2", "新的句子。")
    assert "旧的尾巴" not in channel.heard
    assert channel.heard[-1] == "新的句子。"


def test_disabled_reader_does_nothing():
    channel = FakeChannel()
    reader, _ = _reader(channel, enabled=False)
    reader.on_delta("r1", "这句不该被念。")
    reader.finished = None
    reader.on_finished("这句也不该被念。")
    assert channel.heard == []


# ------------------------------------------------------------------ 订阅
def test_subscribe_hooks_both_finished_and_delta(monkeypatch):
    """订阅面必须同时挂上 finish 与 delta：只挂一个就是"要么整段念、要么永不开口"。"""
    calls: list[str] = []

    class FakeService:
        @classmethod
        def register_global_finished(cls, cb):
            calls.append("finished")

        @classmethod
        def unregister_global_finished(cls, cb):
            calls.append("unfinished")

        @classmethod
        def register_global_delta(cls, cb):
            calls.append("delta")

        @classmethod
        def unregister_global_delta(cls, cb):
            calls.append("undelta")

    channel = FakeChannel()
    reader, _ = _reader(channel)
    monkeypatch.setattr(reader, "_chat_service", staticmethod(lambda: FakeService))
    assert reader.start() is True
    assert calls == ["finished", "delta"]
    reader.stop()
    assert calls[-2:] == ["unfinished", "undelta"]
