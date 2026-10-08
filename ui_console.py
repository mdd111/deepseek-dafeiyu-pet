# -*- coding: utf-8 -*-
"""桌宠控制台 —— v1.1.0 起的新设置界面（左侧分类 + 右侧内容）。

为什么要单独一个文件：这是全新的界面子系统（主题 / 图标 / 控件 / 十几个页面），
塞进 6800 行的 `桌宠.py` 里以后没地方改。PyInstaller 会跟着 `import ui_console`
自动收进去，打包只多一步：把 `assets/icons` 加进 `桌宠.spec` 的 datas。

两条硬规矩（2026-09-14 定的）：
  1. 图标一律单色，颜色走 currentColor，随亮/暗主题换色；
  2. 主题分「跟随系统 / 亮色 / 暗色」三档，默认跟随系统；
     Qt 说不清系统是亮是暗时退回读注册表 AppsUseLightTheme。

外面的 桌宠.py 只做三件事：菜单里开这个窗口、把常量表（ctx）递进来、退出时关掉。
界面逻辑全在本文件里。
"""

import contextlib
import ctypes
import os
import time
from string import Template

from PySide6.QtCore import (QAbstractNativeEventFilter, QEasingCurve, QEvent,
                            QByteArray, QObject, QParallelAnimationGroup, QPoint,
                            QPropertyAnimation, QRect, QRectF, QSize, Qt, QTimer,
                            QUrl, QVariantAnimation)
from PySide6.QtGui import (QColor, QCursor, QFont, QIcon, QImage, QPainter,
                           QPainterPath, QPen, QPixmap, QRegion, QWheelEvent)
from PySide6.QtWidgets import (QAbstractButton, QAbstractScrollArea,
                               QAbstractSlider, QApplication, QButtonGroup,
                               QColorDialog, QComboBox, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QScrollArea, QScrollBar,
                               QSizePolicy, QSlider, QStackedWidget,
                               QVBoxLayout, QWidget)

try:
    from PySide6.QtSvg import QSvgRenderer
    SVG_OK = True
except Exception:          # 缺 QtSvg 也不该让桌宠起不来：图标位置留空就是
    SVG_OK = False

# 视频背景（QtMultimedia）。缺了就只是"视频那一档用不了"，图片背景照常。
try:
    from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
    MEDIA_OK = True
except Exception:
    QMediaPlayer = QVideoSink = None
    MEDIA_OK = False


# 界面自己的版本号。发版时跟着一起改（关于页和侧边栏底部都读它）。
# 注意：**没推送就不算开新版本** —— 同一版里的返工都算在同一个号上
# （2026-09-14 主人定的）。v1.1.1 已经推送过，所以这一版的改动是 1.1.2；
# 之后再改还是 1.1.2，等推送那天才说下一版。
APP_VERSION = "1.1.5"

# 最小化动画时长（毫秒）：照着 Windows 那套"往任务栏收"的感觉来
MINIMIZE_ANIM_MS = 190
# 切页淡入的时长（毫秒）：短到"看得出是换了一页"，又不至于等
PAGE_ANIM_MS = 150
# 搜索跳转之后那一圈高亮闪多久（毫秒）
FLASH_MS = 900

# 图标尺寸只有这三档（全界面统一，别在页面里现写数字）：
#   ICON_SM   小按钮 / 右键菜单
#   ICON_CARD 卡片标题左边那颗（配 13px 的标题）
#   ICON_MD   侧边栏分类、标题栏按钮、对话框按钮
ICON_SM = 16
ICON_CARD = 17
ICON_MD = 18
# 窗口壳那张圆角卡片的半径。样式表里 `QFrame#shell` 的 border-radius 读的就是它 ——
# 页面那几层是不带底色的，壳这张圆角卡片就是窗口四个角的样子（主人 2026-09-14 报过
# "右下角是直角 / 右下角 R 角跟别的不一样"，都出在这个角上）。
SHELL_RADIUS = 14
# 动画节拍：**自己去插值**，一拍 8ms（≈120fps）。
# Qt 自带的动画走的是全局统一计时器（默认 16ms ≈ 60fps），时长相同时帧数只有一半，
# 所以同一段 190ms 我们按 8ms 走 —— 时间不变、帧数翻倍。
ANIM_TICK_MS = 8

GITHUB_URL = "https://github.com/RYANFFY/deepseek-dafeiyu-pet"


# --------------------------------------------------------------------------- #
# 主题
# --------------------------------------------------------------------------- #
# 一套亮、一套暗。键名就是"哪儿用"，别在页面里写死颜色，全从这儿取。
THEMES = {
    "light": {
        "bg": "#f5f6fa",
        "sidebar": "#eceef5",
        "surface": "#ffffff",
        "surface_alt": "#e9ebf3",
        "border": "#e0e3ec",
        "text": "#1d2030",
        "nav_text": "#4d5366",
        "text_dim": "#7b8093",
        "text_faint": "#a2a7b8",
        "accent": "#3b7bf6",
        "accent_hover": "#2f6ae0",
        "accent_soft": "#e3ecfe",
        "accent_text": "#ffffff",
        "seg_on": "#ffffff",
        "switch_off": "#d3d7e3",
        "ok": "#2e9e5b",
        "warn": "#c9770f",
        "danger": "#e04a4a",
        "scroll": "#ccd0dd",
        "shadow": QColor(0, 0, 0, 45),
    },
    "dark": {
        "bg": "#171a24",
        "sidebar": "#12141d",
        "surface": "#1f2331",
        "surface_alt": "#282d3d",
        "border": "#313748",
        "text": "#e9ebf4",
        "nav_text": "#a8aec2",
        "text_dim": "#979db2",
        "text_faint": "#6b7186",
        "accent": "#5b9dff",
        "accent_hover": "#78b0ff",
        "accent_soft": "#20304c",
        "accent_text": "#0d1220",
        "seg_on": "#3b4460",
        "switch_off": "#3a4157",
        "ok": "#43c07a",
        "warn": "#e0a04a",
        "danger": "#ff6b6b",
        "scroll": "#3d4459",
        "shadow": QColor(0, 0, 0, 110),
    },
}

# 三档配色（第三项是图标：跟别处同一套线稿）
THEME_MODES = [("system", "跟随系统", "page.theme-system"),
               ("light", "亮色", "page.theme-light"),
               ("dark", "暗色", "page.theme-dark")]

# --------------------------------------------------------------------------- #
# 控制台自己的样子（背景 / 标题 / 图标）
# --------------------------------------------------------------------------- #
# 全部存在 config.json 里。这些只影响设置窗口自己，跟桌宠本体没关系 ——
# 键名统一带 console_ 前缀，别跟上面那批 pet 的设置混在一起。
BACKDROP_DEFAULTS = {
    "console_bg_path": "",            # 底图文件；空 = 没有背景（图片还是视频看后缀）
    "console_bg_fit_window": True,    # 自动适配窗口：开着铺满并可挑截取位置，关掉完整显示
    "console_bg_focus": "cc",         # 铺满时留哪一块（九宫格：tl / tc / tr / cl / cc / …）
    "console_bg_bright": 0,           # -100（压暗）~ +100（提亮）
    "console_bg_blur": 0,             # 0 ~ 40：越大越糊
    "console_bg_scrim": 34,           # 0 ~ 100%：蒙在底图上的那层底色，越高字越清楚
    "console_brand_title": "大肥鱼桌宠",
    "console_logo_path": "",
    "console_accent": "",             # 强调色；空 = 跟主题默认
    "console_card_alpha": 100,        # 卡片不透明度 %（调低背景能从卡片里透出来）
    "console_card_radius": 12,        # 卡片圆角
    "console_remember_geo": True,     # 记住窗口大小和位置
    "console_geo": "",                # 记下来的几何（base64，不是给人看的）
    "console_start_page": "balance",  # 打开时先看哪一页
    "console_page_anim": True,        # 切页时淡入一下（嫌晃眼就关掉）
    "console_reduce_motion": False,   # 减少动效：窗口的动画一律不播（省电优先）
}

# 铺满时"留哪一块"的九宫格（先竖后横：tl = 上左，cc = 正中）。
BG_FOCUS = [("tl", "左上"), ("tc", "上"), ("tr", "右上"),
            ("cl", "左"), ("cc", "正中"), ("cr", "右"),
            ("bl", "左下"), ("bc", "下"), ("br", "右下")]
# 强调色的现成配色。第一项是空串 = 不覆盖，跟主题默认那套走。
ACCENT_PRESETS = [("", "跟主题默认"), ("#3b7bf6", "蓝"), ("#17a2b8", "青"),
                  ("#22a06b", "绿"), ("#8b5cf6", "紫"), ("#f0883e", "橙"),
                  ("#e8608c", "玫红")]
IMAGE_FILTER = "图片 (*.png *.jpg *.jpeg *.webp *.bmp *.gif)"
VIDEO_FILTER = "视频 (*.mp4 *.webm *.mkv *.mov *.avi *.m4v)"
# 背景只留一个"导入文件"：图片和视频一起给，是哪种看后缀，不让用户再选一次类型
MEDIA_FILTER = ("图片或视频 (*.png *.jpg *.jpeg *.webp *.bmp *.gif "
                "*.mp4 *.webm *.mkv *.mov *.avi *.m4v *.wmv)"
                ";;图片 (*.png *.jpg *.jpeg *.webp *.bmp *.gif)"
                ";;视频 (*.mp4 *.webm *.mkv *.mov *.avi *.m4v *.wmv)")
VIDEO_EXTS = (".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v", ".wmv")
VIDEO_FRAME_S = 0.066          # 视频背景最多 15 帧/秒：再快只是白烧 CPU
BACKDROP_MAX_PX = 4096         # 底图最长边超过这个先缩一刀，免得一张 8K 图把内存吃光

_mode = "system"
_current = dict(THEMES["light"])
# 用户自己挑的强调色 / 卡片样式。放模块级是因为 build_qss() 和老的对话框都读这儿，
# 而且这些设置本来就是"整个界面一起变"，不是某一页的事。
_accent_pick = None
_card_alpha = 100
_card_radius = 12


def system_scheme():
    """系统现在是亮还是暗。Qt 说不出来（老旧系统 / 离屏）就退回读注册表。"""
    try:
        from PySide6.QtGui import QGuiApplication
        scheme = QGuiApplication.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return "dark"
        if scheme == Qt.ColorScheme.Light:
            return "light"
    except Exception:
        pass
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return "light" if int(value) else "dark"
    except Exception:
        return "light"


def get_mode():
    return _mode


def set_mode(mode):
    global _mode
    _mode = mode if mode in ("system", "light", "dark") else "system"
    return refresh_tokens()


def _mix(color, other, amount):
    """把 color 往 other 混 amount（0~1）。强调色的 hover / 选中底都是这么算的。"""
    a = max(0.0, min(1.0, float(amount)))
    return QColor(
        int(round(color.red() * (1 - a) + other.red() * a)),
        int(round(color.green() * (1 - a) + other.green() * a)),
        int(round(color.blue() * (1 - a) + other.blue() * a)),
        color.alpha())


def set_accent(color):
    """用户挑的强调色；传空 = 跟主题默认。

    只让他挑**一个**颜色：hover 和选中底是算出来的。要是让他一格格配四五个色，
    十有八九配出看不清的组合，那不是自定义、是自己给自己挖坑。
    """
    global _accent_pick
    text = str(color or "").strip()
    probe = QColor(text)
    _accent_pick = text if (text and probe.isValid()) else None
    return refresh_tokens()


def get_accent():
    return _accent_pick


def set_card_style(alpha=None, radius=None):
    """卡片的不透明度 / 圆角（样式表里的 $card、$card_radius 两个格子）。"""
    global _card_alpha, _card_radius
    if alpha is not None:
        try:
            _card_alpha = max(20, min(100, int(alpha)))
        except (TypeError, ValueError):
            pass
    if radius is not None:
        try:
            _card_radius = max(0, min(24, int(radius)))
        except (TypeError, ValueError):
            pass


def card_style():
    return _card_alpha, _card_radius


def _rgba(color, alpha_percent=100):
    """QSS 里的 rgba()。亮 / 暗两套底色都是实色，卡片要半透明只能自己拼字符串。"""
    c = QColor(color)
    alpha = int(round(255 * max(0, min(100, int(alpha_percent))) / 100))
    return "rgba(%d, %d, %d, %d)" % (c.red(), c.green(), c.blue(), alpha)


def _accent_into(palette, base):
    """把用户挑的强调色套到一套调色板上（refresh_tokens 里调）。"""
    accent = QColor(_accent_pick)
    if not accent.isValid():
        return
    dark = QColor(base["bg"]).lightness() < 128
    palette["accent"] = accent.name()
    # hover：亮色主题往暗走、暗色主题往亮走，"划过去"两边都看得出变化
    palette["accent_hover"] = _mix(
        accent, QColor("#ffffff") if dark else QColor("#000000"), 0.16).name()
    # 选中底：主色掺一丢丢到卡片底色里（掺多了对比度就没了）
    palette["accent_soft"] = _mix(accent, QColor(base["surface"]), 0.82).name()
    # 主色上的文字：亮主色配黑字、深主色配白字
    palette["accent_text"] = "#0d1220" if accent.lightness() > 150 else "#ffffff"


def refresh_tokens():
    """按当前模式重算调色板，返回实际生效的亮/暗。"""
    global _current
    effective = system_scheme() if _mode == "system" else _mode
    base = THEMES[effective]
    _current = dict(base)
    if _accent_pick:
        _accent_into(_current, base)
    return effective


def tokens():
    return _current


def is_dark():
    """现在实际生效的是亮色还是暗色（"跟随系统"也解析过）。

    桌宠那边画气泡要用它：气泡风格选「跟随界面」时，跟着这里走。
    """
    return (_mode if _mode in ("light", "dark") else system_scheme()) == "dark"


def default_accent():
    """主题自带的强调色（不受用户挑的那一个影响）。色卡上那颗「默认」用它。"""
    effective = system_scheme() if _mode == "system" else _mode
    return THEMES[effective]["accent"]


# --------------------------------------------------------------------------- #
# 图标（单色 SVG，用 currentColor 换色；随主题重画）
# --------------------------------------------------------------------------- #
_ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icons")
_ICON_CACHE = {}


def set_asset_dir(asset_dir):
    """由 桌宠.py 把 ASSET_DIR 递进来，省得自己猜打包后的路径。"""
    global _ICON_DIR
    if asset_dir:
        _ICON_DIR = os.path.join(asset_dir, "icons")


def icon_path(name):
    return os.path.join(_ICON_DIR, name + ".svg")


def icon_pixmap(name, color, size=18):
    """把某个图标渲染成指定颜色的位图（2 倍分辨率，高分屏不糊）。"""
    key = (name, color, size)
    hit = _ICON_CACHE.get(key)
    if hit is not None:
        return hit
    dpr = 2.0
    pix = QPixmap(int(size * dpr), int(size * dpr))
    pix.fill(Qt.GlobalColor.transparent)
    if SVG_OK:
        try:
            with open(icon_path(name), "r", encoding="utf-8") as fp:
                source = fp.read().replace("currentColor", color)
            renderer = QSvgRenderer(source.encode("utf-8"))
            painter = QPainter(pix)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            renderer.render(painter)
            painter.end()
        except Exception:
            pass
    pix.setDevicePixelRatio(dpr)
    _ICON_CACHE[key] = pix
    return pix


def icon(name, color, size=18):
    return QIcon(icon_pixmap(name, color, size))


def button_icon_color(style):
    """按钮上的小图标用哪个颜色（跟这颗按钮的文字一路）。"""
    if style == "primary":
        return tokens()["accent_text"]
    if style == "danger":
        return tokens()["danger"]
    return tokens()["text"]


def swatch_pixmap(color, size=18):
    """色卡上那一颗（2 倍分辨率，圆角方块）。"""
    px = int(size) * 2
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(QRectF(1.0, 1.0, px - 2.0, px - 2.0), 6.0, 6.0)
    painter.end()
    pm.setDevicePixelRatio(2.0)
    return pm


def clear_icon_cache():
    """换主题时清一遍（同一张图要按新颜色重画）。"""
    _ICON_CACHE.clear()


def bundle_icon(bundle_dir):
    """窗口 / 任务栏用的图标。

    原来全项目一个 `setWindowIcon` 都没有 → 任务栏上是一只**空白方块**（Windows
    找不到图标时的占位图）。这里优先用打包用的 `icon.ico`（16~256 各尺寸都齐），
    退回 `sprites/icon.png`。
    """
    for rel in ("icon.ico", os.path.join("sprites", "icon.png")):
        path = os.path.join(bundle_dir or "", rel)
        try:
            if os.path.exists(path):
                ico = QIcon(path)
                if not ico.isNull():
                    return ico
        except Exception:
            pass
    return QIcon()


