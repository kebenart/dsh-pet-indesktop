# PR 报告：气泡朗读（2026-10-25）

> **基线**：`main` 快照（zip 解包，无 `.git`；逐文件 numstat 见 §二，用原快照做 `git diff --no-index`）
> **分支**：`feat/bubble-voice`　**日期**：`2026-10-25`
> **范围**：16 个文件（实现 14、测试 2；新增 `pet/bubble_voice.py`、`tests/test_bubble_voice.py`）
> **关联**：[`PR-REPORT-CHAT-REPLY-VOICE-2026-10-20.md`](PR-REPORT-CHAT-REPLY-VOICE-2026-10-20.md)（同一条音频通道的上一个消费者）、
> [`ADDING-A-TTS-PROVIDER.md`](ADDING-A-TTS-PROVIDER.md)（音色/后端参数来源）

## 一、核心特性

**需求**：桌宠现在只有零星几处会「念出来」（报时 / 节日 / 抽签 / 待办 / 点击台词 /
聊天窗回答）。定时自言自语、看看屏幕、截图问答、余额、天气、网络、更新提示、审批
提问、主动识屏、文件解读——**全部只有字，没有声**。

本刀不逐个功能补 `speak()`，而是在气泡的**唯一出口**接一个消费者：

| # | 能力 | 说明 |
|---|---|---|
| 1 | 所有气泡都念 | 切口是 `PetSpeechBubble.show_text()`（所有气泡最后都落到它）；新模块 `pet/bubble_voice.py` 在这里报一次，未来新功能自动获得朗读，不需要再接线 |
| 2 | 不念两遍 | 已经自带朗读的链路（报时/节日/抽签/待办/点击台词/歌词）在上游包一层 `bubble_voice.muted()`，气泡照显示、朗读让位 |
| 3 | 不念垃圾 | 少于 2 个可见字符、纯标点不念；Markdown 先清洗（复用 `clean_for_speech`）；最多 3 句 / 120 字（识屏与审批文案可能很长） |
| 4 | 不念重复 | 同一段文本 8 秒内再次上屏不念第二遍（粘滞气泡恢复、免打扰汇总重挂、"让我看看…"连发） |
| 5 | 不叠音 | 复用进程内唯一音频通道（`VoiceChimeService`），继承按句滴灌：先问 `channel_idle` 再送下一句 |
| 6 | 默认关 | 新全局键 `bubble_voice_enabled` 默认 `False`：每个气泡一次合成 = 一次网络往返 + 一次计费，属主动打扰型能力 |
| 7 | 设置入口 | 设置 → 语音 → 「语音」组新增一行「气泡朗读」 |

**红线 / 不变量**：

- 关着时**零对象、零队列、零定时器**：`report()` 在没装朗读器时只做一次 `None` 判断；
- 语音通道仍是**唯一**的出声路径，不新起播放器（否则结构上可能叠音）；
- 自动既有朗读语义一字未改：报时/节日/抽签/待办/点击台词全部走原路径，
  只是多了一条「让位」标记；
- 歌词永不进入朗读（歌词不是桌宠在说话）；
- 免打扰期间不出声（`respect_quiet=True`，与提醒类同口径；与点击台词/回复朗读
  这类"即时回应"的 `False` 有意区分）。

## 二、修改文件说明

