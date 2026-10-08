# -*- coding: utf-8 -*-
"""大肥鱼桌宠 · 动作帧生成工具

把画好的立绘丢进本目录下的 `源图\\`，跑这个脚本，就会自动抠图、统一尺寸、
生成三档，写进桌宠的 `sprites\\dsh\\`。

## 命名（任选一种，脚本自动识别）

    approval.png        approval-1.png       approval_1.png
    tool_pwsh-1.png     start-work1.png      ← start 的第 1 帧
    动作名-2.png                              ← 该动作的第 2 帧

## 动作名（11 个，必须用这些）

    start 开工 / approval 等批准 / error 报错 / done 收工
    tool_pwsh 敲命令 / tool_edit 改代码 / tool_read 翻文件 / tool_web 上网查
    idle 发呆 / sing 放歌 / working 思考中

## 处理流程

    ① 从四边泛洪抠白底（保住人物内部的白色，不会把脸 / 头饰抠掉）
    ② 裁到角色，量出角色尺寸
    ③ 统一缩放：角色高度 = 画布高 × 0.95（所有动作一致 → 切换不跳大小）
    ④ 生成三档，写入 <桌宠目录>\\sprites\\dsh\\<动作>\\<帧>_<档位>.png

## 输出目录怎么找

按顺序试：命令行第 1 个参数 → 本目录 / 上一级 / 上两级的 `sprites\\dsh`
→ 都没有就用本机默认路径。所以放在仓库里的 `工具\\` 下能直接用。

跑完重启桌宠即可看到效果。
"""
import io
import os
import re
import sys
from collections import deque

from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = HERE                              # 源图放在本目录下的 源图\
WS = os.path.join(BASE, "源图")


def _find_dst():
    """桌宠读动作帧的目录：命令行参数 → 上级找 sprites\\dsh → 本机默认。"""
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if os.path.basename(os.path.normpath(arg)) == "dsh":
            return arg
        return os.path.join(arg, "dsh")
    for up in (HERE, os.path.dirname(HERE), os.path.dirname(os.path.dirname(HERE))):
        if os.path.isdir(os.path.join(up, "sprites")):
            return os.path.join(up, "sprites", "dsh")
    return r"D:\dafeiyu-pet-full\sprites\dsh"


DST_ROOT = _find_dst()
REPORT = os.path.join(BASE, "生成报告.txt")

TIERS = [("特小", 122), ("中", 245), ("大", 306)]   # 三档显示高度
FLOOD_TOL = 40          # 泛洪容差
FEATHER = 0.7           # 边缘羽化（像素）
CHAR_RATIO = 0.95       # 角色高 / 画布高（统一值，别乱改）
PAD_RATIO = 0.02        # 左右留白占画布高的比例
# 这些动作单独用「贴紧」的画布（人物瘦，统一宽画布会白占地方，
# 而且代码里给它单独放大时会把窗口撑宽）
TIGHT_CANVAS = {"sing"}

ACT_NAMES = ["start", "approval", "error", "done",
             "tool_pwsh", "tool_edit", "tool_read", "tool_web", "idle",
             "sing", "working"]

sys.stdout = io.open(REPORT, "w", encoding="utf-8")


def parse_frame(stem, act):
    """文件名 → 帧序号；不是这个动作的文件返回 None。

    'approval' → 1    'approval-2' → 2    'start-work1' → 1    'tool_edit_3' → 3
    """
    s, a = stem.lower(), act.lower()
    if s == a:
        return 1
    if not (s.startswith(a + "-") or s.startswith(a + "_")):
        return None
    head = s[len(a) + 1:].split("_")[0]      # 去掉可能的档位后缀
    m = re.search(r"(\d+)$", head)
    return int(m.group(1)) if m else None


