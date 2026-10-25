# PR 报告：流式边收边念（2026-10-25）

> **基线**：`main` 快照（zip 解包，无 `.git`；numstat 用原快照做 `git diff --no-index`）
> **分支**：`feat/chat-stream-voice`　**日期**：`2026-10-25`
> **范围**：3 个文件（实现 2、测试 1；新增 `tests/test_chat_stream_voice.py`）
> **关联**：[`PR-REPORT-CHAT-REPLY-VOICE-2026-10-20.md`](PR-REPORT-CHAT-REPLY-VOICE-2026-10-20.md)（同一个朗读器的整段路径）、
> [`PR-REPORT-BUBBLE-VOICE-2026-10-25.md`](PR-REPORT-BUBBLE-VOICE-2026-10-25.md)（复用同一继承链的气泡朗读）

## 一、核心特性

**需求**：「流式边收边念」——不要等整段回复生成完才开口，模型吐出一句就念一句。

**改动前**：朗读器只订阅 `ChatService.register_global_finished`，整段回复落地后才切句、合成、
播放。一条 800 字的回复要等模型全部生成完 + 第一句合成完才开始出声（首字延迟 = 整段生成时间）。

**改动后**：新增进程级「增量」订阅（`ChatService.register_global_delta`），朗读器按**句边界**
边收边切、边切边念。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 增量订阅 | `ChatService` 增加 `register_global_delta(cb)` / `unregister_global_delta(cb)`，与 `finished` 同一纪律：类级列表、只在 GUI 线程回调、异常逐个吞掉 |
| 2 | 按句开口 | 增量进缓冲，只把**已经成句**的部分送去合成；半句留在缓冲等下一个增量——逐 token 合成会把网络往返乘几十倍，还会念出"总之，我们需要"这种半句 |
| 3 | 整段只念一次 | `finished` 到达时只补缓冲尾巴；这一轮已经从增量念过就**绝不**再整段重念（老路径会重念，是本刀最容易踩的重复出声） |
| 4 | 非流式后端不变 | 一次增量都没来过（非流式 provider / 旧 ChatService / 极短回复）→ 走原来的整段 `feed`，行为与改动前逐字一致 |
| 5 | 代码不念 | Markdown 围栏内的内容整段丢弃；围栏前那句引言（"下面这段代码："）照念 |
| 6 | 有上限 | 缓冲超过 160 字还没句末标点（长英文串 / 代码）→ 按就近标点硬切，避免"等了整段才开口" |
| 7 | 新一轮覆盖旧一轮 | `request_id` 变了就丢掉旧缓冲与旧队列，与通道"新覆盖旧"同口径 |

**红线 / 不变量**：

- 通道仍是唯一出声路径（`VoiceChimeService.speak`），不新起播放器；
- 开关仍是**已有的** `chat_reply_voice_enabled`，不新增配置键、不改默认值；
- 关着时不订阅增量、不建缓冲（`on_delta` 第一行现读开关）；
- 不在流式里念思考过程（`activity` 是另一条信号，本模块不订阅）。

## 二、修改文件说明

