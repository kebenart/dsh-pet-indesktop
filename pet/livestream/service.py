"""Qt 主线程装配直播采集、独立聊天会话、音频与表演。"""
from dataclasses import replace
import hashlib
import json
import logging
import re
import sqlite3
import time
import uuid

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Qt
from PySide6.QtWebSockets import QWebSocket
from PySide6.QtNetwork import QNetworkRequest, QAbstractSocket

from .ledger import Ledger
from .rules import LiveSettings, Inbox, build_messages, clean_reply, music_tracks, text, gift_fields, music_mapping

log = logging.getLogger(__name__)


class LiveService(QObject):
    balance_result = Signal(int, str, object)

    def __init__(self, shell):
        super().__init__()
        from ..chat.service import ChatService
        from .presentation import LiveBubble, LiveBoard, AudienceBoard
        self.shell = shell
        self.settings = LiveSettings.from_dict(shell.config.get('livestream'))
        self.inbox = Inbox(self.settings)
        self.ledger = Ledger(shell.config.dir / 'livestream.sqlite3')
        self.chat = ChatService(parent=self, publish_global=False)
        self.chat.finished.connect(self._finished)
        self.chat.error.connect(self._failed)
        self.chat.usage.connect(self._usage)
        self.socket = QWebSocket(parent=self)
        self.socket.setMaxAllowedIncomingMessageSize(1024 * 1024)
        self.socket.textMessageReceived.connect(self.receive)
        self.socket.connected.connect(lambda: self._status('采集服务已连接，等待直播消息'))
        self.socket.disconnected.connect(self._disconnected)
        from .collector import Collector
        self.collector = Collector(self.settings, self)
        self.collector.status.connect(self._status)
        self.socket.errorOccurred.connect(self._socket_error)
        self.reconnect = QTimer(self)
        self.reconnect.setSingleShot(True)
        self.reconnect.timeout.connect(self._connect)
        self.timer = QTimer(self)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self.tick)
        self.bubble = LiveBubble()
        self.viewer = AudienceBoard(self.settings)
        self.board = LiveBoard(self.toggle_pause, viewer=self.viewer, stop_music=self.stop_music)
        self.balance_result.connect(self._balance_done, Qt.ConnectionType.QueuedConnection)
        self.history = []
        self.pending_reply = ''
        self.current = None
        self.request = None
        self.usage_data = None
        self.last_reply = -1e9
        self.last_dance = -1e9
        self.dance_pending = False
        self.dance_requested_at = 0
        self.balance_last = -1e9
        self.balance_busy = False
        self.balance_generation = 0
        self.balance_blocked = False
        self.paused = False
        self.closed = False
        self.auth_blocked = False
        self.player = None
        self.music_output = None
        self.music_until = 0
        self.music_source = ''
        self.last_action = ''
        self.board_last = -1e9
        self.counts = {'chats': 0, 'gifts': 0, 'accepted': 0, 'filtered': 0, 'spoken': 0}
        self.current_music = ''
        self.tracks = music_tracks(self.settings.music_dir)

    def start(self):
        # 上播是主播现场操作：重启/保存设置不应直接开始读评论、消耗模型额度。
        self.paused = True
        self.board.button.setText('开始营业 / 恢复回复')
        self.viewer.show()
        self.board.show()
        screen = self.board.screen().availableGeometry()
        self.board.move(screen.left() + 24, screen.top() + 32)
        self.viewer.move(max(screen.left(), screen.right() - self.viewer.width() - 24), screen.top() + 32)
        self._update_boards()
        if not self.settings.room:
            self._status('请在设置 → AI 与对话 → 直播营业填写网页直播间号')
            return
        self.timer.start()
        self._connect()

    def _status(self, value):
        self.board.status.setText(value)

    def _connect(self):
        if not self.closed:
            self.socket.open(QNetworkRequest(QUrl(f'{self.settings.endpoint.rstrip("/")}/{self.settings.room}')))

    def _disconnected(self):
        if self.closed or self.auth_blocked:
            return
        code = int(self.socket.closeCode().value)
        if code == 1008:
            self.paused = True
            self._status('采集连接被拒绝，请检查本地服务权限；已停止重连')
            return
        self._status('采集连接断开，5 秒后重连；过期评论不会补播')
        self.reconnect.start(5000)

    def _socket_error(self, error):
        if self.closed:
            return
        reason = self.socket.errorString()
        if '401' in reason or '403' in reason:
            self.auth_blocked = True
            self.reconnect.stop()
            self._status('本机采集服务要求授权，请先处理采集服务登录，已停止重连')
        elif error == QAbstractSocket.SocketError.ConnectionRefusedError:
            self.collector.start()

    def toggle_pause(self):
        self.paused = not self.paused
        self.board.button.setText('恢复回复' if self.paused else '暂停回复')
        self.pending_reply = ''
        self.inbox = Inbox(self.settings)
        if self.request:
            self.ledger.usage(self.request, self.usage_data)
            self.request = None
        self.chat.stop()
        self.current = None
        self.dance_pending = False
        if self.player:
            self.player.stop()
        self.current_music = ''
        self._status('回复已暂停，礼物账本继续记录' if self.paused else '已恢复，等待新消息')

    def stop_music(self):
        if self.player:
            self.player.stop()
        self.music_until = 0
        self.current_music = ''
        self._status('主播已停止当前配乐；后续新礼物或新动作仍按配置配乐')

    def receive(self, raw):
        if self.closed or len(raw) > 1024 * 1024:
            return
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            self._status('忽略了格式错误的采集消息')
            return
        if not isinstance(data, dict):
            return
        if data.get('type') == 'system':
            self._status(text(data.get('message'), 120))
            return
        kind = data.get('method')
        if kind == 'WebcastChatMessage':
            self.counts['chats'] += 1
        elif kind == 'WebcastGiftMessage':
            self.counts['gifts'] += 1
        try:
            if data.get('method') == 'WebcastGiftMessage':
                delta = self.ledger.gift(self.settings.room, data)
                self._update_boards()
                uid, gid, group, *_ = gift_fields(data)
                if not delta and f'{uid}:{gid}:{group}' not in self.inbox.gifts:
                    self.counts['filtered'] += 1
                    return  # 重连/重启回放旧礼物不重复感谢；在途结束帧仍用于结算。
            if not self.paused:
                accepted = self.inbox.accept(data, time.monotonic())
                if kind in ('WebcastChatMessage', 'WebcastGiftMessage'):
                    self.counts['accepted' if accepted else 'filtered'] += 1
        except (OSError, ValueError, sqlite3.Error) as exc:
            log.warning('直播消息记录失败: %s', type(exc).__name__)
            self._status('账本记录失败，请检查数据目录')

    def _channel(self):
        return self.shell.ensure_audio_channel()

    def tick(self):
        if self.closed:
            return
        now = time.monotonic()
        channel = self._channel()
        idle = channel is not None and channel.channel_idle
        if self.music_output:
            self.music_output.setVolume(self.settings.music_volume / 100 * (1 if idle else .25))
            if now >= self.music_until:
                self.player.stop()
                self.current_music = ''
        if now - self.balance_last >= 300 and not self.balance_busy and not self.balance_blocked:
            self._refresh_balance()
        if now - self.board_last >= 1:
            self.board_last = now
            self._update_boards()
        if self.paused:
            return
        if channel is None:
            self._status('请先在功能页启用语音模块，再开始营业')
            return
        if self.dance_pending:
            self._try_dance(now)
        self._observe_action(now)
        if self.pending_reply:
            if idle:
                reply = self.pending_reply
                if channel.speak(reply, log_tag='直播回复', respect_quiet=False):
                    self.pending_reply = ''
                    self.bubble.say(reply, self.shell.win)
                    self.last_reply = now
                    self.counts['spoken'] += 1
            return
        if not idle or self.chat.has_running_workers() or now - self.last_reply < self.settings.reply_interval:
            return
        event = self.inbox.pop(now)
        if event is None:
            return
        self.current = event
        self.board.last_message.setText(f'最近处理：{event.user} · {event.text}' + (f' ×{event.count}' if event.kind == 'gift' else ''))
        if event.kind == 'gift':
            self.pending_reply = f'谢谢{event.user}送的{event.count}个{event.text}，小肥鱼的饭钱又有着落啦！'
            if event.count >= self.settings.gift_dance_min:
                self._dance(now)
            song = music_mapping(self.settings.gift_music).get(event.text)
            if song:
                self._play(song, 8, source='gift')
            return
        command = event.text.strip()
        if command in ('跳舞', '肥鱼跳舞', '大肥鱼跳舞', '小肥鱼跳舞'):
            self._dance(now)
            return
        if command.startswith('点歌 '):
            if self.settings.allow_song_requests:
                song = command[3:].strip()
                if song in self.tracks:
                    self._play(song, 180)
                    self._status(f'正在播放本地曲目：{song}')
                else:
                    self._status('本地歌单里没有这首歌，不会自动搜索或下载')
            return
        if command in ('停止音乐', '关音乐'):
            # 停播是主播操作，观众不能中断其他人的点歌。
            return
        settings = self.shell.config.chat_settings()
        provider = replace(settings.active_config, timeout=min(20., settings.active_config.timeout),
                           max_tokens=160, thinking='disabled', web_search=None)
        provider.api_key = self.shell.config.resolve_api_key(provider)
        if not provider.api_key:
            self._status('请在 AI 设置配置模型 API Key；礼物感谢仍可用')
            return
        provider.collect_usage = True
        self.usage_data = None
        self.request = uuid.uuid4().hex
        messages = build_messages(self.settings, event, self.history)
        self.chat.send(messages, provider, request_id=self.request)

    def _usage(self, rid, raw):
        if rid == self.request:
            try:
                self.usage_data = json.loads(raw)
            except ValueError:
                self.usage_data = None

    def _finished(self, rid, reply):
        if rid != self.request or self.closed:
            return
        self.ledger.usage(rid, self.usage_data)
        self.request = None
        reply = clean_reply(reply, self.settings)
        if reply and not self.paused:
            self.pending_reply = reply
            self.history.extend([{'role': 'user', 'content': json.dumps({'nickname': self.current.user, 'text': self.current.text}, ensure_ascii=False)},
                                 {'role': 'assistant', 'content': reply}])
            self.history = self.history[-6:]

    def _failed(self, rid, message):
        if rid != self.request or self.closed:
            return
        self.ledger.usage(rid, self.usage_data)
        self.request = None
        self.last_reply = time.monotonic()
        permission = re.search(r'\bHTTP\s+(401|403)\b', message)
        if permission:
            self.paused = True
            self.board.button.setText('恢复回复')
            self._status('模型权限校验失败，回复已暂停；请人工修复后恢复')
            log.warning('直播模型请求权限失败: POST chat/completions; 阶段=回复; 凭据=现有模型设置; HTTP %s',
                        permission.group(1))
        else:
            self._status('本轮模型请求失败，已跳过；不会重复播报或无限重试')

    def _dance(self, now):
        self.dance_pending = True
        self.dance_requested_at = now
        self._try_dance(now)

    def _try_dance(self, now):
        if not self.dance_pending:
            return
        if now - self.dance_requested_at > 90:
            self.dance_pending = False
            self._status('表演等待超过90秒，本次取消，避免补播过期动作')
            return
        if now - self.last_dance < self.settings.dance_cooldown:
            self._status('表演已排队，小肥鱼休息后继续；连续请求合并为一支舞')
            return
        target = getattr(self.shell, '_overlay_shell', None) or self.shell.win
        lib = getattr(target, 'lib', None)
        available = set(lib.names()) if lib else set()
        names = [name for name in ('轻快摇摆舞', '可爱宅舞', '优雅女仆舞') if name in available]
        if not names:
            self.dance_pending = False
            self._status('当前角色没有可播放的舞蹈素材，请更换含舞蹈的角色包')
            return
        if getattr(target, '_link_anim_busy', lambda: False)() or getattr(target, '_is_one_shot_playing', lambda: False)():
            self._status('表演已排队，当前动作结束后继续；连续请求合并为一支舞')
            return
        name = names[int(now) % len(names)]
        self.last_dance = now
        self.dance_pending = False
        target.request_link_anim(name)
        duration = max(1, min(30, lib.duration(name)))
        if not self.settings.action_music_enabled and self.settings.dance_music in self.tracks:
            self._play(self.settings.dance_music, duration, source='action')
        self._status(f'正在表演：{name}')

    def _observe_action(self, now):
        if not self.settings.action_music_enabled:
            return
        target = getattr(self.shell, '_overlay_shell', None) or self.shell.win
        lib = getattr(target, 'lib', None)
        if hasattr(target, 'alert_target_sprite'):
            sprite = target.alert_target_sprite()
            if sprite is None:
                return
            name = target.host_for_sprite(sprite).behavior.anim_of(sprite) or ''
            lib = getattr(sprite, 'library', None) or lib
        else:
            name = getattr(target, 'anim', '')
        if name == self.last_action:
            return
        self.last_action = name
        if self.music_source == 'request' and now < self.music_until:
            return
        song = music_mapping(self.settings.action_music).get(name)
        if song and lib:
            self._play(song, max(1, min(60, lib.duration(name))), source='action')
        elif self.player and self.music_source == 'action':
            self.player.stop()

    def _play(self, song, seconds, *, source='request'):
        if song not in self.tracks:
            return
        if self.player is None:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            self.player = QMediaPlayer(self)
            self.music_output = QAudioOutput(self)
            self.player.setAudioOutput(self.music_output)
            self.player.setLoops(QMediaPlayer.Loops.Infinite)
            self.player.errorOccurred.connect(lambda *_: self._status('本地音乐播放失败，请检查音频文件'))
        self.music_until = time.monotonic() + seconds
        self.music_source = source
        self.current_music = song
        self.music_output.setVolume(self.settings.music_volume / 100)
        self.player.setSource(QUrl.fromLocalFile(str(self.tracks[song])))
        self.player.play()

    def _refresh_balance(self):
        import threading
        from ..island.balance import fetch_balance
        provider = self.shell.config.chat_settings().active_config
        key = self.shell.config.resolve_api_key(provider)
        self.balance_last = time.monotonic()
        host = QUrl(provider.base_url).host()
        if not key or not (host == 'deepseek.com' or host.endswith('.deepseek.com')):
            return
        identity = hashlib.sha256((provider.base_url + key).encode()).hexdigest()
        self.balance_busy = True
        generation = self.balance_generation

        def run():
            try:
                result = fetch_balance(provider.base_url, key, timeout=10, verify_ssl=provider.verify_ssl)
            except Exception as exc:
                permission = re.search(r'\bHTTP\s+(401|403)\b', str(exc))
                result = {'error': 'permission' if permission else 'network',
                          'status': permission.group(1) if permission else None}
            try:
                self.balance_result.emit(generation, identity, result)
            except RuntimeError:
                pass  # Qt 已销毁：后台请求只读，不再写账本或访问界面。
        threading.Thread(target=run, daemon=True, name='live-balance').start()

    def _balance_done(self, generation, identity, result):
        if self.closed or generation != self.balance_generation:
            return
        self.balance_busy = False
        if 'error' in result:
            if result['error'] == 'permission':
                self.balance_blocked = True
                self._status('余额查询权限失败，已停止自动查询；聊天按独立权限处理')
                log.warning('直播余额请求权限失败: GET /user/balance; 阶段=账户查询; 凭据=现有模型设置; HTTP %s', result.get('status', '未知'))
            return
        self.ledger.balance(identity, result.get('total', ''), currency=result.get('currency', ''))
        self._update_boards()

    def _update_boards(self):
        totals = self.ledger.today()
        self.board.update_totals(totals)
        self.viewer.update_totals(totals)
        self.viewer.set_live(not self.paused)
        provider = self.shell.config.chat_settings().active_config
        self.board.update_runtime({**self.counts, 'pending': self.inbox.pending,
                                   'room': self.settings.room or '未填写',
                                   'provider': text(provider.name + ' / ' + provider.model, 70),
                                   'tts': text(self.shell.config.get('voice_chime_tts_backend', 'edge'), 30),
                                   'dance_pending': self.dance_pending,
                                   'connection': '已连接' if self.socket.isValid() else '未连接',
                                   'reply': '暂停' if self.paused else ('生成中' if self.request else '等待消息'),
                                   'music': self.current_music or '未播放', 'action': self.last_action})

    def shutdown(self):
        if self.closed:
            return True
        self.closed = True
        self.balance_generation += 1
        self.timer.stop()
        self.reconnect.stop()
        self.socket.abort()
        self.collector.shutdown()
        if self.request:
            self.ledger.usage(self.request, self.usage_data)
            self.request = None
        done = self.chat.shutdown()
        if self.player:
            self.player.stop()
        self.bubble.timer.stop()
        self.bubble.hide()
        self.bubble.deleteLater()
        self.board.hide()
        self.board.deleteLater()
        self.viewer.hide()
        self.viewer.deleteLater()
        self.ledger.close()
        return done