`git diff --no-index --numstat`（原快照 vs 当前工作树；两个新增文件的规模另列）：

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/bubble_voice.py` | **新增 182 行** | 本功能的全部核心：`BubbleVoice` 继承 `ChatReplyReader`（复用滴灌/忙等/世代作废），只覆写 `_split` 加上"3 句 / 120 字"上限；`submit()` 做开关、碎片、去重、标题优先；`install/uninstall/report/active_router` 是气泡控件的唯一入口；`muted()` 上下文是"这条我自己念过了"的唯一声明方式 |
| `pet/chat_reply_voice.py` | +5 / −1 | 把 `feed()` 里的 `split_sentences(...)` 收成一个可覆写点 `_split()`——气泡口径的上限不加进原模块的分支 |
| `pet/speech_bubble.py` | +18 / −0 | 汇合点：`show_text()` 末尾（气泡真正 show 之后）调 `bubble_voice.report(text, subtitle=..., owner=...)`，异常只记 debug（气泡绝不能因为朗读而失败）；新增 `set_voice_owner/_voice_owner` 只用于日志定位 |
| `pet/app.py` | +62 / −0 | `_bubble_voice_wanted()`（voice 模块闸 + 新键）、`_ensure_bubble_voice()` / `_release_bubble_voice()`（懒建、装/卸汇合点）、`_speak_bubble()`（`ensure_audio_channel().speak(..., log_tag="气泡朗读")`）；`_chime_wanted()` 加第七个消费者；启动建、设置保存 `_sync_chime_service()` 同步、退出先摘汇合点再停通道 |
| `pet/config.py` | +4 / −0 | 新键默认 `False` + reload 白名单 + `_bool_or_default`（手改 `"false"` 不会被误开） |
| `pet/voice/chime_settings.py` | +12 / −0 | 「语音」组新增「气泡朗读」行（复用 `SettingRow` / `ToggleSwitch`，无新控件形态）；`apply_to_config` 写入 |
| `pet/voice/chime_service.py` | +18 / −9 | 报时气泡两条落点（`show_bubble` 与设置页抑制期直写 `show_text`）都包 `muted()`：报时语音已由 `_fire` 念过，再让气泡朗读念一次会变成"两声且文本口径不同"（气泡是阿拉伯数字、语音是中文数字） |
| `pet/festival/service.py` | +21 / −8 | 节日气泡两条落点：`festival_reminder_speak` 开着时让位（自己的 `_speak` 念），关着时交给气泡朗读 |
| `pet/divination/service.py` | +15 / −2 | 同上（`divination_speak`） |
| `pet/todo/reminder.py` | +9 / −1 | 同上（`todo_reminder_speak`）——开关关着时提醒仍有声，不再是"只有字" |
| `pet/music/lyric_controller.py` | +6 / −2 | 每拍续期的歌词气泡让位：不让位就是每拍念一遍歌词 |
| `pet/window_alerts.py` | +15 / −2 | 点击台词：自带「点击台词朗读」开着时包 `muted()`（那条链路已念），关着时交给气泡朗读——这是"点击也有声"的唯一分叉点 |
| `pet/window.py` | +2 / −0 | 气泡构造时记 `voice_owner="main"`（legacy 单窗的日志标识） |
| `pet/sprite_bubble.py` | +5 / −0 | 每次 show 前把 `_spawned_slots[sprite]` 写进气泡的 `voice_owner`（overlay 多宠的日志标识） |
| `pet/overlay_shell.py` | +2 / −2 | 注释与空行（本轮改回：参数穿透方案被 `muted()` 取代，见 §三之四） |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_bubble_voice.py` | **新增 231 行 / 14 例** | 关着时零行为、碎片跳过、去重窗口内/外、3 句上限、Markdown 清洗、忙等后按句滴灌、`show_text` 默认提交 / `muted()` 不提交 / 退出即复位、嵌套静音、无朗读器时 `report()` 空操作、装/卸摘挂、六条自带朗读链路的让位标记存在性、设置保存 → 壳留住通道并装上汇合点（死开关守卫） |
| `tests/test_config_schema.py` | +4 / −0 | 新键进两份快照（默认值 + reload 白名单），白名单 162 → 163，带日期注释 |

### 未改动（明确不做）

- 不新增任何音色 / 语速 / 音量键：这些是音频通道级真值（`voice_chime_*` 与各 provider 字段），
  气泡朗读与报时共用一套；
- 不给 `show_bubble` / `show_text` 加 `voice=` 形参（见 §三之四的取舍）；
- 不做流式边收边念（`ChatService.delta` 的增量改写是另一个问题域，见
  `PR-REPORT-CHAT-REPLY-VOICE-2026-10-20.md` §五）；
- 不改 `VoiceChimeService.speak()` 的排队语义（深度 1 新覆盖旧）。

## 三、实现要点

### 1. 为什么切口是 `show_text` 而不是逐功能接线

实测所有气泡的最后落点只有一处：`window.show_bubble`、`overlay_shell._show_bubble_text_for`、
`window_alerts._show_item_on`、`divination/festival/chime` 的直写、`sprite_bubble.show`
——全部经 `PetSpeechBubble.show_text()`。逐功能接线意味着"每加一个功能就补一次"，
而漏掉的那一次只会表现为"某个功能只有字没有声"，没有任何报错。汇合点反过来：
新功能天然获得朗读。

### 2. 复用 `ChatReplyReader` 而不是重写队列