`git diff --no-index --numstat`（原快照 vs 当前工作树）：

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/chat/service.py` | +18 / −1 | 新增 `_global_delta_listeners` 与 `register_global_delta` / `unregister_global_delta`；`_delta()` 在 emit 之后逐个回调（异常吞掉，订阅方崩了不许影响对话）。与 `_global_finished_listeners` 完全同构，评审一眼能对上 |
| `pet/chat_reply_voice.py` | +159 / −5 | ① 新增纯函数 `take_stream_sentences()` + `STREAM_MAX_BUFFER` / `_STREAM_SENTENCE_END` / `_FENCE_MARKS`：围栏感知的增量切句；② `ChatReplyReader` 增加流状态（`_stream_rid/_stream_buffer/_stream_spoke`）与 `on_delta` / `on_finished` / `_begin_stream` / `_drain_stream` / `_flush_stream`；③ `start/stop` 同时订阅/退订 finished 与 delta（`register_global_delta` 不存在时静默跳过，兼容旧宿主）；④ 原有 `feed()` 与 `_split()` 不动（整段路径与气泡子类都靠它） |
| `tests/test_chat_stream_voice.py` | **新增 153 行 / 11 例** | 纯函数四例（只切完整句、围栏丢弃、半截围栏整段吞、超限硬切）；增量三例（句号即开口、finished 只补尾巴、绝不重念整段）；非流式一例；新一轮覆盖一例；开关关零动作一例；订阅面同时挂 finish+delta 一例 |

### 未改动（明确不做）

- 不新增设置键、不改设置页（沿用「助手回复朗读」那一个开关）；
- 不动 `feed()` 的"新回复覆盖旧队列"语义（气泡朗读子类依赖它）；
- 不念 `activity`（思考过程 / 联网进度）——那是 UI 状态，不是要说给用户听的话；
- 不做"停下来的回复继续念"：用户点停止即 `stopped`，本轮不再有 finished，缓冲自然作废。

## 三、实现要点

### 1. 为什么不按 token 念

一次合成一句 vs 一次合成一个 token：后者把 TTS 的网络往返乘上几十倍（一句 20 token），
而且每段只有半个词，合成出来断句、连读都是错的。按句边界切是**唯一**既省请求又自然的粒度。

### 2. 句边界怎么找：只认句末标点

`take_stream_sentences()` 在缓冲上扫一遍，遇到 `。！？!?；;…\n` 就切一句，其余留在
`remainder` 等下次。**不**用"长度到了就切"——那会切在词中间；长度只作为**兜底上限**
（160 字仍无标点时才按就近标点硬切）。

### 3. 代码围栏：进围栏先念引言，围栏内整段丢

流式里代码是最容易出事的地方：半截代码会被念成一串符号。处理方式是显式状态机：

- 进入围栏（` ``` ` / `~~~`）时，先把围栏前的半句当一句送出去（"下面这段代码："）；
- 围栏内字符全部跳过；
- 缓冲停在**半个围栏标记**上时按"还在正文"处理——下一个增量补齐后才真正进围栏，
  不会把两个反引号念出来；
- 到结束时仍未闭合（用户中断）→ `remainder` 直接作废，不把代码当正文念。

### 4. 只念一次的保证

`finished` 与增量是两条信号，最容易出的 bug 是 finished 再把整段念一遍。判断依据是
`_stream_rid is not None`（这一轮来过增量）：

- 来过 → `_flush_stream()`：只把缓冲尾巴切句入队；若尾巴为空且这一轮**已经念过**
  （`_stream_spoke`）→ 什么都不做；
- 没来过 → 退回 `feed(full_text)`（老路径）。

### 5. 新一轮覆盖

`on_delta` 第一件事是比较 `request_id`；不同就 `_begin_stream()`：换 id、清缓冲、
清队列、`_generation += 1`（让上一轮还在飞的 `QTimer` 回调作废）。这与 `feed()` 的
"新回复覆盖旧队列"同口径——用户听到的永远是最新那一轮。

## 四、性能分析

**环境**：Windows 11 x64、Python 3.12.7、PySide6 6.10.1、`QT_QPA_PLATFORM=offscreen`。
**命令/样本**：`timeit`，1100 字回复（约 110 个 10 字增量），n=200（流式）/ 500（整段）。

| 路径 | 结果 | 单次成本 |
|---|---|---|
| 整段切句 `split_sentences`（改动前就有） | 1100 字 | **0.097 ms / 次** |
| 流式整轮：110 个增量各扫一遍缓冲 | 1100 字 / 110 次 | **1.11 ms / 整轮** |
| 单个增量均值 | 约 10 字 | **0.0096 ms / 次** |

逐条回答四问：

- **稳态开销**：关着时零。`on_delta` 第一行读开关（一次 `config.get`）就 return，
  不建缓冲、不改队列；`on_finished` 同一判据。
