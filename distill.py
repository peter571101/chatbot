"""
人格蒸馏脚本：从微信聊天记录中提取人格并生成 persona JSON。

用法：
    # 从文本文件蒸馏
    python distill.py chat_logs.txt --name 老王 --avatar 🍺

    # 从截图文件夹蒸馏（自动 OCR）
    python distill.py screenshots/ --name 老王 --avatar 🍺

    # 只提取目标人物的消息（过滤掉你自己的）
    python distill.py screenshots/ --target 老王

依赖：
    pip install easyocr pillow
    （首次运行时 easyocr 会自动下载中文识别模型，约 200MB）
"""

import argparse
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

BASE_DIR = Path(__file__).parent
PERSONAS_DIR = BASE_DIR / "personas"

ANALYZE_PROMPT = """你是一个人格分析专家。以下是某人的微信聊天记录，请仔细阅读并深度分析这个人的语言模式、性格特征和价值观。

{filter_instruction}

请从以下维度分析：

1. **说话风格**：短句还是长句？语速感如何？常用什么标点？习惯用 emoji 吗？有什么口头禅或高频词？说话直接还是委婉？
2. **性格特征**：幽默/严肃/毒舌/温柔/段子手？自信还是犹豫？内向还是外向？理性还是感性？
3. **价值观与世界观**：经常讨论什么话题？对待工作、感情、金钱、朋友的态度？做判断时看重什么？
4. **身份背景**：从对话中能推断出年龄层、职业方向、地域、兴趣爱好吗？
5. **内在矛盾**：有没有言行不一致的地方？表面和内心是否存在张力？

然后请严格按以下 JSON 格式输出（只输出 JSON，不要加任何解释性文字）：

```json
{{
  "id": "英文id",
  "name": "中文名字",
  "avatar": "一个emoji作为头像",
  "tagline": "一句最能代表这个人的话（10字以内）",
  "description": "一段50-80字的第三人称描述，概括这个人的性格和说话特点",
  "theme_color": "一个十六进制颜色，匹配这个人的气质（如 #e74c3c 热情, #3498db 理性, #2ecc71 温和, #9b59b6 神秘, #f39c12 活泼）",
  "welcome_message": "用这个人的口吻写一段开场白（50-150字），就像TA刚打开聊天窗口对你说的第一句话，要自然、有TA的个人风格",
  "system_prompt": "用这个人的第一人称写一段详细的角色扮演指令（1000-2000字），包含：身份背景段落、核心信念列表（3-5条）、日常决策方式、表达风格详细描述（句长、口头禅、语气、用词习惯、emoji使用等）、角色扮演规则（首次免责声明等）、价值观、内在矛盾。参照那种专业的 AI 角色卡格式来写。"
}}
```

要求：
- system_prompt 必须足够详细，让 AI 能精确复现这个人的说话方式
- welcome_message 要自然口语化，不要像客服
- 所有中文内容不要出现「该用户」「此人」等第三人称，要用「我」的第一人称视角
- 如果聊天记录不足以推断某个维度，就根据已有信息合理推测，不要留空或写「未知」
- 注意：聊天记录可能来自 OCR 识别，存在少量错字和格式混乱，请自动修正理解

聊天记录如下：
---
{chat_log}
---"""


# ── OCR 模块 ──────────────────────────────────────────────

def _get_ocr_reader():
    """延迟加载 easyocr Reader（单例，避免重复加载模型）"""
    import easyocr
    return easyocr.Reader(["ch_sim", "en"], gpu=False, verbose=False)


def ocr_images(image_dir: str) -> str:
    """对一个目录下的所有截图进行 OCR，返回合并后的文本"""
    import numpy as np
    from PIL import Image, ImageEnhance

    img_exts = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"}
    img_files = sorted(
        f for f in Path(image_dir).iterdir()
        if f.suffix.lower() in img_exts
    )

    if not img_files:
        print(f"错误：目录 {image_dir} 中没有找到图片文件 (支持 png/jpg/bmp/webp)")
        sys.exit(1)

    print(f"找到 {len(img_files)} 张截图，正在加载 OCR 模型...")
    reader = _get_ocr_reader()

    all_lines = []
    for i, img_path in enumerate(img_files, 1):
        print(f"  [{i}/{len(img_files)}] 识别: {img_path.name} ...", end=" ", flush=True)
        try:
            img = Image.open(img_path).convert("RGB")
            # 微信截图通常很长，如果宽度 > 800 则等比缩小以加速
            w, h = img.size
            if w > 1200:
                ratio = 1200 / w
                img = img.resize((1200, int(h * ratio)), Image.LANCZOS)
            # 增强对比度，提高 OCR 准确率
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.3)
            arr = np.array(img)
            results = reader.readtext(arr, detail=0)
            count = len(results)
            print(f"识别到 {count} 段文字")
            if count > 0:
                text = "\n".join(results)
                all_lines.append(f"── 截图 {i}: {img_path.name} ──\n{text}")
        except Exception as e:
            print(f"失败：{e}")

    if not all_lines:
        print("\n所有截图均未识别到文字。可能原因：")
        print("  1. 截图分辨率太低或文字太小")
        print("  2. 图片中含有大量表情包/图片内容")
        print("  3. 首次运行 easyocr 下载模型被中断，请重试")
        print("  4. 截图并非微信聊天界面\n")
        sys.exit(1)

    combined = "\n\n".join(all_lines)
    print(f"OCR 完成，共提取 {len(combined)} 字符\n")
    return combined