音频通道待播槽深度 1 且**新覆盖旧**，一次塞三句只剩最后一句。`ChatReplyReader`
已有：按句滴灌、忙时等 `channel_idle`、`generation` 让迟到的延迟回调作废。
气泡口径只多两件事——**上限**（3 句 / 120 字）与**去重**——所以本模块是子类：
`_split()` 加上限，`submit()` 做去重后调 `feed()`。`feed()` 的"新回复覆盖旧队列"
语义对气泡同样成立：旧气泡在屏上已被盖掉，接着念它等于念用户看不到的内容。

### 3. 让位为什么用上下文而不是形参

第一版给 `show_text` / `show_bubble` / `sprite_bubble.show` 加了 `voice=False`，跑相关族
**34 个用例红**：全部是测试替身（`_Win` / `_Host` / 假 follower）签名对不上。更要紧的是
产品面：要让一条"我自己念过了"的标记穿过 legacy 窗口 → overlay 壳 → sprite 跟随器三层，
任何一层漏传都会静默退回"念两遍"。

改成模块级计数器 `_mute_depth` + `muted()` 上下文：所有调用都在 GUI 线程且同步完成，
进出用 `try/finally` 配对，嵌套安全。六个调用点各自包一层，签名零变化，替身零改动。
代价是它是个进程级全局——本文件已把这条约束写在 `_mute_depth` 的注释里。

### 4. 谁让位、谁接管

规则统一为「**自己带朗读开关的功能，开关开着时自己念，关着时交给气泡朗读**」：

| 链路 | 自己念的开关 | 开关关着时 |
|---|---|---|
| 报时 | 无独立开关（`voice_chime_enabled` 即播报） | 气泡朗读也不念（这条气泡就是报时本身的展示） |
| 节日 | `festival_reminder_speak` | 气泡朗读念 |
| 每日一签 | `divination_speak` | 气泡朗读念 |
| 待办 | `todo_reminder_speak` | 气泡朗读念 |
| 点击台词 | `self_talk_speak_enabled` | 气泡朗读念 |
| 歌词 | —— | 永不念（不是桌宠在说话） |

### 5. 去重与标题

- 去重键 = 清洗后的整段文本，窗口 8 秒；表在每次 `submit` 顺手清理过期项，
  不会随运行时长增长。
- 有副标题（"标题 + 正文"结构）时**标题先念**：`subtitle + "。" + text` 一起清洗再切句，
  与用户看到的阅读顺序一致。

## 四、性能分析

**环境**：Windows 11 x64、Python 3.12.7、PySide6 6.10.1、`QT_QPA_PLATFORM=offscreen`。
**命令/样本**：`BubbleVoice.submit()` 直接调用（假通道 + 假定时器，n=2000 取均值；
开关关着那一档 n=5000）。

| 输入 | 结果 | 单次成本 |
|---|---|---|
| 20 字（自言自语） | 1 句 | **9.8 µs** |
| 40 字（提醒/余额） | 2 句 | **12.7 µs** |
| 约 400 字（识屏结果） | 截到 3 句 / 120 字 | **57.2 µs** |
| 开关关着（`report()` 直返） | 无 | **0.08 µs** |

逐条回答四问：

- **稳态开销**：关着时零。`report()` 只做 `_mute_depth`/`_router` 两次判断
  （上表 0.08 µs），不建对象、不建队列、不建定时器；`AppShell._bubble_voice_wanted()`
  每次设置保存多一次 `config.get`。
- **新增路径成本与频率**：每条**上屏的气泡**一次 `submit`（≤57 µs，GUI 线程），
  随后每句一次网络合成（走既有 `VoiceChimeService.speak` 的缓存与播放路径）。
  极端频率参考：定时自言自语最短间隔 20 s、点击台词与工具状态气泡按用户操作；
  识屏一次 4–12 s 展示期只念前 3 句。没有新增线程、没有新增磁盘写入。
- **内存**：去重表最多 8 秒窗口内的文本（个位数条目，KB 级）；句子队列最坏 3 条短串。
  两者都在 `stop()` 时清空。
- **系统调用**：无新增。合成/播放/缓存命中全部复用通道既有实现；未新增子进程
  （豆包 provider 的 ffmpeg 变调只在用户选豆包且音调 > 0 时发生，与本模块无关）。

