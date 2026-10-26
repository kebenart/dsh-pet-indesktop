# 小肥鱼直播营业与双面板（2026-10-26）

## 核心特性

通过本机 douyinLive 采集抖音直播评论与礼物，DeepSeek 生成短句，豆包朗读；礼物连击合并感谢，现有 WebM 舞蹈配合原创本地音乐。观众展示牌采用淡紫、蜜桃、薄荷配色、手写字体和矢量鲸鱼；主播控制台单独显示连接、过滤、队列、账户及操作。每次启动默认暂停回复，主播点击开始营业后才调用模型。

收入为采集期间的礼物钻石，不能冒充提现收入；消费金额是账户余额差估算，真实币种随接口返回，并非本场精确账单；另记模型 usage tokens。观众牌不展示余额、昵称、凭据或错误详情。

## 修改文件说明

| 文件 | 意图 |
|---|---|
| pet/livestream/rules.py | 独立人设、消息清洗、过滤、TTL、有界队列、连击去重与本地曲目映射 |
| pet/livestream/ledger.py | SQLite 日账本、礼物幂等、真实 usage、余额及币种变化 |
| pet/livestream/collector.py | QProcess 管理自有采集器；钥匙串 Cookie 通过临时0600配置传入 |
| pet/livestream/service.py | 本机 WebSocket、串行回复、舞蹈与音乐、暂停与退出生命周期 |
| pet/livestream/presentation.py | 观众彩色展示牌、主播控制台与独立直播气泡 |
| pet/livestream/settings.py、__init__.py | 设置编辑器与包入口 |
| pet/app.py | 按能力与配置挂接服务，退出清理，保留尚未结束的 worker |
| pet/chat/providers.py、service.py | 收集真实 usage；直播回复不进入日常全局朗读链 |
| pet/config.py、features.py | 直播默认配置、规范化、持久化及搜索归属 |
| pet/modern_settings_dialog.py、settings_default_marks.py、settings_page_guide.py | AI与对话下的直播高级组、保存与默认值标记 |
| pet/island/balance.py | 保留余额接口返回的币种 |
| pet/bubble_appearance.py、speech_bubble.py、speech_bubble_text.py | 全局可爱字体、暖白气泡、正文24px、分页及低缩放布局 |
| pet/voice/loudness.py、chime_service.py | 后台生成响度一致的播放副本、旧缓存预热、播放状态日志 |
| scripts/generate_livestream_music.py、assets/sounds/livestream/*.wav | 原创合成8首配乐，无外部歌曲或采样 |
| tests/test_livestream.py、test_livestream_qt.py、test_voice_loudness.py | 过滤、记账、真实Qt网络、生命周期、隐私、标签布局、语音副本 |
| tests/test_architecture.py、test_bubble_text_scale.py、test_config_schema.py、test_desktop_pet_features.py、test_speech_bubble.py | 更新相应配置、字号与快照契约；设置主文件预算仅增加接线6行 |
| docs/SETTINGS-CHANGE-GATES.md、INDEX.md | 新设置契约与报告索引 |

原有 assets/icon.ico 修改属于用户已有工作，不纳入本次实现；构建输入从构建前备份恢复。

## 实现与边界

评论队列20、礼物组队列20，去重结构上限2048。评论25秒、礼物60秒过期。连击以累计数量差值计账，repeatEnd只结算，不按网络帧次数重复感谢。模型没有工具，观众内容以不可信数据输入，最多160输出token。单句串行，礼物优先；播放语音时配乐降低音量，表演请求合并并等待当前动作结束。

舞蹈直接复用轻快摇摆舞、可爱宅舞、优雅女仆舞等已有素材，未新增图片生成或骨架动画。八首曲目为营业、心动、花开、糖果、庆典、摇摆、棋盘、像素闯关，可在设置替换本地歌单。点歌默认关闭，仅允许本地已列出的曲目。

## 性能分析

macOS arm64、Python3.12、PySide6，本机运行 `.scratch/livestream/perf.py`。10000条过滤均摊0.0131ms，200笔SQLite礼物写入均摊0.7313ms，1000次账本读取均摊0.1245ms。账本界面每秒刷新；没有记录改前同项对照，不能据此宣称整体性能提升。新增一个本机采集子进程、WebSocket及按需模型/TTS/余额网络请求，音乐走Qt播放器，响度副本后台ffmpeg生成；缓存与队列有上界，音频副本会增加磁盘占用。

## 实机运行记录

原生Qt Cocoa实测运行 `.scratch/livestream/runtime.py`，42秒内真实采集到评论16帧、礼物3帧；一条明确的本地测试评论通过真实模型与TTS，usage275，播放器进入PlayingState、进度8472ms后结束。确认轻快摇摆舞、音乐播放器及两个面板同时可见。没有向直播间发评论或送礼。

`.scratch/livestream/capture.py` 在原生Qt生成明暗主题720/1100宽设置窗、全局气泡和观众展示牌截图。新版展示牌400×844逻辑像素，礼物标签固定宽度且不换行，长名省略；截图样例128钻石/0.10元为演示数据，不是用户收入。实际营业状态跟随暂停按钮。

语音反馈排查：用户消息已有缓存音频生成，原文件并非静音，但音量差异明显，系统音量19%。已统一播放副本响度并补播放器日志；这只能证明本轮播放链运行，尚不能断言所有偶发无声根因都已解决，用户听感仍待确认。系统音量未改。

失败路径由真实Qt本机WebSocket测试覆盖断线重连、权限拒绝停连、暂停仍记账、无舞蹈素材时提示；未在真实抖音账号上人为制造权限拒绝。Windows/Linux未实机验收。

## 测试与验证

- 最终UI聚焦：直播规则、Qt、余额、响度与架构，共57 passed（8.63秒）。
- 受影响大集合：446 passed、4 skipped；核心集合166 passed。
- 全量首次9038 passed、83 skipped、5 failed；其中本次引起的气泡低缩放与快照两项已修复并单独复验通过。
- 另外3项在HEAD独立基线均复现：flight测试替身缺_cfg、帧序列门与已有personal fork bypass冲突、weather搜索既有归属差异。没有修改这些测试来制造全绿。最终代码未重复全量，不能声称全量通过。
- ruff检查实现与测试通过，git diff --check通过。构建使用 scripts/build_macos.sh 的 webm-chat 唯一入口。

## 风险与恢复

采集器属于第三方非官方协议实现，平台变化可能导致失效；只连接本机ws。登录Cookie在系统钥匙串，临时配置由本服务退出时清理，不输出秘密。只终止本服务自己启动的采集器。直播关闭即可回到原日常行为，账本单独留存。应用替换保留旧包备份，不删除用户配置、聊天历史、钥匙串或原音频。观众收入只累计采集期间，网络离线期间可能漏记；不能用于财务结算。

## 观众牌实机更新与恢复入口

最终包已通过官方构建入口，原应用正常菜单退出后换为新包，旧包保留备份。真实安装版展示彩色观众牌，主播现场恢复营业后收到评论并累计usage。另发现主播控制台误关闭后缺少恢复入口，增加观众牌右键“打开主播控制台”；不占用观众画面，关闭/恢复测试10项通过。报告纪律检查235项通过。

## 语音音调差异根因与修复

用户指定的参照句“呜，有点困……不能睡。”命中self_talk_voice/ed805834ef22ea32.mp3，为魅力苏菲+15%。此前仅凭参数相同推断听感一致不成立。实际复现：自言自语使用保留.mp3扩展名的临时文件，而VoiceChimeService即时合成使用.part；doubao._write_with_pitch未声明输出格式，ffmpeg无法推断.part容器后异常，代码静默写原音。导致即时回复被标记+15%却没有升调。

修改pet/tts/doubao.py：明确-f mp3；非零升调缓存flavor增加pitch-mp3-v2，使旧错误缓存失效，原文件保留；变调缺依赖/失败不再将原音冒充已升调音频。tests/test_tts_doubao.py新增真实ffmpeg回归：440Hz输入在修复前.part输出仍440Hz，断言失败；修复后.mp3和.part均约506Hz、时长保持。另验证缺ffmpeg不产错误缓存、零升调缓存保持旧身份。

相关语音集合338项通过，最终新增失败与缓存回归后provider10项通过，ruff与diff检查通过。真实豆包请求同一句，保留同一原音分别走预缓存与实际_TTSWorker（.part→原子落盘）路径，输出63020字节且逐字相同，日志记录后端doubao、Sophie、pitch15。该验证证明两条处理路径一致，不承诺云端不同请求/不同句子的韵律完全相同。原参考文件复制留存于.scratch/livestream/voice-comparison，未改写原文件。

## 收入显示人民币

用户选择预计到手口径，尚未提供账号实际比例，要求按默认最低。官方协议没有统一最低比例承诺（https://sf3-cdn-tos.douyinstatic.com/obj/ies-hotsoon-draft/douyin/36ba590b-4606-410f-b035-bc38f7ef6a50.html），因此本机临时按30%估算，基础暂按10钻/元；两项均可设置调整，不作为核验的真实账号收益。观众牌移除钻石显示，改“今日预计到手¥…”并注明暂按比例、未扣税费；主播保留原始礼物价值。金额使用Decimal到分四舍五入，比例为0时不冒充零收入，显示待设置。账本仍保存原始计数，不损失历史。转换不会扣一次平台分成再扣一次，费用消费也不参与收入相减。

修改rules.py、settings.py、presentation.py及对应规则/Qt测试；最终相关集合98项通过。金额示例128钻按30%为¥3.84，示例非账号实际收益。

## 最终展示与音色选择

用户随后明确“先按照10比1”，本机改为10钻直接换算1元（income_share_percent=100），取代上一节暂定30%方案。用户要求观众牌只写“今日收入”和“元”，换算及分成解释保留在主播控制台和设置。该数值为礼物价值换算，非已核验平台实际到账。本地设置新增比例控制，不改原始计数。

豆包常用音色新增用户指定的zh_female_roumeinvyou_uranus_bigtts（柔美女音）、zh_female_qingchezizi_uranus_bigtts（清澈欣欣）、zh_female_qinqienv_uranus_bigtts（亲切女声音）。仅加入选项，不自动换掉当前魅力苏菲；尚未对三款新音色逐个发真实合成请求验证账号权限。最后语音、直播与音色编辑器集合36项通过，报告及架构251项通过。

## README与脱敏配置交付

README新增直播互动章节：依赖项目与版本、安装启用、Cookie钥匙串隐藏输入、双面板、过滤及礼物配乐、收入消费口径、参考音色与本机硬件/软件配置。新增examples/livestream.config.example.json，包含当前直播提示词、日常大肥鱼提示词、互动参数、配乐映射、10:1换算及语音模型设置；直播默认关闭，房间号和采集程序路径留空，不含密钥或Cookie。当前直播人设逐字同步到rules.DEFAULT_PROMPT。用户最终要求观众牌只写“今日收入/元”，所有换算说明保留主播侧。
