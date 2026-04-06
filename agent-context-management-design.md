# Agent 上下文管理与召回体系设计方案

> **版本:** 1.0
> **日期:** 2026-04-06
> **作者:** Agent Development Team

---

## 1. 设计目标

构建一套**基于文件存储的 Agent 上下文管理与召回体系**，实现以下核心目标：

1. **对话持久化**：每次用户对话后自动存储（摘要 + 原文）
2. **智能召回**：对话中基于摘要快速召回，必要时精准召回原文
3. **上下文压缩**：当上下文接近溢出（80%）时自动压缩，与 Claude Code 内置压缩逻辑协同工作

---

## 2. 整体架构

### 2.1 架构概览

```
Conversation Flow                           Storage Layer
┌───────────────────┐                      ┌─────────────────────────┐
│  Agent Core       │                      │  File System Store        │
│                   │                      │                         │
│  ┌─────────────┐  │  ┌──────────────┐    │  ┌───────────────────┐  │
│  │  Pre-Recall │──┼─▶│ Recall Engine│───▶│  │ summaries/        │  │
│  │  (摘要召回)  │  │  │              │    │  │   YYYYMMDD_HHmm.md│  │
│  └─────────────┘  │  └──────────────┘    │  └───────────────────┘  │
│                   │                      │                         │
│  ┌─────────────┐  │                      │  ┌───────────────────┐  │
│  │ Conversation│  │                      │  │ transcripts/      │  │
│  │   Handler   │  │                      │  │   YYYYMMDD_HHmm.md│  │
│  └──────┬──────┘  │                      │  └───────────────────┘  │
│         │         │                      │                         │
│  ┌──────▼──────┐  │  ┌──────────────┐    │  ┌───────────────────┐  │
│  │ Post-Store  │──┼─▶│ Store Engine │───▶│  │ index.json         │  │
│  │ (存储触发)   │  │  │              │    │  │  (语义索引)        │  │
│  └─────────────┘  │  └──────────────┘    │  └───────────────────┘  │
│                   │                      │                         │
│  ┌─────────────┐  │                      │  ┌───────────────────┐  │
│  │ Context     │  │                      │  │ compression_log.md │  │
│  │ Monitor     │  │                      │  │  (压缩历史)        │  │
│  │ (80%阈值)   │  │                      │  └───────────────────┘  │
│  └─────────────┘  │                      └─────────────────────────┘
└───────────────────┘
```

### 2.2 核心模块

| 模块 | 职责 | 优先级 |
|------|------|--------|
| **Store Engine** | 对话结束后存储摘要+原文到文件 | P0 |
| **Recall Engine** | 基于摘要召回补充上下文，必要时召回原文 | P0 |
| **Context Monitor** | 监控上下文使用率，80% 触发压缩 | P0 |
| **Index Builder** | 维护语义索引，支持快速检索 | P0 |

---

## 3. 文件系统设计

### 3.1 目录结构

```
~/.openclaw/workspace/context-store/
├── summaries/                    # 摘要存储
│   ├── 20260406_143021.md       # 单轮对话摘要
│   ├── 20260406_143045.md
│   └── ...
├── transcripts/                  # 原文存储
│   ├── 20260406_143021.md       # 单轮对话原文
│   ├── 20260406_143045.md
│   └── ...
├── index.json                    # 语义索引（核心检索入口）
├── compression_log.md            # 压缩操作日志
└── active_summaries.md           # 当前活跃会话摘要汇总
```

### 3.2 摘要文件格式

```markdown
# 对话摘要 - YYYY-MM-DD HH:mm:ss

## 元信息
- **会话ID:** `<session_id>`
- **轮次ID:** `<turn_id>` (如 turn_001, turn_002)
- **时间戳:** `2026-04-06T14:30:21Z`
- **原文路径:** `transcripts/20260406_143021.md`
- **关键词:** `["关键词1", "关键词2", ...]`
- **主题:** `主题分类`
- **Token 估算:** `<user_tokens> / <assistant_tokens>`

## 摘要内容
[AI 生成的 2-3 段摘要]

## 关键决策/行动项
- 决策1
- 行动项1

## 语义指纹
[用于向量匹配的关键词/短语列表，用于快速召回]
- semantic_tag_1
- semantic_tag_2
```

