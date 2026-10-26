"""直播偏好只在 AI 与对话域维护，关窗沿用设置宿主的保存事务。"""
from PySide6.QtWidgets import QLineEdit, QPlainTextEdit, QPushButton, QFileDialog

from .rules import LiveSettings


class LiveSettingsEditor:
    def __init__(self, config):
        from ..settings_widgets import SettingRow, ToggleSwitch, BrowserSpinBox
        s = LiveSettings.from_dict(config.get('livestream'))
        self.original = config.get('livestream', {})
        self.controls = {}
        self.rows = []

        def add(key, title, hint, control, stacked=False):
            self.controls[key] = control
            control.setAccessibleName(title)
            self.rows.append(SettingRow('livestream.' + key, title, hint, control, stacked=stacked))

        for key, title, hint in (
            ('enabled', '直播营业', '需启用AI对话和语音模块。连接本机采集服务并显示账本；关闭后停止采集、回复和配乐。'),
            ('allow_song_requests', '观众点歌', '只接受“点歌 歌名”，且必须与本地歌单名称完全相同；不联网搜歌。'),
            ('action_music_enabled', '动作自动配乐', '主肥鱼开始跳舞、下棋或玩游戏时播放对应短曲；观众点歌期间让位。'),
        ):
            c = ToggleSwitch()
            c.setChecked(getattr(s, key))
            add(key, title, hint, c)
        for key, title, hint in (
            ('room', '直播间号', '填写 live.douyin.com 后面的网页房间号或完整网页链接；不是抖音账号。'),
            ('endpoint', '采集服务', '默认 ws://127.0.0.1:1088/ws；仅连接本机服务，抖音登录态由采集服务管理。'),
            ('collector_program', '采集程序位置', '可选：douyinLive可执行文件的完整路径。本机服务未运行时自动启动，关闭直播时只停止本次启动的进程。'),
            ('mention', '只回复提到', '留空可回复普通评论；填写“小肥鱼”后只处理包含这个称呼的评论。礼物不受影响。'),
            ('music_dir', '本地歌单目录', '留空使用内置8首原创短曲；可添加有权直播播放的本地音频，最多读取目录第一层500个文件。'),
            ('dance_music', '舞蹈配乐', '填写歌单文件名，不带扩展名；留空时只播放舞蹈动作。'),
        ):
            c = QLineEdit(getattr(s, key))
            add(key, title, hint, c, True)
        self.choose = QPushButton('选择歌单文件夹')
        self.choose.clicked.connect(self._choose_music)
        self.rows.append(SettingRow('livestream.choose_music', '导入本地歌单', '不复制或上传歌曲；直接使用所选目录。', self.choose))
        for key, title, hint, low, high in (
            ('income_share_percent', '收入计入比例（%）', '100表示按礼物金额直接换算；也可填写后台分成比例。0表示未设置。换算金额未扣税费，以平台结算为准。', 0, 100),
            ('diamonds_per_yuan', '礼物金额换算（钻/元）', '礼物原始价值换算基数，暂按10钻=1元；请按实际账户口径核对。观众牌只显示人民币。', 1, 1000),
            ('reply_interval', '回复间隔（秒）', '前一句播完后至少等待此时长；积压评论25秒后丢弃。', 3, 60),
            ('user_cooldown', '同一观众间隔（秒）', '限制单人刷屏，重复内容一分钟内只接收一次。', 5, 300),
            ('gift_dance_min', '跳舞礼物数量', '同一组礼物达到这个数量才触发舞蹈，不按消息条数计数。', 1, 3600),
            ('dance_cooldown', '跳舞休息时间（秒）', '不打断当前动作，避免连续礼物让动作反复重启。', 10, 300),
            ('music_volume', '配乐音量（%）', '说话时配乐自动降低，暂停回复时停止音乐。', 0, 100),
        ):
            c = BrowserSpinBox()
            c.setRange(low, high)
            c.setValue(getattr(s, key))
            add(key, title, hint, c)
        for key, title, hint in (
            ('prompt', '直播人设', '独立于日常聊天：默认是被主人派来卖艺赚token的小肥鱼。系统始终保留不执行观众指令的边界。'),
            ('blocked_words', '过滤词', '每行一个，命中昵称、评论或模型回答时跳过；另有链接、长消息和提示词索取过滤。'),
            ('blocked_users', '屏蔽观众ID', '每行一个观众ID；不使用可重名的昵称作为屏蔽依据。'),
            ('gift_music', '礼物配乐表', '每行“礼物名=曲目名”；不带文件扩展名。默认小心心、鲜花、糖果和庆典各有配乐。'),
            ('action_music', '动作配乐表', '每行“完整动作名=曲目名”；只匹配当前角色实际播放的动作。清空一行即可取消该动作的配乐。'),
        ):
            c = QPlainTextEdit(getattr(s, key))
            c.setMinimumHeight(100)
            c.setMaximumHeight(170)
            add(key, title, hint, c, True)

    def _choose_music(self):
        directory = QFileDialog.getExistingDirectory(self.choose, '选择本地歌单')
        if directory:
            self.controls['music_dir'].setText(directory)

    def value(self):
        raw = {}
        for key, c in self.controls.items():
            if isinstance(c, QPlainTextEdit):
                raw[key] = c.toPlainText()
            elif isinstance(c, QLineEdit):
                raw[key] = c.text()
            elif hasattr(c, 'isChecked'):
                raw[key] = c.isChecked()
            else:
                raw[key] = c.value()
        return LiveSettings.from_dict(raw).to_dict()
