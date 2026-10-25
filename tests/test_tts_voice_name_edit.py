# -*- coding: utf-8 -*-
"""音色名自由输入（豆包）：设置页可敲任意音色名，而不是只能从写死的清单里挑。

五件事：

1. 声明：``TtsField.editable`` 默认关；只有需要自由输入的字段（豆包的音色）打开；
2. 控件：豆包音色行是 ``TtsVoiceNameEdit``（文本框 + 常用下拉），不是纯选择器；
3. 落盘：敲进去的名字原样写进配置（不被清单吸附、不被截断）；
4. 生效：``provider.values()`` → ``plan`` 拿到同一个名字，``flavor`` 带上它
   （换音色必须换缓存键，否则「换了音色却还是旧声音」）；
5. 兜底：清空 = 回到默认音色（``clean`` 的既有语义），不是写一个空音色。
"""

from __future__ import annotations

from pathlib import Path

from pet import tts
from pet.config import Config
from pet.voice.chime_settings import TtsVoiceNameEdit, VoiceChimeSettingsPage

CUSTOM = "zh_female_my_custom_uranus_bigtts"


def _qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _page(tmp_path) -> VoiceChimeSettingsPage:
    _qapp()
    return VoiceChimeSettingsPage(Config(base=tmp_path))


def _doubao_voice(page) -> TtsVoiceNameEdit:
    widget = page._field_widgets["voice_chime_doubao_speaker"]
    assert isinstance(widget, TtsVoiceNameEdit), "豆包音色必须是可输入的文本框"
    return widget


# ------------------------------------------------------------------ 声明
def test_only_free_input_fields_are_editable():
    doubao = tts.get("doubao")
    edge = tts.get("edge")
    assert doubao is not None and edge is not None
    doubao_voice = next(spec for spec in doubao.fields if spec.name == "voice")
    edge_voice = next(spec for spec in edge.fields if spec.name == "voice")
    assert doubao_voice.editable is True, "豆包音色要能自由输入"
    assert edge_voice.editable is False, "其它后端的清单是稳定的，不必开自由输入"


def test_field_contract_defaults_to_not_editable():
    spec = tts.TtsField("voice", "voice_chime_test_voice", "音色", "一句话")
    assert spec.editable is False


# ------------------------------------------------------------------ 控件
def test_doubao_voice_row_is_a_free_text_box(tmp_path):
    page = _page(tmp_path)
    try:
        widget = _doubao_voice(page)
        # 读接口与 ModernSelect 同形（text()），设置页的读写路径不需要为它加分支
        assert widget.text() == "zh_female_peiqi_uranus_bigtts"
        widget.setText(CUSTOM)
        assert widget.text() == CUSTOM
    finally:
        page.deleteLater()


def test_common_voice_menu_fills_the_box(tmp_path):
    page = _page(tmp_path)
    try:
        widget = _doubao_voice(page)
        actions = widget.pick_button.menu().actions()
        assert actions, "「常用」下拉必须有内置音色"
        actions[1].trigger()
        assert widget.text() == actions[1].data(), "选常用音色也要落在同一个文本框里"
        # 菜单只出现中文名，不把音色 id 摆上界面（2026-10-13 机主口径）
        assert actions[1].data() not in actions[1].text()
    finally:
        page.deleteLater()


# ------------------------------------------------------------------ 落盘 + 生效
def test_typed_voice_is_saved_verbatim_and_drives_plan_and_cache_key(tmp_path):
    page = _page(tmp_path)
    try:
        page.backend_select.setCurrentData("doubao")
        _doubao_voice(page).setText(CUSTOM)
        page.apply_to_config()
        cfg = page.config
        assert cfg.get("voice_chime_doubao_speaker") == CUSTOM, "自定义音色必须原样落盘"
        cfg.save()  # 与设置窗关闭时的 _write_config 同一条落盘路径
    finally:
        page.deleteLater()

    # 重新读盘（模拟重启）：值还在
    cfg = Config(base=tmp_path)
    assert cfg.get("voice_chime_doubao_speaker") == CUSTOM

    provider = tts.get("doubao")
    values = provider.values(cfg)
    assert values["voice"] == CUSTOM
    assert provider.plan(values)["speaker"] == CUSTOM, "合成必须真的用这个名字"
    assert CUSTOM in provider.flavor(values), "换音色必须换缓存键（否则永远播旧声音）"


def test_emptied_voice_falls_back_to_default(tmp_path):
    page = _page(tmp_path)
    try:
        _doubao_voice(page).setText("   ")
        page.apply_to_config()
        cfg = page.config
        # 空串落盘 = 没写；provider 读的时候回到默认音色，不是空音色
        assert provider_default() == tts.get("doubao").values(cfg)["voice"]
    finally:
        page.deleteLater()


def provider_default() -> str:
    return next(
        str(spec.default) for spec in tts.get("doubao").fields if spec.name == "voice"
    )