### 3.3 原文文件格式

```markdown
# 对话原文 - YYYY-MM-DD HH:mm:ss

## 元信息
- **会话ID:** `<session_id>`
- **轮次ID:** `<turn_id>`
- **时间戳:** `2026-04-06T14:30:21Z`

## 用户输入
[完整用户消息内容]

## 附件/工具调用
[工具调用记录、文件引用等]

## 助手回复
[完整助手回复内容]
```

### 3.4 语义索引格式 (index.json)

```json
{
  "version": "1.0",
  "updated_at": "2026-04-06T14:30:21Z",
  "conversations": {
    "<session_id>": {
      "created_at": "2026-04-06T14:00:00Z",
      "turns": [
        {
          "turn_id": "turn_001",
          "timestamp": "2026-04-06T14:00:10Z",
          "summary_path": "summaries/20260406_140010.md",
          "transcript_path": "transcripts/20260406_140010.md",
          "tokens": 4500,
          "keywords": ["agent设计", "上下文管理", "文件存储"],
          "topics": ["architecture", "context-management"],
          "semantic_fingerprint": "agent context file-storage session turn",
          "compressed": false,
          "compression_summary_path": null
        }
      ],
      "total_tokens": 4500,
      "last_activity": "2026-04-06T14:00:15Z"
    }
  }
}
```

---

## 4. 核心模块详细设计

### 4.1 Store Engine — 对话后存储

#### 4.1.1 触发时机

存储引擎在**每轮对话完成时**自动触发：

```
用户输入 → Agent处理 → 助手回复完成 → 触发存储
```

#### 4.1.2 存储流程

```
turn_complete
     │
     ├── 1. 生成摘要（调用 LLM 生成 2-3 段摘要）
     │      │
     │      ├── 提取关键决策/行动项
     │      ├── 生成语义指纹（关键词列表）
     │      └── 估算 token 数量
     │
     ├── 2. 保存摘要文件
     │      └── summaries/YYYYMMDD_HHmmss.md
     │
     ├── 3. 保存原文文件
     │      └── transcripts/YYYYMMDD_HHmmss.md
     │
     ├── 4. 更新语义索引
     │      └── index.json (追加新条目)
     │
     └── 5. 更新活跃摘要汇总
            └── active_summaries.md (追加最近 N 轮摘要)
```

#### 4.1.3 摘要生成 Prompt

```
你是一个专业的对话分析助手。请根据以下对话轮次生成摘要。

### 用户输入
{user_message}

### 助手回复
{assistant_response}

### 请输出以下格式的摘要（严格遵守格式）：

## 摘要内容
[2-3 段精准概括，包含核心意图、关键信息、重要决策]

## 关键决策/行动项
[列出具体决策和后续行动项，如果没有则写"无"]

## 语义指纹
[8-15个关键词/短语，用于后续语义匹配召回，一行一个]

要求：
1. 摘要要精炼，不超过 200 字
2. 语义指纹要覆盖技术关键词和主题关键词
3. 行动项要具体可执行
```

### 4.2 Recall Engine — 对话中召回

#### 4.2.1 召回策略

采用**两级召回架构**：

```
新对话输入
    │
    ├── 一级召回：基于摘要（常规触发）
    │     │
    │     ├── 关键词匹配：从 index.json 中匹配相关轮次
    │     ├── 时间衰减：近 1 小时的对话权重更高
    │     ├── 会话连续：同一 session 的最近 3 轮自动召回
    │     └── 输出：匹配轮次的摘要内容
    │
    └── 二级召回：原文（必要时触发）
          │
          ├── 触发条件（满足任一）：
          │   1. 用户显式提及之前的内容（"之前说的…"、"刚才的…"）
          │   2. 一级召回置信度低于阈值（< 0.6）
          │   3. 用户问具体问题而非一般性上下文
          │   4. 匹配到代码/文件引用相关的对话
          │
          └── 输出：匹配轮次的完整原文
```

