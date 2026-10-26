"""只管理本次启动的采集进程，登录Cookie从系统凭据库读取。"""
import json
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, QProcess, Signal


COOKIE_REF = 'livestream/douyin_cookie'


class Collector(QObject):
    status = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.process = None
        self.config_path = None
        self.attempted = False

    def start(self):
        if self.attempted or not self.settings.collector_program:
            return
        self.attempted = True
        program = Path(self.settings.collector_program).expanduser()
        if not program.is_absolute() or not program.is_file():
            self.status.emit('采集程序不存在，请在设置填写完整路径')
            return
        from ..chat.models import SecretStore
        cookie = SecretStore().get(COOKIE_REF)
        endpoint = urlsplit(self.settings.endpoint)
        config = {'port': str(endpoint.port), 'websocket': {'path': endpoint.path.rstrip('/') or '/ws'},
                  'log': {'level': 'warn'}, 'cookie': {'use_stored': bool(cookie), 'douyin': cookie}}
        # NamedTemporaryFile 默认0600；参数/日志中不出现Cookie，退出后删掉这一份临时副本。
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix='.json', prefix='pet-live-', delete=False) as f:
                self.config_path = Path(f.name)
                json.dump(config, f, ensure_ascii=False)
        except OSError:
            self.status.emit('无法准备采集配置，请检查临时目录')
            return
        self.process = QProcess(self)
        self.process.setProgram(str(program))
        self.process.setArguments(['--config', str(self.config_path)])
        self.process.readyReadStandardOutput.connect(lambda: self.process.readAllStandardOutput())
        self.process.readyReadStandardError.connect(lambda: self.process.readAllStandardError())
        self.process.errorOccurred.connect(self._error)
        self.process.finished.connect(lambda *_: self._remove_config())
        self.process.start()
        self.status.emit('正在启动本机采集程序' + ('（使用已保存的抖音登录态）' if cookie else '（未配置抖音登录态，礼物可能不完整）'))

    def _error(self, error):
        self.status.emit('采集程序运行失败，请检查可执行文件')
        if error == QProcess.ProcessError.FailedToStart:
            self._remove_config()

    def _remove_config(self):
        if self.config_path:
            self.config_path.unlink(missing_ok=True)
            self.config_path = None

    def shutdown(self):
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.terminate()
            if not self.process.waitForFinished(1500):
                self.process.kill()
                self.process.waitForFinished(1000)
        self._remove_config()
