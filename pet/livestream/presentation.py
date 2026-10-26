"""直播专用气泡与账本，和桌宠日常提示隔离。"""
from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen, QLinearGradient, QFontMetrics, QAction
from PySide6.QtWidgets import (QWidget, QLabel, QVBoxLayout, QHBoxLayout, QFrame, QPushButton,
                               QGraphicsDropShadowEffect)


from ..bubble_appearance import cute_font
from .rules import LiveSettings, music_mapping, estimated_income


class AudiencePaper(QFrame):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(.8, .8, -.8, -.8)
        path = QPainterPath()
        path.addRoundedRect(rect, 28, 28)
        painter.setClipPath(path)
        background = QLinearGradient(0, 0, self.width() * .5, 260)
        background.setColorAt(0, QColor('#f2edff'))
        background.setColorAt(1, QColor('#fffcf8'))
        painter.fillPath(path, background)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(248, 220, 207, 115))
        painter.drawEllipse(QRectF(self.width() - 102, -26, 150, 150))
        painter.setBrush(QColor(223, 237, 230, 155))
        painter.drawEllipse(QRectF(-45, self.height() - 48, self.width() + 90, 100))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor('#e7dfe8'), 1.3))
        painter.drawPath(path)


class WhaleMark(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(66, 56)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor('#9e91d8'))
        p.drawRoundedRect(QRectF(20, 20, 42, 29), 16, 16)
        tail = QPainterPath()
        tail.moveTo(23, 34)
        tail.cubicTo(10, 36, 6, 25, 2, 25)
        tail.cubicTo(1, 37, 9, 47, 24, 45)
        tail.closeSubpath()
        p.drawPath(tail)
        p.setBrush(QColor('#d6cef1'))
        p.drawRoundedRect(QRectF(26, 36, 31, 10), 5, 5)
        p.setBrush(QColor('#514368'))
        p.drawEllipse(QRectF(49, 28, 3.5, 3.5))
        p.setBrush(QColor('#ecb7ab'))
        p.drawEllipse(QRectF(51, 34, 6, 3))
        p.setBrush(QColor('#b9d9d5'))
        p.drawEllipse(QRectF(32, 7, 5, 9))
        p.drawEllipse(QRectF(40, 2, 4, 7))