#### 4.2.2 召回算法

```python
def recall_context(user_input: str, session_id: str, 
                    mode: RecallMode = RecallMode.AUTO) -> RecallResult:
    """
    召回上下文，支持自动/摘要/原文三种模式
    
    Args:
        user_input: 当前用户输入
        session_id: 当前会话ID
        mode: 召回模式 (AUTO / SUMMARY / TRANSCRIPT)
    
    Returns:
        RecallResult: 召回的上下文片段
    """
    # 步骤1：从 index.json 加载索引
    index = load_index()
    
    # 步骤2：一级召回 — 摘要级别
    user_tokens = tokenize(user_input)
    candidates = []
    
    for session_convo in index["conversations"].values():
        for turn in session_convo["turns"]:
            score = compute_relevance(
                user_tokens,
                turn["keywords"] + turn["semantic_fingerprint"].split(),
                turn["timestamp"],
                turn["session_id"] == session_id  # 同会话加权
            )
            if score > SUMMARY_THRESHOLD:  # 0.4
                candidates.append((score, turn, "summary"))
    
    # 步骤3：判断是否需要二级召回
    if mode == RecallMode.TRANSCRIPT or _should_recall_transcript(user_input, candidates):
        transcript_candidates = []
        for score, turn, _ in candidates:
            if score > TRANSCRIPT_THRESHOLD:  # 0.6
                transcript_content = read_file(turn["transcript_path"])
                transcript_candidates.append((score, transcript_content))
        return RecallResult(summaries=candidates, transcripts=transcript_candidates)
    
    # 步骤4：仅返回摘要
    return RecallResult(summaries=candidates, transcripts=[])


def compute_relevance(user_tokens: list, doc_tokens: list, 
                      timestamp: str, same_session: bool) -> float:
    """
    计算相关度得分
    
    组成部分：
    - 关键词重叠度 (Jaccard):  0.4 权重
    - TF-IDF 余弦相似度:      0.3 权重  
    - 时间衰减因子:            0.3 权重
    - 同会话加分:          +0.15
    """
    # Jaccard 相似度
    jaccard = len(set(user_tokens) & set(doc_tokens)) / len(set(user_tokens) | set(doc_tokens))
    
    # 时间衰减 (指数衰减)
    hours_ago = (now() - parse_time(timestamp)).total_seconds() / 3600
    time_decay = exp(-0.5 * hours_ago)
    
    # 最终得分
    score = 0.4 * jaccard + 0.3 * time_decay + 0.3 * compute_tfidf(user_tokens, doc_tokens)
    if same_session:
        score += 0.15
    
    return min(score, 1.0)
```

#### 4.2.3 触发词检测（二级召回）

```python
TRANSCRIPT_TRIGGERS = [
    # 回溯性引用
    "之前", "刚才", "之前说的", "前面提到", "你刚才说", "你之前说",
    "上次说", "我们之前", "上面", "之前那个",
    # 精确内容查询
    "具体内容", "完整", "原文", "代码", "文件内容",
    # 指代性询问
    "那个是什么", "具体是什么", "详细内容", "详细说",
]

def _should_recall_transcript(user_input: str, 
                               summary_results: list) -> bool:
    """判断是否需要升级到原文召回"""
    # 条件1：触发词检测
    for trigger in TRANSCRIPT_TRIGGERS:
        if trigger in user_input:
            return True
    
    # 条件2：一级召回置信度过低
    if summary_results:
        top_score = max(score for score, _, _ in summary_results)
        if top_score < TRANSCRIPT_THRESHOLD:
            return True
    
    # 条件3：用户明确要求
    if any(word in user_input for word in ["全文", "完整对话", "原始记录"]):
        return True
    
    return False
```