**未测**：TTS 端到端延迟（合成首包 + 播放起播）——本机没有可用于验收的音频输出
环境（见 §五），因此**不声称**任何"更快/更省"的结论，只声称文本层成本与上表。

## 五、实机运行记录

**本机真实执行过的**（命令 + 真实输出摘要）：

1. `python -m ruff check pet tests` → **All checks passed!**
2. `python -m pytest tests/test_bubble_voice.py -q` → **14 passed**（首版 10 passed / 2 failed，
   两条都是断言写错：切句保留句末「。」、副标题先念；修正后全绿）
3. 受影响族：
   `test_bubble_voice + test_click_self_talk_speech + test_overlay_self_talk +
   test_voice_chime_service + test_todo_reminder + test_festival` → **296 passed**
4. 设置/架构族：`test_settings_page_guide / test_settings_pet_tabs /
   test_settings_ia_first_cut / test_settings_compat_layering /
   test_settings_search_aliases / test_settings_default_marks /
   test_settings_reset_defaults / test_voice_chime_settings_layout /
   test_desktop_pet_features / test_feature_modules_gating / test_architecture /
   test_background_service_gates` → **371 passed**
5. 配置 schema：`python -m pytest tests/test_config_schema.py -q` → **68 passed**
6. 微基准（§四表）：`python -c` 跑 `BubbleVoice.submit` 三档 + 关档，数字见上表

**为什么"听见声音"这条不能算已验证**：本机是开发用 Python 环境，没有可用于验收的
音频输出与真实桌面会话（测试全程 `QT_QPA_PLATFORM=offscreen`，不构造播放器）；豆包/edge
的合成结果也没有在这里听过。所以本报告**只声称**"哪条气泡该念、该让位、
按什么顺序进通道"这三件事——它们由假通道 + 假时钟驱动，见
`tests/test_bubble_voice.py` 的 `FakeSpeaker` / `FakeScheduler` / `FakeClock`。

**未跑完整的全量套件结论**：全量 `python -m pytest -q` 已在本机启动（`full-suite.log`），
结果见 §七勾选状态；本轮交付以"聚焦 + 受影响族 + 设置/架构族 + schema"为准。

## 六、已知限制

- **每只宠物独立音色**：不做。`voice_chime_*` 是全局真值（与报时共用），
  每宠音色需要新的槽级键与 `ensure_audio_channel` 按槽取配置，属下一轮；
  `voice_owner` 目前只用于日志。
- **气泡与声音的错位**：字先出、声后到（合成首包数百毫秒），未做预合成。
- **长文本只念前 3 句**：识屏/审批的长文可能被截断；需要"只念前 N 句"可配的话是下一个键。
- **图片气泡不出声**：`show_image` 没有可念的文本（配图自言自语默认静音），与既有口径一致。
- **审批气泡会占住通道**：念审批时如果用户立刻点按钮，语音可能仍在播；通道语义是
  "新覆盖旧"，下一条气泡会把剩下的句子顶掉。

## 七、检查清单

- [x] `ruff check pet tests` 全绿
- [x] 本功能 14 例 + schema 68 例 + 受影响族 296 例 + 设置/架构族 371 例 + 语音相关族 1150 例
- [x] 配置 schema 两份快照同步（白名单 162 → 163，带日期注释）
- [x] 让位标记有源码级守卫（漏一处即红）
- [x] `docs/INDEX.md` 登记 + `SETTINGS-CHANGE-GATES.md` 变更记录
- [ ] 真实出声验收（**未验**：本机无音频验收环境，理由见 §五）
- [ ] 设置页视觉验收（沿用 `SettingRow`/`ToggleSwitch`，未做截图比对）
- [ ] 全量 `pytest`（**未跑完**：本机 9000+ 例，预计 >45 min；本轮跑到 3% 后中止，改为按受影响面跑五批：语音/气泡族 296 + 设置/架构族 371 + schema 68 + 语音相关族 1150 + 本功能 14）

## 八、第二轮：音色名可自由输入（同日）

**需求原文**：「还有音色，目前就固定几个希望是我可以自己随便输入的，就是豆包的，
我可以输入火山里的声音名。」

