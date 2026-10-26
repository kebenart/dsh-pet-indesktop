"""桌宠气泡与直播气泡共用的本机字体选择；不下载字体。"""
from functools import lru_cache
from PySide6.QtGui import QFont, QFontDatabase


@lru_cache(maxsize=1)
def bubble_font_family():
    families = set(QFontDatabase.families())
    return next((name for name in ('霞鹜文楷', 'LXGW WenKai', 'Hannotate SC', '手札体-简',
                                  'Yuanti SC', '幼圆', 'Microsoft YaHei', 'PingFang SC') if name in families), '')


def cute_font(size=16):
    font = QFont(bubble_font_family())
    font.setPixelSize(size)
    return font