### 4.3 Context Monitor — 上下文监控与压缩

#### 4.3.1 上下文使用率监控

```python
CONTEXT_THRESHOLD_WARNING = 0.70  # 70% 预警
CONTEXT_THRESHOLD_COMPRESS = 0.80  # 80% 触发压缩
MODEL_MAX_CONTEXT = 200_000  # Claude Sonnet 的上下文窗口

class ContextMonitor:
    def __init__(self, model: str = "claude-sonnet-4.6"):
        self.max_tokens = MODEL_MAX_CONTEXT
        self.current_tokens = 0
        
    def estimate_context_tokens(self, conversation: list) -> int:
        """
        估算当前上下文的 token 数
        包括：system prompt + 历史消息 + 工具调用 + 召回内容
        """
        total = 0
        for msg in conversation:
            total += count_tokens(msg["content"])
            if "tool_calls" in msg:
                total += count_tokens(str(msg["tool_calls"]))
        return total
    
    def check_and_compress(self, conversation: list) -> CompressResult:
        """
        检查上下文使用率，超过 80% 时触发压缩
        """
        self.current_tokens = self.estimate_context_tokens(conversation)
        usage_ratio = self.current_tokens / self.max_tokens
        
        if usage_ratio >= CONTEXT_THRESHOLD_COMPRESS:
            return self._compress(conversation)
        elif usage_ratio >= CONTEXT_THRESHOLD_WARNING:
            return CompressResult(action="warn", ratio=usage_ratio)
        
        return CompressResult(action="none", ratio=usage_ratio)
```

#### 4.3.2 压缩策略 — 与 Claude Code 协同

Claude Code 的上下文压缩机制（已知行为）：
- Claude Code 在内部会自动将早期消息压缩为摘要
- 压缩是透明的，用户看到的是压缩后的摘要而非原始消息
- 压缩触发时机由 Claude Code 自主判断，通常与上下文窗口使用率相关

我们的设计与 Claude Code 协同工作：

```
┌────────────────────────────────────────────────────────┐
│              Context Compression Pipeline              │
├────────────────────────────────────────────────────────┤
│                                                        │
│  当前上下文 (80%+)                                      │
│       │                                                │
│       ▼                                                │
│  ┌──────────────────────────┐                          │
│  │ 第1层: 早期对话压缩       │ ◄── Claude Code 自动处理│
│  │ (最早期的消息 → 摘要)     │    这部分不需要我们干预  │
│  └──────────┬───────────────┘                          │
│             │                                          │
│             ▼                                          │
│  ┌──────────────────────────┐                          │
│  │ 第2层: 历史对话归档       │ ◄── 我们的 Store Engine │
│  │ (外部文件中的对话已存储， │    负责从 LLM 上下文中   │
│  │  可以从上下文中移除摘要)  │    移除已过时的召回内容  │
│  └──────────┬───────────────┘                          │
│             │                                          │
│             ▼                                          │
│  ┌──────────────────────────┐                          │
│  │ 第3层: 活跃摘要精简       │ ◄── 我们的 Recall Engine│
│  │ (保留最近 3-5 轮的摘要，  │    智能控制召回量        │
│  │  更早的仅保留索引)        │                          │
│  └──────────┬───────────────┘                          │
│             │                                          │
│             ▼                                          │
│  ┌──────────────────────────┐                          │
│  │ 压缩后上下文              │ ◄── 控制在 60% 以内     │
│  │ (目标: < 60% 使用率)      │                          │
│  └──────────────────────────┘                          │
└────────────────────────────────────────────────────────┘
```

#### 4.3.3 压缩算法

