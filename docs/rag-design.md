# RAG 与 Embedding 设计方案

## 当前架构 vs 引入 RAG 后

```
当前                                    RAG 后
────                                    ──────
[system_prompt]                         [system_prompt]
[context_inject]                        [context_inject]
[history (全部塞)]           →          [检索到的相关记忆] ← 关键变化
[user_message]                          [user_message + 最近3轮对话]
                                         ↑
                                    ChromaDB 向量检索
```

当前对话历史是「全量塞入」——对话长了会爆 context window。RAG 后变成「只检索相关记忆」，无关的历史消息不占 token。

---

## 1. Embedding 选择

| 方案 | 成本 | 优点 | 缺点 |
|------|------|------|------|
| **DeepSeek Embedding API** | 按量付费 | 已有 Key，无需额外依赖 | 有网络延迟 |
| Sentence Transformers (local) | 免费 | 离线可用，速度快 | 需要下载模型(~500MB)，CPU 略慢 |
| text2vec-large-chinese (local) | 免费 | 中文效果好 | 模型更大(~1.2GB) |

**推荐 DeepSeek Embedding API**，原因：无需模型部署，项目已依赖 DeepSeek，集成零成本。

---

## 2. 什么东西值得 Embed？

### 2.1 用户记忆（User Memory）

每次对话结束时，自动生成一句话摘要存入 ChromaDB。

```
示例：
  用户说"我最近胃不舒服"，存为记忆: "用户有胃病，注意饮食"
  用户说"我下周出差去上海"，存为记忆: "用户下周在上海出差"

检索时妈妈就能说："你胃不舒服还吃辣的？" "上海那边这两天降温，多带件衣服"
```

**触发时机**：每轮对话结束后，用小模型（DeepSeek 轻量模式）判断「这段话是否包含值得记住的事实」，是则生成摘要存入。

### 2.2 对话片段（Conversation Chunks）

按「话题」而非字数切割对话历史。一个话题 = 一个 chunk。

```
原始对话：
  用户: 妈我出门了
  妈妈: 多穿点，今天冷
  用户: 晚上不回来吃饭
  妈妈: 跟同事吃啊？别喝酒

生成两个 chunk：
  chunk_1: "用户早上出门，妈妈提醒多穿衣服"
  chunk_2: "用户晚上不回家吃饭，妈妈提醒别喝酒"
```

### 2.3 Persona 知识库（可选，后期）

给每个 persona 注入领域知识。

```
苏轼 persona → embed《东坡全集》中的名句、典故
妈妈 persona  → embed 养生知识、家常菜谱
```

---

## 3. 架构设计

```
┌─────────────────────────────────────────────────────┐
│                    FastAPI Server                    │
│                                                     │
│  /api/chat  ──→  build_messages()                   │
│                      │                              │
│                      ├── 1. 获取 persona system_prompt
│                      ├── 2. context_injector (时间+天气)
│                      ├── 3. memory_store.search(user_msg) ← RAG
│                      ├── 4. 拼接最近 3 轮对话
│                      └── 5. 发给 DeepSeek Chat API   │
│                                                     │
│  /api/memory/compact ──→  压缩历史 → embed → 存入     │
└──────────────────────┬──────────────────────────────┘
                       │
               ┌───────▼───────┐
               │   ChromaDB    │  (本地持久化)
               │               │
               │ collection:   │
               │  - memories   │  (用户记忆)
               │  - chats      │  (对话片段)
               │  - personas   │  (知识库，可选)
               └───────────────┘
```

---

## 4. 核心模块设计

### 4.1 `memory_store.py` — 记忆存储与检索

```python
import chromadb
from chromadb.config import Settings

class MemoryStore:
    def __init__(self, persist_dir: str = "./chroma_data"):
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.memories = self.client.get_or_create_collection("memories")
        self.chats = self.client.get_or_create_collection("chats")

    def add_memory(self, text: str, metadata: dict, doc_id: str):
        """存一条记忆"""
        embedding = get_embedding(text)  # DeepSeek Embedding API
        self.memories.add(
            embeddings=[embedding],
            documents=[text],
            metadatas=[metadata],
            ids=[doc_id],
        )

    def search(self, query: str, n: int = 5, collection: str = "memories"):
        """检索最相关的 n 条记忆"""
        embedding = get_embedding(query)
        col = self.memories if collection == "memories" else self.chats
        results = col.query(query_embeddings=[embedding], n_results=n)
        return results["documents"][0] if results["documents"] else []
```

### 4.2 `memory_compactor.py` — 记忆压缩器

```
对话历史（可能 20 轮，3000 tokens）
        ↓
    用 DeepSeek 生成摘要（轻量 prompt，约 100 tokens）
        ↓
    embed → 存入 ChromaDB
        ↓
    context window 只保留「最近 3 轮 + 检索到的记忆」
```

### 4.3 注入逻辑改动 (`main.py`)

```python
# 原来：全量历史
messages += history

# RAG 后：检索 + 最近 N 轮
memories = memory_store.search(message, n=5)
recent = history[-6:]  # 最近 3 轮（3 user + 3 assistant）

# 将记忆注入为 system 消息
if memories:
    mem_text = "以下是关于用户的重要记忆：\n" + "\n".join(f"- {m}" for m in memories)
    messages.append({"role": "system", "content": mem_text})

messages += recent
```

---

## 5. 依赖变化

```
requirements.txt 新增：
chromadb>=0.5
sentence-transformers>=3.0  # 如果用本地 embedding

或直接用 DeepSeek Embedding API（已有 httpx 依赖）：
# POST https://api.deepseek.com/v1/embeddings
```

---

## 6. 落地步骤

| 步骤 | 做什么 | 耗时 |
|------|--------|------|
| 1 | 装 chromadb，创建 `memory_store.py` | 1h |
| 2 | 对接 DeepSeek Embedding API（`embedding.py`） | 1h |
| 3 | 修改 `/api/chat`：注入检索到的记忆 | 1h |
| 4 | 写 `memory_compactor.py`：对话结束后自动摘要+存储 | 2h |
| 5 | 测试：模拟多轮对话，验证记忆检索准确性 | 1h |
| 6 | 调参：检索数量 n、相似度阈值、压缩频率 | 1h |

---

## 7. 设计原则

1. **不是越多越好** —— 每次只检索 3-5 条最相关记忆，多了反而稀释 prompt
2. **记忆要带时间戳** —— "用户上周说胃不舒服" vs "用户说胃不舒服"，前者更有价值
3. **不重要的不记** —— 寒暄（"嗯""好的"）跳过，只有包含事实/偏好的才 embed
4. **相似度阈值** —— 低于 0.6 的不检索，避免无关记忆污染上下文
5. **ChromiumDB 足够** —— 这个量级不需要 Pinecone/Weaviate，本地 ChromaDB 完全够用