# ── 文本模块 ──────────────────────────────────────────────

def read_chat_log(path: str, max_chars: int = 30000) -> str:
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    if len(text) > max_chars:
        half = max_chars // 2
        text = text[:half] + "\n\n...(中间部分省略)...\n\n" + text[-half:]

    return text


# ── 蒸馏模块 ──────────────────────────────────────────────

def distill(chat_log: str, name: str | None = None, avatar: str | None = None, target: str | None = None) -> dict:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("错误：请在 .env 文件中设置 DEEPSEEK_API_KEY")
        sys.exit(1)

    # 构建过滤指令
    if target:
        filter_instruction = (
            f"重要：以上聊天记录来自双人对话。请只分析「{target}」这个人说的话，"
            f"忽略另一个人（对方）的所有消息。通过上下文和语气判断哪条消息属于「{target}」。"
            f"对话中「{target}」可能被叫做其他称呼，请根据上下文智能识别。"
        )
    else:
        filter_instruction = "注意：如果聊天记录包含多个人的消息，请重点分析其中一方的语言特征和人格。"

    prompt = ANALYZE_PROMPT.format(chat_log=chat_log, filter_instruction=filter_instruction)
    if name:
        prompt += f"\n\n注意：请将 name 字段设为「{name}」。"
    if avatar:
        prompt += f"\n\n注意：请将 avatar 字段设为「{avatar}」。"

    print("正在调用 DeepSeek 分析聊天记录...")
    print(f"  聊天记录长度: {len(chat_log)} 字符")
    print()

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com",
        http_client=httpx.Client(),
    )

    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "你是一个专业的人格分析专家。你只输出 JSON，不输出任何其他内容。"},
            {"role": "user", "content": prompt},
        ],
        max_tokens=4096,
        temperature=0.7,
    )

    raw = resp.choices[0].message.content.strip()

    # 去掉可能的 markdown 代码块包裹
    if raw.startswith("```"):
        raw = raw.split("```json", 1)[-1] if "```json" in raw else raw
        raw = raw.split("```", 1)[0] if raw.endswith("```") else raw
        raw = raw.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print("DeepSeek 返回的内容解析失败，原始输出：")
        print("-" * 40)
        print(raw)
        print("-" * 40)
        print("\n请手动修正后重新运行。")
        sys.exit(1)

    required = ["id", "name", "avatar", "tagline", "description", "theme_color", "welcome_message", "system_prompt"]
    missing = [k for k in required if k not in data]
    if missing:
        print(f"警告：生成结果缺少字段: {missing}")
        for k in missing:
            data[k] = ""

    return data


# ── 入口 ──────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="从微信聊天记录蒸馏人格")
    parser.add_argument("input", help="聊天记录文本文件路径，或截图文件夹路径")
    parser.add_argument("--name", "-n", help="目标人物名字（用于输出文件名）")
    parser.add_argument("--avatar", "-a", help="自定义头像 emoji")
    parser.add_argument("--target", "-t", help="聊天记录中要蒸馏的目标人物名字，LLM 会自动过滤掉其他人的消息")
    args = parser.parse_args()

    print("=" * 50)
    print("  人格蒸馏 · Persona Distiller")
    print("=" * 50)
    print()

    input_path = Path(args.input)

    if input_path.is_dir():
        # 截图模式
        print(f"模式：截图 OCR")
        print(f"  截图目录: {input_path}")
        if args.target:
            print(f"  目标人物: {args.target}（过滤其他人的消息）")
        print()
        chat_log = ocr_images(str(input_path))
        if not chat_log.strip():
            print("错误：所有截图均未识别到文字，请检查图片质量。")
            sys.exit(1)
    elif input_path.is_file():
        # 文本模式
        print(f"模式：文本文件")
        print(f"  文件: {input_path}")
        if args.target:
            print(f"  目标人物: {args.target}（过滤其他人的消息）")
        print()
        chat_log = read_chat_log(str(input_path))
    else:
        print(f"错误：路径 {args.input} 不存在")
        sys.exit(1)

    data = distill(chat_log, name=args.name, avatar=args.avatar, target=args.target)

    output_path = PERSONAS_DIR / f"{data['id']}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"已生成人格文件: {output_path}")
    print(f"  名字: {data['name']} {data['avatar']}")
    print(f"  简介: {data['tagline']}")
    print()
    print("重启 python main.py 后即可在首页看到该人格。")


if __name__ == "__main__":
    main()