```python
def compress_context(conversation: list, 
                     store_engine: StoreEngine) -> CompressedContext:
    """
    上下文压缩算法
    
    策略：
    1. 最早期的对话（> 10 轮前）→ 从上下文中移除（已存入文件）
    2. 中间对话 → 仅保留一级摘要（移除原文召回）
    3. 最近对话（最近 3-5 轮）→ 保留完整
    4. 活跃摘要汇总 → 保留 active_summaries.md 的前 5 条
    
    压缩后通过 index.json 保持对全部历史的可召回能力
    """
    compressed = []
    
    # 保留 system message
    for msg in conversation:
        if msg["role"] == "system":
            compressed.append(msg)
            break
    
    # 保留最近的 N 轮完整对话
    recent_turns = conversation[-8:]  # 最近 4 轮对话 (user+assistant)
    
    # 对于更早的对话，仅生成压缩摘要
    older_turns = conversation[1:-8]
    if len(older_turns) > 0:
        # 生成压缩摘要
        summary = generate_compression_summary(older_turns)
        compressed.append({
            "role": "system",
            "content": f"[上下文压缩摘要 - 包含 {len(older_turns)//2} 轮对话的浓缩信息]\n{summary}"
        })
    
    # 合并最近对话
    compressed.extend(recent_turns)
    
    return {
        "compressed_context": compressed,
        "archived_turns": len(older_turns) // 2,
        "compression_ratio": 1 - (len(compressed) / len(conversation)),
        "log_entry": format_compression_log()
    }
```

#### 4.3.4 压缩日志格式

```markdown
# 上下文压缩日志

| 时间 | 触发前使用率 | 压缩后使用率 | 归档轮次 | 方式 |
|------|-------------|-------------|---------|------|
| 2026-04-06 14:30 | 82% | 58% | 12 | 分级压缩 |
| 2026-04-06 15:15 | 81% | 62% | 8 | 摘要压缩 |

## 压缩详情

### 2026-04-06 14:30 - 分级压缩
- **触发原因:** 上下文使用率达到 82%
- **操作:**
  - 归档 8 轮早期对话 → 外部文件存储
  - 4 轮中间对话 → 保留摘要
  - 保留最近 4 轮完整
- **结果:** 124,000 tokens → 116,000 tokens (58%)
```

---

## 5. 与 Claude Code 的集成设计

### 5.1 集成方式

由于 Claude Code 的上下文管理是其内部机制，我们通过**钩子 + 显式控制**的方式进行协同：

```yaml
# settings.json 中配置 hooks
{
  "hooks": {
    "PostToolUse": {
      "matcher": ".*",
      "hooks": [
        {
          "type": "exec",
          "command": "python context_manager.py --store-after-turn"
        }
      ]
    },
    "PreUserMessage": {
      "matcher": ".*",
      "hooks": [
        {
          "type": "exec", 
          "command": "python context_manager.py --recall-context '{user_input}'"
        }
      ]
    },
    "PreResponse": {
      "matcher": ".*",
      "hooks": [
        {
          "type": "exec",
          "command": "python context_manager.py --check-context-threshold"
        }
      ]
    }
  }
}
```

### 5.2 协同工作流

```
用户发消息
    │
    ├── [PreUserMessage Hook] Recall Engine 召回相关上下文
    │     └── 根据召回级别注入摘要或原文
    │
    ├── Claude Code 处理对话（自动管理内部上下文压缩）
    │
    ├── [PreResponse Hook] Context Monitor 检查使用率
    │     └── 如果 > 80%，触发压缩（精简召回内容和旧对话摘要）
    │
    ├── Claude 生成回复
    │
    └── [PostToolUse Hook] Store Engine 存储当前轮次
          ├── 生成摘要
          ├── 保存原文
          └── 更新索引
```

### 5.3 关键设计决策