- **新增路径成本与频率**：每个增量一次 `take_stream_sentences`（单次约 0.01 ms，扫的是
  **当前未成句的尾巴**，不是整段），每句一次 `speak()`（走既有合成/缓存/播放路径）。
  频率 = 模型吐字频率（约每 10–50 ms 一个增量），成本比渲染那一帧还低。
- **内存**：缓冲只存"还没成句的尾巴"，上限 160 字（约 0.3 KB）；达到上限即硬切。
  句子队列最大同时几句（受通道滴灌约束），不随回复长度增长。
- **系统调用**：无新增。合成的网络请求数由"整段一次/几句"变成"每句一次"，但总字符数
  不变、缓存键不变——对 edge/豆包都是按字符计费，**费用不升**，只是请求更早发出。

**未测**：首字出声延迟的真实收益（需要真实模型 + 真实 TTS 端到端计时；本机没有可验收的
音频输出环境）。因此**不声称**"快了 N 秒"，只给出上表的文本层开销。

## 五、实机运行记录

**本机真实执行过的**（命令 + 真实输出摘要）：

1. `python -m pytest tests/test_chat_stream_voice.py -q` → **11 passed**（一次通过）
2. 聊天/朗读相关族：
   `test_chat_stream_voice + test_chat_reply_voice + test_bubble_voice +
   test_chat_service + test_chat_shared_behavior + test_chat_safe_emit +
   test_chat_subsystem + test_quick_chat + test_island_chat +
   test_island_chat_identity + test_architecture + test_chat_memory +
   test_chat_memory_extract` → **371 passed / 1 skipped**
3. 同一批里唯一的红是环境问题：`test_secret_store_rejects_a_subclass_of_the_fail_backend`
   因本机没装 `keyring` 报 `ModuleNotFoundError`；装上 `keyring 25.7.0` 后
   `test_chat_subsystem` **149 passed / 1 skipped**
4. `python -m ruff check pet tests` → **All checks passed!**
5. 微基准（§四表）：`python -c` 跑整段切句与 110 个增量的流式切句

**为什么"边收边念"这条不能算端到端已验证**：本机没有可用的音频输出与真实模型流
（测试全程 `QT_QPA_PLATFORM=offscreen`，朗读器用假通道 + 假定时器）。本报告只声称
"哪一段该在什么时候进队列、整段是否只念一次"——这两件事由
`tests/test_chat_stream_voice.py` 的 `FakeChannel` / `FakeScheduler` 驱动。

## 六、已知限制

- **只有流式后端才有收益**：非流式（或旧宿主没有 `register_global_delta`）自动退回整段，
  行为与改动前一致。
- **首句仍要等一句**：模型吐到第一个句号才能开口；极短的回复（一句到底）＝整段念。
- **代码块静默跳过**：流式路径不念"代码略"占位（整段路径会念）。用户看到字在流，
  听不到代码，属有意取舍。
- **多轮并发**：`ChatService.send()` 本来就会 `stop()` 上一轮，所以"同时两轮"不存在；
  新 `request_id` 到达即覆盖旧缓冲。
- **未做**：逐字高亮与朗读同步（字幕跟着念到哪），需要另一条"播放进度"回传链路。

## 七、检查清单

- [x] `ruff check pet tests` 全绿
- [x] 本功能 11 例 + 聊天/朗读相关族 371 例（+ 子系统 149 例复跑）
- [x] 不新增配置键、不改设置页、不改默认值（无 schema 快照变更）
- [x] 整段路径/气泡子类的既有用例原样全绿（`test_chat_reply_voice` 10 例、`test_bubble_voice` 14 例）
- [x] `docs/INDEX.md` 登记
- [ ] 真实端到端听感（**未验**：本机无音频验收环境，理由见 §五）
- [ ] 全量 `pytest`（**未跑**：9000+ 例，预计 >45 min；按受影响面替代，理由同上一份报告）
