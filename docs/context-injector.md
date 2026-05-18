# 上下文注入 · context-injector

## 一句话总结

LLM 不知道现在是几点。`context_injector.py` 把当前时间拼成一条 **硬指令** 塞进用户消息开头，AI 无法跳过。

---

## 问题演进

| 版本 | 做法 | 结果 |
|------|------|------|
| v1 | system 消息注入天气+时间 | 中午12点问早饭 |
| v2 | system_prompt 加时段规则 + `_meal_hint()` | 仍偶尔混淆 |
| v3 | user 消息前缀加中文描述 | 描述太长，AI 不当成指令 |
| **v4** | user 消息前缀改为结构化命令 | **强制指定问候语 + 禁止词** |

---

## v4 核心思路

不再描述当前时段，而是 **直接命令 AI 的第一句话**。

v3（描述式，AI 可能忽略）：
```
[现在是午后，午饭吃过了晚饭还没到，你作为妈妈关心下午茶/水果]
```

v4（命令式，AI 必须执行）：
```
[现在14点|你必须说下午好|关心下午茶/水果|禁止提早饭午饭晚饭-都吃过了]
```

关键改动：
- `|` 分隔，结构清晰，像配置文件
- `你必须说X` — 直接指定问候语，不给 AI 选择空间
- `禁止提A B C — 理由` — 否定指令比肯定指令记得更牢
- `现在N点` — 具体数字，消除歧义

---

## 三层防幻觉架构（当前）

```
┌─ Layer 0（user消息前缀，最强）────────────────────────────────┐
│ [user] [现在14点|你必须说下午好|关心下午茶/水果|禁止提...]     │
│        用户消息正文...                                         │
│        ↑ meal_prefix(datetime.now().hour)                     │
├─ Layer 1（第一条 system 消息）─────────────────────────────────┤
│ [system] [系统实时信息]                                       │
│   现在是 2026年5月18日 周一 北京时间 14:05。                  │
│   当前时段：下午。  ← _meal_hint() 时段标签                    │
│   南京当前天气：晴，气温 26°C...  ← wttr.in                   │
│   请在对话中自然地运用以上时间和天气信息。                      │
├─ Layer 2（第二条 system 消息）─────────────────────────────────┤
│ [system] 妈妈人格 system_prompt                               │
│   ## 最高优先规则：用户消息开头的方括号指令必须服从             │
│   ## 吃饭时间规则                                             │
└───────────────────────────────────────────────────────────────┘
```

### `meal_prefix()` — Layer 0 对照表

| 小时 | 输出 |
|------|------|
| 6–9 | `[现在N点\|你必须说早上好\|只关心早饭吃了没\|禁止提午饭晚饭睡觉]` |
| 9–11 | `[现在N点\|你必须说上午好\|关心加餐/水果\|禁止提早饭-已过\|禁止提午饭-还早]` |
| 11–13 | `[现在N点\|你必须说中午好\|只关心午饭吃了没\|禁止提早饭晚饭]` |
| 13–17 | `[现在N点\|你必须说下午好\|关心下午茶/水果\|禁止提早饭午饭晚饭-都吃过了]` |
| 17–20 | `[现在N点\|你必须说晚上好\|只关心晚饭吃了没\|禁止提早饭午饭]` |
| 20–23 | `[现在N点\|你必须说晚上好\|提醒别吃夜宵早点睡\|禁止提早饭午饭晚饭]` |
| 23–6 | `[现在N点\|你必须说这么晚了\|只催睡觉\|禁止提任何吃饭-几点了还吃]` |

### `_meal_hint()` — Layer 1 时段标签

返回单个词：`早晨` / `上午` / `中午` / `下午` / `傍晚` / `晚间` / `深夜`

---

## 消息组装逻辑 (`main.py` L70-L89)

```python
messages = []

# Layer 1: 上下文放第一条 system（权重最高）
if needs_ctx:
    context_text = await build_context(location="南京")
    messages.append({"role": "system", "content": context_text})

# Layer 2: persona system_prompt
messages.append({"role": "system", "content": persona["system_prompt"]})

# 历史对话
messages += history

# Layer 0: 时段指令拼到用户消息前面（无 法 跳 过）
if needs_ctx:
    prefix = meal_prefix(datetime.now().hour)
    message = f"{prefix}\n{message}"

messages.append({"role": "user", "content": message})
```

---

## system_prompt 配合事项

为了避免 system_prompt 和 prefix 打架：

1. **删除绝对化的吃饭强调**：「早饭最重要」→「到什么点吃什么饭」
2. **典型句式要带时段**：「哎呀你吃饭了没」→「中午啦午饭吃了没呀」
3. **写清最高优先规则**：明确告诉 AI 用户消息里的方括号指令必须服从
4. **welcome_message 不提饭**：不包含无条件的时间/吃饭内容

---

## 触发条件

| 字段 | 类型 | 说明 |
|------|------|------|
| `needs_context` | `bool` | `true` 开启三层注入 |
| `location` | `string` | 城市名，默认 `"北京"` |

---

## 天气 API — wttr.in

免费免注册。`GET https://wttr.in/南京?format=j1` → 当前天气 + 今/明预报。

缓存 10 分钟，请求失败时返回兜底文本不阻塞对话。

---

## 文件清单

| 文件 | 作用 |
|------|------|
| `context_injector.py` | `meal_prefix()` (Layer 0)、`_meal_hint()` (Layer 1)、天气 API、缓存 |
| `main.py` L70-L89 | 三层消息组装 |
| `personas/mother.json` | 妈妈人格，`needs_context: true` + `location: "南京"` |
| `docs/context-injector.md` | 本文档 |

---

## 常见问题

**Q: 还是问错饭？**  
A: 排查顺序：(1) 服务器 `datetime.now()` 是否正确（时区）；(2) 浏览器打开开发者工具看 Network 标签里 `/api/chat` 的请求 body，确认 `message` 字段开头有方括号指令；(3) 如果 DeepSeek 仍然出错，在 prefix 里加英文辅助 `[TIME=14:00 AFTERNOON\|SAY good afternoon\|FORBID breakfast lunch dinner]`。

**Q: 天气不准？**  
A: wttr.in 有 30-60 分钟延迟。可换成和风天气 API。

**Q: 动态切换城市？**  
A: 前端加选择器，通过请求 body 传 `location` 字段到 `/api/chat`。