| 问题 | 方案 | 原因 |
|------|------|------|
| 谁来生成摘要 | LLM 生成 | 需要理解语义才能生成高质量摘要 |
| 谁来监控上下文 token | 基于估算 | 准确的 token 数需要 LLM API，用 tiktoken 库估算 |
| 压缩 vs Claude Code 内部压缩 | 互补而非冲突 | Claude Code 处理内部消息压缩，我们处理外部存储召回管理 |
| 召回原文还是摘要 | 两级自动 | 默认摘要，必要时原文 |
| 存储格式 | Markdown | 人类可读，易于调试 |
| 索引格式 | JSON | 便于程序解析和更新 |

---

## 6. 核心数据流

### 6.1 完整数据流图

```
                    ┌─────────────────┐
                    │   用户发送消息    │
                    └────────┬────────┘
                             │
              ┌──────────────▼──────────────┐
              │   PreUserMessage Hook       │
              │                             │
              │   1. 解析用户输入            │
              │   2. RecallEngine.recall()  │
              │   3. 注入相关上下文          │  ◄── 从 index.json 匹配
              └──────────────┬──────────────┘
                             │
                    ┌────────▼────────┐
                    │  Claude 处理对话 │  ◄── Claude Code 自动压缩
                    │  并生成回复      │     内部早期消息
                    └────────┬────────┘
                             │
              ┌──────────────▼──────────────┐
              │   PreResponse Hook          │
              │                             │
              │   1. 估算当前 token 使用率   │
              │   2. 如果 > 80%             │◄── CONTEXT_THRESHOLD_COMPRESS
              │      context.compress()     │
              │   3. 更新 active_summaries  │
              └──────────────┬──────────────┘
                             │
                    ┌────────▼────────┐
                    │ 回复发送给用户   │
                    └────────┬────────┘
                             │
              ┌──────────────▼──────────────┐
              │   PostToolUse Hook          │
              │                             │
              │   1. StoreEngine.store()    │
              │   2. 生成摘要（LLM）         │
              │   3. 保存原文文件            │
              │   4. 更新 index.json         │
              │   5. 追加到 active_summaries│
              └─────────────────────────────┘
```

### 6.2 召回数据流

```
用户输入: "之前那个数据库设计方案是什么来着？"
     │
     ▼
RecallEngine.recall("之前那个数据库设计方案是什么来着？")
     │
     ├── 一级召回: 关键词匹配
     │     ├── 从 index.json 搜索所有 turn 的 keywords + semantic_fingerprint
     │     ├── 匹配 "数据库", "设计", "方案" 关键词
     │     ├── 找到 turn_005 (score=0.82) - "数据库架构设计讨论"
     │     └── 找到 turn_012 (score=0.65) - "数据库迁移方案"
     │
     ├── 二级判定: 是否需要原文
     │     ├── 检测到 "之前那个" → 触发词匹配
     │     └── 决定召回 turn_005 的完整原文
     │
     └── 召回结果:
           {
             "summaries": [
               {"turn_012": "数据库迁移方案摘要"},
             ],
             "transcripts": [
               {"turn_005": "完整的数据库架构设计讨论原文"},
             ]
           }
     │
     ▼
注入到系统消息中
```

### 6.3 压缩数据流

```
PreResponse Hook 触发
     │
     ├── ContextMonitor.check() → 当前 84%
     │
     ├── 压缩策略:
     │     │
     │     ├── 检查哪些召回内容可以移除
     │     │     ├── turn_001 摘要 (20 轮前) → 移除
     │     │     └── turn_005 原文 (8 轮前) → 降级为摘要
     │     │
     │     ├── 重新生成 active_summaries.md
     │     │     └── 保留最近 5 轮摘要
     │     │
     │     └── 记录到 compression_log.md
     │
     └── 结果: 84% → 58%

```

---

## 7. API 设计

### 7.1 核心 API