def load_image(path):
    """读一张图（QImage）。读不出来给 None —— 用户把文件删了 / 挪走了也不能让窗口崩。"""
    try:
        if not path or not os.path.exists(path):
            return None
        img = QImage(path)
        if img.isNull():
            return None
        # 超大图先缩一刀再进后面的流程：一张 8000px 的图裁完就得 100MB 内存
        if max(img.width(), img.height()) > BACKDROP_MAX_PX:
            img = img.scaled(BACKDROP_MAX_PX, BACKDROP_MAX_PX,
                             Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        return img
    except Exception:
        return None


def bg_kind_of(path):
    """这个文件是图片还是视频 —— 只看后缀，不再让用户自己选一次。"""
    return "video" if os.path.splitext(str(path or ""))[1].lower() in VIDEO_EXTS \
        else "image"


def scale_cover(img, width, height, focus="cc"):
    """等比缩放到**刚好盖住** width×height，再裁一张正好那么大的。

    focus 是九宫格（先竖后横）：tl 留左上、cc 留正中、br 留右下 ——
    竖图铺进横窗口时"想留上半身还是下半身"就靠它。
    """
    if img is None or img.isNull() or width <= 0 or height <= 0:
        return img
    scaled = img.scaled(width, height,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation)
    focus = str(focus or "cc")
    hx = {"l": 0.0, "c": 0.5, "r": 1.0}.get(focus[1:2], 0.5)
    vy = {"t": 0.0, "c": 0.5, "b": 1.0}.get(focus[0:1], 0.5)
    x = int(round(max(0, scaled.width() - width) * hx))
    y = int(round(max(0, scaled.height() - height) * vy))
    return scaled.copy(x, y, width, height)


def brighten_image(img, amount):
    """亮暗度 -100 ~ +100：整张蒙一层黑或白。比逐像素算快一个数量级。"""
    amount = max(-100, min(100, int(amount or 0)))
    if img is None or img.isNull() or amount == 0:
        return img
    out = QImage(img)
    painter = QPainter(out)
    color = QColor("#ffffff") if amount > 0 else QColor("#000000")
    color.setAlpha(int(abs(amount) * 255 / 100))
    painter.fillRect(out.rect(), color)
    painter.end()
    return out


def blur_image(img, radius):
    """模糊：**缩到 1/s 再放大回来**，做两遍。

    直接卷一遍高斯太慢（125% 缩放下 1150×800 要几百毫秒，拖滑块会一顿一顿的）；
    而 Qt 在大比例缩小时走的是面积平均，等效一次盒式模糊，代价只有几毫秒。
    缩-放做两遍，把盒式那点方块感磨掉，肉眼分不出来。
    """
    radius = max(0, int(radius or 0))
    if img is None or img.isNull() or radius <= 0:
        return img
    out = img
    factor = 1.0 + radius * 0.30
    for _ in range(2):
        w = max(1, int(round(out.width() / factor)))
        h = max(1, int(round(out.height() / factor)))
        if w >= out.width() and h >= out.height():
            return out
        out = out.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
        out = out.scaled(img.width(), img.height(),
                         Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    return out


def pick_accent(img):
    """从一张图里挑一个能当强调色的颜色。

    做法很土但够用：缩到 64×64，按色相分 12 个桶，把"鲜艳又亮"的像素按权重
    累加，挑权重最大的那一桶取平均色。太暗的会提亮一档 —— 深蓝当强调色，
    按钮上那几个字会糊成一团。
    """
    if img is None or img.isNull():
        return ""
    small = img.scaled(64, 64, Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
    buckets = {}
    for y in range(small.height()):
        for x in range(small.width()):
            color = small.pixelColor(x, y)
            if color.alpha() < 32:
                continue
            hue, sat, val, _a = color.getHsv()
            if hue < 0 or sat < 60 or val < 60:      # 灰的、快黑的，不算
                continue
            weight = sat * val
            r, g, b, n = buckets.get(hue // 30, (0.0, 0.0, 0.0, 0.0))
            buckets[hue // 30] = (r + color.red() * weight,
                                  g + color.green() * weight,
                                  b + color.blue() * weight, n + weight)
    if not buckets:
        return ""
    _key, (r, g, b, n) = max(buckets.items(), key=lambda kv: kv[1][3])
    color = QColor(int(r / n), int(g / n), int(b / n))
    hue, sat, val, _a = color.getHsv()
    if val < 175:
        color = QColor.fromHsv(max(0, hue), sat, 175)
    return color.name()


def style_dialog(dlg, bundle_dir=None):
    """把设置窗口那套配色套到老对话框上（形象库 / 上传形象 / 扫描应用 / 各种小窗口）。

    这些窗口原来是 Qt 默认灰样式，跟新界面放一起像两个软件。套上同一份调色板，
    字体、按钮、下拉、列表、输入框就都统一了。
    """
    refresh_tokens()
    clear_icon_cache()
    dlg.setStyleSheet(build_qss())
    dlg.setFont(QFont("Microsoft YaHei UI", 9))
    ico = bundle_icon(bundle_dir)
    if not ico.isNull():
        dlg.setWindowIcon(ico)


# --------------------------------------------------------------------------- #
# 滚轮：不许它改滑块 / 下拉的值
# --------------------------------------------------------------------------- #
class _WheelGuard(QObject):
    """鼠标划过去随手一滚，数值 / 选项就变了 —— 那是误触，不是操作。

    处理办法不是简单吞掉：**把这一下转给外面的滚动区**（页面照常滚），
    外面没有滚动区（比如音量那个小窗口）才当没发生。
    滚动条自己的滚轮不拦 —— 那是正常的滚动。
    """

    def eventFilter(self, obj, ev):
        if ev.type() != QEvent.Type.Wheel:
            return False
        if not isinstance(obj, (QAbstractSlider, QComboBox)):
            return False
        if isinstance(obj, QScrollBar):
            return False
        area = obj.parentWidget()
        while area is not None and not isinstance(area, QAbstractScrollArea):
            area = area.parentWidget()
        if area is not None and area.viewport() is not obj:
            try:
                QApplication.sendEvent(area.viewport(), QWheelEvent(
                    ev.position(), ev.globalPosition(), ev.pixelDelta(),
                    ev.angleDelta(), ev.buttons(), ev.modifiers(),
                    ev.phase(), ev.inverted()))
            except Exception:
                pass
        return True


_WHEEL_GUARD = None


def install_wheel_guard(app):
    """整个程序装一遍：滑块 / 下拉不再被滚轮改值（多次调用也只装一个）。"""
    global _WHEEL_GUARD
    if _WHEEL_GUARD is None:
        _WHEEL_GUARD = _WheelGuard()
    try:
        app.installEventFilter(_WHEEL_GUARD)
    except Exception:
        pass
    return _WHEEL_GUARD


# --------------------------------------------------------------------------- #
# 样式表
# --------------------------------------------------------------------------- #
_QSS = Template("""
QWidget#shellRoot { font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"; }
QFrame#shell { background: $bg; border: 1px solid $border; border-radius: $shell_radius; }
QFrame#sidebar { background: $sidebar; border: none;
                 border-top-left-radius: 13px; border-bottom-left-radius: 13px; }
QFrame#header, QFrame#main { background: transparent; border: none; }
QLabel { color: $text; font-size: 13px; background: transparent; }
QLabel#brand { font-size: 14px; font-weight: 700; }
QLabel#pageTitle { font-size: 19px; font-weight: 700; }
QLabel#pageDesc { color: $text_dim; font-size: 12px; }
QLabel#cardTitle { font-size: 13px; font-weight: 700; }
QLabel#cardDesc { color: $text_faint; font-size: 11px; }
QLabel#rowTitle { font-size: 13px; }
QLabel#rowDesc { color: $text_dim; font-size: 11px; }
QLabel#big { font-size: 30px; font-weight: 700; }
QLabel#muted { color: $text_dim; font-size: 12px; }
QLabel#faint { color: $text_faint; font-size: 11px; }
QLabel#ok { color: $ok; font-size: 12px; }
QLabel#warn { color: $warn; font-size: 12px; }
QLabel#danger { color: $danger; font-size: 12px; }
QFrame#card { background: $card; border: 1px solid $border; border-radius: $card_radius; }
QFrame#divider { background: $border; border: none; max-height: 1px; }
QFrame#segBox { background: $surface_alt; border: none; border-radius: 9px; }
QPushButton#segBtn { background: transparent; border: none; border-radius: 7px;
                     padding: 5px 12px; color: $text_dim; font-size: 12px; }
QPushButton#segBtn:hover { color: $text; }
QPushButton#segBtn:checked { background: $seg_on; color: $text; font-weight: 700; }
QPushButton { background: $surface; border: 1px solid $border; border-radius: 8px;
              padding: 6px 14px; color: $text; font-size: 12px; }
/* hover 只换底色，不换细边框的颜色：这台机器 125% 缩放时，
   1px 边框在 hover 重绘那一下容易画丢顶边（看着像被什么挡了一截）。 */
QPushButton:hover { background: $surface_alt; border-color: $border; }
QPushButton:pressed { background: $surface_alt; }
QPushButton:disabled { color: $text_faint; border-color: $border; }
QPushButton#primary { background: $accent; border: 1px solid $accent;
                      color: $accent_text; font-weight: 700; }
QPushButton#primary:hover { background: $accent_hover; border-color: $accent_hover;
                            color: $accent_text; }
QPushButton#danger { color: $danger; }
QPushButton#danger:hover { background: $surface_alt; border-color: $danger;
                           color: $danger; }
QPushButton#winBtn { background: transparent; border: none; padding: 5px; border-radius: 6px; }
QPushButton#winBtn:hover { background: $surface_alt; }
/* 「控制台外观」里那排色卡：色块本身不带字，选中靠一圈描边 */
QPushButton#swatch { background: transparent; border: 2px solid transparent;
                     border-radius: 8px; padding: 0px; }
QPushButton#swatch:hover { background: transparent; border-color: $text_faint; }
QPushButton#swatch:checked { background: transparent; border-color: $text; }
QPushButton#swatchText, QPushButton#swatchIcon { background: $surface;
                     border: 1px solid $border; border-radius: 8px;
                     padding: 0px 8px; color: $text; font-size: 12px; }
QPushButton#swatchText:hover, QPushButton#swatchIcon:hover { background: $surface_alt; }
QPushButton#swatchText:checked { border: 2px solid $text; }
/* 「截取位置」那 9 个小格：选中那格填成主色 */
QPushButton#alignCell { background: $surface_alt; border: 1px solid $border;
                        border-radius: 5px; padding: 0px; }
QPushButton#alignCell:hover { border-color: $accent; }
QPushButton#alignCell:checked { background: $accent; border-color: $accent; }
QPushButton#alignCell:disabled { background: transparent; border-color: $border; }
/* 滑块右边那个数字：点一下能直接填数（省得拖半天） */
QPushButton#numBox { background: transparent; border: 1px solid transparent;
                     border-radius: 6px; padding: 0px; color: $text_dim;
                     font-size: 12px; }
QPushButton#numBox:hover { background: $surface_alt; border-color: $border;
                           color: $text; }
QComboBox { background: $surface_alt; border: 1px solid $border; border-radius: 8px;
            padding: 5px 8px; color: $text; font-size: 12px; min-width: 132px; }
QComboBox:hover { background: $surface; border-color: $accent; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: url($chevron); width: 11px; height: 11px; }
QComboBox QAbstractItemView { background: $surface; color: $text;
            border: 1px solid $border; outline: none; padding: 4px;
            selection-background-color: $accent_soft; selection-color: $text; }
QLineEdit { background: $surface_alt; border: 1px solid $border; border-radius: 8px;
            padding: 6px 10px; color: $text; font-size: 12px; }
QLineEdit:focus { border-color: $accent; background: $surface; }
/* 侧边栏里那个"搜设置…" */
QLineEdit#searchBox { background: $surface_alt; border-color: transparent;
                      padding: 5px 8px; margin-bottom: 6px; }
QLineEdit#searchBox:focus { border-color: $accent; background: $surface; }
/* 搜索结果列表：贴着侧边栏，别做成一张卡片 */
QListWidget#searchResults { background: transparent; border: none; padding: 0px; }
QListWidget#searchResults::item { padding: 6px 8px; border-radius: 7px;
                                  color: $nav_text; }
QListWidget#searchResults::item:hover { background: $surface_alt; color: $text; }
QListWidget#searchResults::item:selected { background: $accent_soft; color: $text; }
QSlider::groove:horizontal { height: 4px; background: $surface_alt; border-radius: 2px; }
QSlider::sub-page:horizontal { background: $accent; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; margin: -6px 0; border-radius: 7px;
                             background: #ffffff; border: 1px solid $border; }
QSlider::handle:horizontal:hover { border-color: $accent; }
QDialog { background: $bg; }
QListWidget { background: $surface; border: 1px solid $border; border-radius: 10px;
              color: $text; font-size: 12px; outline: none; padding: 4px; }
QListWidget::item { padding: 6px 8px; border-radius: 6px; }
QListWidget::item:hover { background: $surface_alt; }
QListWidget::item:selected { background: $accent_soft; color: $text; }
QPlainTextEdit, QTextEdit { background: $surface_alt; border: 1px solid $border;
              border-radius: 8px; color: $text; font-size: 12px; padding: 6px; }
QPlainTextEdit:focus, QTextEdit:focus { border-color: $accent; }
QCheckBox, QRadioButton { color: $text; font-size: 12px; }
QLabel#thumb { border: 1px dashed $border; border-radius: 8px; color: $text_faint; }
QLabel#thumbOn { border: 1px solid $border; border-radius: 8px; }
QLabel#dim { color: $text_dim; }
QLabel#warnText { color: $warn; }
QLabel#okText { color: $ok; }
QLabel#preview { border: 1px solid $border; border-radius: 10px; color: $text_faint;
                 background: $surface; }
/* 滚动区 / 页面内容都**不带底色**：底色由壳来画（壳是圆角卡片，带抗锯齿）。
   页面自己带底色的话，它铺满的是直角矩形，会把壳右下角的圆角填成直角
   （主人 2026-09-14 报的"右下角一直是直角"）。代价是视口不能再标"不透明"，
   滚动时父窗口要一起重画 —— 真机量过：滚一屏 3.65ms vs 原来的 3.71ms，没变慢。 */
QScrollArea { background: transparent; border: none; }
QWidget#pageInner { background: transparent; }
/* 视口（真正滚动的那一层）也保持透明：上面那两块不画了，壳自己的圆角
   （带抗锯齿）就露出来了，四个角形状一致。 */
#qt_scrollarea_viewport { background: transparent; }
/* 竖滚动条底下的留白从 2px 加到 6px：不加的话，滚到底时滑块的下端会探出壳右下角的圆角
   （真机实测：滑块色有 1~2 个像素落在圆弧外面，看着就是"滚动条长出来一点点"）。 */
QScrollBar:vertical { background: transparent; width: 10px;
                      margin: 2px 2px 6px 2px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $scroll; border-radius: 5px; min-height: 32px; }
QScrollBar::handle:vertical:hover { background: $accent; }
QScrollBar::handle:horizontal { background: $scroll; border-radius: 5px; min-width: 32px; }
QScrollBar::handle:horizontal:hover { background: $accent; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
""")


# 用户设了背景图 / 视频时追加的一段：把"实色底"换成"透一层"，
# 底图才看得见；卡片还是实心的，字不会跟着糊。
# 只加在控制台窗口上（build_qss(glass=True)），老对话框照旧用实色底。
_QSS_GLASS = Template("""
QFrame#shell { background: transparent; }
QFrame#sidebar { background: $sidebar_glass; }
QScrollArea { background: transparent; }
QWidget#pageInner { background: transparent; }
QDialog { background: $dialog_bg; }
""")


def build_qss(glass=False):
    data = dict(tokens())
    data["chevron"] = icon_path("ui.chevron-down").replace("\\", "/")
    data["shell_radius"] = "%dpx" % SHELL_RADIUS
    # 卡片那两个格子：默认就是实心 + 12px 圆角，用户在「控制台外观」里能改
    data["card"] = _rgba(tokens()["surface"], _card_alpha)
    data["card_radius"] = "%dpx" % int(_card_radius)
    out = _QSS.substitute(data)
    if glass:
        out += _QSS_GLASS.substitute(dict(
            data,
            sidebar_glass=_rgba(tokens()["sidebar"], 62),
            dialog_bg=tokens()["bg"]))
    return out


# --------------------------------------------------------------------------- #
# 小控件
# --------------------------------------------------------------------------- #
class Switch(QAbstractButton):
    """小开关（轨道 + 圆钮）。颜色跟着主题走，所以 paintEvent 里现取。"""

    def __init__(self, checked=False, on_change=None, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(bool(checked))
        # 高度取 24：125% 缩放时正好 30 物理像素（26 会落在半像素上，
        # 一列控件累积下来，细边框那几条线就会忽隐忽现）
        self.setFixedSize(44, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if on_change is not None:
            self.toggled.connect(on_change)

    def sizeHint(self):
        return QSize(44, 24)

    def paintEvent(self, _ev):
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        track = QRectF(1.0, 3.0, self.width() - 2.0, self.height() - 6.0)
        radius = track.height() / 2.0
        if not self.isEnabled():
            color = t["surface_alt"]
        elif self.isChecked():
            color = t["accent"]
        else:
            color = t["switch_off"]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(track, radius, radius)
        knob = track.height() - 5.0
        x = track.right() - knob - 2.5 if self.isChecked() else track.left() + 2.5
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(x, track.top() + 2.5, knob, knob))
        painter.end()


class Segmented(QWidget):
    """一排互斥按钮（"三选一"那种），比下拉框点得少。"""

    def __init__(self, options, current=None, on_change=None, parent=None):
        super().__init__(parent)
        self._on_change = on_change
        self._buttons = {}
        self._icons = {}              # 值 → 图标名（options 第三项给了才有）
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._box = QFrame()
        self._box.setObjectName("segBox")
        self._line = QHBoxLayout(self._box)
        self._line.setContentsMargins(3, 3, 3, 3)
        self._line.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._fill(options, current)
        outer.addWidget(self._box)
        outer.addStretch(1)

    def _fill(self, options, current):
        """按 (值, 文字[, 图标]) 摆一排按钮。"""
        for opt in options:
            value, label = opt[0], opt[1]
            self._add(value, label, value == current,
                      opt[2] if len(opt) > 2 else None)

    def _add(self, value, label, checked=False, icon_name=None):
        btn = QPushButton(label)
        btn.setObjectName("segBtn")
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setChecked(bool(checked))
        btn.clicked.connect(lambda _=False, v=value: self._pick(v))
        if icon_name:
            self._icons[value] = icon_name
            btn.setIconSize(QSize(ICON_SM, ICON_SM))
            btn.setIcon(icon(icon_name, tokens()["nav_text"], ICON_SM))
        self._line.addWidget(btn)
        self._group.addButton(btn)
        self._buttons[value] = btn
        return btn

    def set_options(self, options, current=None):
        """整排换内容（城市列表这种"条目本身会变"的地方用）。"""
        for btn in list(self._buttons.values()):
            self._line.removeWidget(btn)
            self._group.removeButton(btn)
            btn.setParent(None)
            btn.deleteLater()
        self._buttons.clear()
        self._icons.clear()
        self._fill(options, current)
        self.update()

    def repaint_theme(self):
        """换主题后重画里面的小图标（颜色跟着主题的文字色走）。"""
        for value, name in self._icons.items():
            btn = self._buttons.get(value)
            if btn is not None:
                btn.setIcon(icon(name, tokens()["nav_text"], ICON_SM))

    def _pick(self, value):
        if self._on_change is not None:
            self._on_change(value)

    def set_value(self, value):
        """选中某一项；传 None（或找不到）就把整排取消选中。"""
        btn = self._buttons.get(value)
        if btn is None:
            self._group.setExclusive(False)
            for one in self._buttons.values():
                one.setChecked(False)
            self._group.setExclusive(True)
            return
        if not btn.isChecked():
            btn.setChecked(True)

    def set_label(self, value, text, tooltip=""):
        """改某一项的文字（「现在是谁」要跟着库里的形象名换）。"""
        btn = self._buttons.get(value)
        if btn is None:
            return
        if btn.text() != text:
            btn.setText(text)
        btn.setToolTip(tooltip or text)


class ColorSwatches(QWidget):
    """一排色卡 + 「自定义…」+ 「从背景取色」。

    比下拉框少一步：色块点一下就是它，不用先展开再挑。
    「自定义…」那颗自己也能显示颜色 —— 当前颜色是用户自己挑的（不在预设里），
    它会被点亮并变成那个色，一眼就知道现在用的是哪颗。
    """

    def __init__(self, current, on_pick, on_custom, on_from_bg, parent=None):
        super().__init__(parent)
        self._on_pick = on_pick
        self._current = str(current or "")
        box = QHBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(5)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons = {}
        for value, label in ACCENT_PRESETS:
            btn = QPushButton()
            btn.setObjectName("swatch")
            btn.setCheckable(True)
            btn.setFixedSize(26, 26)
            btn.setIconSize(QSize(18, 18))
            btn.setIcon(QIcon(swatch_pixmap(value or default_accent(), 18)))
            btn.setToolTip(label)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, v=value: self._on_pick(v))
            self._group.addButton(btn)
            box.addWidget(btn)
            self._buttons[value] = btn

        self._custom = QPushButton("自定义…")
        self._custom.setObjectName("swatchText")
        self._custom.setCheckable(True)
        self._custom.setFixedHeight(26)
        self._custom.setIconSize(QSize(15, 15))
        self._custom.setCursor(Qt.CursorShape.PointingHandCursor)
        self._custom.setToolTip("自己挑一个 —— 取色盘右边那颗吸管能吸屏幕上的任意一点")
        self._custom.clicked.connect(lambda _=False: on_custom())
        self._group.addButton(self._custom)
        box.addWidget(self._custom)

        self._from_bg = QPushButton()
        self._from_bg.setObjectName("swatchIcon")
        self._from_bg.setFixedSize(26, 26)
        self._from_bg.setIconSize(QSize(16, 16))
        self._from_bg.setCursor(Qt.CursorShape.PointingHandCursor)
        self._from_bg.setToolTip("从背景图里挑一个颜色")
        self._from_bg.setIcon(icon("ui.pipette", tokens()["text"], ICON_SM))
        self._from_bg.clicked.connect(lambda _=False: on_from_bg())
        box.addWidget(self._from_bg)
        self.set_value(current)

    def set_value(self, value):
        """把色卡摆成"现在用的是哪个"（自己挑的颜色点亮「自定义…」）。"""
        value = str(value or "")
        self._current = value
        default_btn = self._buttons.get("")
        if default_btn is not None:
            default_btn.setIcon(QIcon(swatch_pixmap(default_accent(), 18)))
        if value and value not in self._buttons:
            self._custom.setIcon(QIcon(swatch_pixmap(value, 15)))
            self._custom.setToolTip(f"自定义 {value}（点了可以再换）")
            self._custom.setChecked(True)
            return
        self._custom.setIcon(QIcon(swatch_pixmap(tokens()["accent"], 15)))
        self._custom.setToolTip("自己挑一个 —— 取色盘右边那颗吸管能吸屏幕上的任意一点")
        btn = self._buttons.get(value)
        if btn is not None:
            btn.setChecked(True)
            return
        self._group.setExclusive(False)
        for one in self._buttons.values():
            one.setChecked(False)
        self._custom.setChecked(False)
        self._group.setExclusive(True)

    def repaint_theme(self):
        """换主题（亮/暗）之后重画那颗「默认」和图标按钮。"""
        self.set_value(self._current)
        self._from_bg.setIcon(icon("ui.pipette", tokens()["text"], ICON_SM))


class AlignGrid(QWidget):
    """九宫格：铺满的时候"留哪一块"（选中的那格填成主色）。"""

    def __init__(self, current, on_pick, parent=None):
        super().__init__(parent)
        self._on_pick = on_pick
        self._buttons = {}
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(3)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for index, (value, label) in enumerate(BG_FOCUS):
            btn = QPushButton()
            btn.setObjectName("alignCell")
            btn.setCheckable(True)
            btn.setFixedSize(24, 24)
            btn.setToolTip(label)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, v=value: self._on_pick(v))
            self._group.addButton(btn)
            grid.addWidget(btn, index // 3, index % 3)
            self._buttons[value] = btn
        self.set_value(current)

    def set_value(self, value):
        btn = self._buttons.get(str(value or "cc")) or self._buttons.get("cc")
        if btn is not None and not btn.isChecked():
            btn.setChecked(True)


class NavItem(QAbstractButton):
    """左侧一条分类：图标 + 文字，选中时铺一层主题色底片。"""

    def __init__(self, key, text, icon_name, parent=None):
        super().__init__(parent)
        self.key = key
        self.icon_name = icon_name
        self.setText(text)
        self.setCheckable(True)
        self.setFixedHeight(36)          # 36 = 45 物理像素（125% 下是整数）
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._hover = False

    def enterEvent(self, _ev):
        self._hover = True
        self.update()

    def leaveEvent(self, _ev):
        self._hover = False
        self.update()

    def paintEvent(self, _ev):
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.isChecked():
            bg, fg = t["accent_soft"], t["accent"]
        elif self._hover:
            bg, fg = t["surface_alt"], t["text"]
        else:
            bg, fg = None, t["nav_text"]
        if bg is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(bg))
            painter.drawRoundedRect(
                QRectF(0.0, 0.5, float(self.width()), self.height() - 1.0), 9, 9)
        painter.drawPixmap(11, (self.height() - 18) // 2,
                           icon_pixmap(self.icon_name, fg, ICON_MD))
        font = QFont(self.font())
        font.setPixelSize(13)
        font.setBold(self.isChecked())
        painter.setFont(font)
        painter.setPen(QColor(fg))
        painter.drawText(
            QRectF(39, 0, self.width() - 48, float(self.height())),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self.text())
        painter.end()


class _NativeMsg(ctypes.Structure):
    """原生消息（只用到前面几个字段）。"""
    _fields_ = [("hWnd", ctypes.c_void_p), ("message", ctypes.c_uint),
                ("wParam", ctypes.c_void_p), ("lParam", ctypes.c_void_p)]


class _MinimizeGuard(QAbstractNativeEventFilter):
    """把"从系统那边来的最小化"也接过来，改走我们那套缩放动画。

    来源包括：点任务栏图标、系统菜单里的「最小化」、Alt+空格+M。

    为什么必须拦：我们的窗口是无边框 + 半透明（分层窗口），
    Windows **不会**给它跑最小化动画（实测：`ShowWindow(SW_MINIMIZE)` 之后
    窗口矩形一采样就跳到 -32000，压根没有过渡帧）。
    所以这里在原生消息层把 `SC_MINIMIZE` 吃掉，自己放动画 ——
    这样"点任务栏图标"和"点右上角那颗按钮"看到的是同一套动画。
    """

    WM_SYSCOMMAND = 0x0112
    SC_MINIMIZE = 0xF020
    SC_RESTORE = 0xF120

    def __init__(self, window):
        super().__init__()
        self._win = window

    def nativeEventFilter(self, _event_type, message):
        try:
            msg = ctypes.cast(int(message), ctypes.POINTER(_NativeMsg)).contents
        except Exception:
            return False, 0
        if msg.message != self.WM_SYSCOMMAND:
            return False, 0
        command = int(msg.wParam) & 0xFFF0
        if command not in (self.SC_MINIMIZE, self.SC_RESTORE):
            return False, 0
        try:
            if int(msg.hWnd) != int(self._win.winId()):
                return False, 0            # 不是我们这个窗口的最小化，别管
        except Exception:
            return False, 0
        # 不能在过滤器里直接跑动画（还在消息处理里），下一拍再说。
        # SC_MINIMIZE = 点任务栏图标/系统菜单要最小化；SC_RESTORE = 最小化着再点一次要还原
        if command == self.SC_RESTORE:
            QTimer.singleShot(0, self._win.restore_with_anim)
        else:
            QTimer.singleShot(0, self._win.minimize_with_anim)
        return True, 0                     # 吃掉：不让系统自己 minimize（否则会先闪一下）


class DragBar(QFrame):
    """标题栏：空白处按住能拖窗口（子控件自己吃掉点击，互不打架）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_from = None

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            window = self.window()
            self._drag_from = (ev.globalPosition().toPoint()
                               - window.frameGeometry().topLeft())
            ev.accept()
        else:
            super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._drag_from is not None and ev.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(ev.globalPosition().toPoint() - self._drag_from)
            ev.accept()
        else:
            super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        self._drag_from = None
        super().mouseReleaseEvent(ev)


class EmptyState(QWidget):
    """空状态：一张小插图 + 一句人话（比光丢一行灰字好看，也一眼看懂该干嘛）。

    插图用跟别处同一套线稿（assets/icons），颜色取当前主题的淡字色，
    所以换主题时由页面的 repaint_cards() 一起重画。
    """

    def __init__(self, icon_name, title, hint="", size=54, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self._size = size
        col = QVBoxLayout(self)
        col.setContentsMargins(6, 10, 6, 12)
        col.setSpacing(6)
        self._mark = QLabel()
        self._mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mark.setPixmap(icon_pixmap(icon_name, tokens()["text_faint"], size))
        col.addWidget(self._mark)
        self._title = QLabel(title)
        self._title.setObjectName("muted")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setWordWrap(True)
        col.addWidget(self._title)
        self._hint = None
        if hint:
            self._hint = QLabel(hint)
            self._hint.setObjectName("faint")
            self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._hint.setWordWrap(True)
            col.addWidget(self._hint)

    def set_text(self, title, hint=""):
        self._title.setText(title)
        if self._hint is not None:
            self._hint.setText(hint)

    def repaint_theme(self):
        self._mark.setPixmap(icon_pixmap(self._icon_name, tokens()["text_faint"],
                                        self._size))


class _FlashBox(QWidget):
    """跳到某个设置项之后，在那一行上闪一圈主色边框。

    自己画一圈就走，不动那一行自己的样式 —— 改样式表会牵连里面的子控件。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._t = 1.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def set_opacity(self, value):
        self._t = max(0.0, min(1.0, float(value)))
        self.update()

    def paintEvent(self, _ev):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = QColor(tokens()["accent"])
        color.setAlphaF(min(1.0, 0.9 * self._t))
        pen = QPen(color)
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(1.0, 1.0, self.width() - 2.0,
                                       self.height() - 2.0), 9.0, 9.0)
        painter.end()


class Page(QScrollArea):
    """一页内容。卡片 / 行 / 分隔线都从这儿长出来，风格自然统一。"""

    def __init__(self, title, desc=""):
        super().__init__()
        self.title = title
        self.desc = desc
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # **千万不要**给视口标 WA_OpaquePaintEvent：那是"我这块整片都会画满"的承诺，
        # 页面现在不带底色（底色归壳画，这样壳右下角的圆角才不会被填成直角），
        # 标了它 Qt 就不再重画底下的壳，圆角那块会变成一片透明（真机踩过）。
        # 代价（滚动时父窗口跟着重画）真机量过：滚一屏 3.65ms vs 3.71ms，没变慢。
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        inner = QWidget()
        inner.setObjectName("pageInner")
        self.body = QVBoxLayout(inner)
        self.body.setContentsMargins(22, 2, 22, 22)
        self.body.setSpacing(14)
        self.body.addStretch(1)
        self.setWidget(inner)
        self._card_icons = []
        self._btn_icons = []          # [(按钮, 图标名, 样式名)]：换主题时要重画颜色
        self._segments = []           # 这一页上的分段控件：换主题时也要重画里面的图标
        self._empties = []            # 空状态块：换主题时也要重画插图
        self._index = []              # [(标题, 说明, 控件)] —— 给"设置项搜索"用的目录

    # ---- 积木 ----
    def card(self, title, desc="", icon_name=None):
        """加一张卡片，返回它的内容布局（往里面放行）。"""
        frame = QFrame()
        frame.setObjectName("card")
        box = QVBoxLayout(frame)
        box.setContentsMargins(16, 13, 16, 14)
        box.setSpacing(11)
        head = QHBoxLayout()
        head.setSpacing(8)
        if icon_name:
            mark = QLabel()
            mark.setFixedSize(17, 17)
            mark.setPixmap(icon_pixmap(icon_name, tokens()["accent"], ICON_CARD))
            self._card_icons.append((mark, icon_name))
            head.addWidget(mark)
        label = QLabel(title)
        label.setObjectName("cardTitle")
        head.addWidget(label)
        head.addStretch(1)
        if desc:
            hint = QLabel(desc)
            hint.setObjectName("cardDesc")
            head.addWidget(hint)
        box.addLayout(head)
        self.body.insertWidget(self.body.count() - 1, frame)
        return box

    def row(self, layout, title, desc="", control=None):
        wrap = QWidget()
        line = QHBoxLayout(wrap)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(12)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(1)
        name = QLabel(title)
        name.setObjectName("rowTitle")
        col.addWidget(name)
        if desc:
            sub = QLabel(desc)
            sub.setObjectName("rowDesc")
            sub.setWordWrap(True)
            col.addWidget(sub)
        # 左边这栏文字**整块居中**，不让标题和说明被拉开：
        # 右边控件高（比如"截取位置"那个九宫格）时，原来两行字会一个在顶一个在底。
        holder = QWidget()
        holder.setLayout(col)
        line.addWidget(holder, 1, Qt.AlignmentFlag.AlignVCenter)
        if control is not None:
            line.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(wrap)
        # 挂两个引用：外面要改这一行的文字时不用再去翻 QLabel（背景那行就靠它刷文件名）
        wrap.title_label = name
        wrap.desc_label = sub if desc else None
        self._index.append((title, desc or "", wrap))
        return wrap

    def empty(self, icon_name, title, hint="", size=54, layout=None):
        """放一个空状态（插画 + 一句话）。layout 给了就放进那张卡片里。

        返回它，方便按状态 set_text / 显隐。
        """
        widget = EmptyState(icon_name, title, hint, size)
        if layout is not None:
            layout.addWidget(widget)
        else:
            self.body.insertWidget(self.body.count() - 1, widget)
        self._empties.append(widget)
        return widget

    def buttons(self, layout, items, align_right=True):
        """一行按钮：items = [(文字, 回调, 样式名 or None[, 图标名]), …]。

        图标是可选的第四项：给了就画在文字前面，颜色按按钮样式走
        （主按钮用主色上的字色、危险按钮用危险色、普通按钮用正文色），
        换主题时由 repaint_cards() 一起重画。
        """
        wrap = QWidget()
        line = QHBoxLayout(wrap)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        if align_right:
            line.addStretch(1)
        btns = []
        for item in items:
            text, slot, style = item[0], item[1], item[2]
            icon_name = item[3] if len(item) > 3 else None
            btn = QPushButton(text)
            # 固定高度 32：125% 缩放下 = 整 40 物理像素（30 会落在半像素上，
            # 细边框和圆角那一下容易画糊）
            btn.setFixedHeight(32)
            if style:
                btn.setObjectName(style)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if icon_name:
                btn.setIconSize(QSize(ICON_SM, ICON_SM))
                btn.setIcon(icon(icon_name, button_icon_color(style), ICON_SM))
                self._btn_icons.append((btn, icon_name, style))
            if slot is not None:
                btn.clicked.connect(lambda _=False, f=slot: f())
            line.addWidget(btn)
            btns.append(btn)
        if not align_right:
            line.addStretch(1)
        layout.addWidget(wrap)
        # 挂个按钮清单：外面要改按钮文字（比如"我的形象库…（三维 1 · 挂件 0）"的条目数）时
        # 不用再去翻 QPushButton，也不用赌 findChildren 的先后顺序
        wrap.buttons = btns
        # 一排按钮当成一条目录项（搜索「删除」能一次找到这一排）
        texts = [b.text() for b in btns if b.text()]
        if texts:
            self._index.append((" / ".join(texts), "", wrap))
        return wrap

    def hint(self, layout, text, style="faint"):
        label = QLabel(text)
        label.setObjectName(style)
        label.setWordWrap(True)
        layout.addWidget(label)
        return label

    def divider(self, layout):
        line = QFrame()
        line.setObjectName("divider")
        line.setFixedHeight(1)
        layout.addWidget(line)
        return line

    def slider(self, layout, title, desc, low, high, value, unit, on_change):
        """一行带滑块的设置：拖动时右边数字跟着变，边拖边生效。"""
        box = QWidget()
        line = QHBoxLayout(box)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(12)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(1)
        name = QLabel(title)
        name.setObjectName("rowTitle")
        col.addWidget(name)
        if desc:
            sub = QLabel(desc)
            sub.setObjectName("rowDesc")
            col.addWidget(sub)
        line.addLayout(col, 1)
        # 右边的数字做成一颗粒按钮：点一下直接填数（拖到 -35 这种位置太费劲）。
        # 填超了上下限也没关系 —— QInputDialog 自己就夹在 range 里，而且只收整数。
        show = QPushButton(f"{value}{unit}")
        show.setObjectName("numBox")
        # 宽度跟着文字走：以前写死 54px，像「30 分钟」这种四五个字就装不下、会被切掉
        # （v1.1.4 免打扰那行"30 分钟"只剩半截就是这个原因）

        def fit_box(text):
            show.setFixedSize(max(54, show.fontMetrics().horizontalAdvance(text) + 18), 24)

        # 按**这一行最大能出现的数字**定宽：「30 分钟」放得下，拖到 180 也不会跳
        # （"100%" 这种还是原来的 54px，别的页一点没变）
        fit_box(max((f"{low}{unit}", f"{high}{unit}"),
                    key=lambda t: show.fontMetrics().horizontalAdvance(t)))
        show.setCursor(Qt.CursorShape.PointingHandCursor)
        show.setToolTip(f"点一下直接填（{low} ~ {high}，整数）")
        bar = QSlider(Qt.Orientation.Horizontal)
        bar.setRange(low, high)
        bar.setValue(value)
        bar.setFixedWidth(190)
        bar.setCursor(Qt.CursorShape.PointingHandCursor)
        bar.value_label = show          # 外面要改数字（比如点档位）时用得上

        def moved(v):
            show.setText(f"{v}{unit}")
            on_change(v)

        def typed():
            got, ok = QInputDialog.getInt(self, "填一个数", f"{title}：",
                                          int(bar.value()), int(low), int(high), 1)
            if ok:
                bar.setValue(int(got))

        show.clicked.connect(typed)
        bar.valueChanged.connect(moved)
        line.addWidget(bar, 0, Qt.AlignmentFlag.AlignVCenter)
        line.addWidget(show, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(box)
        self._index.append((title, desc or "", box))
        return bar

    def combo(self, layout, title, desc, options, current, on_change):
        """一行配一个下拉框：options = [(值, 显示文字), …]。"""
        box = QComboBox()
        for value, label in options:
            box.addItem(label, value)
        for index in range(box.count()):
            if box.itemData(index) == current:
                box.setCurrentIndex(index)
                break
        box.setCursor(Qt.CursorShape.PointingHandCursor)
        box.currentIndexChanged.connect(lambda _i: on_change(box.currentData()))
        self.row(layout, title, desc, box)
        return box

    def repaint_cards(self):
        """换主题后重画这一页上的所有小图标（卡片标题 / 按钮 / 分段控件）。"""
        for label, name in self._card_icons:
            label.setPixmap(icon_pixmap(name, tokens()["accent"], ICON_CARD))
        for btn, name, style in self._btn_icons:
            btn.setIcon(icon(name, button_icon_color(style), ICON_SM))
        for seg in self._segments:
            seg.repaint_theme()
        for empty in self._empties:
            empty.repaint_theme()


# --------------------------------------------------------------------------- #
# 窗口壳：背景图画在这一层（所有控件底下）
# --------------------------------------------------------------------------- #
class _PageFade(QWidget):
    """切页时铺在整壳上的那张"上一屏"截图，按自己的拍子淡掉。

    刻意**不用** QGraphicsOpacityEffect：它会把那一页整棵子树塞进离屏图里重画一遍，
    配这个"无边框 + 半透明"的窗口会闪、会错位，而且一帧就贵得多
    （一帧一次整页离屏合成，滚动也跟着慢）。这里只是把一张截图按不透明度贴出来，
    跟最小化动画是同一套做法。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pm = None
        self._op = 1.0
        # 动画这 150 毫秒里别吃鼠标：点哪就点到底下的真控件
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def set_pixmap(self, pm):
        self._pm = pm
        self.update()

    def set_opacity(self, value):
        self._op = max(0.0, min(1.0, float(value)))
        self.update()

    def paintEvent(self, _ev):
        if self._pm is None or self._pm.isNull():
            return
        painter = QPainter(self)
        painter.setOpacity(self._op)
        painter.drawPixmap(0, 0, self._pm)
        painter.end()


class ShellFrame(QFrame):
    """窗口那张圆角卡片。

    平时它就是一块纯色（底色交给样式表）；用户设了背景图 / 视频时，
    把处理好的底图贴在这儿 —— 它是最外层的子控件，所以天然在所有内容底下。
    样式表那边同时把 `#shell` 的底色改成透明，不然底图会被自己的底色盖住。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.backdrop = None            # 已按窗口大小裁好（+亮暗/模糊）的底图
        self.backdrop_scrim = 0         # 遮罩不透明度 0~255
        self.backdrop_rgb = "#000000"   # 遮罩颜色：跟当前主题的底色走

    def paintEvent(self, ev):
        if self.backdrop is not None and not self.backdrop.isNull():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            path = QPainterPath()
            path.addRoundedRect(
                QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0),
                14.0, 14.0)
            painter.setClipPath(path)
            painter.drawPixmap(0, 0, self.backdrop)
            if self.backdrop_scrim > 0:
                scrim = QColor(self.backdrop_rgb)
                scrim.setAlpha(self.backdrop_scrim)
                painter.fillPath(path, scrim)
            painter.end()
        # 边框仍旧交给样式表画（开着背景时那边只留一圈 1px 边框）
        super().paintEvent(ev)


# --------------------------------------------------------------------------- #
# 控制台窗口
# --------------------------------------------------------------------------- #
class ConsoleWindow(QWidget):
    """设置窗口本体。pet 是桌宠（PetWindow），ctx 是 桌宠.py 递进来的常量/函数表。

    分类只放**设置**。「看一眼余额 / 看一看天气 / 在放什么」这类是桌宠自己的活儿，
    菜单和桌宠本体上都有，不往设置里塞（v1.1.0 第一版塞过，太重复，撤了）。
    """

    PAGES = [
        ("balance", "余额和用量", "Key、来源、今日已用怎么算",
         "nav.balance", "_page_balance"),
        ("appearance", "桌宠形象", "换成谁、多大、多透明、在哪一层",
         "nav.appearance", "_page_appearance"),
        ("console", "控制台外观", "背景、标题、图标，都随你",
         "nav.console", "_page_console"),
        ("behavior", "动作和互动", "怎么走、双击做什么、怎么防误触",
         "nav.behavior", "_page_behavior"),
        ("weather", "天气和城市", "看哪个城市的天气", "nav.weather", "_page_weather"),
        ("music", "音乐和歌词", "放歌时跟着唱", "nav.music", "_page_music"),
        ("lines", "文案和语录", "闲着时说什么、高峰时段怎么显示",
         "nav.lines", "_page_lines"),
        ("sound", "音效", "按键音效、音量、自己加的音频", "nav.sound", "_page_sound"),
        ("integration", "应用联动", "应用启动 / 使用时长 / 定时提醒、全局快捷键",
         "nav.integration", "_page_integration"),
        ("dsh", "DSH 联动", "跟着 DSH 干活实时换姿势、冒台词",
         "ui.eye", "_page_dsh"),
        ("performance", "性能和工具", "流畅度、回收内存",
         "nav.performance", "_page_performance"),
        ("general", "通用", "显示、主题、开机自启、排查",
         "nav.general", "_page_general"),
        ("about", "关于", "版本与反馈", "nav.about", "_page_about"),
    ]

    def __init__(self, pet, ctx):
        super().__init__(None)
        self.pet = pet
        self.ctx = ctx or {}
        self._pages = {}
        self._nav_items = {}
        # 「这一页要现读一遍数据」的挂点：key → [回调]。
        # 页面是建一次就留着不重建的，凡是"会变的数据"（比如形象库的条目数）都得靠这个刷新，
        # 不然就得重启桌宠才能看见新数（见 _hook_page / _refresh_page）。
        self._page_hooks = {}
        self._cur_page_key = None         # 现在停在哪一页（showEvent 刷新时用）
        self._btn_icons = []              # 窗口自己建的按钮（_text_button）上的图标
        self._search_index = []           # 设置项搜索的目录（见 _build_main）
        self._flash = None                # 搜索跳转之后那一圈高亮
        self._flash_timer = None
        self._shadow_pm = None            # 阴影贴图缓存（见 _shadow_pixmap）
        self._shadow_key = None
        self._min_anim = None             # 最小化动画（跑着的时候不接第二次）
        self._min_pm = None               # 动画期间铺的那张"整窗截图"
        self._min_self = False            # 这一次最小化是不是我们自己发起的
        self._anim_target = None          # 正在往哪边走："min" / "restore"
        self._restoring = False
        self._restore_geo = None          # 正常大小该在哪儿
        self._min_min_size = None
        self._anim_fade = 1.0             # 动画期间那张截图的绘制不透明度（0~1）
        self._anim = None                 # 自己的动画拍子（见 _anim_tick）
        self._tick_timer = None
        # 主题要先定下来：页面里那个"主题三选一"建的时候就要知道现在选的是哪档
        self._mode = pet.cfg.get("ui_theme", "system")
        set_mode(self._mode)
        # 强调色 / 卡片样式是"整个界面"的事（老对话框也套同一套），
        # 而且调色板在建控件时就要用上，所以先定下来再建窗口
        set_accent(pet.cfg.get("console_accent"))
        set_card_style(pet.cfg.get("console_card_alpha"),
                       pet.cfg.get("console_card_radius"))
        # 滚轮改值这个毛病在设置窗口里最明显，这里也保证装上（重复装无副作用）
        try:
            install_wheel_guard(QApplication.instance())
        except Exception:
            pass

        # 控制台自己的样子（背景 / 标题 / 图标）。全部现读 config.json，
        # 存的是 `console_` 开头那几个键（见 BACKDROP_DEFAULTS）。
        self._bg_src = None               # 原图缓存
        self._bg_src_key = None
        self._bg_out = None               # 裁好 + 亮暗 + 模糊之后的底图
        self._bg_out_key = None
        self._bg_out_params = None        # 上面那张图是按哪些参数算的（自检用）
        self._video_pm = None             # 视频当前帧（还没处理）
        self._video_path = None
        self._video_player = None
        self._video_sink = None
        self._video_ts = 0.0
        self._video_wanted = False
        self._brand_img = None            # 侧边栏图标（用户的图）
        self._brand_key = None
        self._glass_state = None          # 样式表现在是"透"的还是"实"的
        self._bg_size_timer = QTimer(self)
        self._bg_size_timer.setSingleShot(True)
        self._bg_size_timer.setInterval(140)      # 拖窗口时别每帧都重算底图
        self._bg_size_timer.timeout.connect(
            lambda: self._apply_backdrop(force=True))
        self._style_timer = QTimer(self)
        self._style_timer.setSingleShot(True)
        self._style_timer.setInterval(60)      # 连拖滑块时攒一下再重下样式表
        self._style_timer.timeout.connect(self.apply_theme)
        self._geo_timer = QTimer(self)
        self._geo_timer.setSingleShot(True)
        self._geo_timer.setInterval(500)       # 松手半秒之后再记窗口大小 / 位置
        self._geo_timer.timeout.connect(self._geo_save)

        self.setWindowTitle("大肥鱼桌宠 · 设置")
        self.setWindowFlags(Qt.WindowType.Window
                            | Qt.WindowType.FramelessWindowHint
                            # 一定要带这个：Windows 只有认到 WS_MINIMIZEBOX 才会
                            # 让"点任务栏图标 = 最小化 / 再点唤出"生效
                            | Qt.WindowType.WindowMinimizeButtonHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # 高度 620 是这一版涨上来的：左侧分类从 11 条变成 12 条，560 会把
        # 底下那条版本号挤出去（12×36 + 11×4 + 品牌 + 边距 ≈ 558，壳得够高）。
        self.setMinimumSize(820, 620)
        self.resize(920, 640)
        self._geo_restore()          # 「记住窗口大小和位置」开着就摆回上次那儿
        self.setFont(QFont("Microsoft YaHei UI", 9))
        ico = bundle_icon(self.ctx.get("BUNDLE_DIR"))
        if not ico.isNull():
            self.setWindowIcon(ico)       # 不然任务栏上是一只空白方块

        # 外面留 20px 给阴影，里面才是"真正的窗口"
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        self.shell = ShellFrame()
        self.shell.setObjectName("shell")
        outer.addWidget(self.shell)

        body = QHBoxLayout(self.shell)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_sidebar())
        body.addWidget(self._build_main(), 1)

        self.apply_theme()
        # 一开始先摆哪一页。原来这儿写的是 "home" —— 而 "home" 这一页 v1.1.0
        # 早就删了，等于什么都没切，所以打开时标题栏那片是空的（一直没人发现）。
        self.switch_page(self._start_page())

        # 系统切亮暗时，只有"跟随系统"这一档要跟着变
        try:
            from PySide6.QtGui import QGuiApplication
            QGuiApplication.styleHints().colorSchemeChanged.connect(
                self._on_system_scheme)
        except Exception:
            pass

        # 拦"点任务栏图标 / 系统菜单"那条最小化，改走我们自己的动画
        try:
            self._min_guard = _MinimizeGuard(self)
            inst = QApplication.instance()
            if inst is not None:
                inst.installNativeEventFilter(self._min_guard)
        except Exception:
            self._min_guard = None

        # 首页那几张卡（余额 / 天气 / 在放什么）要活着
        self._live = QTimer(self)
        self._live.setInterval(2000)
        self._live.timeout.connect(self._refresh_balance_card)
        self._live.start()

    # ---------------- 骨架 ----------------
    def _build_sidebar(self):
        side = QFrame()
        side.setObjectName("sidebar")
        self.sidebar = side
        side.setFixedWidth(210)
        box = QVBoxLayout(side)
        box.setContentsMargins(12, 16, 12, 14)
        box.setSpacing(4)

        brand = QHBoxLayout()
        brand.setContentsMargins(6, 0, 0, 10)
        brand.setSpacing(8)
        self.brand_logo = QLabel()
        self.brand_logo.setFixedSize(26, 26)
        brand.addWidget(self.brand_logo)
        self.brand_label = QLabel("")
        self.brand_label.setObjectName("brand")
        brand.addWidget(self.brand_label)
        brand.addStretch(1)
        box.addLayout(brand)
        # 名字和图标都能改成自己的（「控制台外观」那一页）
        self._apply_brand()

        # ---- 设置项搜索 ----
        # 敲字就把左边的分类换成"结果列表"，清空回分类；点一条就跳到那一页并闪一下那一行
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("searchBox")
        self.search_edit.setPlaceholderText("搜设置…")
        self.search_edit.setClearButtonEnabled(True)
        try:
            self.search_edit.addAction(
                icon("ui.search", tokens()["text_faint"], ICON_SM),
                QLineEdit.ActionPosition.LeadingPosition)
        except Exception:
            pass
        self.search_edit.textChanged.connect(self._on_search_text)
        box.addWidget(self.search_edit)

        # 分类那一块（搜索时整块藏起来）
        self.nav_box = QWidget()
        nav = QVBoxLayout(self.nav_box)
        nav.setContentsMargins(0, 2, 0, 0)
        nav.setSpacing(4)
        for key, title, _desc, icon_name, _builder in self.PAGES:
            item = NavItem(key, title, icon_name)
            item.clicked.connect(lambda _=False, k=key: self.switch_page(k))
            self._nav_items[key] = item
            nav.addWidget(item)
        nav.addStretch(1)
        box.addWidget(self.nav_box, 1)

        # 搜索结果那一块（平时藏着）
        self.search_box = QWidget()
        found = QVBoxLayout(self.search_box)
        found.setContentsMargins(0, 2, 0, 0)
        found.setSpacing(6)
        self.search_list = QListWidget()
        self.search_list.setObjectName("searchResults")
        self.search_list.itemClicked.connect(self._on_search_hit)
        self.search_list.itemActivated.connect(self._on_search_hit)
        found.addWidget(self.search_list, 1)
        self.search_empty = EmptyState("empty.search", "没找到相关的设置",
                                       "换个词试试，比如「气泡」「城市」「锁定」", size=34)
        self.search_empty.setVisible(False)
        found.addWidget(self.search_empty)
        self.search_box.setVisible(False)
        box.addWidget(self.search_box, 1)

        foot = QLabel(f"v{APP_VERSION}")
        foot.setObjectName("faint")
        foot.setContentsMargins(8, 0, 0, 0)
        box.addWidget(foot)
        return side

    # ---------------- 设置项搜索 ----------------
    def _on_search_text(self, text):
        """敲字：左边从"分类"换成"搜索结果"；清空就换回来。"""
        query = (text or "").strip()
        searching = bool(query)
        self.nav_box.setVisible(not searching)
        self.search_box.setVisible(searching)
        if not searching:
            self.search_list.clear()
            return
        terms = [t for t in query.lower().split() if t]
        hits = []
        for ent in self._search_index:
            blob = " ".join((ent["title"], ent["desc"], ent["page"])).lower()
            if all(t in blob for t in terms):
                hits.append(ent)
        self.search_list.clear()
        for ent in hits[:60]:
            item = QListWidgetItem(f"{ent['title']}　·　{ent['page']}")
            item.setData(Qt.ItemDataRole.UserRole, ent)
            self.search_list.addItem(item)
        self.search_list.setVisible(bool(hits))
        self.search_empty.setVisible(not hits)
        if not hits:
            self.search_empty.set_text(f"没找到「{query}」",
                                       "换个词试试，比如「气泡」「城市」「锁定」")

    def _on_search_hit(self, item):
        """点一条结果：切到那一页、滚到那一行、闪一下。"""
        ent = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not ent:
            return
        key = ent.get("key")
        if key and key != self._cur_page_key:
            self.switch_page(key)
        widget = ent.get("widget")
        page = self._pages.get(key)
        if widget is None or page is None:
            return
        try:
            page.ensureWidgetVisible(widget, 0, 40)
        except Exception:
            pass
        self._flash_widget(widget)

    def _stop_flash(self):
        timer = getattr(self, "_flash_timer", None)
        if timer is not None:
            timer.stop()
        box = getattr(self, "_flash", None)
        self._flash = None
        if box is not None:
            try:
                box.hide()
                box.deleteLater()
            except RuntimeError:
                pass

    def _flash_widget(self, widget):
        """在某个控件上闪一圈主色边框（跳转之后"就是这一条"）。"""
        parent = widget.parentWidget()
        if parent is None:
            return
        self._stop_flash()
        box = _FlashBox(parent)
        box.setGeometry(widget.geometry().adjusted(-5, -5, 5, 5))
        box.show()
        box.raise_()
        self._flash = box
        self._flash_t0 = time.perf_counter()
        if getattr(self, "_flash_timer", None) is None:
            self._flash_timer = QTimer(self)
            self._flash_timer.setInterval(ANIM_TICK_MS)
            self._flash_timer.timeout.connect(self._flash_tick)
        self._flash_timer.start()

    def _flash_tick(self):
        box = getattr(self, "_flash", None)
        if box is None:
            self._stop_flash()
            return
        t = (time.perf_counter() - self._flash_t0) / max(0.1, FLASH_MS / 1000.0)
        if t >= 1.0:
            self._stop_flash()
            return
        box.set_opacity(1.0 - t)

    def _build_main(self):
        main = QFrame()
        main.setObjectName("main")
        box = QVBoxLayout(main)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)

        header = DragBar()
        header.setObjectName("header")
        header.setFixedHeight(62)
        head = QHBoxLayout(header)
        head.setContentsMargins(22, 14, 14, 8)
        head.setSpacing(10)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(1)
        self.title_label = QLabel("")
        self.title_label.setObjectName("pageTitle")
        col.addWidget(self.title_label)
        self.desc_label = QLabel("")
        self.desc_label.setObjectName("pageDesc")
        col.addWidget(self.desc_label)
        head.addLayout(col)
        head.addStretch(1)
        for tip, icon_name in (("最小化", "ui.minimize"), ("关闭", "ui.close")):
            btn = QPushButton()
            btn.setObjectName("winBtn")
            btn.setFixedSize(30, 30)
            btn.setIconSize(QSize(ICON_SM, ICON_SM))
            btn.setIcon(icon(icon_name, tokens()["text_dim"], ICON_SM))
            btn.setToolTip(tip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            # 最小化 = 真最小化（任务栏图标还在，点一下能还原）；关闭 = 收起来
            if tip == "最小化":
                btn.clicked.connect(self.minimize_with_anim)
            else:
                btn.clicked.connect(self.hide)
            head.addWidget(btn)
        box.addWidget(header)

        self.stack = QStackedWidget()
        box.addWidget(self.stack, 1)
        for key, title, desc, _icon, builder in self.PAGES:
            page = Page(title, desc)
            self._pages[key] = page
            self.stack.addWidget(page)
            getattr(self, builder)(page)
            # 这一页上的分段控件：换主题时要连里面的小图标一起重画
            page._segments = page.findChildren(Segmented)
        # 设置项搜索的目录：每一页建完之后把它自己的条目收上来
        self._search_index = []
        for key, title, _desc, _icon, _builder in self.PAGES:
            for item_title, item_desc, widget in self._pages[key]._index:
                self._search_index.append({"key": key, "page": title,
                                           "title": item_title, "desc": item_desc,
                                           "widget": widget})
        return main

    def _logo_pixmap(self, size):
        """侧边栏那张小鲸鱼：直接用桌宠自己的图标，不另画一份。"""
        sprite_dir = self.ctx.get("SPRITE_DIR") or ""
        pix = QPixmap(os.path.join(sprite_dir, "icon.png"))
        if pix.isNull():
            return QPixmap(size, size)
        return pix.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)

    # ---------------- 控制台外观：背景 / 标题 / 图标 ----------------
    # 这一块只管"设置窗口自己长什么样"，跟桌宠本体一点关系都没有。
    # 设置存 config.json 里那几个 console_ 开头的键（BACKDROP_DEFAULTS）。
    def _bg(self, key):
        """取一个 console_ 设置：配置里没有（老 config.json）就用默认值。"""
        try:
            value = self.pet.cfg.get(key, BACKDROP_DEFAULTS[key])
        except Exception:
            value = BACKDROP_DEFAULTS.get(key)
        return BACKDROP_DEFAULTS.get(key) if value is None else value

    def _bg_int(self, key):
        try:
            return int(self._bg(key))
        except (TypeError, ValueError):
            return int(BACKDROP_DEFAULTS[key])

    def _bg_bool(self, key):
        value = self._bg(key)
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)

    def _bg_path(self):
        return str(self._bg("console_bg_path") or "").strip()

    def _glass_on(self):
        """现在该不该"透一层"。

        只看**有没有挑文件**（+ 文件还在不在），不看"这一帧有没有画面" ——
        视频第一帧要等解码，要是按"有画面"来算，那几百毫秒里样式表给的是实色底、
        又没人画底图，会闪一下。宁可先按平的底色画（看着就是原来的窗口），
        有帧了自然就上来了。
        """
        path = self._bg_path()
        return bool(path) and os.path.exists(path)

    def _set_bg(self, key, value):
        self.pet.cfg[key] = value
        try:
            self.pet.save_config()
        except Exception:
            pass

    # ---- 动效（切页淡入 / 减少动效）----
    def _reduce_motion(self):
        """「减少动效」开着吗：开着的话这个窗口一个字都不动。"""
        return self._bg_bool("console_reduce_motion")

    def _page_anim_on(self):
        """切页要不要淡入一下（「减少动效」开着时一律不播）。"""
        return self._bg_bool("console_page_anim") and not self._reduce_motion()

    def _set_motion(self, key, on):
        """改「页面切换动效 / 减少动效」：存下来，顺手把正跑着的那段动画收干净。"""
        self._set_bg(key, bool(on))
        if not self._page_anim_on():
            self._stop_page_fade()

    def _stop_page_fade(self):
        """把手里那段切页淡出收干净：停拍子、把那张截图撤掉。"""
        timer = getattr(self, "_page_fade_timer", None)
        if timer is not None:
            timer.stop()
        fade = getattr(self, "_page_fade", None)
        self._page_fade = None
        if fade is not None:
            try:
                fade.hide()
                fade.deleteLater()
            except RuntimeError:
                pass

    def _start_page_fade(self):
        """切页前先把"这一屏"拍下来，切完之后把它淡掉 —— 新页面就浮出来了。

        拍的是整个壳（含侧边栏和底图），所以淡出的时候只有内容区在变，
        侧边栏看着一动不动。截图一定要在 `setCurrentWidget` **之前**拍。
        """
        if not self._page_anim_on() or not self.isVisible():
            self._stop_page_fade()
            return
        # 先把上一次那张撤掉：不然这次会把"半透明的旧图"一起拍进新图里
        self._stop_page_fade()
        pm = None
        try:
            pm = self._shell_shot()
        except Exception as exc:
            print("切页截图失败:", exc)
        if pm is None or pm.isNull():
            return
        fade = _PageFade(self.shell)
        fade.setGeometry(self.shell.rect())
        fade.set_pixmap(pm)
        fade.set_opacity(1.0)
        fade.show()
        fade.raise_()
        self._page_fade = fade
        self._page_fade_t0 = time.perf_counter()
        if getattr(self, "_page_fade_timer", None) is None:
            self._page_fade_timer = QTimer(self)
            self._page_fade_timer.setInterval(ANIM_TICK_MS)
            self._page_fade_timer.timeout.connect(self._page_fade_tick)
        self._page_fade_timer.start()

    def _page_fade_tick(self):
        fade = getattr(self, "_page_fade", None)
        if fade is None:
            self._stop_page_fade()
            return
        dur = max(0.05, PAGE_ANIM_MS / 1000.0)
        t = (time.perf_counter() - self._page_fade_t0) / dur
        if t >= 1.0:
            self._stop_page_fade()
            return
        fade.set_opacity((1.0 - t) ** 3)      # 前快后慢，最后收得很轻

    def _shell_shot(self):
        """给切页淡出拍一张"壳"的截图。

        **别用 `self.shell.grab()`**：它是按"窗口背景"画的 —— 会把壳整个矩形
        填一遍，壳四角（屏幕上本该是透的，圆角就靠那儿露出来）就被填成主题底色，
        于是淡出动画的第一帧看着是**四个直角**（主人 2026-09-14 报的那一下，
        真机实测：切页后 47ms 时四个角 16 个采样点全被盖住）。

        自己开一张透明底图、只画控件自己（含壳的 `paintEvent`）和子树，
        圆角该透的地方就还是透的 —— 跟屏幕上看到的一模一样。
        """
        shell = self.shell
        dpr = shell.devicePixelRatioF() or 1.0
        pm = QPixmap(int(round(shell.width() * dpr)),
                     int(round(shell.height() * dpr)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        shell.render(pm, QPoint(0, 0), QRegion(),
                     QWidget.RenderFlag.DrawChildren)
        return pm

    def _ask_file(self, title, filt, current=""):
        """挑文件。期间让桌宠站住不动（跟别的对话框一个规矩）。"""
        guard = getattr(self.pet, "_ui_guard", None)
        ctx = guard() if callable(guard) else contextlib.nullcontext()
        try:
            with ctx:
                path, _ok = QFileDialog.getOpenFileName(
                    self, title, current or "", filt)
        except Exception:
            return ""
        return path or ""

    # ---- 底图 ----
    def _image_source(self, path):
        """原图。按路径 + 修改时间缓存：换了图、或者把同一张图改了，都会重读。"""
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            stamp = 0
        key = (path, stamp)
        if key != self._bg_src_key:
            self._bg_src = load_image(path)
            self._bg_src_key = key
            self._bg_out_key = None
        return self._bg_src

    def _apply_backdrop(self, force=False):
        """把这一帧的底图贴到窗口壳上。

        图片那边做了两级缓存（原图一份、处理完一份），拖滑块时只重算"处理"这一步；
        视频每来一帧当新图处理，所以那边一直是 force。
        """
        glass = self._glass_on()
        if glass != self._glass_state:
            # 样式表得跟着"变透 / 变实"。用户把背景文件删了 / 挪走了就是这条：
            # 底图没了、样式表还是透明的那套，窗口会变成一片空白。
            self.apply_theme()
            return
        path = self._bg_path()
        exists = bool(path) and os.path.exists(path)
        live = exists and bg_kind_of(path) == "video"
        if live:
            self._video_ensure(path)
        else:
            self._video_stop()

        src = None
        if exists and not live:
            src = self._image_source(path)
        elif live:
            src = self._video_pm

        shell = self.shell
        if (src is None or src.isNull()) and not glass:
            shell.backdrop = None
            self._bg_out = None
            self._bg_out_key = None
            shell.update()
            return

        dpr = self.devicePixelRatioF() or 1.0
        width = max(1, int(round(shell.width() * dpr)))
        height = max(1, int(round(shell.height() * dpr)))
        bright = self._bg_int("console_bg_bright")
        blur = self._bg_int("console_bg_blur")
        scrim = max(0, min(100, self._bg_int("console_bg_scrim")))
        # 自动适配窗口 = 铺满（多出来的裁掉，可以挑留哪一块）；
        # 关掉 = 完整显示（不裁图 / 不裁视频，空的地方露主题底色）。
        fit = "cover" if self._bg_bool("console_bg_fit_window") else "contain"
        focus = str(self._bg("console_bg_focus") or "cc")

        params = (bright, blur, fit, focus)
        key = (width, height, dpr, params,
               "video" if live else self._bg_src_key)
        if not force and self._bg_out is not None and key == self._bg_out_key:
            out = self._bg_out
        else:
            base = QImage(width, height,
                          QImage.Format.Format_ARGB32_Premultiplied)
            # 先铺一层主题底色：用户的图带透明时露出来的是它，不是花屏
            base.fill(QColor(tokens()["bg"]))
            if src is not None and not src.isNull():
                painter = QPainter(base)
                self._paint_backdrop(painter, src, width, height, fit, focus)
                painter.end()
            out = brighten_image(base, bright)
            out = blur_image(out, blur)
            self._bg_out = out
            self._bg_out_key = key
            self._bg_out_params = params

        pm = QPixmap.fromImage(out)
        pm.setDevicePixelRatio(dpr)
        shell.backdrop = pm
        shell.backdrop_rgb = tokens()["bg"]          # 遮罩用当前主题的底色
        shell.backdrop_scrim = scrim * 255 // 100
        shell.update()

    @staticmethod
    def _paint_backdrop(painter, src, width, height, fit, focus="cc"):
        """底图怎么放：铺满（按 focus 裁）或完整显示（留边）。"""
        if fit == "contain":
            fitted = src.scaled(width, height,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
            painter.drawImage((width - fitted.width()) // 2,
                              (height - fitted.height()) // 2, fitted)
            return
        painter.drawImage(0, 0, scale_cover(src, width, height, focus))

    # ---- 视频背景 ----
    def _video_ensure(self, path):
        """需要就换片、需要就播。这台机器上 QtMultimedia 缺失时这一档直接不生效。"""
        if not MEDIA_OK:
            return
        if self._video_player is None:
            self._video_player = QMediaPlayer(self)
            self._video_sink = QVideoSink(self)
            self._video_player.setVideoSink(self._video_sink)
            self._video_sink.videoFrameChanged.connect(self._on_video_frame)
            try:
                self._video_player.setLoops(QMediaPlayer.Loops.Infinite)
            except Exception:
                pass
        if self._video_path != path:
            self._video_path = path
            self._video_pm = None
            self._bg_out_key = None
            self._video_ts = 0.0
            self._video_player.setSource(QUrl.fromLocalFile(path))
        if self._video_wanted:
            if (self._video_player.playbackState()
                    != QMediaPlayer.PlaybackState.PlayingState):
                self._video_player.play()
        else:
            self._video_player.pause()

    def _video_stop(self):
        self._video_pm = None
        if self._video_player is not None:
            self._video_player.stop()

    def _video_follow_visibility(self):
        """窗口收起来 / 最小化时别再解码了 —— 视频背景最费的就是这一段。"""
        want = bool(self.isVisible() and not self.isMinimized())
        self._video_wanted = want
        player = self._video_player
        if player is None:
            return
        try:
            if want:
                player.play()
            else:
                player.pause()
        except Exception:
            pass

    def _on_video_frame(self, frame):
        if not self._video_wanted or frame is None:
            return
        now = time.monotonic()
        if now - self._video_ts < VIDEO_FRAME_S:
            return                     # 15 帧够了，剩下的别浪费在解码 + 模糊上
        self._video_ts = now
        try:
            img = frame.toImage()
        except Exception:
            return
        if img.isNull():
            return
        self._video_pm = img
        self._apply_backdrop(force=True)

    # ---- 标题和图标 ----
    def _brand_image(self, path):
        """图标文件。按路径 + 修改时间缓存 —— 打字改标题时每个字都会走到这儿。"""
        if not path:
            return None
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            return None
        key = (path, stamp)
        if key != self._brand_key:
            self._brand_key = key
            self._brand_img = load_image(path)
        return self._brand_img

    def _apply_brand(self):
        """左上角那个名字和图标：用户改过就用用户的，没改就是默认。"""
        title = str(self._bg("console_brand_title") or "").strip() or "大肥鱼桌宠"
        self.brand_label.setText(title)
        self.brand_label.setToolTip(title)
        pm = None
        img = self._brand_image(str(self._bg("console_logo_path") or "").strip())
        if img is not None and not img.isNull():
            pm = QPixmap.fromImage(img).scaled(
                26, 26, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
        if pm is None or pm.isNull():
            pm = self._logo_pixmap(26)
        self.brand_logo.setPixmap(pm)

    def _logo_text(self):
        path = str(self._bg("console_logo_path") or "").strip()
        if path and os.path.exists(path):
            return f"当前：{os.path.basename(path)}"
        return "当前：默认的小鲸鱼"

    def _bg_path_text(self):
        path = self._bg_path()
        if path and os.path.exists(path):
            kind = "视频" if bg_kind_of(path) == "video" else "图片"
            return f"{kind}：{os.path.basename(path)}"
        if path:
            return f"文件不在了：{path}"
        return "还没导入"

    def _bg_pick_text(self):
        return "换个文件…" if self._bg_path() else "导入文件…"

    # ---- 强调色 / 卡片 / 侧边栏 ----
    def _sync_accent_row(self):
        """把色卡摆成配置里的样子（自己挑的颜色会点亮「自定义…」那颗）。"""
        row = getattr(self, "accent_row", None)
        if row is not None:
            row.set_value(str(self._bg("console_accent") or ""))

    def _apply_accent(self, value, save=True):
        """换强调色：调色板 → 样式表 → 整个界面（连老对话框一起）。"""
        if save:
            self._set_bg("console_accent", value)
        set_accent(value)
        self.apply_theme()
        self._hint_accent("点一下就是它")

    def _pick_accent(self):
        """自己挑一个颜色。

        用 Qt 那套**非原生**取色盘：自带一颗吸管，能直接吸屏幕上任意一点
        （Windows 原生那个只有 RGB/HSV，吸不了屏）。操作也简单：
        色卡上点「自定义…」，想吸哪儿就点吸管再点屏幕上那一点。
        """
        start = QColor(str(self._bg("console_accent") or "") or tokens()["accent"])
        guard = getattr(self.pet, "_ui_guard", None)
        ctx = guard() if callable(guard) else contextlib.nullcontext()
        try:
            with ctx:
                picked = QColorDialog.getColor(
                    start, self, "挑一个强调色",
                    QColorDialog.ColorDialogOption.DontUseNativeDialog)
        except Exception:
            return
        if picked is None or not picked.isValid():
            return
        self._apply_accent(picked.name())

    def _accent_from_bg(self):
        """从背景图里取一个颜色当强调色。"""
        img = None
        if self._bg_path() and bg_kind_of(self._bg_path()) == "image":
            img = self._image_source(self._bg_path())
        if img is None:
            img = self._video_pm
        color = pick_accent(img)
        if not color:
            self._hint_accent("这张图挑不出颜色，换张鲜艳点的")
            return
        self._apply_accent(color)
        self._hint_accent(f"取自背景图：{color}")

    def _hint_accent(self, text):
        """拿「强调色」那行的说明文字当回执（不额外占一行）。"""
        row = getattr(self, "accent_row_wrap", None)
        label = getattr(row, "desc_label", None) if row is not None else None
        if label is not None:
            label.setText(text)

    def _on_card_style(self, key, value):
        """卡片不透明度 / 圆角：改的是样式表里的格子，攒一下再重下。"""
        self._set_bg(key, int(value))
        set_card_style(self._bg_int("console_card_alpha"),
                       self._bg_int("console_card_radius"))
        self._style_later()

    def _style_later(self):
        """连着拖的滑块：攒一下再重下样式表，别每一格都让 Qt 重新解析一遍。"""
        self._style_timer.start()

    def _start_page(self):
        key = str(self._bg("console_start_page") or "")
        return key if key in self._pages else "balance"

    # ---- 窗口大小 / 位置 ----
    def _on_remember_geo(self, on):
        self._set_bg("console_remember_geo", bool(on))
        if on:
            self._geo_save()          # 立刻记一次，别等用户拖窗口

    def _geo_save(self):
        if not self._bg("console_remember_geo"):
            return
        # 最小化动画期间窗口会被改成"往任务栏收"的那个尺寸（1 像素那么大），
        # 那会儿要是记下来，下次打开窗口就是一粒芝麻 —— 放过这几种时刻。
        if (not self.isVisible() or self.isMinimized()
                or getattr(self, "_min_anim", None) is not None
                or getattr(self, "_restoring", False)
                or getattr(self, "_min_pm", None) is not None):
            return
        try:
            blob = bytes(self.saveGeometry().toBase64()).decode("ascii")
        except Exception:
            return
        if self.pet.cfg.get("console_geo") == blob:
            return
        self._set_bg("console_geo", blob)

    def _geo_restore(self):
        if not self._bg("console_remember_geo"):
            return
        blob = str(self.pet.cfg.get("console_geo") or "")
        if not blob:
            return
        try:
            self.restoreGeometry(QByteArray.fromBase64(blob.encode("ascii")))
        except Exception:
            return
        self._geo_clamp()

    def _geo_clamp(self):
        """存下来的位置要是落在已经拔掉的显示器上，拉回看得见的地方。"""
        try:
            screen = QApplication.screenAt(self.frameGeometry().center())
            if screen is None:
                best, best_area = None, 0
                frame = self.frameGeometry()
                for one in QApplication.screens():
                    inter = one.availableGeometry().intersected(frame)
                    area = inter.width() * inter.height()
                    if area > best_area:
                        best, best_area = one, area
                screen = best or QApplication.primaryScreen()
            if screen is None:
                return
            avail = screen.availableGeometry()
            width = max(self.minimumWidth(), min(self.width(), avail.width()))
            height = max(self.minimumHeight(), min(self.height(), avail.height()))
            self.resize(width, height)
            x = max(avail.left(), min(self.x(), avail.right() - width + 1))
            y = max(avail.top(), min(self.y(), avail.bottom() - height + 1))
            self.move(x, y)
        except Exception:
            pass

    # ---------------- 主题 ----------------
    def apply_theme(self):
        glass = self._glass_on()
        self._glass_state = glass
        effective = refresh_tokens()
        clear_icon_cache()
        self.setStyleSheet(build_qss(glass))
        # 页面那块一律"透"：底色（或背景图）都是壳画的，视口标成不透明就会盖住它，
        # 右下角的圆角也会被填成直角（详见 Page.__init__ 里那段说明）。
        for page in self._pages.values():
            page.viewport().setAttribute(
                Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self._repaint_icons()
        for page in self._pages.values():
            page.repaint_cards()
        for btn, name, style in self._btn_icons:      # 窗口自己建的那些按钮
            try:
                btn.setIcon(icon(name, button_icon_color(style), ICON_SM))
            except RuntimeError:
                pass
        for item in self._nav_items.values():
            item.update()
        self._apply_backdrop(force=True)
        self._sync_accent_row()     # 「默认」那颗色卡跟着亮/暗主题换
        self.update()
        return effective

    def _repaint_icons(self):
        """窗口按钮这些带 QIcon 的，换主题后要重画一份。"""
        for btn in self.findChildren(QPushButton):
            if btn.objectName() != "winBtn":
                continue
            name = "ui.close" if btn.toolTip() == "关闭" else "ui.minimize"
            btn.setIcon(icon(name, tokens()["text_dim"], ICON_SM))

    def _on_system_scheme(self, _scheme=None):
        if self._mode == "system":
            self.apply_theme()

    def set_theme(self, mode):
        self._mode = mode
        # 关键：全局调色板也要跟着切 —— Switch / NavItem 这些是在 paintEvent 里
        # 现取颜色的，只改样式表它们还按旧色画。
        set_mode(mode)
        self.pet.cfg["ui_theme"] = mode
        try:
            self.pet.save_config()
        except Exception:
            pass
        self.apply_theme()
        self.pet.update()

    # ---------------- 切页 ----------------
    def _hook_page(self, key, fn):
        """给某一页挂一个"现读一遍数据"的回调（切页 / 窗口重新露出来时都会跑）。"""
        self._page_hooks.setdefault(key, []).append(fn)

    def _refresh_page(self, key):
        """把某一页上"会变的东西"按现在的实际状态重摆一遍。"""
        for fn in self._page_hooks.get(key) or ():
            try:
                fn()
            except Exception as exc:
                print(f"刷新「{key}」页失败:", exc)

    def _refresh_current_page(self):
        if self._cur_page_key:
            self._refresh_page(self._cur_page_key)

    def refresh_pages(self):
        """外面（桌宠）改了配置之后叫一声：把当前这一页"会变的"重读一遍。

        城市是**后台联网**加进来的 —— 加完那一刻窗口还开着，靠这个立刻反映
        （见 桌宠.py 的 `_notify_console`）。
        """
        self._refresh_current_page()

    def switch_page(self, key):
        page = self._pages.get(key)
        if page is None:
            return
        self._cur_page_key = key
        # 先拍下"切之前"这一屏，切完把它淡掉（关掉动效时这一步什么都不做）
        self._start_page_fade()
        self.stack.setCurrentWidget(page)
        self.title_label.setText(page.title)
        self.desc_label.setText(page.desc)
        for name, item in self._nav_items.items():
            item.setChecked(name == key)
        if key == "balance":
            self._refresh_balance_card()
        elif key == "appearance":
            self._sync_size_controls()
        elif key == "console":
            self._sync_console_controls()
        # 页面是建一次留着的，这里补一遍"现读一遍数据"的（形象库条目数这类）
        self._refresh_page(key)

    # ---------------- 余额那张卡（开着窗口就自己刷）----------------
    def _refresh_balance_card(self):
        if (not self.isVisible()
                or self.stack.currentWidget() is not self._pages["balance"]):
            return
        pet = self.pet
        balance = getattr(pet, "balance", None)
        symbol = self.ctx.get("currency_symbol", lambda _c: "¥")
        if not balance:
            self.bal_amount.setText("—")
            self.bal_amount.setStyleSheet(f"color:{tokens()['text_faint']};")
            self.bal_note.setText("还没取到，点右边「刷新」看一眼")
        elif balance.get("no_api"):
            self.bal_amount.setText("—")
            self.bal_amount.setStyleSheet(f"color:{tokens()['text_faint']};")
            self.bal_note.setText(f"{balance.get('name', '?')} 没有余额接口")
        else:
            sign = symbol(balance.get("currency", ""))
            self.bal_amount.setText(f"{sign}{pet._display_amount():.2f}")
            self.bal_amount.setStyleSheet("")
            self.bal_note.setText(
                f"来源：{balance.get('name', '?')}，今日已用 "
                f"{sign}{(balance.get('today') or 0.0):.2f}")

    # ---------------- 余额和用量 ----------------
    def _page_balance(self, page):
        pet = self.pet
        has_key = self._has_key()
        card = page.card("现在的余额", "配好 Key 才会出来数", "nav.balance")
        self.bal_amount = QLabel("—")
        self.bal_amount.setObjectName("big")
        self.bal_amount.setStyleSheet(f"color:{tokens()['text_faint']};")
        card.addWidget(self.bal_amount)
        self.bal_note = QLabel("")
        self.bal_note.setObjectName("muted")
        card.addWidget(self.bal_note)
        page.row(card, "余额常显", "余额气泡常驻显示",
                 Switch(pet.balance_always, pet.set_balance_always))
        page.buttons(card, [
            ("刷新", lambda: pet.refresh_balance(silent=False), "primary", "ui.refresh"),
        ])

        card = page.card("余额来源", "换来源会重新取一次数", "nav.balance")
        # 来源名单和"Key 配没配"都会变（自己加 / 删服务、换 Key），都靠 _sync_source_controls 现读
        self.source_combo = page.combo(
            card, "看谁的余额", "DeepSeek，或你自己加的服务",
            [(name, name) for name in self._source_names()],
            pet.cfg.get("balance_source") or "DeepSeek",
            lambda name: self._run(pet.set_balance_source, name))
        self.key_btn = self._text_button("换一个…" if has_key else "现在配…",
                                        self._set_key, "primary")
        self.key_row = page.row(
            card, "API Key",
            "当前：已配置" if has_key else "当前：还没配，配了才看得到余额",
            self.key_btn)
        page.buttons(card, [
            ("添加其他 API Key…", self._add_other_key, None, "ui.add"),
            ("删除其他 API Key…", self._remove_other_key, "danger", "ui.delete"),
        ])
        self._hook_page("balance", self._sync_source_controls)

        card = page.card("今日已用怎么算", "按余额差值算，可能和平台对不上",
                         "page.calibrate")
        page.row(card, f"每轮对话后显示消耗（当前：{pet.agent_name}）",
                 f"读 {pet.agent_name} 的会话日志，算这一轮用掉多少",
                 Switch(pet.turn_cost_on, pet.set_turn_cost))
        page.row(card, "去哪个文件夹读对话记录", str(pet.agent_dir),
                 self._pair_buttons(
                     ("名称…", lambda: self._run(pet.set_agent_name_dialog)),
                     ("日志目录…", lambda: self._run(pet.set_agent_dir_dialog))))
        page.divider(card)
        page.row(card, "校准今日已用", "按平台用量页对一次数",
                 self._text_button("校准…",
                                   lambda: self._run(pet.calibrate_usage_dialog),
                                   "primary", "page.calibrate"))

    def _sync_source_controls(self):
        """余额来源那一栏现读：自己加 / 删过服务、换过 Key 之后要说得出现在是啥。"""
        pet = self.pet
        box = getattr(self, "source_combo", None)
        if box is not None:
            names = self._source_names()
            shown = [box.itemText(i) for i in range(box.count())]
            if shown != names:
                box.blockSignals(True)
                box.clear()
                for name in names:              # 值就是名字，跟 page.combo 建的时候一样
                    box.addItem(name, name)
                box.blockSignals(False)
            want = pet.cfg.get("balance_source") or "DeepSeek"
            for i in range(box.count()):
                if box.itemData(i) == want:
                    if box.currentIndex() != i:
                        box.blockSignals(True)
                        box.setCurrentIndex(i)
                        box.blockSignals(False)
                    break
        has_key = self._has_key()
        row = getattr(self, "key_row", None)
        if row is not None and row.desc_label is not None:
            row.desc_label.setText(
                "当前：已配置" if has_key else "当前：还没配，配了才看得到余额")
        btn = getattr(self, "key_btn", None)
        if btn is not None:
            btn.setText("换一个…" if has_key else "现在配…")

    def _add_other_key(self):
        self._run(self.pet.add_other_key_dialog)
        self._sync_source_controls()

    def _remove_other_key(self):
        self._run(self.pet.remove_other_key_dialog)
        self._sync_source_controls()

    def _set_key(self):
        self._run(self.pet._set_key_dialog)
        self._sync_source_controls()

    # ---------------- 天气与城市 ----------------
    def _page_weather(self, page):
        pet = self.pet
        card = page.card("城市", "点一下切过去", "page.location")
        # 城市列表是"条目本身会变"的那类（联网加、删掉都算），所以建的时候先空着，
        # 交给 _sync_weather_controls 按现在的配置摆 —— 加完 / 删完立刻就反映
        self.city_seg = Segmented([], None,
                                  lambda name: self._run(pet._apply_city, name))
        card.addWidget(self.city_seg)
        page.buttons(card, [
            ("手动输入…", self._set_city_manual, "primary", "ui.edit"),
            ("自动定位（按 IP）", lambda: self._run(pet.auto_locate_city), None, "page.location"),
            ("添加城市（联网搜索）",
             self._add_city_search, None, "ui.add"),
        ])
        # 这一行只有"列表里不止一个城市"时才露出来 —— 建的时候先放着，靠 sync 显隐
        self.city_del_row = page.buttons(card, [
            ("从列表里删掉城市…", self._remove_city, "danger", "ui.delete")])
        page.hint(card, "挂梯子时 IP 定位不准，建议手动填。"
                        "想看一眼天气：右键 →「查看天气」。")
        self._hook_page("weather", self._sync_weather_controls)
        self._sync_weather_controls()

    def _city_list(self):
        """现在该显示哪些城市：**当前城市排最前面**，其余按原顺序（on 是当前那个）。"""
        pet = self.pet
        current = pet.cfg.get("city", "汕头")
        cities = pet.cities_ordered()
        if current and current not in cities:
            cities.insert(0, current)
        return cities, current

    def _sync_weather_controls(self):
        """城市那一排现读一遍：加城市 / 删城市 / 联网定位回来都要立刻反映。"""
        cities, current = self._city_list()
        seg = getattr(self, "city_seg", None)
        if seg is not None:
            if list(seg._buttons) != cities:      # 条目变了才整排重建（顺序也算）
                seg.set_options([(c, c) for c in cities], current)
            else:
                seg.set_value(current)
        row = getattr(self, "city_del_row", None)
        if row is not None:
            row.setVisible(len(cities) > 1)

    def _set_city_manual(self):
        self._run(self.pet.set_city_dialog)
        self._sync_weather_controls()

    def _add_city_search(self):
        """联网搜出来的城市是**后台**加进来的，加完那一刻桌宠会叫一声（refresh_pages）。"""
        self._run(self.pet.search_city_dialog)
        self._sync_weather_controls()

    def _remove_city(self):
        self._run(self.pet.remove_city_dialog)
        self._sync_weather_controls()

    # ---------------- 音乐与歌词 ----------------
    def _page_music(self, page):
        pet = self.pet
        card = page.card("联动", "播放音乐时的联动", "nav.music")
        page.row(card, "放歌时看着", "QQ音乐 / 网易云 播放时联动",
                 Switch(pet.music_on, pet.set_music_link))
        page.row(card, "显示歌词内容", "关掉只报歌名",
                 Switch(pet.music_lyrics, pet.set_music_lyrics))
        # 网易云那个播放器拿不到歌词（只有歌名），别让人一直等歌词
        page.hint(card, "网易云不报播放进度，所以只能显示歌名。")
        page.hint(card, "想看一眼在放什么：右键 →「看一眼在放什么」。")

        card = page.card("歌词对不上？", "跟播放器显示的时间对齐最准", "page.clock")
        page.combo(card, "歌词比音乐早还是晚", "不同步时先选择一档",
                   [(off, label) for label, off
                    in (self.ctx.get("LYRIC_OFFSET_LEVELS") or [])],
                   pet.lyric_offset,
                   lambda off: self._run(pet.set_lyric_offset, off))
        page.buttons(card, [
            ("往前赶 0.5 秒", lambda: pet.nudge_lyric(0.5), None),
            ("往后压 0.5 秒", lambda: pet.nudge_lyric(-0.5), None),
            ("按播放器时间对齐…",
             lambda: self._run(pet.align_lyric_dialog), "primary", "page.clock"),
            ("清零", lambda: pet.nudge_lyric(0.0, True), None),
        ])

        # 合体新增：放歌时换成自己的唱歌立绘
        card = page.card("唱歌时的姿势", "放歌时换成你画的立绘", "nav.appearance")
        page.row(card, "放歌时换姿势", "关掉就一直用默认三视图",
                 Switch(pet.sing_on, pet.set_sing_on))
        n = len((((getattr(pet, "dsh_acts", None) or {}).get("sing")) or {}))
        page.hint(card, (f"已加载唱歌立绘：{n} 帧。" if n else
                         "还没画唱歌立绘（放了也不生效）。把图丢进 "
                         "dafeiyu-shiyanchang\\源图\\ 再跑 make_frames.py。"))
        page.hint(card, "唱歌时只轻轻摇晃、不蹦不跳；DSH 反应演完会自动接回唱歌姿势。")

    # ---------------- DSH 联动 ----------------
    def _page_dsh(self, page):
        pet = self.pet

        card = page.card("跟着 DSH 干活做反应",
                         "读本地会话日志，实时换立绘 + 冒台词", "ui.eye")
        page.row(card, "启用 DSH 联动", "关掉就完全不读会话日志",
                 Switch(pet.dsh_on, pet.set_dsh_on))
        page.hint(card, "读的是 ~\\.dsh\\sessions 下的会话日志，纯本地只读、不外传。")
        page.hint(card, "免打扰期间不触发；右键菜单里也能开关。")

        card = page.card("排查", "联动没反应时，打开日志看它读到了什么", "ui.help")
        page.row(card, "记调试日志", "写到程序目录下的 dsh-debug.log",
                 Switch(bool(pet.cfg.get("dsh_debug", False)), pet.set_dsh_debug))

        # 动作一览：画了图的会换成对应立绘，没画的自动回三视图兜底
        card = page.card("动作一览", "现在每个动作有没有自己的立绘", "nav.appearance")
        acts = getattr(pet, "dsh_acts", None) or {}
        zoom = self.ctx.get("DSH_ACT_ZOOM") or {}
        for key, info in (self.ctx.get("DSH_ACT_INFO") or {}).items():
            name, when = info if isinstance(info, (tuple, list)) else (info, "")
            n = len(acts.get(key) or {})
            if n:
                state = f"{n} 帧"
                if zoom.get(key):
                    state += f" · 放大 {zoom[key]:.2f}×"
            else:
                state = "用三视图兜底"
            mark = QLabel(state)
            mark.setObjectName("rowDesc")
            page.row(card, f"{name}　{key}", when, mark)
        page.hint(card, "加图：立绘丢进 dafeiyu-shiyanchang\\源图\\，跑 make_frames.py，"
                        "再重启桌宠。详见同目录的「说明.md」。")

    # ---------------- 形象与外观 ----------------
    def _page_appearance(self, page):
        pet = self.pet
        skin_pet = self.ctx.get("SKIN_PET", "大肥鱼")
        skin_widget = self.ctx.get("SKIN_WIDGET", "小鲸鱼挂件")
        card = page.card("形象", "换形象、上传自己的图", "nav.appearance")
        # 「现在是谁」和"形象库有几个"都是会变的：建的时候摆一次，
        # 之后每次切到这一页（或把窗口重新露出来）都按实际状态重摆（见 _sync_skin_controls）
        self.skin_seg = Segmented([(skin_pet, self._skin_option_text("pet", skin_pet, "（三视图）")),
                                   (skin_widget, self._skin_option_text("widget", skin_widget, "（单张）"))],
                                  pet.skin, lambda name: self._run(pet.set_skin, name))
        page.row(card, "现在是谁", "", self.skin_seg)
        row = page.buttons(card, [
            (self._skin_lib_text(),
             self._open_skin_library, "primary", "nav.appearance"),
            ("全部恢复默认形象", self._reset_all_skin, "danger", "ui.reset"),
        ])
        btns = getattr(row, "buttons", [])
        self.skin_lib_btn = btns[0] if btns else None
        self._hook_page("appearance", self._sync_skin_controls)

        card = page.card("大小", "脚底和中心不动，原地缩放", "page.resize")
        levels = list((self.ctx.get("SIZE_LEVELS") or {}).items())
        self.size_levels = levels
        current_level = None
        for _label, mult in levels:
            if abs(getattr(pet, "cur_h", 0) - 340 * mult) < 2:
                current_level = mult
        # 档位和滑块是同一个大小：点档位 → 滑块跳过去；拖滑块停在哪一档 → 那一档点亮
        self.size_seg = Segmented([(mult, label) for label, mult in levels],
                                  current_level, self._on_size_level)
        page.row(card, "档位", "五档预设，选择后滑块同步",
                 self.size_seg)
        lo = self._size_pct(self.ctx.get("SIZE_MIN", 0.30))
        hi = self._size_pct(self.ctx.get("SIZE_MAX", 1.20))
        now = self._size_pct(pet.cfg.get("size", 0.72))
        self.size_slider = page.slider(
            card, "精确调节", f"{lo}% ~ {hi}%，跟上面的档位是同一个大小",
            lo, hi, min(max(now, lo), hi), "%", self._on_size_percent)

        card = page.card("外观", "", "page.opacity")
        page.slider(card, "透明度", "过低会难以看清", 20, 100,
                    int(pet.opacity * 100), "%",
                    lambda v: self._run(pet.set_opacity, v / 100.0))
        # 气泡（语录 / 余额 / 歌词）用哪套配色：默认跟着上面那套界面主题的亮暗走，
        # 也能自己定死浅色 / 深色（深色底上原来的白气泡太刺眼）
        self.bubble_seg = Segmented(
            list(self.ctx.get("BUBBLE_STYLES") or [("auto", "跟随界面")]),
            getattr(pet, "bubble_style", "auto"),
            lambda name: self._run(pet.set_bubble_style, name))
        page.row(card, "气泡风格", "语录、余额、歌词三种气泡一起换",
                 self.bubble_seg)
        page.row(card, "窗口层级", "相对其他窗口的层级", self._layer_combo())
        page.row(card, "拖拽吸附四边", "拖到屏幕边缘时自动吸附",
                 Switch(pet.snap_on, pet.set_snap))
        page.row(card, "左吸附时翻面", "吸附左侧时朝向屏幕内侧",
                 Switch(pet.flip_on_left, pet.set_flip_on_left))

    def _skin_lib_text(self):
        """「我的形象库…」按钮上的字：条目数**现读**，不存下来。"""
        pet = self.pet
        try:
            n_pet = len(pet.skin_library("pet"))
            n_widget = len(pet.skin_library("widget"))
        except Exception:
            return "我的形象库…"
        return f"我的形象库…（三维 {n_pet} · 挂件 {n_widget}）"

    def _skin_name(self, kind, builtin):
        """这一本现在用着谁：用着库里的自定义形象就是它的名字，否则是自带的那个。"""
        try:
            ref = self.pet._current_skin_ref(kind)
            ent = self.pet.skin_entry(kind, ref) if ref else None
            if ent and ent.get("name"):
                return str(ent["name"])
        except Exception:
            pass
        return builtin

    def _skin_option_text(self, kind, builtin, suffix):
        """「现在是谁」那一档的文字：名字 + 按本的说法。

        「（三视图）」「（单张）」是**按本**来的、永远跟着这一档走，截断也只会截名字 ——
        用着库里的自定义形象就把前面的名字换成它的。
        """
        return f"{self._shorten(self._skin_name(kind, builtin), 12)}{suffix}"

    @staticmethod
    def _shorten(text, limit=16):
        """太长就截断（档位那一排很窄，左边那行说明别被挤没了）。全名挂 tooltip。"""
        return text if len(text) <= limit else text[:limit - 1] + "…"

    def _sync_skin_controls(self):
        """形象库条目数 + "现在是谁"，都按现在的实际状态重摆一遍。

        上传 / 换图 / 删条目 / 恢复默认形象都会改这两个数 —— 以前只在建页面时读一次，
        所以非得重启桌宠才更新；现在改成切回这一页、以及关掉形象库窗口之后就重读。
        """
        btn = getattr(self, "skin_lib_btn", None)
        if btn is not None:
            btn.setText(self._skin_lib_text())
        seg = getattr(self, "skin_seg", None)
        if seg is not None:
            # 名字跟着库里的形象走（用着自定义的就把档位文字换成它的名字）
            # 注意：这一排的"值"就是两套自带的形象名（SKIN_PET / SKIN_WIDGET），
            # 档位文字才是会变的那部分
            skin_pet = self.ctx.get("SKIN_PET", "大肥鱼")
            skin_widget = self.ctx.get("SKIN_WIDGET", "小鲸鱼挂件")
            # 悬停给全名（档位上那个是截过的）
            seg.set_label(skin_pet, self._skin_option_text("pet", skin_pet, "（三视图）"),
                          f"{self._skin_name('pet', skin_pet)}（三视图）")
            seg.set_label(skin_widget, self._skin_option_text("widget", skin_widget, "（单张）"),
                          f"{self._skin_name('widget', skin_widget)}（单张）")
            # clear_custom_skin 可能把挂件退回"大肥鱼"，这里跟着对上
            seg.set_value(getattr(self.pet, "skin", None))
        bubble = getattr(self, "bubble_seg", None)
        if bubble is not None:
            bubble.set_value(getattr(self.pet, "bubble_style", "auto"))

    def _open_skin_library(self):
        """我的形象库…：关掉窗口之后马上把这一页的数刷新一遍（不用再切页 / 重启）。"""
        self._run(self.pet.skin_library_dialog)
        self._sync_skin_controls()

    def _reset_all_skin(self):
        self._run(self.pet.clear_custom_skin, None)
        self._sync_skin_controls()

    # ---------------- 控制台外观 ----------------
    def _page_console(self, page):
        card = page.card("背景", "铺在窗口最底下", "page.layers")
        # 只有"导入文件"这一个入口：图片 / 视频一起给，是哪种看后缀。
        # （原来有「不用 / 图片 / 视频」一排 + 另外一颗「清掉」，
        #   「不用」和「清掉」干的是同一件事，主人说分不清。）
        self.bg_pick_btn = self._text_button(self._bg_pick_text(),
                                             self._pick_backdrop, None, "ui.upload-image")
        bg_buttons = QWidget()
        bg_line = QHBoxLayout(bg_buttons)
        bg_line.setContentsMargins(0, 0, 0, 0)
        bg_line.setSpacing(8)
        bg_line.addWidget(self.bg_pick_btn)
        bg_line.addWidget(self._text_button("移除", self._clear_backdrop, None, "ui.delete"))
        self.bg_path_row = page.row(card, "图片 / 视频", self._bg_path_text(),
                                    bg_buttons)
        self.bg_fit_switch = Switch(self._bg_bool("console_bg_fit_window"),
                                    self._on_fit_window)
        page.row(card, "自动适配窗口", "关掉就完整显示", self.bg_fit_switch)
        self.bg_focus_grid = AlignGrid(self._bg("console_bg_focus"),
                                       self._on_bg_focus)
        self.bg_focus_grid.setEnabled(self._bg_bool("console_bg_fit_window"))
        self.bg_focus_row = page.row(card, "截取位置", "铺满时留哪一块",
                                     self.bg_focus_grid)
        self.bg_bright_bar = page.slider(
            card, "亮暗", "负数压暗，正数提亮",
            -100, 100, self._bg_int("console_bg_bright"), "",
            lambda v: self._on_bg_slider("console_bg_bright", v))
        self.bg_blur_bar = page.slider(
            card, "模糊", "越高越糊，字更清楚",
            0, 40, self._bg_int("console_bg_blur"), "",
            lambda v: self._on_bg_slider("console_bg_blur", v))
        self.bg_scrim_bar = page.slider(
            card, "遮罩", "越高底图越淡",
            0, 100, self._bg_int("console_bg_scrim"), "%",
            lambda v: self._on_bg_slider("console_bg_scrim", v))
        self.bg_hint = page.hint(card, "视频循环播放，窗口收起时会自己暂停。")
        if not MEDIA_OK:
            page.hint(card, "这台机器上没有视频解码器，只能导入图片。")

        card = page.card("标题和图标", "左上角那两样", "ui.edit")
        self.brand_edit = QLineEdit(str(self._bg("console_brand_title") or ""))
        self.brand_edit.setFixedWidth(220)
        self.brand_edit.setPlaceholderText("大肥鱼桌宠")
        self.brand_edit.textChanged.connect(self._on_brand_text)
        page.row(card, "标题", "清空 = 用默认名字", self.brand_edit)
        self.brand_row = page.row(
            card, "图标", self._logo_text(),
            self._pair_buttons(("换一张…", self._pick_logo),
                               ("恢复默认", self._clear_logo)))

        card = page.card("颜色和卡片", "按钮、滑块、卡片", "page.theme-system")
        self.accent_row = ColorSwatches(
            str(self._bg("console_accent") or ""), self._apply_accent,
            self._pick_accent, self._accent_from_bg)
        # 这行的说明文字顺便当回执用（取色失败时就地写一句，不另占一行）
        self.accent_row_wrap = page.row(card, "强调色", "点一下就是它",
                                        self.accent_row)
        self.card_alpha_bar = page.slider(
            card, "卡片不透明度", "越低越透",
            40, 100, self._bg_int("console_card_alpha"), "%",
            lambda v: self._on_card_style("console_card_alpha", v))
        self.card_radius_bar = page.slider(
            card, "圆角", "0 = 方角", 0, 18,
            self._bg_int("console_card_radius"), "",
            lambda v: self._on_card_style("console_card_radius", v))

        card = page.card("窗口", "开在哪儿", "page.resize")
        self.geo_switch = Switch(bool(self._bg("console_remember_geo")),
                                 self._on_remember_geo)
        page.row(card, "记住大小位置", "下次打开照旧", self.geo_switch)
        self.start_combo = page.combo(
            card, "默认打开", "一开就停在这一页",
            [(key, title) for key, title, _desc, _icon, _builder in self.PAGES],
            self._start_page(), self._on_start_page)

        card = page.card("恢复默认", "一把清干净", "ui.reset")
        page.buttons(card, [("全部恢复默认", self._reset_console_look, "danger", "ui.reset")])

    # ---- 控制台外观：动一下就要顺手存盘 ----
    def _pick_backdrop(self):
        """导入背景：图片和视频一起给，是哪种看后缀（不再让用户先选一次类型）。"""
        path = self._ask_file("挑一张图或一段视频", MEDIA_FILTER, self._bg_path())
        if not path:
            return
        if bg_kind_of(path) == "video" and not MEDIA_OK:
            self._hint_bg("这台机器上没有视频解码器，只能导入图片。")
            return
        self._set_bg("console_bg_path", path)
        self.apply_theme()
        self._sync_console_controls()
        self._hint_bg("视频循环播放，窗口收起时会自己暂停。")

    def _clear_backdrop(self):
        self._set_bg("console_bg_path", "")
        self._video_stop()
        self.apply_theme()
        self._sync_console_controls()
        self._hint_bg("还没导入 —— 点右边「导入文件…」")

    def _on_bg_slider(self, key, value):
        self._set_bg(key, int(value))
        self._apply_backdrop(force=True)

    def _on_fit_window(self, on):
        """自动适配窗口：开 = 铺满（可挑截取位置），关 = 完整显示。"""
        on = bool(on)
        self._set_bg("console_bg_fit_window", on)
        switch = getattr(self, "bg_fit_switch", None)
        if switch is not None and switch.isChecked() != on:
            switch.blockSignals(True)       # 从别处改的值，开关也得跟着摆对
            switch.setChecked(on)
            switch.blockSignals(False)
        grid = getattr(self, "bg_focus_grid", None)
        if grid is not None:
            grid.setEnabled(on)             # 不放满就没有"截哪一块"这回事
        self._apply_backdrop(force=True)

    def _on_bg_focus(self, focus):
        focus = str(focus or "cc")
        if focus == self._bg("console_bg_focus"):
            return
        self._set_bg("console_bg_focus", focus)
        self._apply_backdrop(force=True)

    def _hint_bg(self, text):
        """拿「背景」那张卡的说明当回执（不额外占一行）。"""
        label = getattr(self, "bg_hint", None)
        if label is not None:
            label.setText(text)

    def _on_start_page(self, key):
        self._set_bg("console_start_page", str(key or ""))

    def _on_brand_text(self, text):
        if text == self._bg("console_brand_title"):
            return
        self._set_bg("console_brand_title", text)
        self._apply_brand()

    def _pick_logo(self):
        path = self._ask_file("挑一张图标", IMAGE_FILTER + ";;图标 (*.ico)",
                              str(self._bg("console_logo_path") or ""))
        if not path:
            return
        self._set_bg("console_logo_path", path)
        self._apply_brand()
        self._sync_console_controls()

    def _clear_logo(self):
        self._set_bg("console_logo_path", "")
        self._apply_brand()
        self._sync_console_controls()

    def _reset_console_look(self):
        """背景 / 标题 / 图标一起回到默认。"""
        for key, value in BACKDROP_DEFAULTS.items():
            self.pet.cfg[key] = value
        try:
            self.pet.save_config()
        except Exception:
            pass
        self._video_stop()
        set_accent(self.pet.cfg.get("console_accent"))
        set_card_style(self._bg_int("console_card_alpha"),
                       self._bg_int("console_card_radius"))
        self._apply_brand()
        self._sync_console_controls()
        self._sync_motion_switches()      # 动效那两颗开关也在 BACKDROP_DEFAULTS 里，一起复位
        self.apply_theme()

    def _sync_console_controls(self):
        """把这一页上的控件摆成配置里的样子（恢复默认 / 从别处改过之后用）。"""
        fit_on = self._bg_bool("console_bg_fit_window")
        pick_btn = getattr(self, "bg_pick_btn", None)
        if pick_btn is not None:
            pick_btn.setText(self._bg_pick_text())
        fit_switch = getattr(self, "bg_fit_switch", None)
        if fit_switch is not None and fit_switch.isChecked() != fit_on:
            fit_switch.blockSignals(True)
            fit_switch.setChecked(fit_on)
            fit_switch.blockSignals(False)
        grid = getattr(self, "bg_focus_grid", None)
        if grid is not None:
            grid.set_value(self._bg("console_bg_focus"))
            grid.setEnabled(fit_on)
        self._hint_bg("视频循环播放，窗口收起时会自己暂停。" if MEDIA_OK
                      else "这台机器上没有视频解码器，只能导入图片。")
        for name, key, unit in (("bg_bright_bar", "console_bg_bright", ""),
                                ("bg_blur_bar", "console_bg_blur", ""),
                                ("bg_scrim_bar", "console_bg_scrim", "%"),
                                ("card_alpha_bar", "console_card_alpha", "%"),
                                ("card_radius_bar", "console_card_radius", "")):
            bar = getattr(self, name, None)
            if bar is None:
                continue
            value = self._bg_int(key)
            if bar.value() != value:
                bar.blockSignals(True)
                bar.setValue(value)
                bar.blockSignals(False)
            label = getattr(bar, "value_label", None)
            if label is not None:
                label.setText(f"{value}{unit}")
        self._sync_accent_row()
        switch = getattr(self, "geo_switch", None)
        if switch is not None:
            want = bool(self._bg("console_remember_geo"))
            if switch.isChecked() != want:
                switch.blockSignals(True)
                switch.setChecked(want)
                switch.blockSignals(False)
        start = getattr(self, "start_combo", None)
        if start is not None:
            key = self._start_page()
            if start.currentData() != key:
                index = start.findData(key)
                if index >= 0:
                    start.blockSignals(True)
                    start.setCurrentIndex(index)
                    start.blockSignals(False)
        edit = getattr(self, "brand_edit", None)
        if edit is not None:
            text = str(self._bg("console_brand_title") or "")
            if edit.text() != text:
                edit.blockSignals(True)
                edit.setText(text)
                edit.blockSignals(False)
        for row, text in ((getattr(self, "bg_path_row", None), self._bg_path_text()),
                          (getattr(self, "brand_row", None), self._logo_text())):
            label = getattr(row, "desc_label", None) if row is not None else None
            if label is not None:
                label.setText(text)

    # ---------------- 行为与互动 ----------------
    def _page_behavior(self, page):
        pet = self.pet
        card = page.card("模式", "桌宠的移动方式", "nav.behavior")
        page.row(card, "移动方式", "",
                 Segmented([("wander", "自由散步"), ("follow", "跟随鼠标"),
                            ("still", "原地待着")],
                           pet.mode, lambda key: self._run(pet.set_mode, key)))
        page.row(card, "原地待着时跟随鼠标转向", "仅改变朝向，不移动位置",
                 Switch(pet.still_face_cursor, pet.set_still_face_cursor))

        card = page.card("快速双击", "双击它一下会做什么", "page.click")
        choices = list(self.ctx.get("DOUBLE_CLICK_CHOICES") or [])
        page.combo(card, "双击效果", "未配置 Key 时不能选择「看一眼余额」",
                   [(k, label) for k, label in choices],
                   pet._double_click_choice(),
                   lambda key: self._run(pet.set_double_click, key))
        page.buttons(card, [
            ("改写这几句台词…",
             lambda: self._run(pet.edit_lines_dialog, "DOUBLE_CLICK_LINES"),
             None)])

        card = page.card("防误触", "按住它拖不动、点不到它", "page.pointer-off")
        page.row(card, "锁定位置", "拖不动，点击 / 双击照常",
                 Switch(pet.locked, pet.set_locked))
        page.row(card, "鼠标穿透", "点不到它（托盘图标能解除）",
                 Switch(pet.cfg.get("passthrough", False), pet.set_passthrough))
        page.hint(card, "若已无法点击：双击托盘图标，或在「通用」中执行救急恢复。")

        # 合体新增：AI 对话 / 喂食
        card = page.card("AI 对话", "跟大肥鱼聊天（走 DeepSeek）", "ui.quote")
        page.hint(card, "每句不超过 25 字，记住最近 40 条；"
                        "用的是「余额和用量」里那个 Key。")
        page.buttons(card, [
            ("现在聊一句", lambda: self._run(pet._show_chat_dialog), "primary", "ui.quote"),
            ("设置 Key…", lambda: self._run(pet._set_key_dialog), None, "nav.balance"),
        ])

        card = page.card("喂食", "小鱼干 / 蛋糕 / 棒棒糖 / 团子 / 钻石", "page.sparkle")
        page.hint(card, "也可以把「快速双击」设成「喂食」，双击它就端出零食盘。")
        page.buttons(card, [
            ("喂它一下", lambda: self._run(pet._open_food_panel), "primary", "page.sparkle"),
        ])

    # ---------------- 文案与语录 ----------------
    def _page_lines(self, page):
        pet = self.pet
        card = page.card("高峰 / 空闲时段", "DeepSeek 不同时段价格不同",
                         "nav.lines")
        page.row(card, "显示当前峰谷时段", "在余额气泡中标注高峰或空闲",
                 Switch(pet.show_peak, pet.set_show_peak))
        page.combo(card, "峰谷文案", "选择文案风格",
                   [(name, name) for name
                    in (self.ctx.get("PEAK_TEXT_STYLES") or {})],
                   pet.peak_style,
                   lambda style: self._run(pet.set_peak_style, style))

        card = page.card("语录", "闲置时自动说话", "ui.quote")
        levels = list((self.ctx.get("LINE_FREQ_LEVELS") or {}).items())
        page.combo(card, "语录频率", "控制自动说话的间隔",
                   [(name, f"{name}（{conf.get('hint', '')}）")
                    for name, conf in levels],
                   pet.line_freq,
                   lambda name: self._run(pet.set_line_freq, name))
        page.row(card, "离开 / 返回提醒", "离开超过 30 分钟后返回时提醒一次",
                 Switch(pet.cfg.get("back_greet", True), pet.set_back_greet))
        page.row(card, "全屏时静音", "全屏（游戏 / 视频）时不显示气泡，提醒暂存",
                 Switch(pet.cfg.get("fullscreen_silent", True),
                        pet.set_fullscreen_silent))

        # 语录板块：哪几块参与说话（关掉的整块不再开口，台词本身留着）
        self.section_switches = {}
        sec_card = page.card("语录板块", "选择哪几块参与说话", "ui.quote")
        for sec_id, sec_name, sec_desc, _keys in (self.ctx.get("LINE_SECTIONS") or []):
            sw = Switch(pet.line_section_on(sec_id),
                        (lambda on, sid=sec_id: self._run(pet.set_line_section, sid, on)))
            self.section_switches[sec_id] = sw
            page.row(sec_card, sec_name, sec_desc, sw)
        page.hint(sec_card, "关掉的板块整块不再说话（台词还留着，随时能再打开）。"
                            "快速双击不受影响：双击该做什么还做什么。")

        self.lines_row = page.row(card, "台词内容", self._lines_desc(),
                                  self._text_button("打开编辑器…",
                                                    self._open_lines_editor,
                                                    "primary"))
        page.hint(card, "优先级：触发类提示（应用启动 / 使用时长 / 定时 / 快捷键 / 双击）"
                        "高于语录；触发提示显示期间语录暂不显示。")
        self._hook_page("lines", self._sync_lines_controls)

    def _lines_desc(self):
        n_custom = len(self.pet.cfg.get("custom_lines") or {})
        return (f"自己写 / 改写内置（已改 {n_custom} 类）" if n_custom
                else "自己写 / 改写内置")

    def _sync_lines_controls(self):
        """台词改了哪几类、哪几块被关了，现读一遍（切回这一页时也走这儿）。"""
        row = getattr(self, "lines_row", None)
        if row is not None and row.desc_label is not None:
            row.desc_label.setText(self._lines_desc())
        pet = self.pet
        for sec_id, sw in (getattr(self, "section_switches", None) or {}).items():
            want = pet.line_section_on(sec_id)
            if sw.isChecked() != want:
                sw.blockSignals(True)
                sw.setChecked(want)
                sw.blockSignals(False)

    def _open_lines_editor(self):
        self._run(self.pet.edit_lines_dialog)
        self._sync_lines_controls()

    # ---------------- 音效 ----------------
    def _page_sound(self, page):
        pet = self.pet
        card = page.card("音效", "点击、拖拽时的音效", "nav.sound")
        page.row(card, "按键音效", "关闭后无音效",
                 Switch(pet.sound_on, pet.set_sound))
        self.sound_combo = page.combo(card, "音效选择", "内置若干套，可自行添加",
                                      [(name, name) for name in pet._sound_names()],
                                      pet.sound_set,
                                      lambda name: self._run(pet.set_sound_set, name))
        page.slider(card, "音量", "", 0, 100, int(pet.volume * 100), "%",
                    lambda v: self._run(pet.set_volume, v / 100.0))
        page.buttons(card, [
            ("试听", lambda: pet.preview_sounds(), "primary", "page.volume-high"),
            ("添加我的音效…", self._add_sound, None, "ui.add"),
            ("删掉我加的音效…", self._remove_sound, "danger", "ui.delete"),
        ])
        self._hook_page("sound", self._sync_sound_controls)

    def _sync_sound_controls(self):
        """音效名单现读一遍：自己加 / 删过的，回到这一页就看得见（不用重启）。"""
        box = getattr(self, "sound_combo", None)
        if box is None:
            return
        pet = self.pet
        names = list(pet._sound_names())
        shown = [box.itemText(i) for i in range(box.count())]
        if shown != names:
            box.blockSignals(True)
            box.clear()
            for name in names:                      # 值就是名字，跟 page.combo 建的时候一样
                box.addItem(name, name)
            box.blockSignals(False)
        for i in range(box.count()):
            if box.itemData(i) == pet.sound_set:
                if box.currentIndex() != i:
                    box.blockSignals(True)
                    box.setCurrentIndex(i)
                    box.blockSignals(False)
                break

    def _add_sound(self):
        self._run(self.pet.add_custom_sound_dialog)
        self._sync_sound_controls()

    def _remove_sound(self):
        self._run(self.pet.remove_custom_sound_dialog)
        self._sync_sound_controls()

    # ---------------- 联动与自动化 ----------------
    def _page_integration(self, page):
        pet = self.pet
        card = page.card("应用启动提醒", "打开指定应用时显示一条提示",
                         "nav.integration")
        page.row(card, "应用启动提醒", "可为每个应用单独设置提示文字",
                 Switch(pet.process_alerts, pet.set_process_alerts))
        page.buttons(card, [
            ("扫描本机应用并添加…",
             lambda: self._run(pet.scan_apps_dialog), "primary", "ui.spinner"),
            ("清理自定义文字…",
             lambda: self._run(pet.remove_custom_app_dialog), "danger", "ui.delete"),
        ])
        page.hint(card, "每个应用可单独设置提示文字；未添加的应用不受影响。")
        # 一条都没配过时给张插图 + 一句"下一步做什么"，别只留一片空白
        self.integration_empty = page.empty(
            "empty.app", "尚未配置应用提示",
            "点「扫描本机应用并添加…」选择一个应用", size=44, layout=card)
        self._hook_page("integration", self._sync_integration_empty)

        card = page.card("使用时长提醒", "连续使用同一应用达到设定时长后提醒",
                         "ui.timer")
        page.row(card, "使用时长提醒", "达到设定分钟数时显示一条提示",
                 Switch(pet.cfg.get("app_time_on", True), pet.set_app_time_on))
        page.buttons(card, [("配置应用与时长…",
                             self._open_app_time, "primary", "ui.edit")])
        self.app_time_hint = page.hint(card, self._app_time_text(), "muted")

        card = page.card("定时提醒", "按每天、每周或固定间隔提醒",
                         "page.clock")
        page.row(card, "定时提醒", "到设定时间显示一条提示",
                 Switch(pet.cfg.get("timed_on", True), pet.set_timed_on))
        page.buttons(card, [("配置时间与台词…",
                             self._open_timed, "primary", "ui.edit")])
        self.timed_hint = page.hint(card, self._timed_text(), "muted")

        card = page.card("全局快捷键", "在任意窗口按组合键触发",
                         "ui.keyboard")
        page.row(card, "全局快捷键", "按键与动作都可自定义",
                 Switch(pet.cfg.get("hotkeys_on", True), pet.set_hotkeys_on))
        page.buttons(card, [("配置按键与动作…",
                             self._open_hotkeys, "primary", "ui.edit")])
        self.hotkey_hint = page.hint(card, self._hotkey_text(), "muted")
        self._hook_page("integration", self._sync_autosay_texts)

    # 三个"配置…"按钮：窗口关掉之后顺手把下面那行小字重读一遍
    def _open_app_time(self):
        self._run(self.pet.app_time_dialog)
        self._sync_autosay_texts()

    def _open_timed(self):
        self._run(self.pet.timed_lines_dialog)
        self._sync_autosay_texts()

    def _open_hotkeys(self):
        self._run(self.pet.hotkeys_dialog)
        self._sync_autosay_texts()

    def _app_time_text(self):
        rules = [r for r in (self.pet.app_time_rules() or {}).values()
                 if isinstance(r, dict) and r.get("on", True) and (r.get("lines") or [])]
        return (f"已启用 {len(rules)} 个应用。" if rules
                else "未配置。点「配置应用与时长…」添加。")

    def _timed_text(self):
        rules = [r for r in self.pet.clock_rules()
                 if r.get("on", True) and (r.get("lines") or [])]
        return (f"已启用 {len(rules)} 条定时提醒。" if rules
                else "未配置。点「配置时间与台词…」添加。")

    def _hotkey_text(self):
        rules = [r for r in self.pet.hotkey_rules()
                 if r.get("on", True) and (r.get("lines") or [])]
        if not rules:
            return "未配置。点「配置按键与动作…」添加。"
        text = "已启用 %d 个：%s。" % (len(rules),
                                      "、".join(r.get("seq") or "?" for r in rules))
        bad = self.pet.hotkey_failed_texts()
        if bad:
            text += f"（{'、'.join(bad)} 被别的程序占用了，按不出来，换一个键）"
        return text

    def _sync_autosay_texts(self):
        """三张卡下面的那行小字：回到这一页时现读一遍。"""
        for name, fn in (("app_time_hint", self._app_time_text),
                         ("timed_hint", self._timed_text),
                         ("hotkey_hint", self._hotkey_text)):
            label = getattr(self, name, None)
            if label is not None:
                label.setText(fn())

    def _sync_integration_empty(self):
        """一个自定义 / 改写的应用都没有时，把那块空状态露出来。"""
        pet = self.pet
        custom = pet.cfg.get("custom_process_lines") or {}
        overrides = pet.cfg.get("default_line_overrides") or {}
        empty = getattr(self, "integration_empty", None)
        if empty is not None:
            empty.setVisible(not (custom or overrides))

    # ---------------- 性能与工具 ----------------
    def _page_performance(self, page):
        pet = self.pet
        card = page.card("流畅度", "动画优先还是省资源", "nav.performance")
        page.row(card, "怎么跑", "",
                 Segmented([(True, "性能模式 · 动画优先"),
                            (False, "休闲模式 · 省资源")],
                           pet.perf_mode,
                           lambda on: self._run(pet.set_perf_mode, on)))

        # 合体新增：系统状态监控
        card = page.card("系统状态监控", "CPU / 内存 / 显卡超阈值时冒泡提醒",
                         "nav.performance")
        page.row(card, "启用监控", "10 秒查一次，超阈值才说话",
                 Switch(bool(pet.cfg.get("sys_monitor_on", True)), pet.set_sys_monitor))
        page.hint(card, "阈值：CPU ≥ 90%、内存 ≥ 95%、NVIDIA 显卡 ≥ 80℃；"
                        "没装 N 卡时显卡那项自动跳过。")

        card = page.card("百宝箱 · 回收内存",
                         "把后台程序不用的内存先还给系统", "page.sparkle")
        page.row(card, "回收时不动前台程序", "跳过当前前台程序，避免卡顿",
                 Switch(pet.cfg.get("mem_skip_foreground", True),
                        pet.set_mem_skip_foreground))
        self.mem_hint = page.hint(card, self._mem_hint_text(), "muted")
        page.buttons(card, [("回收内存", lambda: pet.mem_trim_now(), "primary", "page.sparkle")])
        # 回收是后台跑的，点完这一下数还不准 —— 回到这一页时现读一遍就够了
        self._hook_page("performance", self._sync_mem_hint)

        card = page.card("免打扰", "开启期间不显示气泡，提醒暂存，结束后汇总",
                         "ui.bell-off")
        page.slider(card, "默认时长", "菜单中「免打扰」使用的时长",
                    5, 180, int(pet.cfg.get("quiet_minutes") or 30), " 分钟",
                    lambda v: self._run(pet.set_quiet_minutes, v))
        page.buttons(card, [
            ("开始免打扰", lambda: self._run(pet.start_quiet), "primary", "ui.bell-off"),
            ("结束免打扰", lambda: self._run(pet.stop_quiet), None, "ui.reset"),
        ])
        self.quiet_hint = page.hint(card, self._quiet_text(), "muted")

        self._hook_page("performance", self._sync_tool_texts)

    def _quiet_text(self):
        left = self.pet.quiet_left()
        return (f"已开启，剩余 {left // 60} 分 {left % 60} 秒；期间不显示气泡，提醒暂存。"
                if left else "未开启。")

    def _sync_tool_texts(self):
        """免打扰那行状态（回到这一页时现读）。"""
        label = getattr(self, "quiet_hint", None)
        if label is not None:
            label.setText(self._quiet_text())

    def _mem_hint_text(self):
        last = getattr(self.pet, "_mem_last", None)
        human = self.ctx.get("human_mb", lambda n: f"{n / 1048576:.0f} MB")
        return (f"上次：{last[0]} 个程序腾出 {human(last[1])}" if last
                else "尚未执行。首次效果最明显，连续执行通常变化很小。")

    def _sync_mem_hint(self):
        label = getattr(self, "mem_hint", None)
        if label is not None:
            label.setText(self._mem_hint_text())

    def _sync_motion_switches(self):
        """把「页面切换动效 / 减少动效」两颗开关摆成配置里的样子（恢复默认之后也要对得上）。"""
        for name, key in (("page_anim_switch", "console_page_anim"),
                          ("reduce_motion_switch", "console_reduce_motion")):
            switch = getattr(self, name, None)
            if switch is None:
                continue
            want = self._bg_bool(key)
            if switch.isChecked() != want:
                switch.blockSignals(True)
                switch.setChecked(want)
                switch.blockSignals(False)

    # ---------------- 通用 ----------------
    def _page_general(self, page):
        pet = self.pet
        card = page.card("显示", "", "ui.eye")
        page.buttons(card, [
            ("显示 / 隐藏", lambda: pet.toggle_visible(), "primary", "ui.eye"),
            ("回到屏幕内", lambda: pet.snap_into_screen(), None, "page.location"),
            ("救急恢复", lambda: pet.force_recover(), None, "page.rescue"),
        ], align_right=False)

        card = page.card("开机", "", "page.power")
        page.row(card, "开机自启", "下次开机自己出来",
                 Switch(pet.cfg.get("autostart", False), pet.set_autostart))
        page.hint(card, "自启是在「启动」文件夹里放一个快捷方式，随时关得掉。")

        card = page.card("主题", "默认跟着 Windows 的亮暗走", "page.theme-system")
        seg = Segmented(THEME_MODES, self._mode, self.set_theme)
        self.theme_seg = seg
        page.row(card, "界面配色", "亮色 / 暗色 / 跟系统",
                 seg)
        page.hint(card, "「跟随系统」会在你切 Windows 深色模式时自动跟着变。")

        card = page.card("动效", "这个窗口自己的动画", "page.sparkle")
        self.page_anim_switch = Switch(
            self._bg_bool("console_page_anim"),
            lambda on: self._set_motion("console_page_anim", on))
        page.row(card, "页面切换动效", "切分类时新页面淡入一下",
                 self.page_anim_switch)
        self.reduce_motion_switch = Switch(
            self._bg_bool("console_reduce_motion"),
            lambda on: self._set_motion("console_reduce_motion", on))
        page.row(card, "减少动效",
                 "一切动画都不播：切页直接换、最小化 / 还原也直接到位（省电）",
                 self.reduce_motion_switch)
        page.hint(card, "「减少动效」开着的时候，上面那条切页动效也会一起停。")
        self._hook_page("general", self._sync_motion_switches)

        card = page.card("排查问题", "右键菜单不听话的时候才用得上", "ui.help")
        page.row(card, "记录菜单日志", "会写一个 menu-debug.log 方便查",
                 Switch(bool(pet.cfg.get("menu_debug", False)),
                        lambda on: pet.set_menu_debug(on)))
        page.divider(card)
        page.row(card, "右键菜单用经典版",
                 "打开后右键弹的是旧版那份完整菜单（功能全，但很长）",
                 Switch(bool(pet.cfg.get("classic_menu", False)),
                        pet.set_classic_menu))
        page.buttons(card, [
            ("打开经典菜单…（旧版那份长菜单）",
             lambda: self._run(pet._open_classic_menu), None, "ui.chevron")])

        card = page.card("最小化动画", "窗口最小化时往哪儿收", "ui.minimize")
        page.row(card, "落点",
                 "默认落在任务栏中间；想对准任务栏上自己那个图标就校准一次",
                 self._text_button("校准…", self._calibrate_min_target))
        saved = pet.cfg.get("minimize_target")
        self._cal_hint = page.hint(
            card,
            (f"现在记的是：({int(saved[0])}, {int(saved[1])})"
             if isinstance(saved, (list, tuple)) and len(saved) == 2
             else "还没校准 —— 动画会落在任务栏正中间。"),
            "muted")

    # ---------------- 关于 ----------------
    def _page_about(self, page):
        card = page.card("大肥鱼桌宠", "Windows 桌面宠物", "nav.about")
        head = QHBoxLayout()
        head.setSpacing(12)
        logo = QLabel()
        logo.setFixedSize(56, 56)
        logo.setPixmap(self._logo_pixmap(56))
        head.addWidget(logo)
        col = QVBoxLayout()
        col.setSpacing(2)
        name = QLabel("大肥鱼桌宠")
        name.setObjectName("cardTitle")
        col.addWidget(name)
        ver = QLabel(f"版本 v{APP_VERSION}")
        ver.setObjectName("muted")
        col.addWidget(ver)
        col.addStretch(1)
        head.addLayout(col)
        head.addStretch(1)
        card.addLayout(head)
        page.hint(card, "显示 DeepSeek 余额、天气、正在放的歌与歌词；"
                        "能换形象、带音效、可开机自启。")
        page.buttons(card, [
            ("项目主页", lambda: self._open_url(GITHUB_URL), "primary", "ui.external"),
            ("反馈 / 提需求",
             lambda: self._open_url(GITHUB_URL + "/issues"), None, "ui.help"),
        ], align_right=False)

    # ---------------- 小工具 ----------------
    def _size_pct(self, mult):
        """倍率 → 滑块上的百分比（桌宠那边算，界面这边只负责显示）。"""
        fn = self.ctx.get("size_percent")
        if fn is not None:
            try:
                return int(fn(mult))
            except Exception:
                pass
        try:
            return int(round(float(mult) * 100))
        except (TypeError, ValueError):
            return 100

    def _mult_from_pct(self, pct):
        fn = self.ctx.get("size_from_percent")
        if fn is not None:
            try:
                return float(fn(pct))
            except Exception:
                pass
        return float(pct) / 100.0

    def _on_size_level(self, mult):
        """点了某个档位：先改大小，再把滑块挪到同一个百分比上。"""
        self._run(self.pet.set_size, mult)
        bar = getattr(self, "size_slider", None)
        if bar is None:
            return
        pct = self._size_pct(mult)
        if bar.value() != pct:
            bar.blockSignals(True)          # 别让 setValue 再回调一次
            bar.setValue(pct)
            bar.blockSignals(False)
        label = getattr(bar, "value_label", None)
        if label is not None:
            label.setText(f"{pct}%")

    def _on_size_percent(self, pct):
        """拖滑块：改大小，并且"停在某一档上"时把那一档点亮。"""
        self._run(self.pet.set_size, self._mult_from_pct(pct))
        seg = getattr(self, "size_seg", None)
        if seg is None:
            return
        hit = None
        for _label, mult in getattr(self, "size_levels", []):
            if self._size_pct(mult) == pct:
                hit = mult
                break
        seg.set_value(hit)                  # 没停在任何一档上就把整排取消选中

    def _sync_size_controls(self):
        """从配置里读一次大小，把档位和滑块都摆对（别的地方改过大小也追得上）。"""
        if not hasattr(self, "size_slider"):
            return
        pct = self._size_pct(self.pet.cfg.get("size", 0.72))
        bar = self.size_slider
        if bar.value() != pct:
            bar.blockSignals(True)
            bar.setValue(pct)
            bar.blockSignals(False)
        if hasattr(bar, "value_label"):
            bar.value_label.setText(f"{pct}%")
        seg = getattr(self, "size_seg", None)
        if seg is not None:
            hit = None
            for _label, mult in getattr(self, "size_levels", []):
                if self._size_pct(mult) == pct:
                    hit = mult
                    break
            seg.set_value(hit)

    def _run(self, fn, *args, **kwargs):
        """界面上的动作统一入口：抛异常别把窗口带崩，也别吃掉消息。"""
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            print("控制台动作失败:", exc)
            return None

    def _open_url(self, url):
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl(url))
        except Exception:
            pass

    def _has_key(self):
        try:
            return bool(self.pet._current_source()[1])
        except Exception:
            return False

    def _source_names(self):
        names = ["DeepSeek"]
        for item in (self.pet.cfg.get("other_keys") or []):
            name = item.get("name")
            if name and name not in names:
                names.append(name)
        return names

    def _text_button(self, text, slot, style=None, icon_name=None):
        """单独一颗按钮（不在 page.buttons 那一行里的）。第四项 = 图标名。"""
        btn = QPushButton(text)
        btn.setFixedHeight(32)
        if style:
            btn.setObjectName(style)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if icon_name:
            btn.setIconSize(QSize(ICON_SM, ICON_SM))
            btn.setIcon(icon(icon_name, button_icon_color(style), ICON_SM))
            self._btn_icons.append((btn, icon_name, style))
        btn.clicked.connect(lambda _=False: slot())
        return btn

    def _pair_buttons(self, *pairs):
        wrap = QWidget()
        line = QHBoxLayout(wrap)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        for text, slot in pairs:
            line.addWidget(self._text_button(text, slot))
        return wrap

    def _layer_combo(self):
        labels = self.ctx.get("LAYER_LABELS") or {"top": "置顶"}
        box = QComboBox()
        for key, label in labels.items():
            box.addItem(label, key)
        for index in range(box.count()):
            if box.itemData(index) == self.pet.layer:
                box.setCurrentIndex(index)
                break
        box.setCursor(Qt.CursorShape.PointingHandCursor)
        box.currentIndexChanged.connect(
            lambda _i: self._run(self.pet.set_layer, box.currentData()))
        return box

    # ---------------- 窗口事件 ----------------
    def minimize_with_anim(self):
        """最小化：照着 Windows 那套"整窗缩到任务栏"的感觉做一遍。

        关键是**等比缩放**，不是把窗口越改越小：改小窗口的话，里面的字和控件会跟着重新排版，
        看着像"往下划拉"。所以先把窗口拍成一张图，动画期间只画这张图、把系统那套控件藏起来
        （`self.shell.hide()`），窗口一缩这张图就整体跟着缩 —— 跟 Windows 最小化一个观感。

        收完再**真正 minimize**（任务栏图标还在，点一下能还原）。
        """
        if self.isMinimized():
            return
        if getattr(self, "_anim_target", None) == "min":
            return                       # 已经在往最小化走，别重复起
        if self._reduce_motion():
            # 「减少动效」开着：不拍截图、不播动画，直接最小化。
            # `_min_self` 是给 changeEvent 那条兜底看的（不然它会把窗口拉回来再播一遍）。
            self._min_self = True
            self._min_pm = None          # 不留素材，还原时也不会突然冒出动画
            self._min_min_size = None
            self.showMinimized()
            return
        if getattr(self, "_min_pm", None) is None:
            self._min_pm = self.grab()   # 素材：整窗截图（还原动画也用它）
        self._restoring = False
        self.shell.hide()                # 动画期间只画那张截图
        geo = self.geometry()
        # 只有"手里没动画、也不是半路接回来的"才更新这个基准 ——
        # 不然连点时会把动画中间那个尺寸当成"正常大小"记下来，
        # 后面还原就会停在一个不上不下的大小上（连点 bug 的来源之一）。
        if (getattr(self, "_min_anim", None) is None
                and not getattr(self, "_restoring", False)):
            self._restore_geo = geo
        # 窗口平时有最小尺寸（820x560，免得被拖得太小），但动画要缩到任务栏那么点大，
        # 所以先把下限松开 —— 不松的话 Qt 会把几何钳在 820x560，
        # 看着就只剩"往下划拉"了（这坑真踩过）
        self._min_min_size = self.minimumSize()
        self.setMinimumSize(0, 0)
        self.update()
        self._start_anim(going_min=True)

    def _start_anim(self, going_min, force_from=None):
        """起一段动画。**可以被打断**：手里要是有正在跑的，先停掉，
        从"现在这个大小 / 现在这个透明度"接着往新方向走（跟 Windows 一样是接管，
        不是忽略新请求、也不是跳回去重头再来）。

        这里**不用** Qt 的 QPropertyAnimation：它跑在全局统一计时器上（≈60fps），
        同一段时长帧数只有一半。改成自己按 `ANIM_TICK_MS`（8ms ≈120fps）插值，
        时间不变、帧数翻倍，掉帧也更容易补上。
        """
        self._stop_anim()
        normal = getattr(self, "_restore_geo", None) or self.geometry()
        small = self._minimize_end_rect(normal)
        # force_from：有些路径（从最小化里出来）show() 之后 Qt 会把"原来的几何"用回去，
        # 这时候不能信 self.geometry()，否则动画就从满尺寸起步 —— 那一帧就是闪大窗口
        cur_geo = force_from if force_from is not None else self.geometry()
        cur_op = getattr(self, "_anim_fade", 1.0)
        self._anim = {
            "t0": time.perf_counter(),
            "dur": max(0.05, MINIMIZE_ANIM_MS / 1000.0),
            "from": QRect(cur_geo),
            "to": QRect(small if going_min else normal),
            "fade0": cur_op,
            "fade1": 0.0 if going_min else 1.0,
            "going_min": going_min,
        }
        self._min_anim = self                    # 外面拿它当"动画在跑"的标记（.stop() 也有）
        self._anim_target = "min" if going_min else "restore"
        if self._tick_timer is None:
            self._tick_timer = QTimer(self)
            self._tick_timer.setTimerType(Qt.TimerType.PreciseTimer)
            self._tick_timer.timeout.connect(self._anim_tick)
        self._tick_timer.start(ANIM_TICK_MS)
        self._anim_tick()                    # 立刻走第一拍，别等 8ms

    def stop(self):
        """给外面看的：答应"能 stop()"这个接口（_start_anim 里会调）。"""
        self._stop_anim()

    def _stop_anim(self):
        if self._tick_timer is not None:
            self._tick_timer.stop()
        self._anim = None
        self._min_anim = None
        self._anim_target = None

    def _anim_tick(self):
        """动画的一拍：按真实流逝时间算进度，所以掉一两帧也不会变慢。"""
        a = self._anim
        if not a:
            self._stop_anim()
            return
        p = (time.perf_counter() - a["t0"]) / a["dur"]
        p = 0.0 if p < 0.0 else (1.0 if p > 1.0 else p)
        # InCubic / OutCubic，和原来一致
        e = p ** 3 if a["going_min"] else 1.0 - (1.0 - p) ** 3
        f, t = a["from"], a["to"]
        geo = QRect(int(f.x() + (t.x() - f.x()) * e),
                    int(f.y() + (t.y() - f.y()) * e),
                    int(f.width() + (t.width() - f.width()) * e),
                    int(f.height() + (t.height() - f.height()) * e))
        self.setGeometry(geo)
        self._anim_fade = a["fade0"] + (a["fade1"] - a["fade0"]) * e
        self.update()
        if p >= 1.0:
            going_min = a["going_min"]
            self._stop_anim()
            self._anim_done(going_min)

    def _anim_done(self, going_min):
        self._anim_target = None
        if going_min:
            self._minimize_done(getattr(self, "_restore_geo", None) or self.geometry())
        else:
            self._finish_restore()

    def _minimize_target(self):
        """最小化动画往哪儿收。

        理想是"缩到任务栏上我自己那个按钮"—— 但那个按钮在 Windows 11 上是 XAML 画的，
        拿不到它的矩形（试过两条路：.NET UIA 查询要 15~50 秒还查不到；
        MSAA 命中测试在任务栏上返回的是前台窗口的元素）。所以做成**可校准**：
        「通用」页里点一下校准，把鼠标停在任务栏那个图标上，记下来当落点。
        """
        saved = self.pet.cfg.get("minimize_target")
        if isinstance(saved, (list, tuple)) and len(saved) == 2:
            try:
                return QPoint(int(saved[0]), int(saved[1]))
            except (TypeError, ValueError):
                pass
        full = (self.screen() or QApplication.primaryScreen()).geometry()
        return QPoint(full.center().x(), full.bottom() - 10)

    def _minimize_end_rect(self, from_geo):
        """最小化动画的终点矩形（按 from_geo 的 1/8 缩，落在 _minimize_target() 上）。"""
        small = QRect(0, 0,
                      max(46, from_geo.width() // 8),
                      max(34, from_geo.height() // 8))
        small.moveCenter(self._minimize_target())
        return small

    def restore_with_anim(self):
        """从任务栏点回来：把最小化动画**倒着放一遍** —— 从落点那一点点大，一边放大一边淡进来。

        系统和最小化一样不给这种窗口跑动画（分层窗口），所以要自己来：
        素材就是最小化时留下的那张整窗截图。
        """
        if getattr(self, "_anim_target", None) == "restore":
            return                       # 已经在往还原走了
        if self._reduce_motion():
            # 「减少动效」开着：不播动画，直接摆回来（_finish_restore 顺带把控件放回来、
            # 清掉可能留着的素材，没素材时它也是个幂等的收尾）
            self._restoring = False
            self.showNormal()
            self._finish_restore()
            return
        if not self.isMinimized() and getattr(self, "_min_pm", None) is None:
            # 正常开着、也没素材：谈不上"从任务栏还原"，抬到前面就行
            self.showNormal()
            self.raise_()
            self.activateWindow()
            return
        shot = getattr(self, "_min_pm", None)
        if not self.isMinimized() and (shot is None or shot.isNull()):
            self._finish_restore()          # 没素材（没走我们的最小化）：直接还原
            return
        # 打断最小化动画（窗口还没真最小化）时，什么都不用摆，直接从当前位置往回走
        if self.isMinimized():
            normal = getattr(self, "_restore_geo", None) or self.geometry()
            small = self._minimize_end_rect(normal)
            # 顺序有讲究（不然会闪一下大的）：
            #   ① 先 hide（脱离最小化）→ ② 清掉最小化状态 → ③ 隐身 →
            #   ④ 摆到落点那么小 → ⑤ show
            # 反过来（先 showNormal 再挪）中间会有一帧停在"原来那么大"上 —— 那就是闪烁。
            # 另外 changeEvent 里那条兜底是"没在放动画又脱离最小化 → 收拾干净"，
            # 这里先举个牌子，别让它把我正在建的动画对象清掉。
            self._restoring = True
            self.hide()
            # hide() 不会把"最小化"这个状态清掉 —— 不清的话下面 show() 回来
            # 窗口还是最小化的（等于还原白做了）
            self.setWindowState(Qt.WindowState.WindowNoState)
            self._anim_fade = 0.0
            self.setMinimumSize(0, 0)
            self.setGeometry(small)
            self.show()
            # show() 之后再钉一次：Qt 有时会在这一步把窗口摆回它记住的几何
            self.setGeometry(small)
            self._start_anim(going_min=False, force_from=small)
            self.update()
            return
        else:
            # 从"正在缩小"半路接回来：把最小尺寸松开就行，剩下的交给 _start_anim
            self._restoring = True
            self.setMinimumSize(0, 0)
        self.update()
        self._start_anim(going_min=False)

    def _finish_restore(self):
        """还原收尾：把真控件显示回来、清掉那张素材图、状态复位。"""
        if getattr(self, "_anim_target", None) == "min":
            return          # 正往最小化走，别把真控件放出来（那一帧会闪）
        self._min_anim = None
        self._restoring = False
        try:
            if getattr(self, "_min_min_size", None):
                self.setMinimumSize(self._min_min_size)
            self._min_pm = None
            self.shell.show()
            self._anim_fade = 1.0
            self.update()
            self.raise_()
            self.activateWindow()
        except Exception:
            pass

    def restore_or_show(self):
        """从菜单「打开设置…」进来：最小化着就先播还原动画，否则抬到前面。"""
        if self.isMinimized():
            self.restore_with_anim()
            return
        self.show()
        self.raise_()
        self.activateWindow()

    def _minimize_done(self, restore_geo):
        """动画收尾：把窗口和控件还原（这会儿还是全透明的，看不见），再真正最小化。"""
        self._min_anim = None
        try:
            self.setGeometry(restore_geo)
            if getattr(self, "_min_min_size", None):
                self.setMinimumSize(self._min_min_size)
            # 摆大小这一下必须是全透明的（否则会闪出一帧大窗口），稳一手再最小化
            self._anim_fade = 0.0
            # 注意：这里**不清** `_min_pm`、也不把 shell 显示回来 ——
            # 那张整窗截图留着当"还原动画"的素材（从任务栏点回来时反向放一遍）。
            # 万一窗口被系统自己还原了，changeEvent 里那条兜底会把状态收拾干净。
            # 这一下是我们自己按下去的：打上标记，免得下面 changeEvent 里
            # 的兜底逻辑又把窗口拽回来重放一遍动画
            self._min_self = True
            self.showMinimized()
        except Exception:
            pass
        # 注意：**这里不要把不透明度放回 1.0**。
        # showMinimized() 是异步的，紧接着恢复不透明的话，窗口在真正最小化之前
        # 还会在屏幕上待一帧 —— 那一帧就是满尺寸 + 全不透明的"闪一下"
        # （采集日志实测：t=10.651 满尺寸 + 透明=1.0 + 最小化=1）。
        # 留着全透明不管，等还原动画（或 _finish_restore）需要显示时再放回去。

    def paintEvent(self, _ev):
        """自己画一圈柔和阴影。

        原来用的是 `QGraphicsDropShadowEffect`：它会把整棵子树先画进一张离屏图再贴出来，
        配"无边框 + 半透明"的窗口时，子控件一重绘（比如按钮 hover）就容易留残影 ——
        表现成"某条边像被什么挡了一块"。自己画几圈半透明圆角矩形就没有这个问题。

        阴影**画一次缓存成图**：不然每滚一帧都要重画 7 圈抗锯齿圆角矩形，快速滚动会掉帧。
        """
        painter = QPainter(self)
        shot = getattr(self, "_min_pm", None)
        if shot is not None:
            # 最小化动画进行中：把这帧"整窗截图"按当前窗口大小等比铺上去，
            # 于是看起来就是整只窗口在缩小（里面的字和控件不会重排）
            # 注意用 FastTransformation：平滑缩放一张上千像素的图，每帧要十几毫秒，
            # 动画就会一顿一顿的（"掉帧卡顿"就是这么来的）
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            painter.setOpacity(max(0.0, min(1.0, getattr(self, "_anim_fade", 1.0))))
            painter.drawPixmap(self.rect(), shot)
        else:
            painter.drawPixmap(0, 0, self._shadow_pixmap())
        painter.end()

    def _on_fade(self, value):
        """淡入淡出的每一拍：只更新一个数 + 重画，不去动窗口属性。"""
        try:
            self._anim_fade = float(value)
        except (TypeError, ValueError):
            return
        self.update()

    def _shadow_pixmap(self):
        """窗口阴影：同一尺寸 / 同一主题只画一次，之后都是贴图。"""
        key = (self.width(), self.height(), tokens()["shadow"].name(),
               tokens()["shadow"].alpha(), self.devicePixelRatioF())
        if getattr(self, "_shadow_key", None) == key and self._shadow_pm is not None:
            return self._shadow_pm
        dpr = self.devicePixelRatioF() or 1.0
        pm = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
        pm.fill(Qt.GlobalColor.transparent)
        pm.setDevicePixelRatio(dpr)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        shadow = QColor(tokens()["shadow"])
        base = QRectF(self.shell.geometry())
        for step in range(6, 0, -1):
            color = QColor(shadow)
            color.setAlpha(max(3, int(shadow.alpha() * (1.0 - step / 7.0) * 0.62)))
            painter.setBrush(color)
            painter.drawRoundedRect(
                base.adjusted(-step, -step + 3, step, step + 3),
                14 + step, 14 + step)
        painter.end()
        self._shadow_pm = pm
        self._shadow_key = key
        return pm

    def closeEvent(self, ev):
        self._live.stop()
        self._video_stop()
        super().closeEvent(ev)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self._glass_on():
            self._bg_size_timer.start()     # 拖着改大小时别每帧都重算底图
        if self._bg("console_remember_geo"):
            self._geo_timer.start()

    def moveEvent(self, ev):
        super().moveEvent(ev)
        if self._bg("console_remember_geo"):
            self._geo_timer.start()

    def showEvent(self, ev):
        super().showEvent(ev)
        self._video_follow_visibility()
        self._bg_size_timer.start()         # 布局这会儿才定下来，迟一拍按真尺寸重算
        # 窗口收起来过一阵再打开：期间在右键菜单里改过的东西（形象库、音效…）要追得上
        self._refresh_current_page()

    def hideEvent(self, ev):
        # hideEvent 里 isVisible() 已经是 False 了，别绕一圈判断，直接停
        self._video_wanted = False
        if self._video_player is not None:
            try:
                self._video_player.pause()
            except Exception:
                pass
        super().hideEvent(ev)

    def changeEvent(self, ev):
        """兜底：万一原生消息那条路没拦到（别的入口进来的最小化），也走我们的动画。"""
        if ev.type() == QEvent.Type.WindowStateChange:
            self._video_follow_visibility()     # 最小化时把视频背景停下来
            if self.isMinimized():
                if getattr(self, "_min_self", False):
                    self._min_self = False      # 自己发起的那一次，放行
                else:
                    QTimer.singleShot(0, self._minimize_from_system)
            elif (getattr(self, "_min_pm", None) is not None
                    and getattr(self, "_min_anim", None) is None
                    and not getattr(self, "_restoring", False)):
                # 窗口被系统自己还原了：别把那张旧截图留在屏幕上，收拾干净
                QTimer.singleShot(0, self._finish_restore)
        super().changeEvent(ev)

    def _minimize_from_system(self):
        """系统那边把窗口最小化了（而我们没拦到）：先还原，再走自己的动画。"""
        if getattr(self, "_min_anim", None) is not None:
            return
        try:
            self.showNormal()
        except Exception:
            return
        self.minimize_with_anim()

    def _calibrate_min_target(self):
        """校准最小化动画的落点。

        点一下开始：鼠标移到自己那个任务栏图标上，**按空格**就记现在这一点
        （按 Enter 也行；不想按就 8 秒后自动记下当时鼠标在哪）。
        再点一次这颗按钮 = 也是"就记这儿"。
        """
        if getattr(self, "_cal_timer", None) is not None:
            self._capture_min_target()          # 已经在等 → 这一下就是"就记这儿"
            return
        self._cal_left = 8.0
        self._cal_timer = QTimer(self)
        self._cal_timer.setInterval(100)
        self._cal_timer.timeout.connect(self._cal_tick)
        self._cal_timer.start()
        self._cal_tick()

    def _cal_tick(self):
        self._cal_left -= 0.1
        pos = QCursor.pos()
        if self._cal_left <= 0:
            self._capture_min_target()
            return
        self._set_cal_hint(
            f"鼠标现在在 ({pos.x()}, {pos.y()}) —— 停到任务栏上你自己那个图标上，"
            f"按空格记住（{self._cal_left:.0f} 秒后自动记）")

    def _capture_min_target(self):
        timer = getattr(self, "_cal_timer", None)
        if timer is not None:
            timer.stop()
            self._cal_timer = None
        pos = QCursor.pos()
        self._run(self.pet.set_minimize_target, (pos.x(), pos.y()))
        self._set_cal_hint(f"记下了：({pos.x()}, {pos.y()}) —— 以后最小化就往这儿收")

    def _set_cal_hint(self, text):
        label = getattr(self, "_cal_hint", None)
        if label is not None:
            label.setText(text)

    def keyPressEvent(self, ev):
        if (getattr(self, "_cal_timer", None) is not None
                and ev.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter)):
            self._capture_min_target()      # 校准期间按空格 = 就记这儿
            return
        if ev.key() == Qt.Key.Key_Escape:
            # 搜索框里按 Esc = 清空搜索（回到分类），不是关窗口
            if (getattr(self, "search_edit", None) is not None
                    and self.search_edit.hasFocus() and self.search_edit.text()):
                self.search_edit.clear()
                return
            self.hide()
            return
        # Ctrl+F：直接跳到搜索框（顺手）
        if (ev.key() == Qt.Key.Key_F and ev.modifiers() & Qt.KeyboardModifier.ControlModifier
                and getattr(self, "search_edit", None) is not None):
            self.search_edit.setFocus()
            self.search_edit.selectAll()
            return
        super().keyPressEvent(ev)