class LiveBubble(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.label = QLabel()
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setFont(cute_font(24))
        self.label.setWordWrap(True)
        self.label.setMaximumWidth(480)
        self.label.setStyleSheet('QLabel {background:#fffefa;color:#403d46;border:1px solid #eae4df;'
                                 'border-radius:20px;padding:17px 21px;}')
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(63, 48, 43, 28))
        self.label.setGraphicsEffect(shadow)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 18)
        layout.addWidget(self.label)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

    def say(self, text, target):
        self.label.setText(text)
        self.adjustSize()
        if target is None:
            return
        if hasattr(target, 'visible_content_rect'):
            rect = target.visible_content_rect()
        elif hasattr(target, 'frameGeometry'):
            rect = target.frameGeometry()
        else:
            return
        host_screen = QGuiApplication.screenAt(rect.center()) or self.screen()
        screen = host_screen.availableGeometry()
        x = max(screen.left(), min(rect.center().x() - self.width() // 2, screen.right() - self.width()))
        y = max(screen.top(), min(rect.top() - self.height() + 12, screen.bottom() - self.height()))
        self.move(x, y)
        self.show()
        self.timer.start(max(5000, min(16000, len(text) * 200)))


class AudienceBoard(QWidget):
    """观众专用的暖白海盐色展示牌，可拖动并独立捕获。"""
    def __init__(self, settings: LiveSettings):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.settings = settings
        self.setWindowTitle('小肥鱼 · 观众展示牌')
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(400)
        self.setMaximumWidth(480)
        self.setStyleSheet('QLabel{color:#51465d;background:transparent;border:0;}')
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 16)
        paper = AudiencePaper()
        outer.addWidget(paper)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 5)
        shadow.setColor(QColor(84, 59, 105, 30))
        paper.setGraphicsEffect(shadow)
        layout = QVBoxLayout(paper)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)

        def label(value, size=16, color=None):
            widget = QLabel(value)
            widget.setFont(cute_font(size))
            widget.setTextFormat(Qt.TextFormat.PlainText)
            widget.setWordWrap(True)
            if color:
                widget.setStyleSheet('color:' + color + ';background:transparent;border:0;')
            return widget

        heading = QHBoxLayout()
        self.badge = label('小肥鱼营业中', 13)
        self.badge.setStyleSheet('background:#e1eee5;color:#47765c;border-radius:11px;padding:5px 10px;')
        heading.addWidget(self.badge)
        heading.addStretch(1)
        self.date = label('今日营业', 12, '#8e7d96')
        heading.addWidget(self.date)
        layout.addLayout(heading)
        brand = QHBoxLayout()
        title = label('小肥鱼的\n打工日记', 30, '#5c4a70')
        brand.addWidget(title, 1)
        brand.addWidget(WhaleMark(), 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(brand)
        motto = label('被主人派来卖艺，努力赚够自己的 token 饭钱。', 15, '#91809b')
        layout.addWidget(motto)
        metrics = QHBoxLayout()
        metrics.setSpacing(10)
        self.income = label('—', 38, '#b76a5d')
        self.income_unit = label('待设置分成', 12, '#bc8376')
        self.expense = label('—', 38, '#7d69a2')
        self.expense_unit = label('等待余额记录', 12, '#9b89b0')
        for title_text, value, unit, background, ink in (
            ('今日收入', self.income, self.income_unit, '#fff0e9', '#a96b5e'),
            ('今日消费', self.expense, self.expense_unit, '#eee8fa', '#806b9d'),
        ):
            card = QFrame()
            card.setStyleSheet('QFrame{background:' + background + ';border:0;border-radius:17px;}')
            column = QVBoxLayout(card)
            column.setContentsMargins(16, 13, 12, 13)
            column.setSpacing(3)
            column.addWidget(label(title_text, 14, ink))
            column.addWidget(value)
            column.addWidget(unit)
            metrics.addWidget(card, 1)
        layout.addLayout(metrics)
        self.tokens = label('今日已记录 0 tokens', 13, '#9a89a3')
        layout.addWidget(self.tokens)

        performance = QFrame()
        performance.setStyleSheet('QFrame{background:#eaf2eb;border:1px solid #dce8de;border-radius:17px;}')
        show = QVBoxLayout(performance)
        show.setContentsMargins(16, 14, 16, 14)
        show.setSpacing(5)
        show.addWidget(label('小肥鱼表演单', 20, '#537960'))
        dance = f'任意礼物同组满 {settings.gift_dance_min} 个 → 跳一支舞'
        trigger = (settings.mention + '跳舞') if settings.mention else '跳舞'
        self.rules = label(dance + f'\n弹幕“{trigger}” → 邀请小肥鱼跳舞', 16, '#547c62')
        show.addWidget(self.rules)
        show.addWidget(label(f'舞间休息 {settings.dance_cooldown} 秒，动作结束后安排。\n连续邀请会合并成一支舞。', 12, '#86a08b'))
        layout.addWidget(performance)

        layout.addWidget(label('送一份心意，听一段小曲', 16, '#8b769a'))
        colors = [('#fff1ed', '#b77c70'), ('#edf3ef', '#739583'), ('#f4edf8', '#9b80b4'), ('#fff4df', '#b29962'), ('#f0edfb', '#9584b3')]
        menu = QVBoxLayout()
        menu.setSpacing(7)
        for index, (gift, song) in enumerate(list(music_mapping(settings.gift_music).items())[:5]):
            row = QHBoxLayout()
            row.setSpacing(10)
            pastel, ink = colors[index % len(colors)]
            gift_label = label(gift, 15, ink)
            gift_label.setObjectName('viewerGiftName')
            gift_label.setWordWrap(False)
            gift_label.setFixedWidth(96)
            gift_label.setText(QFontMetrics(gift_label.font()).elidedText(gift, Qt.TextElideMode.ElideRight, 76))
            gift_label.setToolTip(gift)
            gift_label.setStyleSheet(f'background:{pastel};color:{ink};border-radius:9px;padding:5px 10px;')
            row.addWidget(gift_label)
            row.addWidget(label('→', 16, '#c3b4c9'))
            row.addWidget(label(song, 16, '#82728e'), 1)
            menu.addLayout(row)
        layout.addLayout(menu)
        if settings.allow_song_requests:
            layout.addWidget(label('想听歌？发送“点歌 歌名”，从本地歌单里选。', 13, '#8c789c'))
        notes = label('谢谢你陪小肥鱼一起营业\n消费按账户余额变化估算', 11, '#a698a6')
        notes.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(notes)

    def set_live(self, active):
        self.badge.setText('小肥鱼营业中' if active else '小肥鱼休息中')
        self.badge.setStyleSheet('background:' + ('#e1eee5;color:#47765c;' if active else '#eee6f6;color:#9475a9;')
                                + 'border-radius:11px;padding:5px 10px;')

    def update_totals(self, data):
        self.date.setText(data['day'])
        income = estimated_income(data['diamonds'], self.settings)
        self.income.setText('¥' + income if income is not None else '—')
        self.income_unit.setText('元' if income is not None else '待设置收入比例')
        self.expense.setText(data['balance_drop'] if data['balance_drop'] is not None else '—')
        currency = {'CNY': '元', 'USD': '美元'}.get(data.get('currency'), data.get('currency') or '原币种')
        self.expense_unit.setText(currency + ' · 余额差估算' if data['balance_drop'] is not None else '等待余额记录')
        self.tokens.setText(f"今日已记录 {data['tokens']} tokens")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.windowHandle():
            self.windowHandle().startSystemMove()
            event.accept()
        else:
            super().mousePressEvent(event)


class LiveBoard(QWidget):
    def __init__(self, toggle, *, viewer=None, stop_music=None):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.settings = viewer.settings if viewer is not None else LiveSettings()
        self.setWindowTitle('小肥鱼 · 主播控制台')
        self.setMinimumWidth(420)
        self.setMaximumWidth(680)
        self.setStyleSheet('QWidget{background:#fffefa;color:#403d46;} QPushButton{'
                           'background:#f2ede8;border:1px solid #e4dcd4;border-radius:9px;padding:7px 12px;}')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        title = QLabel('直播控制台 · 仅主播查看')
        title.setFont(cute_font(20))
        layout.addWidget(title)
        note = QLabel('上播时只捕获“观众展示牌”窗口；本窗含账户和运行详情。')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.stats = QLabel()
        self.stats.setTextFormat(Qt.TextFormat.PlainText)
        self.stats.setWordWrap(True)
        self.stats.setFont(cute_font(16))
        layout.addWidget(self.stats)
        self.telemetry = QLabel('等待接收消息')
        self.telemetry.setWordWrap(True)
        self.telemetry.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.telemetry)
        self.last_message = QLabel('最近处理：—')
        self.last_message.setWordWrap(True)
        self.last_message.setTextFormat(Qt.TextFormat.PlainText)
        self.last_message.setMaximumWidth(620)
        layout.addWidget(self.last_message)
        self.status = QLabel('等待连接')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.setMaximumWidth(420)
        layout.addWidget(self.status)
        self.button = QPushButton('暂停回复')
        self.button.clicked.connect(toggle)
        layout.addWidget(self.button)
        if stop_music:
            stop = QPushButton('停止当前配乐')
            stop.clicked.connect(stop_music)
            layout.addWidget(stop)
        if viewer:
            show = QPushButton('显示 / 隐藏观众展示牌')
            show.clicked.connect(lambda: viewer.hide() if viewer.isVisible() else viewer.show())
            layout.addWidget(show)
            reopen = QAction('打开主播控制台', viewer)
            reopen.triggered.connect(self.show)
            reopen.triggered.connect(self.raise_)
            viewer.addAction(reopen)
            viewer.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        self._toggle = toggle

    def update_totals(self, data):
        balance = data['balance'] if data['balance'] is not None else '未查询'
        drop = data['balance_drop'] if data['balance_drop'] is not None else '未知 / 充值后不可比较'
        income = estimated_income(data['diamonds'], self.settings)
        income_text = f'¥{income}（{self.settings.income_share_percent}%分成，未扣税费）' if income is not None else '待设置分成比例'
        title = '今日预计到手'
        if self.settings.income_share_percent == 100:
            title = '今日礼物金额'
            income_text = f'¥{income}（暂按{self.settings.diamonds_per_yuan}:1换算，未扣分成税费）'
        self.stats.setText(f"{data['day']} · 北京时间\n{title}  {income_text}\n原始礼物价值  {data['diamonds']} 钻\n"
                           f"直播已消费  {data['tokens']} tokens\n账户余额  {balance}\n账户余额减少  {drop}\n"
                           f"用量未知 {data['unknown_usage']} 次 · 价格未知礼物 {data['unknown_gifts']} 个\n"
                           '仅累计本地监听与直播请求；钻石不是提现收入。\n余额减少可能包含其他程序消费，非本场账单。')

    def update_runtime(self, state):
        self.telemetry.setText(f"房间：{state['room']}\n模型：{state['provider']}　语音：{state['tts']}\n"
                               f"连接：{state['connection']}　回复：{state['reply']}\n"
                               f"评论 {state['chats']} 条 / 礼物消息 {state['gifts']} 条\n"
                               f"已接收处理 {state['accepted']} 条 / 过滤或去重 {state['filtered']} 条\n"
                               f"待处理 {state['pending']} 条 · 已播回复 {state['spoken']} 条 · 待表演 {int(state['dance_pending'])}\n"
                               f"配乐：{state['music']}　动作：{state['action'] or '—'}")

    def closeEvent(self, event):
        # 关闭面板只隐藏；通过设置关闭直播才释放采集和音频服务。
        self.hide()
        event.ignore()