```python
class ContextManager:
    """
    上下文管理器 - 统一入口
    """
    
    def __init__(self, store_path: str = "~/.openclaw/workspace/context-store/"):
        self.store = StoreEngine(store_path)
        self.recall = RecallEngine(store_path)
        self.monitor = ContextMonitor()
    
    def on_conversation_complete(self, user_input: str, 
                                   assistant_output: str) -> None:
        """对话完成后调用，触发存储"""
        self.store.store_turn(user_input, assistant_output)
    
    def on_new_message(self, user_input: str) -> str:
        """新消息到来时调用，触发召回"""
        return self.recall.recall(user_input)
    
    def on_pre_response(self, conversation: list) -> CompressResult:
        """回复前调用，检查是否需要压缩"""
        return self.monitor.check_and_compress(conversation)
```

### 7.2 CLI 接口 (用于 hooks)

```bash
# 存储当前轮次
python context_manager.py --store-after-turn \
    --user-input "用户输入" \
    --assistant-output "助手回复" \
    --session-id "当前会话ID"

# 召回上下文
python context_manager.py --recall-context "用户新输入" \
    --session-id "当前会话ID" \
    --mode auto  # auto | summary | transcript

# 检查上下文阈值
python context_manager.py --check-context-threshold \
    --current-estimated-tokens 160000

# 手动压缩
python context_manager.py --compress

# 查看索引
python context_manager.py --list-sessions
python context_manager.py --search "关键词"
```

---

## 8. 配置文件

### 8.1 context_config.json

```json
{
  "store_path": "~/.openclaw/workspace/context-store/",
  "summarization": {
    "max_summary_length": 200,
    "model": "claude-haiku-4-5-20251001",
    "prompt_template": "default"
  },
  "recall": {
    "summary_threshold": 0.4,
    "transcript_threshold": 0.6,
    "max_summary_returns": 5,
    "max_transcript_returns": 2,
    "time_decay_factor": 0.5,
    "same_session_bonus": 0.15,
    "auto_mode": true
  },
  "compression": {
    "warning_threshold": 0.70,
    "compress_threshold": 0.80,
    "target_after_compress": 0.60,
    "recent_turns_to_keep": 4,
    "model_max_context": 200000
  },
  "index": {
    "max_index_age_days": 30,
    "auto_cleanup_transcripts_days": 90
  }
}
```

---

## 9. 实现路线图

### Phase 1: 基础存储
- StoreEngine 实现
- 摘要生成逻辑
- 文件系统写入
- 基础 index.json 维护

### Phase 2: 智能召回
- RecallEngine 实现
- 关键词匹配算法
- 触发词检测
- 两级召回策略

### Phase 3: 上下文压缩
- ContextMonitor 实现
- 压缩算法实现
- 压缩日志
- 与 Claude Code hooks 集成

### Phase 4: 优化与测试
- 性能优化
- 端到端测试
- 边界情况处理
- 文档完善

---

## 10. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 摘要生成质量差 | 召回不准确 | 使用更高质量的 prompt，加入人工反馈循环 |
| 文件 I/O 延迟高 | 响应变慢 | 异步写入，摘要生成与回复并行 |
| 索引膨胀 | 搜索变慢 | 定期清理，自动归档旧索引 |
| 误触发原文召回 | 上下文膨胀 | 调高触发阈值，加入置信度校验 |
| 压缩丢失关键信息 | 上下文断裂 | 保留最近 4 轮完整压缩 |

---

## 附录 A: 关键文件清单

| 文件 | 职责 |
|------|------|
| `context_manager.py` | 主入口，统一 CLI |
| `store_engine.py` | 对话存储引擎 |
| `recall_engine.py` | 召回引擎 |
| `context_monitor.py` | 上下文监控与压缩 |
| `index.py` | 索引管理 |
| `summarizer.py` | 摘要生成器 |
| `config.py` | 配置加载 |
| `context_config.json` | 配置文件 |

## 附录 B: 错误处理

- **文件写入失败**: 重试 3 次，失败后降级到内存缓冲
- **索引损坏**: 从文件列表重建索引
- **摘要生成失败**: 使用规则-based fallback（提取前 50 字 + 关键词）
- **召回空结果**: 不注入任何上下文，正常处理
