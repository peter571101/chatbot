"""
微信聊天记录自动截图工具（仅截取聊天消息区域）

用法：
    python wechat_capture.py

流程：
    1. 打开微信 → 进入目标聊天窗口
    2. 鼠标停在聊天区左上角 → 按 Enter
    3. 鼠标停在聊天区右下角 → 按 Enter
    4. 测试截图确认 → 自动开始，按 Ctrl+C 停止

注意：截图过程中你的鼠标会自动移动，不要动鼠标。
"""

import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent


def get_mouse_pos():
    import pyautogui

    input("  鼠标停在目标位置别动，现在按 Enter 记录坐标...")
    x, y = pyautogui.position()
    print(f"  记录: ({x}, {y})")
    return x, y


def define_region():
    print("\n划定聊天消息区域（鼠标停在位置别动，按 Enter）：")
    print("  第一步：鼠标移到聊天区左上角")
    x1, y1 = get_mouse_pos()
    print("  第二步：鼠标移到聊天区右下角")
    x2, y2 = get_mouse_pos()

    if x1 > x2:
        x1, x2 = x2, x1
    if y1 > y2:
        y1, y2 = y2, y1

    w, h = x2 - x1, y2 - y1
    print(f"\n  区域: ({x1},{y1}) → ({x2},{y2})  {w}x{h}")
    return x1, y1, w, h


def test_capture(x1, y1, w, h, output_dir: Path):
    import pyautogui

    test_path = output_dir / "_TEST.png"
    try:
        img = pyautogui.screenshot(region=(x1, y1, w, h))
        img.save(str(test_path))
        print(f"\n  测试截图: {test_path}")
        ok = input("  确认无误？(Y/n): ").strip().lower()
        if ok and ok != "y":
            return define_region()
    except Exception as e:
        print(f"  截图失败: {e}，重新划定。")
        return define_region()
    return x1, y1, w, h


def find_wechat_window():
    import pygetwindow as gw

    for w in gw.getAllWindows():
        if any(k in w.title for k in ["微信", "WeChat"]):
            return w
    return None


def scroll_chat():
    """
    先点微信标题栏获取键盘焦点（绝对不误触消息），
    然后狂按 Page Down 翻页。
    """
    import pyautogui

    win = find_wechat_window()
    if win is None:
        return

    # 激活窗口
    try:
        win.activate()
    except Exception:
        pass
    time.sleep(0.05)

    # 点标题栏——绝对安全
    title_x = win.left + win.width // 2
    title_y = win.top + 10
    pyautogui.click(title_x, title_y)
    time.sleep(0.05)

    # 猛按 Page Down
    for _ in range(3):
        pyautogui.press("pagedown")
        time.sleep(0.03)


def main():
    print("=" * 50)
    print("  微信聊天记录 · 自动截图")
    print("=" * 50)

    name = input("\n聊天对象名字: ").strip() or "unknown"
    output_dir = BASE_DIR / "captures" / name
    output_dir.mkdir(parents=True, exist_ok=True)

    x1, y1, w, h = define_region()
    x1, y1, w, h = test_capture(x1, y1, w, h, output_dir)

    print(f"\n保存到: {output_dir}")
    print("3 秒后开始，按 Ctrl+C 停止...")
    time.sleep(3)

    import pyautogui

    idx = 1
    try:
        while True:
            filename = f"{idx:04d}_{time.strftime('%H%M%S')}.png"
            try:
                img = pyautogui.screenshot(region=(x1, y1, w, h))
                img.save(str(output_dir / filename))
            except Exception as e:
                print(f"  [{idx}] 截图失败: {e}")
                time.sleep(1)
                continue

            print(f"  [{idx}] {filename}")

            scroll_chat()
            time.sleep(0.3)

            idx += 1

    except KeyboardInterrupt:
        print(f"\n\n已停止，共 {idx - 1} 张截图 → {output_dir}")
        print(f"下一步: python distill.py captures/{name}/ --target {name}")


if __name__ == "__main__":
    main()