def flood_cut(im, tol=FLOOD_TOL, feather=FEATHER):
    """从四边泛洪抠背景 → (RGBA, bbox, 背景占比)。

    关键：只抠「连到画布边缘」的浅色区域。人物内部的白色（脸、头饰）
    不连通边缘，因此会被完整保留 —— 这是和"按颜色阈值抠图"的本质区别。
    """
    rgb = im.convert("RGB")
    w, h = rgb.size
    px = rgb.load()
    s = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]
    s.sort(key=lambda c: sum(c))
    br, bgc, bb = s[len(s) // 2]

    is_bg = bytearray(w * h)
    q = deque()

    def near(x, y):
        r, g, b = px[x, y]
        return abs(r - br) <= tol and abs(g - bgc) <= tol and abs(b - bb) <= tol

    for x in range(w):
        for y in (0, h - 1):
            if near(x, y) and not is_bg[y * w + x]:
                is_bg[y * w + x] = 1
                q.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if near(x, y) and not is_bg[y * w + x]:
                is_bg[y * w + x] = 1
                q.append((x, y))
    while q:
        x, y = q.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h:
                i = ny * w + nx
                if not is_bg[i] and near(nx, ny):
                    is_bg[i] = 1
                    q.append((nx, ny))

    a = Image.frombytes("L", (w, h), bytes(0 if v else 255 for v in is_bg))
    if feather:
        a = a.filter(ImageFilter.GaussianBlur(feather))
    out = rgb.convert("RGBA")
    out.putalpha(a)
    return out, a.getbbox(), sum(is_bg) * 100.0 / (w * h)


# ---------- 1. 扫描 ----------
print("=== 1. 扫描 %s 里的动作图 ===" % WS)
found = {}
try:
    names = os.listdir(WS)
except OSError:
    names = []
for fn in names:
    stem, ext = os.path.splitext(fn)
    if ext.lower() not in (".png", ".jpg", ".jpeg"):
        continue
    for act in ACT_NAMES:
        idx = parse_frame(stem, act)
        if idx:
            found.setdefault(act, []).append((idx, os.path.join(WS, fn)))
            break

if not found:
    print("  没找到动作图。命名示例：approval.png / tool_pwsh-1.png / start-work1.png")
    sys.stdout.close()
    sys.stdout = sys.__stdout__
    print("没有可处理的图，检查下 源图\\ 目录")
    raise SystemExit(0)

for act in ACT_NAMES:
    if act in found:
        print("  %-11s ← %s" % (act, ", ".join(os.path.basename(p) for _i, p in sorted(found[act]))))

print("\n输出目录: %s" % DST_ROOT)

# ---------- 2. 抠图 ----------
print("\n=== 2. 泛洪抠图 ===")
chars = {}
for act, items in found.items():
    for idx, p in items:
        im = Image.open(p)
        out, bbox, bg = flood_cut(im)
        crop = out.crop(bbox)
        chars[(act, idx)] = (crop, crop.size[0], crop.size[1])
        print("  %-11s 帧%d  %-20s 原%-12s → 角色 %dx%d (比 %.3f)"
              % (act, idx, os.path.basename(p), "%dx%d" % im.size,
                 crop.size[0], crop.size[1], crop.size[0] / float(crop.size[1])))

mx = max((w / float(h) for _c, w, h in chars.values()), default=0)
print("\n最宽的角色宽高比: %.3f（画布按它定宽，保证谁都放得下）" % mx)

# ---------- 3. 生成 ----------
print("\n=== 3. 生成三档（角色高统一 = 画布高 × %.2f）===" % CHAR_RATIO)
made = 0
for act in found:
    d = os.path.join(DST_ROOT, act)
    os.makedirs(d, exist_ok=True)
    for old in os.listdir(d):
        if old.lower().endswith(".png"):
            os.remove(os.path.join(d, old))

for tname, th in TIERS:
    char_h = th * CHAR_RATIO
    pad = max(2, int(round(th * PAD_RATIO)))
    canvas_w = int(round(char_h * mx)) + pad * 2
    # 贴紧画布：人物瘦的动作（如唱歌）用它自己的宽度，不占统一画布的空位
    # —— 这样代码里给它单独放大时，也不会把窗口撑宽
    tight = {}
    for act in TIGHT_CANVAS:
        ratios = [cw / float(ch) for (a, _i), (_c, cw, ch) in chars.items() if a == act]
        if ratios:
            tight[act] = int(round(char_h * max(ratios))) + pad * 2
    print("  %s 档: 画布 %dx%d，角色高 %.0f，贴紧的: %s"
          % (tname, canvas_w, th, char_h, tight or "无"))
    for (act, idx), (crop, cw, ch) in chars.items():
        cw_canvas = tight.get(act, canvas_w)
        scale = char_h / float(ch)
        tw = max(1, int(round(cw * scale)))
        nh = max(1, int(round(char_h)))
        canvas = Image.new("RGBA", (cw_canvas, th), (0, 0, 0, 0))
        rz = crop.resize((tw, nh), Image.LANCZOS)
        canvas.paste(rz, ((cw_canvas - tw) // 2, th - nh), rz)
        canvas.save(os.path.join(DST_ROOT, act, "%d_%d.png" % (idx, th)))
        made += 1

print("\n共生成 %d 张 → %s" % (made, DST_ROOT))
print("\n=== 4. 各动作现状 ===")
for act in ACT_NAMES:
    d = os.path.join(DST_ROOT, act)
    n = len([f for f in os.listdir(d) if f.lower().endswith(".png")]) if os.path.isdir(d) else 0
    print("  %-11s %s" % (act, ("%d 张 ✅" % n) if n else "没图（会用三视图兜底）"))
print("\n改完重启桌宠即可看到效果。")

sys.stdout.close()
sys.stdout = sys.__stdout__
print("报告:", REPORT)