### 修改文件说明（本轮）

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/tts/base.py` | +5 / −0 | `TtsField` 新增 `editable: bool = False`：声明"这个 select 允许自由输入"。默认关——只有清单天然滞后的字段才开 |
| `pet/tts/doubao.py` | +4 / −1 | 豆包音色字段 `editable=True` + placeholder「填火山控制台里的音色名」；提示改成「豆包 2.0 音色，可自己输入。」（≤20 字，且不含 `uranus` / 错误码等界面禁词） |
| `pet/voice/chime_settings.py` | 本轮约 +72 / −1（整文件相对基线 +84 / −1，含上一轮气泡朗读行） | 新增 `TtsVoiceNameEdit`：文本框（唯一真值）+「常用」下拉（只把名字填进文本框，菜单**只显示中文音色名**）。`_build_field_widget` 对 `select + editable` 走它；`_read_widget` 的 select 分支改成"有 `currentData()` 就读它，否则读 `text()`"——两种控件同一条读路径 |
| `tests/test_tts_voice_name_edit.py` | **新增 95 行 / 6 例** | 声明默认关/豆包开、控件是文本框、常用菜单填值且不露 id、敲进去的名字原样落盘并驱动 `plan`/`flavor`、清空回落默认 |

### 实现要点

- **为什么不用可编辑 QComboBox**：设置页的 `ModernSelect` 是自绘按钮 + 弹层（不是 QComboBox），
  风格统一靠它。可编辑组合框会带一套原生外观与另一套状态（"当前项"与"当前文本"），
  正是双向真值的来源。这里改用「文本框 + 菜单按钮」：文本是唯一真值，菜单只是写入快捷方式。
- **控件对设置页的契约保持同形**：`text()` 读、`setText()` 写。`_read_widget` /
  `apply_to_config` / `_current_field_values` 三处都不需要为新控件加分支。
- **不做白名单校验**：音色名由厂家发布（还会被下架、改名），本地清单永远滞后。
  配置里存什么就发什么；发错了由 provider 的 `synth()` 报回来，服务层照既有降级路径提示。
  这与 `ADDING-A-TTS-PROVIDER.md` 的红线 0（"对配置里已不成立的东西必须兜底"）不冲突：
  豆包音色的有效性只能在联网合成时才知道，`preflight()`（不许联网）无从判断。
- **界面禁词仍然生效**：`tests/test_voice_chime_settings_layout.py` 会扫每一行的
  label + hint，`uranus` / `55000000` / `接口` / `错误码` 一律不许出现——本轮提示文案
  按这条改了两遍（首版 36 字且带技术细节，被既有测试当场拦下）。
- **换音色 = 换缓存键**：`flavor()` 本来就含 speaker，自定音色自动不同键；
  测试里显式钉了一条，防以后有人把 flavor 改成只看后端。

### 性能分析（本轮）

纯字符串与控件装配，无新增 IO/线程/定时器：

| 动作 | 成本 |
|---|---|
| `TtsVoiceNameEdit.text()` | 一次 `QLineEdit.text().strip()`（Python 层 < 1 µs） |
| 设置页构造时多一个文本框 + 一个菜单按钮 | 与原来的 `ModernSelect` 同量级（菜单项 6 条） |
| 保存时读控件 | 走既有 `_read_widget`，无额外分支开销 |
| 运行时合成 | 与本轮无关：`plan()` 只是把字符串搬进请求体 |

### 实机运行记录（本轮）

1. `python -m pytest tests/test_tts_voice_name_edit.py -q` → **6 passed**
   （首跑 5 passed / 1 failed：断言漏了 `config.save()`，补上与设置窗同一条落盘路径后全绿）
2. 语音相关族：`test_voice_chime_settings_layout + test_voice_chime_mimo +
   test_voice_chime + test_voice_chime_service + test_architecture +
   test_settings_page_guide + test_config_schema + test_bubble_voice` → **448 passed**
3. `python -m ruff check pet tests` → **All checks passed!**
4. 被既有测试拦下的两次（如实登记）：首版提示 36 字、含 `uranus`，`test_field_copy_is_human_and_short`
   与 `test_page_never_teaches_technical_details` 同时红；改文案后又因为丢了「豆包 2.0」
   让 `test_search_reveals_a_row_inside_a_folded_backend` 搜不到，最终定稿为
   「豆包 2.0 音色，可自己输入。」（16 字，含搜索关键词）

**未验**：真实合成（拿自定义音色名去火山接口）——本机没有可用的豆包 Key 与音频输出；
菜单/文本框的视觉未做截图比对。



