import json
import time
from types import SimpleNamespace

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.livestream.rules import LiveSettings
from tests.test_livestream import chat, gift

app = QApplication.instance() or QApplication([])


def until(predicate, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if predicate():
            return
        time.sleep(.005)
    assert predicate()


def make_service(tmp_path):
    from pet.livestream.service import LiveService
    cfg = Config(base=tmp_path)
    cfg.set('livestream', {'enabled': True, 'room': '123'})
    spoken = []
    channel = SimpleNamespace(channel_idle=True, speak=lambda value, **_: spoken.append(value) or True)
    host = SimpleNamespace(visible_content_rect=lambda: QRect(100, 300, 200, 200))
    shell = SimpleNamespace(config=cfg, win=host, ensure_audio_channel=lambda: channel)
    service = LiveService(shell)
    service._refresh_balance = lambda: None
    return service, channel, spoken


def test_gift_received_twice_is_accounted_and_spoken_once(tmp_path):
    service, channel, spoken = make_service(tmp_path)
    try:
        service.receive(json.dumps(gift(count=2)))
        service.receive(json.dumps(gift(count=2, end=1, mid='g2')))
        service.settings = LiveSettings.from_dict({'gift_dance_min': 100})
        service.tick()
        assert service.pending_reply
        service.tick()
        assert len(spoken) == 1
        assert '2个小心心' in spoken[0]
        assert service.ledger.today()['diamonds'] == 2
        assert service.bubble.label.text() == spoken[0]
    finally:
        service.shutdown()


def test_paused_keeps_accounting_but_does_not_reply(tmp_path):
    service, channel, spoken = make_service(tmp_path)
    try:
        service.toggle_pause()
        service.receive(json.dumps(gift(count=3)))
        service.receive(json.dumps(chat('你好呀')))
        service.tick()
        assert service.ledger.today()['diamonds'] == 3
        assert not spoken and service.inbox.pending == 0
        service.shutdown()
        service.shutdown()  # shutdown 必须幂等，迟到网络消息不访问已关闭账本。
        service.receive(json.dumps(gift(count=4)))
    finally:
        service.shutdown()


def test_live_chat_does_not_broadcast_to_personal_voice_reader(tmp_path):
    from pet.chat.service import ChatService
    service, _, _ = make_service(tmp_path)
    seen = []
    ChatService.register_global_finished(seen.append)
    try:
        service.chat._request_id = 'r'
        service.chat._finished('r', '直播专用回复')
        assert not seen
    finally:
        ChatService.unregister_global_finished(seen.append)
        service.shutdown()


def test_editor_roundtrip_and_sanitization(tmp_path):
    from pet.livestream.settings import LiveSettingsEditor
    cfg = Config(base=tmp_path)
    editor = LiveSettingsEditor(cfg)
    editor.controls['enabled'].setChecked(True)
    editor.controls['room'].setText('https://live.douyin.com/14287526523')
    cfg.set('livestream', editor.value())
    assert cfg.save()
    loaded = Config(base=tmp_path)
    assert loaded.get('livestream')['enabled'] is True
    assert loaded.get('livestream')['room'] == '14287526523'


def test_default_system_bubble_is_warm_white_and_uses_same_font():
    from pet.speech_bubble import PetSpeechBubble, BUBBLE_STYLE_PRESETS
    from pet.bubble_appearance import bubble_font_family
    bubble = PetSpeechBubble()
    try:
        assert BUBBLE_STYLE_PRESETS['classic_top']['background'] == '#fffefa'
        assert bubble.label.font().family() == bubble_font_family()
        bubble.show_text('小肥鱼正在努力营业，今天也要赚够自己的 token 饭钱。', QRect(100, 300, 200, 200), 5000)
        app.processEvents()
        assert bubble.isVisible()
        assert bubble.label.width() > 0
    finally:
        bubble.close()


def test_real_local_websocket_delivers_gift_and_reconnects(tmp_path):
    from PySide6.QtNetwork import QHostAddress
    from PySide6.QtWebSockets import QWebSocketServer
    server = QWebSocketServer('live-test', QWebSocketServer.SslMode.NonSecureMode)
    assert server.listen(QHostAddress.SpecialAddress.LocalHost, 0)
    service, _, _ = make_service(tmp_path)
    peers = []

    def connected():
        peer = server.nextPendingConnection()
        peers.append(peer)
        peer.sendTextMessage(json.dumps(gift(count=2)))

    server.newConnection.connect(connected)
    service.settings = LiveSettings.from_dict({'enabled': True, 'room': '123',
                                              'endpoint': f'ws://127.0.0.1:{server.serverPort()}/ws'})
    try:
        service.start()
        until(lambda: service.ledger.today()['diamonds'] == 2)
        peers[0].close()
        until(lambda: len(peers) == 2, timeout=8)
        assert service.ledger.today()['diamonds'] == 2
    finally:
        service.shutdown()
        for peer in peers:
            peer.close()
        server.close()


def test_usage_arrives_before_reply_and_permission_failure_pauses(tmp_path):
    from pet.chat.models import ProviderConfig
    from pet.chat.providers import StreamEvent

    class Provider:
        def stream(self, messages, config, cancel):
            yield '今天也要努力赚饭钱。'
            yield StreamEvent('usage', '{"total_tokens":23}')

    service, _, _ = make_service(tmp_path)
    try:
        service.chat.provider = Provider()
        service.request = 'known-request'
        service.current = SimpleNamespace(user='观众', text='你好')
        service.chat.send([], ProviderConfig('test'), request_id=service.request)
        until(lambda: service.ledger.today()['tokens'] == 23)
        assert service.pending_reply == '今天也要努力赚饭钱。'
        service.request = 'failed-request'
        service.usage_data = None
        service._failed('failed-request', 'HTTP 403: denied')
        assert service.paused
        assert service.ledger.today()['unknown_usage'] == 1
    finally:
        service.shutdown()


def test_audience_board_has_rules_and_never_shows_private_balance():
    from PySide6.QtWidgets import QLabel
    from pet.livestream.presentation import AudienceBoard
    board = AudienceBoard(LiveSettings.from_dict({'gift_dance_min': 3, 'income_share_percent': 50}))
    try:
        board.update_totals({'day': '2026-10-26', 'diamonds': 123, 'tokens': 456,
                             'balance': '9876.54', 'balance_drop': '0.25', 'currency': 'CNY',
                             'unknown_usage': 0, 'unknown_gifts': 0})
        labels = '\n'.join(w.text() for w in board.findChildren(QLabel))
        assert '9876.54' not in labels
        assert '¥6.15' in labels and '0.25' in labels
        assert '钻' not in labels
        assert '满 3 个' in labels and '心动小曲' in labels
        assert 'API' not in labels and '连接' not in labels
        board.show()
        app.processEvents()
        for name in board.findChildren(QLabel, 'viewerGiftName'):
            assert not name.wordWrap()
            assert name.width() >= name.fontMetrics().horizontalAdvance(name.text()) + 20
            assert name.height() >= name.fontMetrics().height()
    finally:
        board.close()


def test_gift_dance_waits_for_current_action_and_merges_requests(tmp_path):
    service, _, _ = make_service(tmp_path)
    busy = [True]
    played = []
    service.shell.win = SimpleNamespace(lib=SimpleNamespace(names=lambda: ['可爱宅舞'], duration=lambda name: 4),
                                        _is_one_shot_playing=lambda: busy[0], request_link_anim=played.append)
    try:
        service._dance(100)
        service._dance(101)
        assert service.dance_pending and not played
        busy[0] = False
        service._try_dance(102)
        assert played == ['可爱宅舞'] and not service.dance_pending
        service._dance(103)
        assert service.dance_pending and len(played) == 1
        service._try_dance(140)
        assert played == ['可爱宅舞', '可爱宅舞']
        service.toggle_pause()
        assert not service.dance_pending
    finally:
        service.shutdown()


def test_viewer_can_reopen_hidden_operator():
    from pet.livestream.presentation import AudienceBoard, LiveBoard
    app = QApplication.instance() or QApplication([])
    viewer = AudienceBoard(LiveSettings())
    board = LiveBoard(lambda: None, viewer=viewer)
    board.show()
    board.close()
    app.processEvents()
    assert not board.isVisible()
    action = next(action for action in viewer.actions() if action.text() == '打开主播控制台')
    action.trigger()
    app.processEvents()
    assert board.isVisible()
    board.hide()
    viewer.hide()
