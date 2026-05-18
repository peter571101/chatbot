# 上下文注入 · context-injector

## 一句话总结

LLM 不知道现在是几点、什么天气。在发消息给 AI 之前，`context_injector.py` 查好时间 + 天气 + 时段提示，作为一条 system 消息注入对话。

---

## 设计动机

没有注入时，对话面目全非：

> **用户**：妈我出门了（中午 12:00）  
> **AI 妈妈**：早餐吃了没呀？记得穿外套！ ← 午饭时间问早饭，离谱

注入后：

> **系统**：现在是 12:05，南京 26°C 晴。当前时段：中午，应该关心午饭。千万不要问早饭！  
> **用户**：妈我出门了  
> **AI 妈妈**：中午啦！午饭吃了没呀？今天倒是暖和，别穿太多捂出汗了 🏃

---

## 消息结构

```
┌─────────────────────────────────────────────────┐
│ [system] 妈妈人格 system_prompt                 │  ← 定义说话风格
├─────────────────────────────────────────────────┤
│ [system] [系统实时信息]                          │  ← context_injector 注入（用户不可见）
│  现在是 2026年5月18日 周一 北京时间 12:05。      │
│  南京当前天气：晴，气温 26°C（体感 28°C）...     │
│  当前时段：中午，应该关心午饭。千万不要问早饭！    │  ← 时段提示
├─────────────────────────────────────────────────┤
│ [user]  妈我今天不回来吃饭了                     │
│ [assistant] 又不回来！跟谁吃去啊...               │
└─────────────────────────────────────────────────┘
```

**三个组成部分：**

| 段落 | 来源 | 说明 |
|------|------|------|
| 时间句 | `datetime.now()` | 精确到分钟，中文星期 |
| 天气句 | wttr.in API | 当前天气 + 今天/明天预报 |
| 时段提示 | `_meal_hint(hour)` | 强制约束 AI 别问错饭 |

---

## 时段提示机制（防问错饭）

这是 v2 新增的关键设计。之前 system_prompt 里一句「中午关心午饭」太软，AI 有时会忽略。现在采用 **双层兜底**：

### 第一层：注入层 — `_meal_hint()`

在注入的上下文里直接插一段硬指令，AI 每轮对话都能看到：

| 小时 | 指令 |
|------|------|
| 6–9 | 早晨，关心早饭。 |
| 9–11 | 上午，早饭已过，关心零食/水果。 |
| 11–13 | 中午，关心午饭。**千万不要问早饭！** |
| 13–17 | 午后，关心下午茶/水果。 |
| 17–20 | 傍晚，关心晚饭。 |
| 20–23 | 晚间，别吃夜宵，早睡。 |
| 23–6 | 深夜/凌晨，**禁止问吃饭**，催睡觉。 |

### 第二层：system_prompt 层 — 吃饭时间规则

`mother.json` 的 system_prompt 里有对照规则，确保即使 AI 没仔细看注入消息，也能被 system_prompt 约束。

### 为什么用「千万不要问早饭」

经验证，DeepSeek 偶尔会机械地按 system_prompt 里的「关心吃饭」去问，而不检查时间。在注入消息里写 **否定句**（「千万不要问早饭」）比肯定句（「应该关心午饭」）更有效，因为 AI 对负面指令的记忆更深刻。

---

## 触发条件 (`main.py` L72-L76)

```python
location = persona.get("location")
if persona.get("needs_context") or location:
    context_text = await build_context(location=location or "北京")
    messages.append({"role": "system", "content": context_text})
```

两个 JSON 字段，任一存在即触发：

| 字段 | 类型 | 说明 |
|------|------|------|
| `needs_context` | `bool` | `true` 开启注入 |
| `location` | `string` | 城市名，中文或英文，默认 `"北京"` |

只设 `location` 不设 `needs_context` 也会触发（因为 weather 依赖 location）。

不设这两个字段的 persona 零影响。

---

## 天气 API — wttr.in

免费，无需注册，无需 API Key。

```
GET https://wttr.in/南京?format=j1
```

返回结构：

```
current_condition[0]
  ├── weatherDesc[0].value  → "晴" / "多云" / "小雨"
  ├── temp_C               → "26"
  ├── FeelsLikeC           → "28"
  ├── humidity             → "45"
  └── windspeedKmph        → "12"

weather[0]  ← 今天
  ├── mintempC / maxtempC
  └── weatherDesc[0].value

weather[1]  ← 明天
  ├── mintempC / maxtempC
  └── weatherDesc[0].value
```

**缓存**：同一城市 10 分钟内不重复请求，避免命中 wttr.in 的频率限制。

**容错**：请求失败或超时时返回兜底文本，不阻塞对话：
> 南京天气：暂时无法获取天气数据，请提醒用户自行查看天气预报。

---

## 如何给其他 persona 加上上下文注入

只需在 persona JSON 中加：

```json
{
  "id": "my-character",
  "name": "...",
  ...
  "needs_context": true,
  "location": "深圳"
}
```

如果 persona 的主角不关心天气只关心时间，可以不设 `location`：

```json
{ "needs_context": true }
```

此时默认取北京天气，但 `_meal_hint` 和本地时间仍然生效。

---

## 文件清单

| 文件 | 作用 |
|------|------|
| `context_injector.py` | 时间 + 天气 + 时段提示，缓存 10min |
| `main.py` L13, L72-L76 | 导入 `build_context`，判断注入触发 |
| `personas/mother.json` | 妈妈人格，`needs_context: true` + `location: "南京"` |
| `docs/context-injector.md` | 本文档 |

## 常见问题

**Q: 问错饭了，明明中午却问早饭？**  
A: 两层原因可能同时出问题。(1) 检查 `_meal_hint()` 的小时边界是否合理；(2) 检查 `mother.json` 的 system_prompt 里「吃饭时间规则」是否被其他 prompt 覆盖；(3) DeepSeek 有时会遗漏 system 消息——可尝试在注入消息末尾加重语气。

**Q: 天气数据不准？**  
A: wttr.in 数据源有延迟（通常 30–60 分钟），极端天气下可能不准。免费方案无法做到实时。如需更准确的天气，可换成和风天气 API（需要注册获取 Key）。

**Q: 能否支持用户实时切换城市？**  
A: 当前城市是写在 persona JSON 里的静态值。如果需要用户动态切换，可以在前端加一个城市选择器，通过请求参数传到 `/api/chat`，后端读取该参数传给 `build_context()`。
