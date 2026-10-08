# -*- coding: utf-8 -*-
"""
大肥鱼桌宠 —— 三视图透明桌宠（只会走 + 看天气 + 报余额）

保留：桌面移动、天气（城市可联网添加）、外观（大肥鱼 / 小鲸鱼挂件切换）
余额挂件特性（对齐 MeteorNOX/DeepSeek-Balance-Whale-Widget, MIT）：
余额泡泡（余额 / 今日已用）、数字滚动动画、拖拽四边吸附、左吸附整体翻转、
按压 Q 弹、按键音效、每轮 Codex 对话消耗换算（峰谷定价表取自该项目）
音乐联动：放 QQ音乐 / 网易云 时读 Windows 媒体会话，把当前歌词挂在气泡里
"""
import ctypes
import contextlib
import hashlib
import json
import math
import os
import random
import re
import subprocess
import sys
import threading
import time
import wave
from array import array
from datetime import datetime, timedelta

def load_config():
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("配置读取失败:", e)
        return {
            "city": "北京"
        }

import requests
import psutil
try:
    import pynvml
    pynvml.nvmlInit()
    GPU_AVAILABLE = True
except Exception:
    GPU_AVAILABLE = False
from PySide6.QtCore import (Qt, QTimer, QPoint, QPointF, QRectF, QUrl, QIODevice,
                            QEventLoop, QSize, QFileInfo, QEvent, QAbstractNativeEventFilter,
                            QObject)
from PySide6.QtGui import (QPainter, QPixmap, QFont, QColor, QIcon, QFontMetrics,
                           QPolygonF, QImage, QCursor, QMouseEvent, QKeySequence)
from PySide6.QtWidgets import (QApplication, QWidget, QMenu, QSystemTrayIcon,
                               QMessageBox, QInputDialog, QLineEdit, QVBoxLayout,
                               QHBoxLayout, QPushButton, QFrame, QDialog, QToolButton,
                               QSlider, QWidgetAction, QFileDialog, QListWidget,
                               QListWidgetItem, QLabel, QFileIconProvider, QSizePolicy,
                               QComboBox)

try:
    from PySide6.QtMultimedia import QSoundEffect
    from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices
    AUDIO_AVAILABLE = True
except Exception:
    AUDIO_AVAILABLE = False


# ===== 合体新增：DeepSeek AI 对话（自原版 1190fasheqi/dafeiyu-pet 移植） =====
DS_BASE_URL = "https://api.deepseek.com/v1"
DS_MODEL = "deepseek-chat"
DS_SYSTEM = "你是桌面宠物大肥鱼，贱兮兮但可爱，每句话不超过25字，偶尔吐槽主人但别真骂人。"
CHAT_MAX_HISTORY = 40

# ===== 合体新增：喂食面板（自原版移植） =====
FOODS = ["🐟", "🍰", "🍭", "🍡", "💎"]
FOOD_LINES = {
    "🐟": ["小鱼干！我的最爱！", "咔嚓咔嚓……谢谢投喂！", "唔，鲜！"],
    "🍰": ["蛋糕！罪恶但快乐……", "甜到冒泡泡～", "嗝～又圆了一圈……"],
    "🍭": ["棒棒糖！转圈圈～", "嘎嘣脆，好吃！"],
    "🍡": ["三色团子！软乎乎～", "糯叽叽，爱了爱了！"],
    "💎": ["钻石？！这能吃吗……咕咚。真香！", "发财啦！明天开始吃高级鱼粮！"],
}


class _NativeMsg(ctypes.Structure):
    _fields_ = [("hWnd", ctypes.c_void_p), ("message", ctypes.c_uint),
                ("wParam", ctypes.c_void_p), ("lParam", ctypes.c_void_p),
                ("time", ctypes.c_ulong), ("pt_x", ctypes.c_long), ("pt_y", ctypes.c_long)]


class SubmenuPlaceFix(QObject):
    """子菜单**一显示的那一瞬间**就把它摆到"贴住这一条"的位置。

    为什么需要：Qt 自己弹子菜单时用的是它自己那套摆法（在条目边上、没有我们那 12px 重叠），
    我们下一拍（120ms 后）才发现"位置不对"再挪过去 —— 主人看到的就是
    "先小部分重叠、再往里移动"。装上这个过滤器以后，摆正发生在同一帧里，看不出来。
    """

    def __init__(self, pet):
        super().__init__(pet)
        self.pet = pet

    def eventFilter(self, obj, ev):
        if isinstance(obj, QMenu) and ev.type() == QEvent.Type.Show:
            try:
                self.pet._place_shown_submenu(obj)
            except Exception:
                pass
        return False


class MenuClickBridge(QAbstractNativeEventFilter):
    """把"落在子菜单上、却被 Windows 送给上层菜单"的点击自己处理掉。

    实测：二级菜单弹出后，鼠标点在它上面时，Windows 把 WM_LBUTTONDOWN/UP 送给了
    **持有鼠标捕获的上层菜单**；Qt 一看坐标在自己外面，就把整个菜单关掉 —— 所以
    二级菜单永远收不到点击（点了就消失）。这里在原生消息层拦截并自己执行那一项。
    """

    DOWN, UP = 0x0201, 0x0202

    def __init__(self, pet):
        super().__init__()
        self.pet = pet

    def nativeEventFilter(self, eventType, message):
        try:
            msg = ctypes.cast(int(message), ctypes.POINTER(_NativeMsg)).contents
        except Exception:
            return False, 0
        if MENU_DEBUG and msg.message in (0x0200, 0x0201, 0x0202, 0x0204, 0x0205):
            name = {0x0200: "WM_MOUSEMOVE", 0x0201: "WM_LBUTTONDOWN", 0x0202: "WM_LBUTTONUP",
                    0x0204: "WM_RBUTTONDOWN", 0x0205: "WM_RBUTTONUP"}.get(msg.message)
            info = f"[原生] {name} hwnd={msg.hWnd} pt=({msg.pt_x},{msg.pt_y})"
            try:
                root = getattr(self.pet, "_menu_keepalive", None)
                for m in self.pet._all_menus(root) if root else []:
                    if int(m.winId()) == msg.hWnd:
                        info += f" → 是菜单(层级{getattr(m, '_dfy_depth', '?')})"
                        break
                else:
                    if int(self.pet.winId()) == msg.hWnd:
                        info += " → 是桌宠"
            except Exception:
                pass
            if msg.message == 0x0200:
                if "是菜单" in info:                 # 只记落在菜单上的移动
                    menu_debug_throttled(info, 250)
            else:
                menu_debug(info)
        if msg.message not in (self.DOWN, self.UP) or not self.pet.ui_open:
            # v1.0.11：菜单窗口收到的鼠标移动，Qt 自己不去处理（这台机器上 Qt 弹出菜单
            # 收不到输入）→ 菜单里"光标停在哪一条"的高亮就不动，快速上下滑看着就是"卡住"。
            # 这里把原生的每一帧移动直接喂给对应那层菜单，高亮就能跟着手走。
            if msg.message == 0x0200 and self.pet.ui_open:
                try:
                    m = self.pet._menu_by_hwnd(msg.hWnd)
                    if m is not None:
                        self.pet._highlight_menu_item(m, QCursor.pos())
                except Exception:
                    pass
            return False, 0
        menu = self.pet.submenu_under_cursor()
        if menu is None:
            return False, 0
        menu_debug(f"[原生] 拦截到落在子菜单上的点击（层级{getattr(menu, '_dfy_depth', '?')}）")
        if msg.message == self.UP:
            self.pet.activate_menu_item(menu)
        return True, 0


class HotkeyBridge(QAbstractNativeEventFilter):
    """全局快捷键：Windows 把热键消息投给"注册它的那个线程"。

    桌宠在主线程用 RegisterHotKey 注册（见 PetWindow._register_hotkeys），
    按下时 Windows 往主线程消息队列里投一条 WM_HOTKEY；Qt 的事件循环
    会先过一遍原生消息过滤器 —— 就在这儿认出来，转给桌宠说一句。
    """

    WM_HOTKEY = 0x0312

    def __init__(self, pet):
        super().__init__()
        self.pet = pet

    def nativeEventFilter(self, eventType, message):
        try:
            if bytes(eventType) not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                return False, 0
            msg = ctypes.cast(int(message), ctypes.POINTER(_NativeMsg)).contents
        except Exception:
            return False, 0
        if msg.message != self.WM_HOTKEY:
            return False, 0
        try:
            self.pet._on_hotkey(int(msg.wParam or 0))
        except Exception as exc:
            print("快捷键处理失败:", exc)
        return True, 0



if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
    BUNDLE_DIR = getattr(sys, "_MEIPASS", APP_DIR)
    PYTHONW = sys.executable
    # 打包版的配置/账本写到用户目录，别往 exe 旁边（桌面）丢文件
    USER_DIR = os.path.join(os.environ.get("APPDATA") or APP_DIR, "大肥鱼桌宠")
    try:
        os.makedirs(USER_DIR, exist_ok=True)
    except Exception:
        USER_DIR = APP_DIR
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = APP_DIR
    PYTHONW = os.path.join(APP_DIR, ".venv", "Scripts", "pythonw.exe")
    USER_DIR = APP_DIR
SPRITE_DIR = os.path.join(BUNDLE_DIR, "sprites")
ASSET_DIR = os.path.join(BUNDLE_DIR, "assets")     # 音效 + 小鲸鱼挂件形象
CONFIG_PATH = os.path.join(USER_DIR, "config.json")

# 新界面（设置窗口）：v1.1.0 起，菜单里的「打开设置…」开的是它。
# 单独一个模块；万一它起不来，也绝不能拖垮桌宠本身 —— 老菜单照旧能用。
# （先把自己的目录塞进 sys.path：直接 exec 加载本文件时也能找到 ui_console）
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
try:
    import ui_console
    ui_console.set_asset_dir(ASSET_DIR)
except Exception as _ui_exc:                       # pragma: no cover
    ui_console = None
    print("控制台界面加载失败:", _ui_exc)


def theme_color(key, fallback):
    """取当前主题里的一个颜色（界面模块没加载起来时退回写死的值）。"""
    try:
        return ui_console.tokens()[key]
    except Exception:
        return fallback


# Qt 自带的中文翻译得留个引用，不然会被回收（回收了按钮又变回 OK / Cancel）
_QT_TRANSLATORS = []


def install_qt_translator(app):
    """让 Qt 内置对话框的按钮显示中文。

    `QInputDialog` / `QMessageBox` 那些窗口里的 OK / Cancel 是 Qt 自己的词条，
    只能靠 Qt 的翻译文件；PySide6 自带 `translations/qtbase_zh_CN.qm`，装上就全汉化了
    （弹出的"触发文字"窗口底下那两个按钮就是它）。
    """
    try:
        from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
    except Exception:
        return
    try:
        QLocale.setDefault(QLocale(QLocale.Language.Chinese, QLocale.Country.China))
    except Exception:
        pass
    path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    for name in ("qtbase_zh_CN", "qt_zh_CN"):
        try:
            tr = QTranslator(app)
            if tr.load(name, path):
                app.installTranslator(tr)
                _QT_TRANSLATORS.append(tr)
        except Exception:
            pass

BUBBLE_H = 112         # 气泡区高度（要放得下四行余额气泡：余额 / 金额 / 今日已用 / 峰谷）
MARGIN = 4
# 五档。**滑块上的百分比以「大」为 100%**（2026-09-14 定的：选「大」时滑块就停在 100%），
# 所以这几档特意按"乘出来是整百分数"排：30% / 40% / 60% / 80% / 100%。
SIZE_LEVELS = {"迷你": 0.27, "特小": 0.36, "小": 0.54, "中": 0.72, "大": 0.90}
SIZE_REF = SIZE_LEVELS["大"]      # 滑块上的 100% = 这一档（340 * 0.9 = 306px）
# 无级调节的范围：20% ~ 150%（原来只有 30% ~ 120%）
SIZE_MIN = 0.18
SIZE_MAX = 1.35
SIZE_DEFAULT = SIZE_LEVELS["中"]


def size_percent(mult):
    """大小倍率 → 滑块上那个百分比（「大」= 100%）。"""
    try:
        return int(round(float(mult) / SIZE_REF * 100))
    except (TypeError, ValueError):
        return int(round(SIZE_DEFAULT / SIZE_REF * 100))


def size_from_percent(pct):
    """滑块上那个百分比 → 大小倍率。"""
    try:
        return float(pct) / 100.0 * SIZE_REF
    except (TypeError, ValueError):
        return SIZE_DEFAULT
MIN_WIN_W = 168        # 窗口最窄宽度：小档位也别把气泡挤成一条（气泡要放得下三四行字）

# 语录（闲着时自己冒话）的触发频率档位
# cooldown = 两句之间最少隔多少帧（20ms/帧）。"正常"就是原来的行为，其它档只动这个间隔。
LINE_FREQ_LEVELS = {
    "安静": {"cooldown": 1500, "hint": "约 30 秒一句"},
    "正常": {"cooldown": 600, "hint": "约 12~17 秒一句"},
    "话多": {"cooldown": 300, "hint": "约 7~8 秒一句"},
    "话痨": {"cooldown": 150, "hint": "约 4~6 秒一句"},
}
LINE_FREQ_DEFAULT = "正常"
SPEED = 380.0
TICK = 20
# 「原地待着时也跟着鼠标转」的"鼠标贴身上"半径：鼠标在这个圈里就当正面（不左右转）
STILL_FACE_NEAR = 70

# ===== 它说话的调子 =====
# 统一风格：俏皮、机灵、有点小得意也爱撒娇的少女；句子短、口语、（呀／嘛／啦／诶／哦）。
# 三条不要：不要"AI 味"的排比和解释腔、不要说教、不要脏话。
# 加新台词照这个调子写就行。
#
# 闲着时冒的一句"双击我给你看余额"——双击被改成别的（或没配 Key）时就不再冒它（见 _maybe_idle_action）
DOUBLE_CLICK_HINT_LINE = "双击我一下嘛，余额马上端给你看"

LINES = [
    "在的在的，我一直蹲在这儿呢",
    "今天也要元气满满哦～我先替你满了",
    "偷偷瞄了一眼余额，还行，没被你饿着",
    "你专注起来的样子，我看了好久诶",
    "别老看我啦，看屏幕呀",
    "摸鱼是不对的……不过我不告状，放心",
    "我这么可爱，你多看我两眼也正常啦",
    "嗯哼，是不是在想我",
    "我刚刚在心里夸了你一句，你猜是哪句",
    DOUBLE_CLICK_HINT_LINE,
    "嫌我吵？把「语录频率」调成安静，我立刻闭嘴，说到做到",
    "嫌我占地方就把我调小一点点嘛",
]
REACT_LINES = [
    "哎呀别戳啦，痒的呀",
    "干嘛干嘛，我又不是按钮",
    "戳一下就想走？不行，得多戳两下才行",
    "你点到我了……好吧，允许你再来一次",
    "怎么啦，是想我了还是想看余额了",
    "哎哟，轻点儿戳嘛",
    "本鲸今天心情好，不跟你计较啦",
    "戳我干嘛呀，余额又不会自己变多",
    "行行行，我帮你看一眼余额……喏，就这么多",
]
INNER_LINES = [
    "唔…他是不是又想看余额了",
    "今天要不要多夸他两句呢",
    "他发呆的样子好呆哦（可爱那种）",
    "有点想要被摸头…但是不能主动说",
    "刚才那句我说重了吗？",
    "余额别掉那么快嘛，我还没花够",
    "他要是把我关掉就惨了，安静点安静点",
    "他工作起来就不理我了，哼",
    "我悄悄说一句：其实我挺喜欢他的",
]
DRAG_LINES = ["哇——飞起来咯！", "轻点轻点，我发型要乱了呀",
              "放我下来嘛……再玩一次也不是不行", "晕晕晕，转得我眼花了"]
# 快速双击选「说一句我写的台词」时冒的这几句（默认这几句，用户可整组改写）
DOUBLE_CLICK_LINES = [
    "双击算什么本事呀，有本事双击两次",
    "在的在的，说事儿嘛",
    "摸鱼可以，别摸我啦",
    "省着点花嘛，我还想多陪你两年",
]

# 离开一阵子又回来时说的（{away} = 离开了多久）
BACK_LINES = [
    "回来啦？我可是一直数着时间的哦",
    "诶，{away}没见着人，跑哪儿去了呀",
    "欢迎回来～我刚刚打了个小盹",
]

# 切成某一档「语录频率」时冒的话（每档都能在「台词内容…」里自己改写）
FREQ_LINES = {
    "安静": ["行行行，我闭嘴，安静得像块小石头",
             "安静模式启动咯，你忙你的，我不出声"],
    "正常": ["嗯～就按平时的节奏来，我偶尔冒个泡哦",
             "说话频率调回正常啦，我稍微热情一点点"],
    "话多": ["话多是你要的哦，可别回头嫌我",
             "那我多唠两句嘛，反正你也没别的娱乐"],
    "话痨": ["碎碎念模式！接下来请欣赏我的独角戏",
             "嘿嘿，我的嘴从现在开始停不下来咯"],
}
FREQ_LINE_KEYS = {f"FREQ_LINES_{level}": level for level in FREQ_LINES}

# 可以让用户自己改写的台词分组（键 → 给人看的名字）
LINE_GROUPS = [
    ("LINES", "日常台词（闲置时）"),
    ("REACT_LINES", "点击回嘴"),
    ("INNER_LINES", "心声（灰色小气泡）"),
    ("DRAG_LINES", "拖拽时"),
    ("DOUBLE_CLICK_LINES", "快速双击时（自己写）"),
    ("BACK_LINES", "离开 / 返回时（{away} = 离开时长）"),
    ("MUSIC_CLICK_LINES", "放歌时点击（{song} = 歌名——歌手）"),
    ("MUSIC_START_LINES", "换歌时（同上）"),
    ("FREQ_LINES_安静", "语录频率·安静（切换档位时）"),
    ("FREQ_LINES_正常", "语录频率·正常（切换档位时）"),
    ("FREQ_LINES_话多", "语录频率·话多（切换档位时）"),
    ("FREQ_LINES_话痨", "语录频率·话痨（切换档位时）"),
]

# ===== 「语录板块」总开关 =====
# 哪几块参与说话，由主人在「设置 → 文案和语录 → 语录板块」里勾。
# id → (给人看的名字, 说明, 这一块管着哪些台词 key)
# **快速双击不在这个表里**：主人要求"双击触发不受影响"——
# 双击做的那件事（看余额 / 天气 / 在放什么 / 说一句我写的）永远照旧，不受这些开关牵连。
LINE_SECTIONS = [
    ("idle", "日常台词（闲置时）", "闲着的时候自己冒的那几句", ["LINES"]),
    ("inner", "心声（灰色小气泡）", "它自己在心里嘀咕的那几句", ["INNER_LINES"]),
    ("react", "点击回嘴", "点它一下之后回你的话", ["REACT_LINES"]),
    ("drag", "拖拽时", "把它拖来拖去、松手时说的话", ["DRAG_LINES"]),
    ("back", "离开 / 返回时", "离开半小时以上、回来时打的那句招呼", ["BACK_LINES"]),
    ("music_click", "放歌时点击", "放着歌的时候点它，说的那一句", ["MUSIC_CLICK_LINES"]),
    ("music_start", "换歌时", "切到下一首时冒的那一句", ["MUSIC_START_LINES"]),
    ("freq", "语录频率切换时", "把语录频率换成安静 / 正常 / 话多 / 话痨时说的话",
     ["FREQ_LINES_安静", "FREQ_LINES_正常", "FREQ_LINES_话多", "FREQ_LINES_话痨"]),
]
# 台词 key → 板块 id（没列在这儿的就是双击那类，永远说）
LINE_SECTION_OF = {key: sid for sid, _n, _d, keys in LINE_SECTIONS for key in keys}
LINE_SECTION_IDS = {sid for sid, _n, _d, _k in LINE_SECTIONS}


# ===== 余额挂件配置 =====
BALANCE_URL = "https://api.deepseek.com/user/balance"
BALANCE_TTL = 60          # 余额自动刷新间隔（秒）
USAGE_PATH = os.path.join(USER_DIR, "usage.json")   # 今日已用账本
# 账本抗跳变：余额下降不等于"用量"，平台侧（赠送额度到期/回收、退款、接口抽风）
# 也会让余额掉一大块。单次刷新掉得太多就不算用量，改成记「余额变动」。
# 阈值按两次采样的间隔放宽（每小时最多信 5 元），免得关一晚桌宠之后把正常用量也挡掉。
USAGE_JUMP_LIMIT = 20.0   # 元：60 秒这种短间隔下，单次最多信这么多是用量
USAGE_JUMP_RATE = 5.0     # 元/小时：间隔拉长时按这个放宽

# 峰谷定价（每百万 token 单价，元）与时段规则取自
# MeteorNOX/DeepSeek-Balance-Whale-Widget（MIT）
BASE_PRICE = {"hit": 0.05, "miss": 1.5, "out": 4.5}    # 空闲时段
PRO_PRICE = {"hit": 0.10, "miss": 3.0, "out": 9.0}     # 高峰时段
WEEKEND_VALLEY_FROM = datetime(2026, 8, 23)            # 此后周末全天按谷价

# 音效（两套，取自上面那个项目；文件缺失时静默降级）
SOUND_SETS = {
    "小黄鸭": ("Ya1.wav", "Ya2.wav"),
    "音效1": ("D1.wav", "D2.wav"),
}
SOUND_POOL = 3          # 每种音效同时可播的实例数（连点不互相打断）
# 点击音：把原「按压 + 松手」两条 wav 拼成一条，点一次就放完整一段
CLICK_CLIP_FILES = {"小黄鸭": "click-duck.wav", "音效1": "click-fx1.wav"}

# 用户自己加的音效（放在用户目录里，不跟程序混在一起）
SOUND_USER_DIR = os.path.join(USER_DIR, "sounds")
SOUND_IDEAL = (0.15, 0.60)      # 点击音最适合的时长区间（秒）
SOUND_KEEP_MAX = 0.60           # 太长的帮他裁到这个长度
# 给主人看的建议（加音效时会弹出来）
SOUND_TIP = ("点击音最适合 0.15 ~ 0.60 秒：\n"
             "· 太短（不到 0.15 秒）容易听不清，只剩一下咔哒\n"
             "· 太长（超过 0.60 秒）连点时会叠成一团、听着拖\n"
             "· 最稳的是 0.2 ~ 0.4 秒，干脆利落")


# ===== 音乐联动（QQ音乐 / 网易云音乐）=====
# 这两个软件都会把"现在在放什么"登记到 Windows 的媒体会话里（SMTC），
# 所以不用猜窗口标题，直接读系统媒体会话就能拿到歌名 / 歌手 / 播放状态 / 进度。
MUSIC_APPS = {
    "qqmusic": "QQ音乐",
    "qq music": "QQ音乐",
    "cloudmusic": "网易云音乐",
    "netease": "网易云音乐",       # 商店版 / 新版客户端 AUMID 里常写成 Netease.xxx
    "网易云": "网易云音乐",
}
MUSIC_POLL_MS = 1500          # 多久看一眼在放什么歌
# 暂停之后气泡还留着多久（留着才有地方点"继续放"；太久就收起来，别一直挂在那儿）
PAUSED_BUBBLE_SEC = 180
LYRIC_BTN_SIZE = 20            # 歌词气泡右上角那几颗按钮（⏮ ⏸▶ ⏭）的直径
LYRIC_BTN_GAP = 3              # 这几颗按钮之间的间隔
# 顶行「♪ 应用 · 歌名」右边要留出来的宽度：这几颗按钮就住在这一条里，
# 不留就会被文字压住（主人反馈"和原本的文字打架了"）
LYRIC_BTN_PAD = LYRIC_BTN_SIZE * 3 + LYRIC_BTN_GAP * 2 + 12
# 顶行最多占几行：小尺寸下「♪ 应用 《歌名》——歌手」一行塞不下，宁可折两行（别把歌名切掉）
LYRIC_HEAD_ROWS = 2

# 播放器给的信息可能不全（网易云实测会缺歌名/歌手）：缺了就用这几个占位，
# 命名风格保持一致（"无题" / "未知歌手" / "未知应用"）
TITLE_PLACEHOLDER = "无题"
ARTIST_PLACEHOLDER = "未知歌手"
APP_PLACEHOLDER = "未知应用"

# 歌词对时：正数 = 文字延后（等等声音），负数 = 文字提前。不同输出设备延迟不一样：
# 笔记本外放几乎没延迟，蓝牙耳机/音箱能差 0.3~1 秒，所以做成可选项。
LYRIC_OFFSET_LEVELS = [
    ("文字提前 0.5 秒", -0.5),
    ("文字提前 0.2 秒", -0.2),
    ("刚好同步", 0.0),
    ("文字延后 0.2 秒", 0.2),
    ("文字延后 0.5 秒", 0.5),
    ("文字延后 1.0 秒", 1.0),
]
LYRIC_OFFSET_DEFAULT = 0.2      # 默认让文字稍微等一下（实测文字容易抢在声音前头）
LYRIC_ANIM_SEC = 0.15           # 歌词换句时的过渡动画时长（秒）
LYRIC_ANIM_MS = 10              # 过渡期间用 100 帧/秒重绘（主时钟在休闲模式只有 25 帧，不够顺）
BUBBLE_ANIM_SEC = 0.15          # 气泡自己变大/变小也用同样长的过渡（跟着 100 帧/秒的计时器走）
LYRIC_KARAOKE_ON = False        # 逐字高亮（"唱到哪变蓝到哪"）：主人说不要，先关掉（网易云多数歌也没逐字数据）
LYRIC_KARAOKE_COLOR = (72, 104, 240)   # 已唱到的那部分的颜色（DeepSeek 蓝）

# 气泡风格（语录 / 余额 / 歌词三种气泡共用一套，在「设置 → 桌宠形象 → 外观」里换）：
# auto = 跟着设置界面的亮暗走，light / dark = 自己定死。
BUBBLE_STYLES = [("auto", "跟随界面"), ("light", "浅色"), ("dark", "深色")]
# 两套气泡底色 / 字色。亮色那套就是原来写死的值（老 config.json 不变样）。
BUBBLE_INK = {
    "light": {
        "bg": QColor(255, 255, 255, 242),          # 气泡底
        "fg": QColor(60, 60, 80),                  # 正文字
        "inner_bg": QColor(232, 232, 238, 242),    # 心声（（）那种）的底
        "inner_fg": QColor(125, 125, 138),
        "bal_title": QColor(130, 138, 158),        # 余额气泡：标题 / 数字 / 小字
        "bal_big": QColor(32, 49, 112),
        "bal_sub": QColor(150, 150, 165),
        "ly_head": QColor(140, 148, 168),          # 歌词气泡：应用·歌名 / 当前句 / 下一句
        "ly_main": QColor(38, 44, 66),
        "ly_next": QColor(158, 158, 172),
    },
    "dark": {
        "bg": QColor(31, 35, 49, 246),
        "fg": QColor(233, 235, 244),
        "inner_bg": QColor(45, 50, 68, 246),
        "inner_fg": QColor(170, 176, 196),
        "bal_title": QColor(151, 157, 178),
        "bal_big": QColor(150, 186, 255),
        "bal_sub": QColor(128, 135, 160),
        "ly_head": QColor(151, 157, 178),
        "ly_main": QColor(233, 235, 244),
        "ly_next": QColor(128, 135, 160),
    },
}
# 余额气泡里"现在高峰 / 空闲"那行的颜色（深色底上得亮一点才看得清）
BUBBLE_PEAK_COLORS = {"light": (QColor(198, 90, 20), QColor(46, 125, 50)),
                      "dark": (QColor(232, 152, 92), QColor(120, 214, 156))}

# 右键菜单每条前面的小图标：跟设置窗口**同一套**（assets/icons 里的 Lucide 线稿，
# 同一个 24 网格、线宽 1.75）。按文字**前缀**匹配、取最长的那个 ——
# 菜单文字常带状态后缀（「语录频率（现在：话多）」「透明度…（现在 100%）」）。
# 一张表、一份刷图标的代码，两版菜单（瘦身版 / 经典版）一起上 —— 这就是"图标风格统一"。
# 没写进来的条目就留空，菜单不会因为缺图标少显示一条。
MENU_ICONS = (
    ("查看余额", "nav.balance"),
    ("查看天气", "nav.weather"),
    ("看一眼", "ui.eye"),
    ("打开设置", "nav.general"),
    ("快速双击", "page.click"),
    ("说一句我写的台词", "ui.quote"),
    ("改写这几句", "ui.quote"),
    ("模式", "nav.behavior"),
    ("自由散步", "nav.behavior"),
    ("跟随鼠标", "nav.behavior"),
    ("原地待着", "nav.behavior"),
    ("大小", "page.resize"),
    ("迷你", "page.resize"),
    ("特小", "page.resize"),
    ("精确调节", "page.resize"),
    ("形象", "nav.appearance"),
    ("大肥鱼", "nav.appearance"),
    ("小鲸鱼挂件", "nav.appearance"),
    ("我的形象库", "nav.appearance"),
    ("全部恢复默认形象", "nav.appearance"),
    ("层级", "page.layers"),
    ("置顶", "page.layers"),
    ("置底", "page.layers"),
    ("普通层", "page.layers"),
    ("透明度", "page.opacity"),
    ("设置默认城市", "page.location"),
    ("自动定位城市", "page.location"),
    ("添加城市", "page.location"),
    ("天气", "nav.weather"),
    ("设置 Key", "nav.balance"),
    ("余额来源", "nav.balance"),
    ("添加其他 API Key", "nav.balance"),
    ("校准今日已用", "page.calibrate"),
    ("余额常显", "nav.balance"),
    ("每轮消耗统计", "page.calibrate"),
    ("每轮对话后显示消耗", "page.calibrate"),
    ("设置 Agent 名称", "ui.edit"),
    ("设置会话日志目录", "page.location"),
    ("日志目录", "page.location"),
    ("余额", "nav.balance"),
    ("吸附", "page.magnet"),
    ("拖拽吸附四边", "page.magnet"),
    ("左吸附时翻面", "page.magnet"),
    ("文案", "ui.quote"),
    ("显示峰谷时段", "nav.lines"),
    ("峰谷文案", "ui.quote"),
    ("语录频率", "ui.quote"),
    ("台词内容", "ui.quote"),
    ("进程联动", "nav.integration"),
    ("应用启动提醒", "nav.integration"),
    ("扫描本机应用并添加", "nav.integration"),
    ("音乐联动", "nav.music"),
    ("放歌时看着", "nav.music"),
    ("显示歌词内容", "nav.music"),
    ("歌词对时", "page.clock"),
    ("歌词太慢", "page.clock"),
    ("歌词太快", "page.clock"),
    ("按播放器显示的时间对齐", "page.clock"),
    ("这首歌的微调清零", "page.clock"),
    ("这首歌对不上", "page.clock"),
    ("流畅度", "nav.performance"),
    ("性能模式", "nav.performance"),
    ("休闲模式", "nav.performance"),
    ("百宝箱", "page.sparkle"),
    ("回收内存", "page.sparkle"),
    ("免打扰", "ui.bell-off"),
    ("结束免打扰", "ui.bell-off"),
    ("今日汇总", "page.calibrate"),
    ("回收时不动前台程序", "page.sparkle"),
    ("音效选择", "nav.sound"),
    ("按键音效", "nav.sound"),
    ("添加我的音效", "ui.add"),
    ("音量", "page.volume-high"),
    ("试听音效", "page.volume-high"),
    ("音效", "nav.sound"),
    ("显示/隐藏", "ui.eye"),
    ("回到屏幕内", "page.location"),
    ("锁定位置", "page.lock"),
    ("鼠标穿透", "page.pointer-off"),
    ("救急恢复", "page.rescue"),
    ("记菜单日志", "ui.help"),
    ("开机自启", "page.power"),
    ("退出", "page.exit"),
)

# 子菜单里的条目往下继承父项的图标（"大小"下面的迷你 / 小 / 中…都跟大小一个图案），
# 只有**父项和子项本来就不是一回事**的写在这里（天气菜单下面列的是城市）。
MENU_ICON_CHILD = (
    ("天气", "page.location"),
)
LYRIC_MAX_ROWS = 4              # 当前这句最多折几行（再多就先把字号缩一档）
LYRIC_MIN_PT = 7                # 折行还是超了时，字号最小缩到几磅（只有"迷你档 + 超长英文句"才会用到）
LYRIC_OVERFLOW_ROWS = 8         # 缩到底还装不下时最多铺几行（宁可气泡高一点，也别丢歌词）
MUSIC_HOLD_SEC = 5.0          # 放歌时：双击看余额 / 点"查看天气"，都显示 5 秒
MUSIC_PEEK_SEC = MUSIC_HOLD_SEC
PEEK_SEC = MUSIC_HOLD_SEC       # 快速双击看余额：顶上来显示几秒

# 快速双击（鼠标快点两下桌宠）冒什么：一级菜单「快速双击」里选。
# 「看一眼余额」必须**配了 Key 才给选** —— 没配 Key 时双击不会弹余额窗口，
# 还是原来的"换姿势"，只在本次启动里提醒一次怎么配（见 PetWindow._on_double_click）。
DOUBLE_CLICK_CHOICES = [
    ("balance", "看一眼余额（5 秒）"),
    ("weather", "看一眼天气"),
    ("music", "看一眼在放什么"),
    ("lines", "说一句我写的台词"),
    ("feed", "喂食"),
]
DOUBLE_CLICK_DEFAULT = "balance"
# 双击之后留几秒"让位"：这几秒里的自言自语先憋着，别把刚弹出来的那一眼盖掉
DOUBLE_CLICK_HOLD_SEC = {"balance": PEEK_SEC, "weather": MUSIC_HOLD_SEC,
                         "music": MUSIC_HOLD_SEC, "lines": 4.0, "feed": 5.0}
MENU_HOVER_MS = 120           # 菜单悬停兜底的检查间隔
MENU_HOVER_FAST_MS = 40       # 菜单开着时用这个间隔（纠位置差不多是"瞬间"）
MENU_HOVER_DELAY = 0.22       # 光标在带子菜单的项上停多久就替它弹出子菜单
MENU_HOVER_GRACE = 0.5        # 光标离开子菜单后，再等这么久才收（给手抖 / 斜着划过去留余地）
MENU_DEBUG_LOG = os.path.join(USER_DIR, "menu-debug.log")   # 菜单排查用日志
MENU_DEBUG = False            # 菜单排查日志（需要时改成 True，会写 menu-debug.log）
MENU_DEBUG_RUNTIME = False    # 同上，但可以由菜单里的「记菜单日志」开关打开（存在 config.json）
MENU_DEBUG_MOVE_MS = 120      # 鼠标移动最多每 120ms 记一条（免得日志爆掉）


def menu_debug(text):
    """菜单相关的排查日志（只写文件，不打扰使用）。"""
    if not (MENU_DEBUG or MENU_DEBUG_RUNTIME):
        return
    try:
        with open(MENU_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]}  {text}\n")
    except Exception:
        pass


_menu_debug_last = {"t": 0.0}


def menu_debug_throttled(text, ms=None):
    """节流版日志：鼠标移动之类的高频事件用它，别把日志刷爆。"""
    span = (ms if ms is not None else MENU_DEBUG_MOVE_MS) / 1000.0
    now = time.time()
    if now - _menu_debug_last["t"] < span:
        return
    _menu_debug_last["t"] = now
    menu_debug(text)


def defer_dialog(fn):
    """菜单项要弹窗口时用它包一层：**等菜单收完再弹**。

    实测：直接在菜单项回调里 `exec()`，偶尔会被菜单自己的关闭动作一起带走
    （窗口一闪就没了 / 干脆没出现）。隔一个事件循环再弹就稳了。
    """
    def wrapper(*_args, **_kwargs):
        QTimer.singleShot(0, fn)
    return wrapper
LYRIC_CACHE_PATH = os.path.join(USER_DIR, "lyrics_cache.json")
LYRIC_CACHE_MAX = 300         # 歌词缓存最多留多少首
LYRIC_CACHE_VERSION = 2       # 缓存格式版本：2 = 可能含逐字歌词（yrc）；旧缓存会自动重抓一次

# 放歌时点它的回嘴（{song} 会替换成《歌名》——歌手）
MUSIC_CLICK_LINES = [
    "♪ 正放着 {song} 呢，别打断我嘛",
    "刚听到副歌你就戳我，{song} 诶",
    "♪ 我在听 {song}，你品味还行哦",
    "别急别急，{song} 还没放完呢",
    "♪ {song}……要不要跟着哼两句呀",
    "听得正入神呢，{song} 真好听",
    "♪ 现在是 {song}，挑歌水平在线嘛",
]
# 换歌时冒一句
MUSIC_START_LINES = [
    "♪ 换歌啦：{song}",
    "♪ 这首 {song}，我先替你听听",
    "♪ 来活儿咯：{song}",
    "♪ 切到 {song} 啦，这首我记下了",
]


def merge_wavs(dest, sources):
    """把多段 wav 首尾拼成一段（采样率 / 声道 / 位宽必须一致）。"""
    params = None
    out = wave.open(dest, "wb")
    try:
        for src in sources:
            with wave.open(src, "rb") as r:
                p = r.getparams()
                key = (p.nchannels, p.sampwidth, p.framerate)
                if params is None:
                    params = key
                    out.setnchannels(p.nchannels)
                    out.setsampwidth(p.sampwidth)
                    out.setframerate(p.framerate)
                elif key != params:
                    raise ValueError("wav 参数不一致，没法拼接")
                out.writeframes(r.readframes(r.getnframes()))
    finally:
        out.close()
    return dest


def wav_seconds(path):
    """wav 时长（秒），读不出来就返回 0。"""
    try:
        with wave.open(path, "rb") as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except Exception:
        return 0.0


def make_click_wav(src, dest, max_seconds=None, rate=44100):
    """把主人挑的 wav 转成"点击音"要的格式：单声道 / 16 位 / 44100Hz（可选裁短）。

    为什么要转：常开音频流那个播放器只吃"单声道 16 位 44100"的 wav，
    主人随便挑的文件多半是 48kHz 立体声，不转的话要么没声、要么开头被吞。
    返回 (时长秒, 过程说明)；出错就抛异常，由调用方给主人提示。
    """
    with wave.open(src, "rb") as w:
        channels, width = w.getnchannels(), w.getsampwidth()
        src_rate, frames = w.getframerate(), w.getnframes()
        data = w.readframes(frames)
    note = []
    try:
        import audioop
    except Exception:
        audioop = None
    if audioop is not None:
        if width != 2:
            data = audioop.lin2lin(data, width, 2)
            width = 2
            note.append("位深转 16 位")
        if channels == 2:
            data = audioop.tomono(data, 2, 0.5, 0.5)
            channels = 1
            note.append("立体声合单声道")
        if src_rate != rate:
            data, _ = audioop.ratecv(data, 2, 1, src_rate, rate, None)
            note.append(f"{src_rate}Hz → {rate}Hz")
    else:                       # 没有 audioop（以后 Python 可能删掉它）时的兜底
        if width != 2:
            raise ValueError("这个 wav 不是 16 位的，请先转成 16 位 wav")
        if channels == 2:
            samples = array("h")
            samples.frombytes(data)
            mono = array("h", b"\x00\x00" * (len(samples) // 2))
            for i in range(0, len(samples) - 1, 2):
                mono[i // 2] = (samples[i] + samples[i + 1]) // 2
            data = mono.tobytes()
            channels = 1
            note.append("立体声合单声道")
        if src_rate != rate:
            raise ValueError(f"这个 wav 是 {src_rate}Hz 的，请先转成 {rate}Hz")
    if max_seconds:
        cap = int(rate * float(max_seconds)) * 2 * max(1, channels)
        if len(data) > cap:
            data = data[:cap]
            note.append(f"裁到 {float(max_seconds):.2f} 秒")
    folder = os.path.dirname(dest)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with wave.open(dest, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(data)
    return (len(data) // 2) / float(rate), "、".join(note)


def pick_click_clips():
    """每套音效的点击音：按压 + 松手两条拼成一条（拼不了就退回更长的那条）。

    返回 {音效名: wav 绝对路径}。
    """
    clips = {}
    for name, files in SOUND_SETS.items():
        srcs = [p for p in (os.path.join(ASSET_DIR, f) for f in files) if os.path.exists(p)]
        if not srcs:
            continue
        merged = os.path.join(ASSET_DIR, CLICK_CLIP_FILES.get(name, f"click-{name}.wav"))
        try:
            outdated = (not os.path.exists(merged)
                        or os.path.getmtime(merged) < max(os.path.getmtime(s) for s in srcs))
            if outdated:
                merge_wavs(merged, srcs)
            clips[name] = merged
        except Exception:
            clips[name] = max(srcs, key=wav_seconds)
    return clips


class ClickPlayer(QIODevice):
    """常开音频流的小音效播放器（自己混音，音量按样本缩放）。

    为什么不用 QSoundEffect：它每次播放都要重新起流，设备空闲后再点，开头一小段
    会被吞掉（表现为「有时候 ya1 听不见」）。这里改成常开的 QAudioSink + 自己
    喂样本：没人点的时候一直输出静音，所以设备始终是醒的，点下去立刻出声、
    完整一段都不会丢；顺便还支持多条音效重叠（连点）。
    """

    def __init__(self, parent=None, rate=44100):
        super().__init__(parent)
        self.rate = rate
        self.volume = 0.9
        self._clips = {}            # 名字 -> array('h') 样本
        self._voices = []           # [[样本, 播放位置, 音量], ...]
        self._lock = threading.Lock()
        self.sink = None
        self.ok = False
        if not AUDIO_AVAILABLE:
            return
        self._open_sink()

    def _open_sink(self):
        """按**当前**系统默认输出设备开一条常开音频流。"""
        if not AUDIO_AVAILABLE:
            return
        try:
            fmt = QAudioFormat()
            fmt.setSampleRate(self.rate)
            fmt.setChannelCount(1)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            device = QMediaDevices.defaultAudioOutput()
            if device.isNull():
                return
            self.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Unbuffered)
            self.sink = QAudioSink(device, fmt, self)
            self.sink.setBufferSize(int(self.rate * 0.12) * 2)     # ≈120ms 缓冲
            self.sink.start(self)                              # 常开：一直读我们的样本
            # 注意：PySide6 里没有 QAudioSink.Error/State 这两个枚举名，
            # 用字符串判定，免得踩到 AttributeError 直接静音。
            self.ok = "NoError" in str(self.sink.error())
        except Exception:
            self.sink = None
            self.ok = False

    def rebuild_output(self):
        """系统默认输出设备换了（插耳机 / 切蓝牙音箱）→ 重开一条流，让声音跟着走。

        主人反馈："一开始用笔记本外放，插上耳机以后别的声音都进耳机了，
        点击音效还在外放"——就是因为这条常开流一直绑在**开机时那个**设备上。
        """
        old = self.sink
        self.sink = None
        self.ok = False
        try:
            if old is not None:
                old.stop()
                old.deleteLater()
        except Exception:
            pass
        self._open_sink()
        return self.ok

    # --- QIODevice 接口：Qt 音频线程会不断来要数据 ---
    def isSequential(self):
        return True

    def bytesAvailable(self):
        return 1 << 20

    def readData(self, maxlen):
        frames = max(0, int(maxlen) // 2)
        out = array("h", bytes(int(maxlen)))
        with self._lock:
            for voice in list(self._voices):
                samples, pos, gain = voice
                n = min(frames, len(samples) - pos)
                if n > 0:
                    for i in range(n):
                        s = out[i] + int(samples[pos + i] * gain)
                        out[i] = -32768 if s < -32768 else (32767 if s > 32767 else s)
                    voice[1] = pos + n
                if voice[1] >= len(samples):
                    self._voices.remove(voice)
        return out.tobytes()

    def writeData(self, _data, _maxlen):
        return 0

    # --- 给桌宠用的接口 ---
    def load_clip(self, name, path):
        try:
            with wave.open(path, "rb") as w:
                if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, 2, self.rate):
                    return False
                data = w.readframes(w.getnframes())
            samples = array("h")
            samples.frombytes(data)
            self._clips[name] = samples
            return True
        except Exception:
            return False

    def has_clip(self, name):
        return name in self._clips

    def play(self, name, volume=None):
        samples = self._clips.get(name)
        if samples is None:
            return False
        gain = self.volume if volume is None else volume
        with self._lock:
            self._voices.append([samples, 0, gain])
            if len(self._voices) > 12:        # 太密了就把最老的丢掉
                self._voices.pop(0)
        return True

    def stop_all(self):
        with self._lock:
            self._voices = []


# 形象：大肥鱼（三视图）/ 小鲸鱼挂件（单张 cut-out）
SKIN_PET = "大肥鱼"
SKIN_WIDGET = "小鲸鱼挂件"
WIDGET_SKIN_FILE = "small-whale.png"
SPRITE_VIEWS = {"front": "正面", "side": "侧面", "back": "背面"}
VIEW_LABELS = {"front": "正面（朝屏幕下）", "side": "侧面（左右走）",
               "back": "背面（朝屏幕上）", "widget": "小鲸鱼挂件"}
# 短名字：菜单 / 对话框 / 冒泡里用得着（VIEW_LABELS 太长）
VIEW_SHORT = {"front": "正面", "side": "侧面", "back": "背面", "widget": "挂件"}

# 打开的某些应用时冒泡吐槽（进程名小写）
PROCESS_LINES = {
    "steam.exe": ["Steam 一开，今晚的我就没人管了吧", "又要玩游戏啦？我帮你看着时间哦"],
    "wegame.exe": ["开黑去咯～记得回来看看我", "打游戏可以，眼睛也要歇一歇呀"],
    "epicgameslauncher.exe": ["又是白嫖时间？领完就走哦", "Epic 又送游戏啦，快去拿"],
    "league of legends.exe": ["峡谷走起～上分了记得夸我一句", "又打排位呀？输了不许冲我发脾气"],
    "genshinimpact.exe": ["原神启动！抽卡前先看我一眼嘛", "去提瓦特啦？玩累了记得回来"],
    "chrome.exe": ["又开浏览器摸鱼，我什么都没看见哦", "开工还是冲浪？我猜是后者"],
    "msedge.exe": ["上网冲浪咯～", "开这么多标签，内存不会哭吗"],
    "douyin.exe": ["刷抖音记得看时间呀，我掐着表呢", "短视频是个坑，要不要我拉你一把"],
    "qq.exe": ["有人找你哦，别装没看见", "QQ 响了！快去回一下"],
    "wechat.exe": ["微信有人找你，回一下嘛", "别老盯着我看啦，去回消息"],
    "weixin.exe": ["微信有人找你，回一下嘛", "别老盯着我看啦，去回消息"],
    "qqmusic.exe": ["听歌时间！要不要跟着哼两句", "这歌好听诶，再来一首嘛"],
    "cloudmusic.exe": ["网易云开了，今天要 emo 吗", "听歌一时爽，一直听一直爽"],
    "code.exe": ["又写代码啦，记得多喝水哦", "写代码的样子好认真（我盯着呢）"],
    "chatgpt.exe": ["又去找它聊天？我有点吃醋诶", "我在这儿呢，随时待命啦"],
    "taskmgr.exe": ["打开任务管理器？是不是想关掉我…", "别看我占内存嘛，我很省的"],
    "obs64.exe": ["要录屏啦？记得把我拍得可爱一点", "开播咯，我去角落待着"],
    "photoshop.exe": ["开始画图啦，画完给我看看嘛", "修图还是摸鱼？我都支持哦"],
}

# ===== 自动说话：用久了 / 到点 / 快捷键 =====
# 三条规则都住在 config.json 里（app_time_lines / timed_lines / hotkeys），
# 下面这几个是"新装一份"时给的内置默认，主人可以在「设置 → 应用联动」里随便改、关、删。

# 用久了提醒：连续在前台用满这些分钟就说一句（进程名小写）
TIME_LINES = {
    "steam.exe": (60, ["{app} 玩了一个多小时咯，起来动动嘛",
                       "一个小时啦～眼睛也要喘口气的"]),
    "wegame.exe": (60, ["{app} 一个小时了，站起来晃两步嘛",
                        "打了一个多小时咯，腰还撑得住吗"]),
    "league of legends.exe": (90, ["{app} 一个半小时了，赢了也别再加一局哦",
                                   "峡谷再好看也得歇歇呀"]),
    "genshinimpact.exe": (60, ["{app} 一小时咯，眼睛离屏幕远一点点",
                               "一个小时啦，起来走两步再玩嘛"]),
    "douyin.exe": (40, ["{app} 刷了四十分钟啦，抬头看看我嘛",
                        "再刷下去天就黑咯，真的"]),
    "code.exe": (90, ["{app} 一个半小时了，喝口水，脖子也动动",
                      "九十分钟啦，起来走两步再战嘛"]),
    "chatgpt.exe": (90, ["{app} 聊了一个半小时咯，起来伸个懒腰",
                         "一个半小时了，记得喝水哦"]),
}

# 到点说一句：daily=每天这个点 / weekly=每周这几天 / interval=每隔 N 分钟
CLOCK_LINES_DEFAULT = [
    {"id": "builtin-night", "when": "daily", "time": "23:30", "days": [],
     "every": 0, "on": True, "summary": True,
     "lines": ["23:30 咯，早点睡嘛，明天的事明天再说",
               "都这个点啦？眼睛也要下班的哦"]},
]

# 全局快捷键：按一下它就说一句（键和台词都能改、能关、能删）
HOTKEYS_DEFAULT = [
    {"id": "builtin-praise", "seq": "Ctrl+Alt+1", "act": "lines", "on": True,
     "lines": ["哇！这一下也太帅了吧", "不错嘛你，我就知道你能行",
               "这波我给满分，真的满分", "厉害厉害，我在这儿都看呆了"]},
    {"id": "builtin-cheer", "seq": "Ctrl+Alt+2", "act": "lines", "on": True,
     "lines": ["别急别急，慢慢来嘛，我陪着你", "加油哦，再撑一小会儿就顺了",
               "有点难对吧？歇口气再来"]},
    {"id": "builtin-tease", "seq": "Ctrl+Alt+3", "act": "lines", "on": True,
     "lines": ["就这？……好吧，其实也还行啦", "又摸鱼？我可都记在小本本上了哦",
               "行吧，看在你这么认真的份上，我不说了"]},
]

WEEKDAY_NAMES = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

# 快捷键按下之后干什么（跟「快速双击」那四个动作是一套）
HOTKEY_ACTS = [("lines", "说一句（用下面写的台词）"),
               ("balance", "看一眼余额"),
               ("weather", "看一眼天气"),
               ("music", "看一眼在放什么")]

# 全局快捷键：修饰键表 + 认得的那些键
HOTKEY_BASE = 0xA510          # 注册用的 id 从这儿开始（只在桌宠自己这儿用）
HOTKEY_NOREPEAT = 0x4000      # 按住不放只算一次（不加会一直连发）
HOTKEY_MODS = {"ctrl": 0x0002, "control": 0x0002, "alt": 0x0001,
               "shift": 0x0004, "win": 0x0008, "meta": 0x0008}
HOTKEY_SPECIAL = {
    "space": 0x20, "tab": 0x09, "enter": 0x0D, "return": 0x0D, "esc": 0x1B,
    "escape": 0x1B, "backspace": 0x08, "del": 0x2E, "delete": 0x2E,
    "ins": 0x2D, "insert": 0x2D, "home": 0x24, "end": 0x23,
    "pgup": 0x21, "pageup": 0x21, "pgdn": 0x22, "pagedown": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
}
HOTKEY_MIN_MODS = 0x0002      # 至少得带 Ctrl（单键 / 纯 Shift 太容易误触、也容易抢别人的键）
FG_IDLE_FREEZE = 600          # 键鼠静了这么久（秒）就认为人不在："用久了"不累计也不提醒


def clone_rules(rules):
    """复制一份规则表：config 里的默认值不能和模块常量共用同一个 dict（改了会互相串）。"""
    out = []
    for rule in rules:
        item = dict(rule)
        item["lines"] = [str(t) for t in (rule.get("lines") or [])]
        if "days" in rule:
            item["days"] = list(rule.get("days") or [])
        out.append(item)
    return out


def app_time_default_rules():
    """内置的「用久了提醒」，每次调用给一份新的。"""
    return {exe: {"minutes": mins, "repeat": 0, "on": True, "lines": list(lines)}
            for exe, (mins, lines) in TIME_LINES.items()}


def hotkey_parse(text):
    """把 "Ctrl+Alt+1" 拆成 (修饰键, 虚拟键码)；认不出来 / 太危险就返回 None。

    只认字母、数字、F1~F24 和 HOTKEY_SPECIAL 里那几张。别的符号（`-` `[` `;`）
    Qt 的键值和 Windows 的虚拟键码不是一回事，宁可不注册，也别注册成一个按不出来的键。
    """
    text = (text or "").strip()
    if not text:
        return None
    mods, vk = 0, None
    for raw in text.replace("＋", "+").replace(" ", "").split("+"):
        token = raw.strip().lower()
        if not token:
            continue
        if token in HOTKEY_MODS:
            mods |= HOTKEY_MODS[token]
        elif token in HOTKEY_SPECIAL:
            vk = HOTKEY_SPECIAL[token]
        elif len(token) == 1 and token.isalnum():
            vk = ord(token.upper())
        elif token.startswith("f") and token[1:].isdigit() and 1 <= int(token[1:]) <= 24:
            vk = 0x70 + int(token[1:]) - 1
        else:
            return None
    if vk is None or not (mods & HOTKEY_MIN_MODS):
        return None
    return mods, vk


def hotkey_supported_hint():
    """给对话框用的一句话：支持的写法。"""
    return "支持的键：字母 / 数字 / F1~F24 / 空格、Tab、回车、Esc 这些；至少带 Ctrl。"


def idle_seconds():
    """键鼠多久没动过了（秒）；拿不到就返回 None。"""
    try:
        from ctypes import wintypes

        class _LastInput(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        info = _LastInput()
        info.cbSize = ctypes.sizeof(_LastInput)
        if not ctypes.WinDLL("user32.dll").GetLastInputInfo(ctypes.byref(info)):
            return None
        tick = ctypes.WinDLL("kernel32.dll").GetTickCount()
        return max(0.0, ((tick - info.dwTime) & 0xFFFFFFFF) / 1000.0)
    except Exception:
        return None


def app_path_for(exe):
    """从注册表 App Paths 里找这个 exe 的完整路径（找不到返回空串）。

    「用久了提醒」那本列表要给每个应用画真图标 —— 扫到的应用（正在跑 + 开始菜单）
    已经带路径了，剩下那些没在跑的（比如没开着的 Steam）就从这儿补一下。
    """
    exe = (exe or "").strip().lower()
    if not exe.endswith(".exe"):
        return ""
    try:
        import winreg
    except Exception:
        return ""
    sub = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
    # 注意：winreg 没有 HKLM / HKCU 这种简写，得写全名
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, sub + "\\" + exe) as key:
                path, _kind = winreg.QueryValueEx(key, "")
        except OSError:
            continue
        except Exception:
            continue
        path = os.path.expandvars(str(path or "").strip().strip('"'))
        if path and os.path.exists(path):
            return path
    return ""


# ===== 每日小结 / 免打扰 / 应用时长账本 =====
APP_TIME_PATH = os.path.join(USER_DIR, "app_time.json")   # 各应用今天的累计时长
APP_TIME_FLUSH_S = 60          # 每 60 秒把应用时长落一次盘（不要每 2 秒写一次）
# 小结里显示的名字（没列到的就用 exe 名去掉后缀）
APP_LABELS = {
    "steam.exe": "Steam", "wegame.exe": "WeGame", "epicgameslauncher.exe": "Epic",
    "league of legends.exe": "英雄联盟", "genshinimpact.exe": "原神",
    "douyin.exe": "抖音", "code.exe": "VS Code", "chatgpt.exe": "ChatGPT",
    "chrome.exe": "Chrome", "msedge.exe": "Edge", "firefox.exe": "Firefox",
    "qq.exe": "QQ", "wechat.exe": "微信", "weixin.exe": "微信",
    "qqmusic.exe": "QQ音乐", "cloudmusic.exe": "网易云音乐",
    "obs64.exe": "OBS", "photoshop.exe": "Photoshop", "taskmgr.exe": "任务管理器",
}
SUMMARY_MIN_SECONDS = 20 * 60      # 小结里至少用了这么久才点名（按时间从长到短取前两条）
SUMMARY_MAX_APPS = 2
BACK_AWAY_SECONDS = 1800           # 键鼠静这么久算"你走开了"，回来打个招呼
FULLSCREEN_REPORT_MIN = 180        # 全屏至少持续这么久，攒下的提醒才汇报
QUIET_DEFAULT_MIN = 30


def fmt_duration(seconds):
    """秒数说成人话：2 小时 5 分 / 48 分 / 30 秒。"""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} 秒"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} 分"
    hours, mins = divmod(minutes, 60)
    return f"{hours} 小时" + (f" {mins} 分" if mins else "")


def fill_vars(text, **vars):
    """把台词里的 {app} / {minutes} / {away} 这类占位换掉。

    认不出来的占位**原样留着** —— 主人写了 {song} 之类的，别被我们吃掉。
    """
    for key, value in vars.items():
        text = text.replace("{" + key + "}", str(value))
    return text


def foreground_pid():
    """前台窗口属于哪个进程（拿不到返回 0）。"""
    try:
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32.dll")
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return 0
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value or 0)
    except Exception:
        return 0


def foreground_is_fullscreen():
    """前台窗口是不是铺满了它所在那块屏（全屏游戏 / 全屏看电影）。

    桌面和任务栏不算（它们本来就铺满）。无边框全屏也算 —— 主人要的是
    "别在我打游戏 / 看电影的时候冒泡"。
    """
    try:
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32.dll")
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if cls.value in ("Progman", "WorkerW", "Shell_TrayWnd"):
            return False

        class _MonInfo(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        mon = user32.MonitorFromWindow(hwnd, 2)          # 2 = NEAREST
        if not mon:
            return False
        info = _MonInfo()
        info.cbSize = ctypes.sizeof(_MonInfo)
        if not user32.GetMonitorInfoW(mon, ctypes.byref(info)):
            return False
        m = info.rcMonitor
        return (rect.left <= m.left and rect.top <= m.top
                and rect.right >= m.right and rect.bottom >= m.bottom)
    except Exception:
        return False


def read_today_usage(path):
    """从余额账本里读"今天用了多少"（没这本 / 跨天了就返回 0）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            book = json.load(f) or {}
    except Exception:
        return 0.0
    if book.get("date") != datetime.now().strftime("%Y-%m-%d"):
        return 0.0
    try:
        return float(book.get("todayUsage") or 0)
    except (TypeError, ValueError):
        return 0.0


def load_app_time(path):
    """读应用时长账本 → (日期, {exe: 秒})；跨天 / 读不到就重开一本。"""
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        with open(path, "r", encoding="utf-8") as f:
            book = json.load(f) or {}
    except Exception:
        book = {}
    if book.get("date") != today or not isinstance(book.get("apps"), dict):
        return today, {}
    out = {}
    for exe, secs in book["apps"].items():
        try:
            out[str(exe)] = float(secs)
        except (TypeError, ValueError):
            continue
    return today, out


def save_app_time(path, date, apps):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"date": date, "apps": apps}, f, ensure_ascii=False, indent=1)
    except Exception as ex:
        print("应用时长账本保存失败:", repr(ex))


# 余额来源：目前只有 DeepSeek 和 OpenRouter 有公开的余额接口
NO_BALANCE_SERVICES = ("openai", "chatgpt", "gpt")
OPENROUTER_CREDITS_URL = "https://openrouter.ai/api/v1/credits"

# 从任意 agent 的会话日志里认 token 用量时用到的键名（Codex / Claude Code 等结构不同）
USAGE_TOKEN_KEYS = ("input_tokens", "prompt_tokens", "output_tokens", "completion_tokens",
                    "cached_input_tokens", "cache_read_input_tokens", "total_tokens")

# 每轮 Codex 对话消耗：读 Codex 会话日志里的 token 用量
CODEX_SESSIONS_DIR = os.path.join(os.path.expanduser("~"), ".codex-deepseek", "sessions")
CODEX_SCAN_MS = 3000        # 扫描间隔
CODEX_QUIET_S = 20          # 一轮安静这么久就结算并冒泡


class AppScanDialog(QDialog):
    """带图标的应用列表：能搜索、能看图标，选一个给它加"打开时说的话"。

    图标直接从 exe 取（QFileIconProvider），所以不用额外素材；
    ● 表示这个应用默认就有台词，✓ 表示你已经自定义过。
    """

    def __init__(self, owner, apps):
        super().__init__(None)
        if ui_console:                      # 跟设置窗口用同一套配色
            ui_console.style_dialog(self, BUNDLE_DIR)
        self.owner = owner
        self._icons = QFileIconProvider()
        self.setWindowTitle("扫描到的应用")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(470, 580)

        lay = QVBoxLayout(self)
        self.tip = QLabel("选一个应用，然后点下面的按钮。\n"
                          "● 内置默认（已经自带台词，不能重复添加，但可以改）　✎ 已改写　✓ 你自己加的")
        self.tip.setWordWrap(True)
        lay.addWidget(self.tip)

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索应用名或 exe，例如 steam / edge / 微信")
        lay.addWidget(self.search)

        self.listw = QListWidget()
        self.listw.setIconSize(QSize(24, 24))
        lay.addWidget(self.listw, 1)

        row = QHBoxLayout()
        self.add_btn = QPushButton("添加触发文字")
        self.del_btn = QPushButton("删除该应用的文字")
        close_btn = QPushButton("关闭")
        row.addWidget(self.add_btn)
        row.addWidget(self.del_btn)
        row.addWidget(close_btn)
        lay.addLayout(row)

        self.add_btn.clicked.connect(self._add_line)
        self.del_btn.clicked.connect(self._del_line)
        close_btn.clicked.connect(self.accept)
        self.listw.itemDoubleClicked.connect(lambda _item: self._add_line())
        self.listw.currentItemChanged.connect(lambda *_: self._refresh_buttons())
        self.search.textChanged.connect(self._filter)
        self._fill(apps)
        self._refresh_buttons()

    def _fill(self, apps):
        self.listw.clear()
        for exe, label, path in apps:
            item = QListWidgetItem()
            item.setIcon(self._icon_for(path))
            item.setData(Qt.ItemDataRole.UserRole, exe)
            item.setData(Qt.ItemDataRole.UserRole + 1, f"{label}（{exe}）")
            self.listw.addItem(item)
            self._mark_item(item)
        if self.listw.count():
            self.listw.setCurrentRow(0)

    def _icon_for(self, path):
        try:
            if path and os.path.exists(path):
                icon = self._icons.icon(QFileInfo(path))
                if not icon.isNull():
                    return icon
        except Exception:
            pass
        return self._icons.icon(QFileIconProvider.IconType.File)

    def _mark_item(self, item):
        exe = item.data(Qt.ItemDataRole.UserRole)
        base = item.data(Qt.ItemDataRole.UserRole + 1)
        custom = self.owner.cfg.get("custom_process_lines") or {}
        overrides = self.owner.cfg.get("default_line_overrides") or {}
        if exe in PROCESS_LINES:
            # 内置应用：已经自带台词，不能再"重复添加"，但可以改写或恢复
            tag = "✎已改写默认台词" if exe in overrides else "●内置默认（不可重复添加）"
            item.setText(f"{base}　{tag}")
        elif exe in custom:
            item.setText(f"{base}　✓已添加")
        else:
            item.setText(base)

    def _state_of(self, exe):
        """返回 (是否内置, 当前文字列表, 是否已改写/已添加)。"""
        overrides = self.owner.cfg.get("default_line_overrides") or {}
        custom = self.owner.cfg.get("custom_process_lines") or {}
        if exe in PROCESS_LINES:
            lines = overrides.get(exe) or PROCESS_LINES[exe]
            return True, list(lines), exe in overrides
        lines = custom.get(exe) or []
        return False, list(lines), bool(lines)

    def _refresh_buttons(self):
        exe = None
        item = self.listw.currentItem()
        if item is not None and not item.isHidden():
            exe = item.data(Qt.ItemDataRole.UserRole)
        if not exe:
            self.add_btn.setEnabled(False)
            self.del_btn.setEnabled(False)
            return
        is_default, lines, changed = self._state_of(exe)
        self.add_btn.setEnabled(True)
        self.add_btn.setText("修改默认台词" if is_default else
                             ("修改触发文字" if lines else "添加触发文字"))
        self.del_btn.setEnabled(changed)
        self.del_btn.setText("恢复内置台词" if (is_default and changed) else
                             ("删除自定义文字" if (not is_default and lines) else "无需清理"))

    def _filter(self, text):
        text = (text or "").strip().lower()
        for i in range(self.listw.count()):
            item = self.listw.item(i)
            item.setHidden(bool(text) and text not in item.text().lower())

    def _current_exe(self):
        item = self.listw.currentItem()
        if item is None or item.isHidden():
            self.tip.setText("先在上面选一个应用～")
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _add_line(self):
        exe = self._current_exe()
        if not exe:
            return
        is_default, current, _changed = self._state_of(exe)
        title = "修改内置台词" if is_default else "触发文字"
        hint = ("这是内置应用，原来的台词已经在下面了，改完会替换掉它（不会重复添加）："
                if is_default else "打开这个应用时它要说什么？（一句一行，可以写多行）")
        text, ok = QInputDialog.getMultiLineText(
            self, f"{exe} · {title}", hint, "\n".join(current),
            Qt.WindowType.WindowStaysOnTopHint)
        if not ok or not text.strip():
            return
        lines = [t.strip() for t in text.splitlines() if t.strip()]
        if is_default:
            overrides = dict(self.owner.cfg.get("default_line_overrides") or {})
            overrides[exe] = lines
            self.owner.cfg["default_line_overrides"] = overrides
        else:
            custom = dict(self.owner.cfg.get("custom_process_lines") or {})
            custom[exe] = lines
            self.owner.cfg["custom_process_lines"] = custom
        self.owner.save_config()
        self.owner.say(f"记住啦，开 {exe} 我就说这句")
        self.owner._invalidate_proc_lines()
        self.tip.setText(f"{exe} 现在有 {len(lines)} 句，切到这个应用就会冒泡")
        self._mark_item(self.listw.currentItem())
        self._refresh_buttons()

    def _del_line(self):
        exe = self._current_exe()
        if not exe:
            return
        is_default, _lines, changed = self._state_of(exe)
        if not changed:
            self.tip.setText(f"{exe} 用的是内置原版台词，没什么可清的")
            self._refresh_buttons()
            return
        if is_default:
            overrides = dict(self.owner.cfg.get("default_line_overrides") or {})
            overrides.pop(exe, None)
            self.owner.cfg["default_line_overrides"] = overrides
            self.owner.save_config()
            self.owner.say(f"{exe} 的台词恢复成内置的了")
            self.owner._invalidate_proc_lines()
            self.tip.setText(f"{exe} 已恢复内置台词")
            self._mark_item(self.listw.currentItem())
            self._refresh_buttons()
            return
        custom = dict(self.owner.cfg.get("custom_process_lines") or {})
        custom.pop(exe, None)
        self.owner.cfg["custom_process_lines"] = custom
        self.owner.save_config()
        self.owner.say(f"已删掉 {exe} 的自定义文字")
        self.owner._invalidate_proc_lines()
        self.tip.setText(f"已清掉 {exe} 的自定义文字")
        self._mark_item(self.listw.currentItem())
        self._refresh_buttons()


class AutoSayDialog(QDialog):
    """一张表管一类"自动说话"的规则：用久了 / 到点 / 快捷键。

    kind：
      apptime = 用久了提醒（某个应用连续在前台用满 N 分钟）
      clock   = 到点说一句（每天 / 每周 / 每隔一段时间）
      hotkey  = 全局快捷键（按一下就说一句）
    规则都存在 config.json 里；这里只管增删改，改完立刻生效（快捷键会重新注册）。
    """

    KINDS = {
        "apptime": ("应用使用时长提醒",
                    "同一应用连续使用达到设定分钟数时显示一条提示；\n"
                    "无键鼠操作的时间不计入（挂机、看视频不计）。"),
        "clock": ("定时提醒",
                  "按每天、每周指定日期或固定间隔显示提示。"),
        "hotkey": ("全局快捷键",
                   "在任意窗口按下组合键触发。\n"
                   + hotkey_supported_hint()),
    }

    def __init__(self, owner, kind, apps=None):
        super().__init__(None)
        if ui_console:                      # 跟设置窗口用同一套配色
            ui_console.style_dialog(self, BUNDLE_DIR)
        self.owner = owner
        self.kind = kind
        self.apps = list(apps or [])
        # 列表项前面那颗图标：用久了那本画应用的真图标（跟「扫描到的应用」一个口径），
        # 到点 / 快捷键两本画同类的小图标。这里先把 exe → 完整路径 攒起来。
        self._icons = QFileIconProvider()
        self._paths = {}
        if kind == "apptime":
            for exe, _label, path in self.apps:
                if exe and path:
                    self._paths.setdefault(exe.lower(), path)
            try:
                for exe, path in running_processes():
                    if exe and path:            # 正在跑的一般都能拿到真路径
                        self._paths.setdefault(exe.lower(), path)
            except Exception:
                pass
        title, tip = self.KINDS.get(kind, ("自动说话", ""))
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(560, 520)

        lay = QVBoxLayout(self)
        head = QLabel(tip)
        head.setWordWrap(True)
        lay.addWidget(head)
        self.tip = QLabel("")
        self.tip.setWordWrap(True)
        self.tip.setObjectName("dim")
        lay.addWidget(self.tip)

        self.listw = QListWidget()
        self.listw.setIconSize(QSize(24, 24))
        lay.addWidget(self.listw, 1)

        row = QHBoxLayout()
        self.add_btn = QPushButton("添加")
        self.edit_btn = QPushButton("编辑")
        self.del_btn = QPushButton("删除")
        self.try_btn = QPushButton("预览")
        close_btn = QPushButton("关闭")
        for btn in (self.add_btn, self.edit_btn, self.del_btn, self.try_btn):
            row.addWidget(btn)
        row.addStretch(1)
        row.addWidget(close_btn)
        lay.addLayout(row)

        self.add_btn.clicked.connect(lambda: self._edit(None))
        self.edit_btn.clicked.connect(lambda: self._edit(self._current()))
        self.del_btn.clicked.connect(self._delete)
        self.try_btn.clicked.connect(self._try)
        close_btn.clicked.connect(self.accept)
        self.listw.itemDoubleClicked.connect(lambda _i: self._edit(self._current()))
        self.listw.currentItemChanged.connect(lambda *_: self._sync_buttons())
        self._fill()

    # ---------- 规则的读写（都走桌宠那边的接口）----------
    def _entries(self):
        """[(键, 规则)]。apptime 的键是 exe 名，另外两种是规则的 id。"""
        if self.kind == "apptime":
            return [(exe, dict(rule))
                    for exe, rule in (self.owner.app_time_rules() or {}).items()]
        rules = (self.owner.clock_rules() if self.kind == "clock"
                 else self.owner.hotkey_rules())
        out = []
        for i, rule in enumerate(rules or []):
            item = dict(rule)
            item["id"] = item.get("id") or f"auto-{i}"
            out.append((item["id"], item))
        return out

    def _store(self, entries):
        if self.kind == "apptime":
            box = {}
            for key, rule in entries:
                if key:
                    box[key] = rule
            self.owner.set_app_time_rules(box)
        elif self.kind == "clock":
            self.owner.set_clock_rules([rule for _key, rule in entries])
        else:
            self.owner.set_hotkey_rules([rule for _key, rule in entries])
        self.owner.save_config()

    def _new_id(self, prefix):
        return f"{prefix}-{int(time.time() * 1000) % 100000000}"

    @staticmethod
    def _exe_from_text(text):
        """下拉里选的是「微信（wechat.exe）」这种写法，也可能直接手敲一个 exe 名。"""
        text = (text or "").strip()
        if text.endswith("）") and "（" in text:
            text = text.rsplit("（", 1)[1][:-1]
        elif text.endswith(")") and "(" in text:
            text = text.rsplit("(", 1)[1][:-1]
        return text.strip().lower()

    def _app_choices(self):
        """[(exe, 显示文字)]：已经配过的 + 扫到的应用。"""
        items, seen = [], set()
        for exe, _rule in self._entries():
            exe = (exe or "").lower()
            if exe and exe not in seen:
                seen.add(exe)
                items.append((exe, exe))
        for exe, label, _path in self.apps:
            exe = (exe or "").lower()
            if exe and exe not in seen:
                seen.add(exe)
                items.append((exe, f"{label}（{exe}）"))
        return items

    # ---------- 列表 ----------
    def _row_icon(self, key, rule):
        """列表项前面那颗图标。

        用久了那本：exe 的**真图标**（规则里记着路径 → 扫到的路径 → 注册表 App Paths），
        都找不到才退成一张通用文件图标。另外两本给个同类的小图标（钟 / 键盘）。
        """
        if self.kind != "apptime":
            name = "page.clock" if self.kind == "clock" else "ui.keyboard"
            try:
                color = (ui_console.tokens().get("text_dim", "#7b8093")
                         if ui_console else "#7b8093")
                return ui_console.icon(name, color, 18) if ui_console else None
            except Exception:
                return None
        exe = (key or "").lower()
        path = rule.get("path") or self._paths.get(exe)
        if not path and exe:                    # 没在跑、也不在开始菜单里：查注册表
            path = app_path_for(exe)
            if path:
                self._paths[exe] = path
        try:
            if path and os.path.exists(path):
                icon = self._icons.icon(QFileInfo(path))
                if not icon.isNull():
                    return icon
        except Exception:
            pass
        try:
            return self._icons.icon(QFileIconProvider.IconType.File)
        except Exception:
            return None

    def _label(self, key, rule):
        lines = [str(t) for t in (rule.get("lines") or []) if str(t).strip()]
        if self.kind == "apptime":
            head = f"{key}：连续使用 {int(rule.get('minutes') or 60)} 分钟"
            repeat = int(rule.get("repeat") or 0)
            if repeat:
                head += f"，之后每 {repeat} 分钟重复"
        elif self.kind == "clock":
            when = (rule.get("when") or "daily").lower()
            if when == "interval":
                head = f"每隔 {int(rule.get('every') or 60)} 分钟"
            elif when == "weekly":
                days = "、".join(WEEKDAY_NAMES[d] for d in sorted(rule.get("days") or [])
                                 if isinstance(d, int) and 0 <= d < 7)
                head = f"每周 {days or '（未选择星期）'} {rule.get('time') or ''}"
            else:
                head = f"每天 {rule.get('time') or ''}"
            if rule.get("summary"):
                head += "（含今日汇总）"
        else:
            head = rule.get("seq") or "（未设置按键）"
            act = rule.get("act") or "lines"
            if act != "lines":
                head += f"（{dict(HOTKEY_ACTS).get(act, act)}）"
        if not rule.get("on", True):
            head = "（已停用）" + head
        if not lines:
            tail = ("（无附加文字）" if self.kind == "hotkey"
                    and (rule.get("act") or "lines") != "lines" else "（未填写文字）")
        else:
            tail = lines[0]
        return f"{head} —— {tail}"

    def _fill(self):
        keep = None
        cur = self._current()
        if cur:
            keep = cur[0]
        self.listw.clear()
        for key, rule in self._entries():
            item = QListWidgetItem(self._label(key, rule))
            item.setData(Qt.ItemDataRole.UserRole, key)
            icon = self._row_icon(key, rule)
            if icon is not None:
                item.setIcon(icon)
            self.listw.addItem(item)
        if self.listw.count():
            row = self.listw.count() - 1
            for i in range(self.listw.count()):
                if self.listw.item(i).data(Qt.ItemDataRole.UserRole) == keep:
                    row = i
                    break
            self.listw.setCurrentRow(row)
        self._sync_buttons()

    def _sync_buttons(self):
        has = self._current() is not None
        for btn in (self.edit_btn, self.del_btn, self.try_btn):
            btn.setEnabled(has)

    def _current(self):
        item = self.listw.currentItem()
        if item is None:
            return None
        key = item.data(Qt.ItemDataRole.UserRole)
        for k, rule in self._entries():
            if k == key:
                return (k, rule)
        return None

    def _delete(self):
        cur = self._current()
        if not cur:
            return
        key, rule = cur
        what = self._label(key, rule).split(" —— ")[0]
        yes = QMessageBox.question(
            self, "删除", f"删掉这一条？\n{what}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if yes != QMessageBox.StandardButton.Yes:
            return
        self._store([(k, r) for k, r in self._entries() if k != key])
        self.tip.setText(f"已经删掉：{what}")
        self._fill()

    def _try(self):
        cur = self._current()
        if not cur:
            return
        if self.kind == "hotkey" and (cur[1].get("act") or "lines") != "lines":
            self.tip.setText("这一条是动作快捷键，真按下去才看得到效果")
            return
        lines = [str(t) for t in (cur[1].get("lines") or []) if str(t).strip()]
        if not lines:
            self.tip.setText("这条还没有提示文字，先点「编辑」填写")
            return
        self.owner.say(random.choice(lines), again=True, seconds=3.2)

    # ---------- 编辑一条 ----------
    def _edit(self, cur):
        from PySide6.QtCore import QTime
        from PySide6.QtWidgets import (QPlainTextEdit, QSpinBox, QTimeEdit,
                                       QCheckBox, QKeySequenceEdit)
        rule = dict(cur[1]) if cur else {}
        old_key = cur[0] if cur else None
        is_new = cur is None
        title = self.KINDS.get(self.kind, ("自动说话", ""))[0]
        dlg = QDialog(self)
        dlg.setWindowTitle(("添加 · " if is_new else "修改 · ") + title)
        if ui_console:
            ui_console.style_dialog(dlg, BUNDLE_DIR)
        dlg.resize(460, 430)
        lay = QVBoxLayout(dlg)
        box = {}                      # 各种控件，保存时统一读

        if self.kind == "apptime":
            row = QHBoxLayout()
            row.addWidget(QLabel("应用："))
            combo = QComboBox()
            combo.setEditable(True)
            for exe, text in self._app_choices():
                combo.addItem(text, exe)
            want = (old_key or "").lower()
            if want:
                idx = combo.findData(want)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                else:
                    combo.setEditText(want)
            row.addWidget(combo, 1)
            lay.addLayout(row)
            box["exe"] = combo
            hint = QLabel("列表为已配置与本机扫描到的应用，也可直接输入进程名（例如 notepad.exe）。\n"
                          "提示文字支持 {app}（应用名）、{minutes}（分钟数）、{hm}（小时分钟）。")
            hint.setWordWrap(True)
            hint.setObjectName("dim")
            lay.addWidget(hint)

            row2 = QHBoxLayout()
            row2.addWidget(QLabel("连续使用："))
            spin = QSpinBox()
            spin.setRange(1, 600)
            spin.setSuffix(" 分钟")
            spin.setValue(int(rule.get("minutes") or 60))
            row2.addWidget(spin)
            row2.addSpacing(12)
            row2.addWidget(QLabel("重复间隔："))
            rep = QSpinBox()
            rep.setRange(0, 600)
            rep.setSuffix(" 分钟")
            rep.setSpecialValueText("不再提醒")
            rep.setValue(int(rule.get("repeat") or 0))
            row2.addWidget(rep)
            row2.addStretch(1)
            lay.addLayout(row2)
            box["minutes"], box["repeat"] = spin, rep

        elif self.kind == "clock":
            row = QHBoxLayout()
            row.addWidget(QLabel("触发方式："))
            mode = QComboBox()
            mode.addItem("每天这个点", "daily")
            mode.addItem("每周选几天", "weekly")
            mode.addItem("每隔一段时间", "interval")
            when = (rule.get("when") or "daily").lower()
            idx = mode.findData(when)
            mode.setCurrentIndex(idx if idx >= 0 else 0)
            row.addWidget(mode, 1)
            row.addWidget(QLabel("时刻："))
            edit_time = QTimeEdit()
            edit_time.setDisplayFormat("HH:mm")
            hh, mm = 23, 30
            try:
                hh, mm = [int(x) for x in (rule.get("time") or "23:30").split(":")[:2]]
            except Exception:
                pass
            edit_time.setTime(QTime(hh % 24, max(0, min(59, mm))))
            row.addWidget(edit_time)
            lay.addLayout(row)
            box["when"], box["time"] = mode, edit_time

            days_row = QWidget()
            days_lay = QHBoxLayout(days_row)
            days_lay.setContentsMargins(0, 0, 0, 0)
            days_lay.addWidget(QLabel("哪几天："))
            day_boxes = []
            chosen = set(rule.get("days") or [])
            for i, name in enumerate(WEEKDAY_NAMES):
                cb = QCheckBox(name)
                cb.setChecked(i in chosen)
                days_lay.addWidget(cb)
                day_boxes.append(cb)
            days_lay.addStretch(1)
            lay.addWidget(days_row)
            box["days"] = day_boxes

            every_row = QWidget()
            every_lay = QHBoxLayout(every_row)
            every_lay.setContentsMargins(0, 0, 0, 0)
            every_lay.addWidget(QLabel("每隔："))
            every = QSpinBox()
            every.setRange(1, 1440)
            every.setSuffix(" 分钟")
            every.setValue(int(rule.get("every") or 60))
            every_lay.addWidget(every)
            every_lay.addStretch(1)
            lay.addWidget(every_row)
            box["every"] = every

            sum_box = QCheckBox("先说「今日汇总」（余额用量 + 使用时长最长的应用）")
            sum_box.setChecked(bool(rule.get("summary")))
            lay.addWidget(sum_box)
            box["summary"] = sum_box

            def sync_clock_rows(_=None):
                kind_now = mode.currentData()
                days_row.setVisible(kind_now == "weekly")
                every_row.setVisible(kind_now == "interval")
                edit_time.setVisible(kind_now != "interval")

            mode.currentIndexChanged.connect(sync_clock_rows)
            sync_clock_rows()

        else:
            row = QHBoxLayout()
            row.addWidget(QLabel("按键："))
            seq = QKeySequenceEdit()
            if rule.get("seq"):
                seq.setKeySequence(QKeySequence(rule["seq"]))
            row.addWidget(seq, 1)
            lay.addLayout(row)
            box["seq"] = seq
            hint = QLabel(hotkey_supported_hint()
                          + "（点一下右边的框，然后直接按你要的组合键）")
            hint.setWordWrap(True)
            hint.setObjectName("dim")
            lay.addWidget(hint)
            act_row = QHBoxLayout()
            act_row.addWidget(QLabel("触发动作："))
            act_box = QComboBox()
            for value, label in HOTKEY_ACTS:
                act_box.addItem(label, value)
            ai = act_box.findData(rule.get("act") or "lines")
            act_box.setCurrentIndex(ai if ai >= 0 else 0)
            act_row.addWidget(act_box, 1)
            lay.addLayout(act_row)
            box["act"] = act_box

        line_title = QLabel("提示文字（一行一条）：")
        lay.addWidget(line_title)
        edit = QPlainTextEdit()
        edit.setPlainText("\n".join(str(t) for t in (rule.get("lines") or [])))
        lay.addWidget(edit, 1)
        box["lines"] = edit
        if self.kind == "hotkey":
            def sync_act(_=None):
                says = (box["act"].currentData() or "lines") == "lines"
                line_title.setText("提示文字（一行一条）：" if says
                                   else "附加文字（可留空）：")
            box["act"].currentIndexChanged.connect(sync_act)
            sync_act()

        on_box = QCheckBox("启用这一条")
        on_box.setChecked(bool(rule.get("on", True)))
        lay.addWidget(on_box)

        btns = QHBoxLayout()
        btns.addStretch(1)
        ok_btn = QPushButton("保存")
        ok_btn.setObjectName("primary")
        cancel_btn = QPushButton("取消")
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        lay.addLayout(btns)

        result = {}

        def save():
            lines = [t.strip() for t in box["lines"].toPlainText().splitlines() if t.strip()]
            if self.kind != "hotkey" and not lines:
                QMessageBox.information(dlg, "缺少提示文字", "至少填写一条提示文字。",
                                        QMessageBox.StandardButton.Ok)
                return
            item = {"on": on_box.isChecked(), "lines": lines}
            if self.kind == "apptime":
                exe = self._exe_from_text(box["exe"].currentText())
                if not exe:
                    QMessageBox.information(dlg, "未选择应用",
                                            "请选择一个应用，或输入进程名。",
                                            QMessageBox.StandardButton.Ok)
                    return
                item["exe"] = exe
                item["minutes"] = int(box["minutes"].value())
                item["repeat"] = int(box["repeat"].value())
                # 顺手把 exe 的完整路径记下来：下次打开这本列表不用再找一遍就能画图标
                item["path"] = self._paths.get(exe) or rule.get("path") or ""
                result["key"] = exe
            elif self.kind == "clock":
                when = box["when"].currentData()
                item["when"] = when
                item["time"] = box["time"].time().toString("HH:mm")
                item["days"] = [i for i, cb in enumerate(box["days"]) if cb.isChecked()]
                item["every"] = int(box["every"].value())
                item["summary"] = bool(box["summary"].isChecked())
                if when == "weekly" and not item["days"]:
                    QMessageBox.information(dlg, "还没选星期", "「每周选几天」至少要勾一天。",
                                            QMessageBox.StandardButton.Ok)
                    return
                item["id"] = (rule.get("id") if not is_new else None) or self._new_id("t")
                result["key"] = item["id"]
            else:
                text = box["seq"].keySequence().toString()
                if not text or hotkey_parse(text) is None:
                    QMessageBox.information(
                        dlg, "不支持的按键",
                        hotkey_supported_hint() + "\n（例如 Ctrl+Alt+1、Ctrl+Shift+F9）",
                        QMessageBox.StandardButton.Ok)
                    return
                act = box["act"].currentData() or "lines"
                if act == "lines" and not lines:
                    QMessageBox.information(dlg, "缺少提示文字",
                                            "动作选「说一句」时，至少填写一条提示文字。",
                                            QMessageBox.StandardButton.Ok)
                    return
                item["act"] = act
                item["seq"] = text
                item["id"] = (rule.get("id") if not is_new else None) or self._new_id("hk")
                result["key"] = item["id"]
            result["rule"] = item
            dlg.accept()

        ok_btn.clicked.connect(save)
        cancel_btn.clicked.connect(dlg.reject)
        if dlg.exec() != QDialog.DialogCode.Accepted or "rule" not in result:
            return
        entries = [(k, r) for k, r in self._entries() if k != old_key]
        entries.append((result["key"], result["rule"]))
        self._store(entries)
        self._fill()
        if self.kind == "hotkey":
            bad = self.owner.hotkey_failed_texts()
            self.tip.setText("快捷键已生效，按一下试试"
                             + (f"（这几个被别的程序占用了，按不出来：{'、'.join(bad)}）"
                                if bad else ""))
        else:
            self.tip.setText("存好啦，马上生效")


SKIN_KIND_LABELS = {"pet": "三维形象", "widget": "挂件形象"}
# 三维形象的三个槽位（挂件只有一个）
PET_SLOTS = ("front", "side", "back")


class SkinEditDialog(QDialog):
    """上传 / 编辑一个形象：三维的挑三张，挂件的挑一张。

    规矩是主人定的：**三维形象要把正面 / 侧面 / 背面三张照片都挑齐了才算一个形象**
    （少一张不给保存、也不会收录）；名字在这个窗口里起，
    「原图别删、别挪」的提醒也写在这个窗口里。
    """

    SLOTS = {"pet": PET_SLOTS, "widget": ("widget",)}

    def __init__(self, owner, kind, entry=None, prefill=None):
        super().__init__(None)
        if ui_console:                      # 跟设置窗口用同一套配色
            ui_console.style_dialog(self, BUNDLE_DIR)
        self.owner = owner
        self.kind = kind if kind in self.SLOTS else "widget"
        self.entry = dict(entry) if entry else None
        src = self.entry or prefill or {}
        self.slots = {}
        for view in self.SLOTS[self.kind]:
            self.slots[view] = str(src.get("path" if view == "widget" else view) or "")
        self.result_data = None
        self.setWindowTitle(("编辑" if self.entry else "上传") + SKIN_KIND_LABELS[self.kind])
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(580, 340 if self.kind == "pet" else 250)

        lay = QVBoxLayout(self)
        tip = QLabel(
            "三维形象要 正面 / 侧面 / 背面 三张都挑齐了才会收录成一个形象"
            "（先挑哪张都行，点「保存」才算数）。"
            if self.kind == "pet" else
            "挂件形象就一张图（PNG 这类带透明背景的最好看）。")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("名字："))
        self.name_edit = QLineEdit(str(src.get("name") or ""))
        self.name_edit.setPlaceholderText("给这个形象起个名字（挑完图会自动填文件名）")
        name_row.addWidget(self.name_edit, 1)
        lay.addLayout(name_row)

        self.slot_widgets = {}
        for view in self.SLOTS[self.kind]:
            line = QHBoxLayout()
            cap = QLabel(VIEW_LABELS.get(view, view))
            cap.setFixedWidth(150)
            line.addWidget(cap)
            shot = QLabel("（还没选）")
            shot.setFixedSize(76, 76)
            shot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            shot.setObjectName("thumb")
            line.addWidget(shot)
            path_lb = QLabel("")
            path_lb.setWordWrap(True)
            path_lb.setObjectName("dim")
            line.addWidget(path_lb, 1)
            pick = QPushButton("选图片…")
            pick.clicked.connect(lambda _=False, vv=view: self._pick(vv))
            line.addWidget(pick)
            lay.addLayout(line)
            self.slot_widgets[view] = (shot, path_lb)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        warn = QLabel(
            "⚠ 记住两点（桌宠记的是原图在硬盘上的位置，不会复制走）：\n"
            "　· 别把源文件删掉；\n"
            "　· 别改它的路径 —— 改名、挪文件夹、换盘都会让桌宠找不到。\n"
            "真找不到时，「我的形象库…」里点「换图…」重新指一张就行。")
        warn.setWordWrap(True)
        warn.setObjectName("warnText")
        lay.addWidget(warn)

        btns = QHBoxLayout()
        self.save_btn = QPushButton("保存")
        cancel_btn = QPushButton("取消")
        # 对话框按钮也配同一套小图标（颜色按对话框自己的主题算，每次建窗口都现算）
        if ui_console is not None:
            try:
                fg = ui_console.tokens()["text"]      # 保存键是普通按钮，配正文色
                self.save_btn.setIconSize(QSize(16, 16))
                self.save_btn.setIcon(ui_console.icon("ui.save", fg, 16))
            except Exception:
                pass
        btns.addStretch(1)
        btns.addWidget(self.save_btn)
        btns.addWidget(cancel_btn)
        lay.addLayout(btns)

        self.save_btn.clicked.connect(self._save)
        cancel_btn.clicked.connect(self.reject)
        self.name_edit.textChanged.connect(lambda *_: self._refresh())
        self._refresh()

    def _pick(self, view):
        path, _ok = QFileDialog.getOpenFileName(
            self, f"选{VIEW_LABELS.get(view, view)}那张图", self.owner._skin_pick_dir(),
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp *.gif)",
            options=QFileDialog.Option.DontUseNativeDialog)
        if not path:
            return
        if QPixmap(path).isNull():
            self.owner.say("这张图读不了，换一张试试")
            return
        self.slots[view] = path
        self.owner.cfg["skin_pick_dir"] = os.path.dirname(path)
        if not self.name_edit.text().strip():
            self.name_edit.setText(os.path.splitext(os.path.basename(path))[0] or "我的形象")
        self._refresh()

    def missing(self):
        """还差哪几张（没选 / 文件不在了）。"""
        return [v for v in self.SLOTS[self.kind]
                if not self.slots.get(v) or not os.path.exists(self.slots.get(v))]

    def _refresh(self):
        need = self.missing()
        for view, (shot, path_lb) in self.slot_widgets.items():
            path = self.slots.get(view) or ""
            if path and os.path.exists(path):
                pix = QPixmap(path)
                shot.setText("（读不了）" if pix.isNull() else "")
                shot.setPixmap(QPixmap() if pix.isNull() else pix.scaled(
                    76, 76, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
                path_lb.setText(f"{os.path.basename(path)}\n{os.path.dirname(path)}")
            else:
                shot.setPixmap(QPixmap())
                shot.setText("（还没选）" if not path else "（文件不在了）")
                path_lb.setText("还没挑图" if not path else f"{os.path.basename(path)}\n找不到了")
        if need:
            tail = "（三张齐了才能保存）" if self.kind == "pet" else ""
            self.status.setText("还差：" + "、".join(VIEW_SHORT[v] for v in need) + tail)
            self.status.setStyleSheet(f"color:{theme_color('warn', '#c9770f')};")
        elif not self.name_edit.text().strip():
            self.status.setText("图齐了，再起个名字就能保存")
            self.status.setStyleSheet(f"color:{theme_color('warn', '#c9770f')};")
        else:
            self.status.setText("齐了，可以保存 ✓")
            self.status.setStyleSheet(f"color:{theme_color('ok', '#2e9e5b')};")
        self.save_btn.setEnabled(not need and bool(self.name_edit.text().strip()))

    def _save(self):
        name = self.name_edit.text().strip()[:24]
        if self.missing() or not name:
            self._refresh()
            return
        self.result_data = {"name": name, "paths": dict(self.slots)}
        self.accept()


class SkinLibraryDialog(QDialog):
    """我的形象库：两本分开 —— 三维形象（三视图）/ 挂件形象（单张），上面切换。

    三维形象 = 正面 / 侧面 / 背面三张图（**列表和预览默认显示正面那张**），三张齐了才算一个形象；
    挂件形象 = 一张 cut-out。上传、换图、改名、从库里删掉全在这个窗口里（主人要求：两个库 + 上传整合到一起）。
    桌宠只记原图在硬盘上的路径、不复制文件：别删原图、也别挪位置。
    """

    def __init__(self, owner, kind="pet"):
        super().__init__(None)
        if ui_console:                      # 跟设置窗口用同一套配色
            ui_console.style_dialog(self, BUNDLE_DIR)
        self.owner = owner
        self.kind = kind if kind in ("pet", "widget") else "pet"
        self.setWindowTitle("我的形象库")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(720, 520)

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("看哪一本："))
        self.kind_box = QComboBox()
        self.kind_box.addItem("三维形象（三视图）", "pet")
        self.kind_box.addItem("挂件形象（单张）", "widget")
        self.kind_box.setCurrentIndex(0 if self.kind == "pet" else 1)
        self.kind_box.currentIndexChanged.connect(self._kind_changed)
        top.addWidget(self.kind_box, 1)
        lay.addLayout(top)
        self.tip = QLabel()
        self.tip.setWordWrap(True)
        lay.addWidget(self.tip)

        body = QHBoxLayout()
        self.listw = QListWidget()
        self.listw.setIconSize(QSize(56, 56))
        self.listw.setMinimumWidth(260)
        body.addWidget(self.listw, 1)

        right = QVBoxLayout()
        self.preview = QLabel("（选一张看看）")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(230, 165)
        self.preview.setObjectName("preview")
        right.addWidget(self.preview, 1)
        # 这本空着的时候，预览那块地方换成"插图 + 该干嘛"（不是只丢一句灰字）
        self.empty_mark = None
        if ui_console is not None:
            try:
                self.empty_mark = ui_console.EmptyState(
                    "empty.skin", "这本还空着",
                    "点下面的「上传新形象…」加一个", size=64)
                self.empty_mark.setVisible(False)
                right.addWidget(self.empty_mark, 1)
            except Exception:
                self.empty_mark = None
        # 三维形象：三张小图并排（正面 / 侧面 / 背面），一眼看出哪张缺
        self.slot_box = QWidget()
        slot_row = QHBoxLayout(self.slot_box)
        slot_row.setContentsMargins(0, 0, 0, 0)
        self.slot_shots = {}
        for view in PET_SLOTS:
            cell = QVBoxLayout()
            shot = QLabel("（缺）")
            shot.setFixedSize(76, 76)
            shot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            shot.setObjectName("thumb")
            cap = QLabel(VIEW_SHORT[view])
            cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cap.setObjectName("dim")
            cell.addWidget(shot)
            cell.addWidget(cap)
            self.slot_shots[view] = shot
            slot_row.addLayout(cell)
        right.addWidget(self.slot_box)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.info.setObjectName("dim")
        right.addWidget(self.info)

        row1 = QHBoxLayout()
        self.use_btn = QPushButton("用这个形象")
        row1.addWidget(self.use_btn)
        row1.addStretch(1)
        # 只把"这一本"正用着的自定义形象退回自带的（库里的条目都留着，随时能再用）
        self.restore_btn = QPushButton("这套恢复默认")
        row1.addWidget(self.restore_btn)
        right.addLayout(row1)

        row2 = QHBoxLayout()
        self.edit_btn = QPushButton("换图…")
        self.rename_btn = QPushButton("改名…")
        self.del_btn = QPushButton("从库里删掉")
        for b in (self.edit_btn, self.rename_btn, self.del_btn):
            row2.addWidget(b)
        right.addLayout(row2)
        body.addLayout(right, 1)
        lay.addLayout(body, 1)

        bottom = QHBoxLayout()
        self.add_btn = QPushButton("上传新形象…")
        close_btn = QPushButton("关闭")
        bottom.addWidget(self.add_btn)
        bottom.addStretch(1)
        bottom.addWidget(close_btn)
        lay.addLayout(bottom)

        self.add_btn.clicked.connect(self._upload)
        self.use_btn.clicked.connect(self._double_clicked)
        self.restore_btn.clicked.connect(self._restore)
        self.edit_btn.clicked.connect(self._edit)
        self.rename_btn.clicked.connect(self._rename)
        self.del_btn.clicked.connect(self._remove)
        close_btn.clicked.connect(self.accept)
        self.listw.currentItemChanged.connect(lambda *_: self._show_detail())
        self.listw.itemDoubleClicked.connect(self._double_clicked)
        self._refresh()

    # ---------- 列表 ----------
    def _kind_changed(self, _index=None):
        self.kind = self.kind_box.currentData() or "pet"
        self._refresh()

    def _refresh(self):
        """重新读一遍这一本形象库（换本 / 改名 / 换图 / 删掉之后都走这儿）。"""
        self.slot_box.setVisible(self.kind == "pet")
        self.kind_box.blockSignals(True)
        self.kind_box.setItemText(0, f"三维形象（三视图）·  {len(self.owner.skin_library('pet'))} 个")
        self.kind_box.setItemText(
            1, f"挂件形象（单张）·  {len(self.owner.skin_library('widget'))} 个")
        self.kind_box.blockSignals(False)
        keep = self._current_id()
        self.listw.blockSignals(True)
        self.listw.clear()
        for ent in self.owner.skin_library(self.kind):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, ent["id"])
            self._decorate(item, ent)
            self.listw.addItem(item)
        self.listw.blockSignals(False)
        row = 0
        for i in range(self.listw.count()):
            if self.listw.item(i).data(Qt.ItemDataRole.UserRole) == keep:
                row = i
                break
        if self.listw.count():
            self.listw.setCurrentRow(row)
        self._show_detail()

    def _decorate(self, item, ent):
        badges = []
        if self.owner.skin_in_use(self.kind, ent["id"]):
            badges.append("正在用")
        missing = self.owner.skin_missing_views(self.kind, ent)
        if missing:
            badges.append("⚠ " + "、".join(VIEW_SHORT[v] for v in missing) + "那张找不到了")
        item.setText(ent["name"] + ("　" + "　".join(badges) if badges else ""))
        thumb = self.owner.skin_thumb_path(self.kind, ent)     # 三维默认拿正面那张当图标
        pix = QPixmap(thumb) if thumb else QPixmap()
        if not pix.isNull():
            item.setIcon(QIcon(pix.scaled(56, 56, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation)))
        if item.icon().isNull():
            item.setIcon(QFileIconProvider().icon(QFileIconProvider.IconType.File))

    def _current_id(self):
        item = self.listw.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _current_entry(self):
        sid = self._current_id()
        return self.owner.skin_entry(self.kind, sid) if sid else None

    def _show_detail(self):
        ent = self._current_entry()
        if ent is None:
            if self.empty_mark is not None:
                self.empty_mark.setVisible(True)
            self.preview.setVisible(False)
            self.tip.setText(
                ("这本还空着。点下面的「上传新形象…」把正面 / 侧面 / 背面三张图都挑齐，"
                 "起个名字就收录成一个三维形象（列表和预览显示的是正面那张）。")
                if self.kind == "pet" else
                "这本还空着。点下面的「上传新形象…」挑一张图、起个名字就行"
                "（PNG 这类带透明背景的最好看）。")
            if self.empty_mark is not None:
                self.empty_mark.set_text(
                    "这本还空着",
                    "点下面的「上传新形象…」挑三张（正面 / 侧面 / 背面）"
                    if self.kind == "pet" else
                    "点下面的「上传新形象…」挑一张（带透明背景的最好）")
            self.info.setText("")
            for shot in self.slot_shots.values():
                shot.setPixmap(QPixmap())
                shot.setText("（缺）")
            self._enable(False)
            return
        if self.empty_mark is not None:
            self.empty_mark.setVisible(False)
        self.preview.setVisible(True)
        missing = self.owner.skin_missing_views(self.kind, ent)
        self.tip.setText(
            ("三张图齐了才算一个三维形象；下面显示的是正面那张，点「用这个形象」整套换上。\n"
             if self.kind == "pet" else "挑一个，点「用这个形象」就换上了。\n")
            + "桌宠只记【原图在硬盘上的位置】、不复制文件：别删它、也别挪地方；"
              "真挪了就点「换图…」重新指过去；只想退回自带的，点「这套恢复默认」（库里的还留着）。")
        made = ent["added"] or "（早期上传的，没记时间）"
        info = [f"名字：{ent['name']}", f"收进库的时间：{made}",
                "正在用：这本的当前形象" if self.owner.skin_in_use(self.kind, ent["id"])
                else "现在还没用上"]
        for view in (PET_SLOTS if self.kind == "pet" else ("widget",)):
            path = self.owner.skin_view_path(self.kind, ent, view)
            if view in missing:                 # 找不到的才把完整路径摊出来（方便照着找）
                info.append(f"⚠ {VIEW_SHORT[view]}：{path}\n　　（这个位置已经没有文件了）")
            else:
                info.append(f"{VIEW_SHORT[view]}：{os.path.basename(path)}")
        self.info.setText("\n".join(info))

        for view in PET_SLOTS:                      # 三张小图：缺哪张一眼看出来
            path = ent.get(view) or ""
            shot = self.slot_shots[view]
            pix = QPixmap(path) if (path and os.path.exists(path)) else QPixmap()
            shot.setText("" if not pix.isNull() else ("（缺）" if not path else "（不在了）"))
            shot.setPixmap(QPixmap() if pix.isNull() else pix.scaled(
                76, 76, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        main = self.owner.skin_thumb_path(self.kind, ent)   # 三维 = 正面那张
        pix = QPixmap(main) if main else QPixmap()
        if pix.isNull():
            self.preview.setPixmap(QPixmap())
            self.preview.setText("（文件找不到了\n点「换图…」重新指一张）")
        else:
            self.preview.setText("")
            self.preview.setPixmap(pix.scaled(250, 170, Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation))
        self._enable(True, not missing)

    def _enable(self, has_entry, exists=False):
        self.use_btn.setEnabled(bool(has_entry and exists))
        self.edit_btn.setEnabled(bool(has_entry))
        self.rename_btn.setEnabled(bool(has_entry))
        self.del_btn.setEnabled(bool(has_entry))
        # 「这套恢复默认」只看"这一本现在是不是自定义的"，跟选中哪条无关
        in_use = bool(self.owner._current_skin_ref(self.kind))
        self.restore_btn.setEnabled(in_use)
        self.restore_btn.setToolTip(
            "把这一本正用着的自定义形象退回自带的（库里的条目都留着，随时能再挑回来）"
            if in_use else "这一本现在用的就是自带的形象")

    # ---------- 按钮 ----------
    def _restore(self):
        """只把这一本（三维 / 挂件）恢复成自带形象，不动另一本、也不动库。"""
        self.owner.clear_custom_skin(self.kind)
        self._refresh()

    def _apply(self):
        ent = self._current_entry()
        if ent is None:
            return
        if self.owner.apply_skin(self.kind, ent["id"], parent=self):
            self._refresh()

    def _double_clicked(self, _item):
        self._apply()

    def _upload(self):
        if self.owner.upload_skin(self.kind, parent=self) is not None:
            self._refresh()

    def _edit(self):
        ent = self._current_entry()
        if ent is not None and self.owner.edit_skin(self.kind, ent["id"], parent=self) is not None:
            self._refresh()

    def _rename(self):
        ent = self._current_entry()
        if ent is not None and self.owner.rename_skin(self.kind, ent["id"], parent=self):
            self._refresh()

    def _remove(self):
        ent = self._current_entry()
        if ent is not None and self.owner.remove_skin(self.kind, ent["id"], parent=self):
            self._refresh()


def is_peak(ts=None):
    """高峰时段：工作日 9:00-12:00 与 14:00-18:00；周末（自 2026-08-23 起）全天谷价。"""
    dt = datetime.fromtimestamp(ts if ts is not None else time.time())
    if dt >= WEEKEND_VALLEY_FROM and dt.weekday() >= 5:
        return False
    return 9 <= dt.hour < 12 or 14 <= dt.hour < 18


# 峰谷提示文案（学原挂件的三档：默认 / 梁文峰谷 / !?强强?!）
PEAK_TEXT_STYLES = {
    "默认": ("高峰时段", "空闲时段"),
    "梁文峰谷": ("梁文·峰", "梁文·谷"),
    "!?强强?!": ("!?强强?!", "…弱弱…"),
}


def peak_label(peak, style="默认"):
    """当前时段的显示文案。"""
    hi, lo = PEAK_TEXT_STYLES.get(style) or PEAK_TEXT_STYLES["默认"]
    return hi if peak else lo


def usage_cost(usage):
    """按峰谷定价把一次对话的 usage 换算成金额，返回 (金额, 总token)。"""
    if not usage:
        return 0.0, 0
    hit = int(usage.get("prompt_cache_hit_tokens", 0) or 0)
    miss = usage.get("prompt_cache_miss_tokens")
    if miss is None:
        miss = max(0, int(usage.get("prompt_tokens", 0) or 0) - hit)
    miss = int(miss or 0)
    out = int(usage.get("completion_tokens", 0) or 0)
    price = PRO_PRICE if is_peak() else BASE_PRICE
    amount = (hit / 1e6) * price["hit"] + (miss / 1e6) * price["miss"] + (out / 1e6) * price["out"]
    return amount, hit + miss + out


def codex_usage_cost(usage):
    """把 Codex 会话日志里的 token 用量换算成金额，返回 (金额, 总token)。"""
    if not usage:
        return 0.0, 0
    hit = int(usage.get("cached_input_tokens", 0) or 0)
    inp = int(usage.get("input_tokens", 0) or 0)
    miss = max(0, inp - hit)          # Codex 的 input_tokens 已包含 cached
    out = int(usage.get("output_tokens", 0) or 0)
    price = PRO_PRICE if is_peak() else BASE_PRICE
    amount = (hit / 1e6) * price["hit"] + (miss / 1e6) * price["miss"] + (out / 1e6) * price["out"]
    return amount, inp + out


def pick_balance_info(infos):
    """接口返回的多币种顺序不固定：优先 CNY 且余额 > 0，其次任意非零，再退回 CNY，最后取第一项。"""
    if not isinstance(infos, list) or not infos:
        return None

    def num(x):
        try:
            return float((x or {}).get("total_balance"))
        except (TypeError, ValueError):
            return float("nan")

    for want_cny, need_positive in ((True, True), (False, True), (True, False)):
        for x in infos:
            if not isinstance(x, dict):
                continue
            if want_cny and x.get("currency") != "CNY":
                continue
            v = num(x)
            if need_positive and not (v > 0):
                continue
            return x
    return infos[0]


def city_query_variants(name):
    """同一个地名可能有的叫法：原样 + 去掉末尾的"区 / 县"。

    中国天气网的库里是"鹿城"不是"鹿城区"，带上后缀就一条都搜不到
    （2026-09-14 实测 "鹿城区" 0 条、"鹿城" 命中 101210710）。
    """
    q = (name or "").strip()
    out = [q] if q else []
    if len(q) > 1 and q.endswith(("区", "县")):
        out.append(q[:-1])
    return out


def lookup_city(query):
    """联网查城市，返回候选列表 [(显示名, 存进配置的城市名)]。

    先走中国天气网（国内直连、中文库全，"温州 / 汕头"这种简称也认），
    查不到再退到 open-meteo（国外地名靠它兜底）。
    """
    q = (query or "").strip()
    if not q:
        return []
    items = []
    for variant in city_query_variants(q):
        try:
            for _code, name, prov in cn_city_search(variant)[:6]:
                if name not in [x[1] for x in items]:
                    items.append((f"{name}（{prov}）" if prov else name, name))
        except Exception:
            pass
        if items:
            break
    if not items:
        try:
            r = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                             params={"name": q, "count": 6, "language": "zh"}, timeout=8)
            for x in ((r.json() or {}).get("results") or []):
                label = x.get("name") or ""
                extra = " · ".join([v for v in (x.get("admin1"), x.get("country")) if v])
                if label:
                    items.append((f"{label}（{extra}）" if extra else label, label))
        except Exception:
            items = []
    if not items:
        items = [(q, q)]
    return items


def currency_symbol(currency):
    return {"CNY": "¥", "USD": "$", "EUR": "€"}.get((currency or "").upper(), "")


def query_deepseek_balance(key):
    """查 DeepSeek 余额，返回 {ok, total, currency, granted, topped_up} 或 {ok: False, error}。

    granted / topped_up 是接口给的「赠送余额 / 充值余额」，账本靠这两个字段认得出
    「赠送额度整块到期被收回」——那种下降不是用量。
    """
    last = "网络错误"
    for attempt in range(2):
        try:
            r = requests.get(BALANCE_URL, headers={"Authorization": f"Bearer {key}"}, timeout=15)
            if r.status_code == 200:
                info = pick_balance_info((r.json() or {}).get("balance_infos"))
                if info and info.get("total_balance") is not None:
                    def num(name):
                        try:
                            return float(info.get(name))
                        except (TypeError, ValueError):
                            return None

                    return {"ok": True, "total": float(info["total_balance"]),
                            "currency": info.get("currency") or "CNY",
                            "granted": num("granted_balance"),
                            "topped_up": num("topped_up_balance")}
                return {"ok": False, "error": "余额返回结构异常"}
            last = f"HTTP {r.status_code}"
            if r.status_code < 500:
                break
        except Exception as ex:
            last = str(ex)[:60]
        if attempt == 0:
            time.sleep(0.6)
    return {"ok": False, "error": last}


def query_openrouter_balance(key):
    """查 OpenRouter 额度（credits - usage）。"""
    try:
        r = requests.get(OPENROUTER_CREDITS_URL,
                         headers={"Authorization": f"Bearer {key}"}, timeout=15)
        if r.status_code != 200:
            return {"ok": False, "error": f"HTTP {r.status_code}"}
        data = (r.json() or {}).get("data") or {}
        total = float(data.get("total_credits") or 0)
        used = float(data.get("total_usage") or 0)
        return {"ok": True, "total": round(total - used, 4), "currency": "USD"}
    except Exception as ex:
        return {"ok": False, "error": str(ex)[:60]}


def extract_usage(obj, depth=0):
    """从任意 agent 的日志行里挖出 token 用量。

    Codex 的日志是 `payload.usage`，Claude Code 之类是 `message.usage`，键名也不一样
    （input_tokens / prompt_tokens、cached_input_tokens / cache_read_input_tokens）。
    这里递归找第一个带 token 字段的对象，并归一化成内部统一格式。
    """
    if depth > 6 or not isinstance(obj, (dict, list)):
        return None
    if isinstance(obj, dict):
        if any(k in obj for k in USAGE_TOKEN_KEYS):
            inp = obj.get("input_tokens")
            if inp is None:
                inp = obj.get("prompt_tokens")
            out = obj.get("output_tokens")
            if out is None:
                out = obj.get("completion_tokens")
            if isinstance(inp, (int, float)) or isinstance(out, (int, float)):
                inp = int(inp or 0)
                out = int(out or 0)
                hit = int(obj.get("cached_input_tokens")
                          or obj.get("cache_read_input_tokens") or 0)
                total = int(obj.get("total_tokens") or 0) or (inp + out)
                if inp or out:
                    return {"input_tokens": inp, "output_tokens": out,
                            "cached_input_tokens": hit, "total_tokens": total}
        for value in obj.values():
            got = extract_usage(value, depth + 1)
            if got:
                return got
    else:
        for value in obj:
            got = extract_usage(value, depth + 1)
            if got:
                return got
    return None


def scan_apps():
    """扫描本机应用：正在运行的进程 + 开始菜单里的快捷方式。

    返回 [(exe 名小写, 展示名, exe 完整路径)]，按展示名排序。
    路径是给对话框取图标用的（拿不到就是空串）。
    """
    apps = {}
    for name, path in running_processes():
        if name.endswith(".exe"):
            apps.setdefault(name, (name, path))
    # 开始菜单的快捷方式（含用户目录），交给 PowerShell 解析目标 exe
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        "$sh=New-Object -ComObject WScript.Shell;"
        "$dirs=@(\"$env:ProgramData\\Microsoft\\Windows\\Start Menu\\Programs\","
        "\"$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\");"
        "Get-ChildItem $dirs -Recurse -Filter *.lnk | ForEach-Object {"
        "$t=$sh.CreateShortcut($_.FullName).TargetPath;"
        "if($t){ \"$t|$($_.BaseName)\" } }"
    )
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                             capture_output=True, text=True, timeout=25,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for line in (out.stdout or "").splitlines():
            if "|" not in line:
                continue
            target, label = line.split("|", 1)
            target = target.strip()
            exe = os.path.basename(target).lower()
            if exe.endswith(".exe"):
                apps.setdefault(exe, (label.strip() or exe, target))
    except Exception:
        pass
    return sorted(((exe, info[0], info[1]) for exe, info in apps.items()),
                  key=lambda item: item[1].lower())


def foreground_process_name():
    """当前前台窗口属于哪个进程（小写进程名）；拿不到就返回空串。"""
    try:
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32.dll")
        kernel32 = ctypes.WinDLL("kernel32.dll")
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return buf.value.rsplit("\\", 1)[-1].lower()
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        pass
    return ""


def running_processes():
    """枚举当前进程，返回 [(exe 小写名, 完整路径)]。用 Windows API，不依赖 psutil。"""
    out = []
    try:
        from ctypes import wintypes
        psapi = ctypes.WinDLL("psapi.dll")
        kernel32 = ctypes.WinDLL("kernel32.dll")
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        arr = (wintypes.DWORD * 4096)()
        needed = wintypes.DWORD()
        if not psapi.EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr), ctypes.byref(needed)):
            return out
        count = needed.value // ctypes.sizeof(wintypes.DWORD)
        for i in range(count):
            pid = arr[i]
            if not pid:
                continue
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                continue
            try:
                buf = ctypes.create_unicode_buffer(1024)
                size = wintypes.DWORD(len(buf))
                if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                    path = buf.value
                    exe = path.rsplit("\\", 1)[-1].lower()
                    if exe:
                        out.append((exe, path))
            finally:
                kernel32.CloseHandle(handle)
    except Exception:
        pass
    return out


def list_process_names():
    """只要进程名（小写）的旧接口。"""
    return {name for name, _path in running_processes()}


# ---------- 百宝箱：内存回收 ----------
# 只做"温和回收"：对能碰到的进程调 EmptyWorkingSet，把它已经用不着的那部分工作集还给系统。
# 不提权 —— 普通用户身份就能做（桌宠安装包默认就是这个不弹 UAC 的身份）。
# 实测（本机 62.5 GB，探针 F:\Codex\work\probe_mem_optimize.py）：
#   311 个进程里 141 个能碰到（都是同一个用户的），工作集 12.2 GB → 0.29 GB，整轮 150 ~ 850 ms；
#   剩下 170 个（系统 / 提权进程）连句柄都打不开 —— 那部分要管理员，本功能不做。
# 注意：收出来的页并没有消失，只是从"进程工作集"挪进了"备用列表"，程序再用到时是软缺页。
MEM_TRIM_MIN_MB = 20        # 比这还小的进程不动（收了也省不下什么）
MEM_TRIM_SKIP_EXE = {       # 系统关键进程：动了没收益，还可能让服务顿一下
    "system", "idle", "registry", "memory compression", "secure system",
    "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe",
    "lsass.exe", "dwm.exe", "fontdrvhost.exe", "audiodg.exe",
}


def human_mb(nbytes):
    """字节 → 「512 MB」/「1.4 GB」这种好念的字样。"""
    mb = max(0.0, float(nbytes or 0)) / (1024 * 1024)
    return f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{mb:.0f} MB"


def system_memory():
    """(总内存, 可用内存)，单位字节；读不到就返回 (0, 0)。"""
    class _MemStatus(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    try:
        kernel32 = ctypes.WinDLL("kernel32.dll")
        st = _MemStatus()
        st.dwLength = ctypes.sizeof(st)
        if kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return int(st.ullTotalPhys), int(st.ullAvailPhys)
    except Exception:
        pass
    return 0, 0


def trim_working_sets(skip_pids=(), skip_exes=(), min_bytes=None):
    """温和回收：把能碰到的进程的工作集收一遍。

    skip_pids / skip_exes 里的不动（自己和前台程序由调用方传进来）。
    返回字典：trimmed / skipped_small / skipped_named / denied / failed 各种计数，
              freed（这次一共腾出多少字节，按工作集前后差值算），
              avail_before / avail_after（系统可用内存，给气泡里那句话用）、elapsed_ms。
    出错时带 error 字段。只读查询 + 一次回收调用，不碰任何配置。
    """
    from ctypes import wintypes

    class _PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                    ("PrivateUsage", ctypes.c_size_t)]

    floor = MEM_TRIM_MIN_MB * 1024 * 1024 if min_bytes is None else int(min_bytes)
    out = {"trimmed": 0, "skipped_small": 0, "skipped_named": 0, "denied": 0,
           "failed": 0, "freed": 0, "avail_before": 0, "avail_after": 0,
           "elapsed_ms": 0}
    t0 = time.perf_counter()
    try:
        kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
        psapi = ctypes.WinDLL("psapi.dll", use_last_error=True)
        # 原型必须声明：不声明的话，64 位下返回的句柄会被当成 32 位截断
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                       wintypes.LPWSTR,
                                                       ctypes.POINTER(wintypes.DWORD)]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        psapi.EnumProcesses.argtypes = [ctypes.c_void_p, wintypes.DWORD,
                                        ctypes.POINTER(wintypes.DWORD)]
        psapi.EnumProcesses.restype = wintypes.BOOL
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC),
                                              wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
        psapi.EmptyWorkingSet.restype = wintypes.BOOL
    except Exception as exc:
        out["error"] = str(exc)
        return out

    out["avail_before"] = system_memory()[1]
    skip_pids = {int(p) for p in skip_pids}
    skip_exes = {str(x).strip().lower() for x in skip_exes if str(x).strip()}
    skip_exes |= MEM_TRIM_SKIP_EXE

    def _open(access, pid):
        return kernel32.OpenProcess(access, False, int(pid))

    def _ws(handle):
        pmc = _PMC()
        pmc.cb = ctypes.sizeof(pmc)
        if psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), ctypes.sizeof(pmc)):
            return int(pmc.WorkingSetSize)
        return 0

    def _exe_of(handle):
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1].lower()
        return ""

    arr = (wintypes.DWORD * 4096)()
    needed = wintypes.DWORD()
    if not psapi.EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr), ctypes.byref(needed)):
        out["error"] = "枚举进程失败"
        return out

    targets = []                     # [(pid, 回收前的工作集)]
    for i in range(needed.value // ctypes.sizeof(wintypes.DWORD)):
        pid = int(arr[i])
        if not pid or pid in (0, 4) or pid in skip_pids:
            continue
        handle = _open(0x0410, pid)              # QUERY_INFORMATION | VM_READ
        if not handle:
            out["denied"] += 1                   # 系统 / 提权进程：普通身份碰不到
            continue
        try:
            name = _exe_of(handle)
            if name in skip_exes:
                out["skipped_named"] += 1
                continue
            ws = _ws(handle)
        finally:
            kernel32.CloseHandle(handle)
        if ws < floor:
            out["skipped_small"] += 1
            continue
        targets.append((pid, ws))

    for pid, _before in targets:
        handle = _open(0x0500, pid)              # QUERY_INFORMATION | SET_QUOTA
        if not handle:
            out["failed"] += 1
            continue
        try:
            if psapi.EmptyWorkingSet(handle):
                out["trimmed"] += 1
            else:
                out["failed"] += 1
        finally:
            kernel32.CloseHandle(handle)

    if out["trimmed"]:
        time.sleep(0.2)                          # 等内存管理器把账记完再量（实测 0.2 秒够）
    for pid, ws_before in targets:
        handle = _open(0x0410, pid)
        if not handle:
            continue
        try:
            ws_after = _ws(handle)
        finally:
            kernel32.CloseHandle(handle)
        if ws_after:
            out["freed"] += max(0, ws_before - ws_after)
    out["avail_after"] = system_memory()[1]
    out["elapsed_ms"] = (time.perf_counter() - t0) * 1000
    return out


def process_exe_by_pid(pid):
    """pid → 进程可执行文件名（小写）；拿不到返回空串。"""
    try:
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32.dll")
        handle = kernel32.OpenProcess(0x1000, False, int(pid))     # QUERY_LIMITED_INFORMATION
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return buf.value.rsplit("\\", 1)[-1].lower()
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        pass
    return ""


def music_app_name(app_id):
    """媒体会话的应用标识 / 进程名 → 「QQ音乐」这种名字；不是这两个软件就返回空串。"""
    low = (app_id or "").lower()
    if not low:
        return ""
    for key, name in MUSIC_APPS.items():
        if key in low:
            return name
    return ""


def app_name_from_id(app_id):
    """认不出来的标识，收拾成人能看的样子（总比「未知应用」强）。

    商店版的 AUMID 长这样：`Netease.CloudMusic_pfh4abc!App`，普通版是 `cloudmusic.exe`
    或完整路径。这里取最后一段、去掉 .exe / 下划线，截短到 24 个字。
    """
    text = (app_id or "").strip()
    if not text:
        return ""
    text = text.split("!")[0]
    text = text.replace("\\", "/").rstrip("/").split("/")[-1]
    if text.lower().endswith(".exe"):
        text = text[:-4]
    text = text.replace("_", " ").strip()
    return text[:24]


def smtc_available():
    """本机能不能读 Windows 媒体会话（读不了就走"看窗口标题"的退路）。"""
    try:
        import winrt.windows.media.control     # noqa: F401
        return True
    except Exception:
        return False


def _music_session_of(manager):
    """从系统媒体会话里挑出"在放歌的那一个" → (session, 显示名)；挑不到就是 (None, "")。

    名字认不出来（各家版本 AUMID 写法五花八门）就看播放器窗口：
    窗口那边认得出是 QQ音乐 / 网易云，就跟着当前会话走（不然气泡顶上会显示「未知应用」）。
    """
    first = manager.get_current_session()
    for one in [first] + list(manager.get_sessions()):
        if one is None:
            continue
        got = music_app_name(one.source_app_user_model_id)
        if got:
            return one, got
    if first is not None:
        window = read_music_window()
        if window is not None:
            return first, (window.get("app") or "").strip()
    return None, ""


def elide_text(fm, text, limit):
    """把一行文字塞进 limit 宽：塞不下就截住加个「…」。"""
    if fm.horizontalAdvance(text) <= limit:
        return text
    ell = fm.horizontalAdvance("…")
    out = ""
    for ch in text:
        if fm.horizontalAdvance(out + ch) > limit - ell:
            break
        out += ch
    return (out + "…") if out else "…"


def toggle_media_playpause():
    """放歌时切一下"播放 / 暂停"（气泡右上角那颗小按钮）。

    走的是同一套系统媒体会话（SMTC）—— QQ音乐、网易云都支持，所以不用去猜
    播放器的快捷键、也不用去点它的窗口。返回 True / False；False = 没找到会话
    或者播放器没接受（桌宠自己会冒一句让主人手动点）。
    """
    try:
        import asyncio
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as _Manager)
    except Exception:
        return False

    async def _toggle():
        manager = await _Manager.request_async()
        session, _name = _music_session_of(manager)
        if session is None:
            return False
        return bool(await session.try_toggle_play_pause_async())

    try:
        return bool(asyncio.run(_toggle()))
    except Exception:
        return False


def skip_media(direction):
    """切上一首 / 下一首（direction 给 "prev" / "next"）。

    跟播放 / 暂停一样走系统媒体会话（SMTC）—— QQ音乐、网易云都支持，
    不用去猜播放器的快捷键、也不用去点它的窗口。返回 True / False；
    False = 没找到会话或者播放器没接受（桌宠自己会冒一句让主人手动点）。
    """
    if direction not in ("prev", "next"):
        return False
    try:
        import asyncio
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as _Manager)
    except Exception:
        return False

    async def _skip():
        manager = await _Manager.request_async()
        session, _name = _music_session_of(manager)
        if session is None:
            return False
        if direction == "next":
            return bool(await session.try_skip_next_async())
        return bool(await session.try_skip_previous_async())

    try:
        return bool(asyncio.run(_skip()))
    except Exception:
        return False


def read_media_session():
    """读系统媒体会话 → dict；没在放歌 / 读不到返回 None。

    position 是"读取那一刻"的进度，配上 at（读取时间）就能自己往后推。
    """
    try:
        import asyncio
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as _Manager)
    except Exception:
        return None

    async def _read():
        manager = await _Manager.request_async()
        session, name = _music_session_of(manager)
        if session is None:
            return None
        status = getattr(session.get_playback_info().playback_status, "name", "")
        props = await session.try_get_media_properties_async()
        line = session.get_timeline_properties()
        return {
            "app": name,
            # 原始标识留着：万一还是没名字，气泡顶上能拿它当兜底（见 _app_label）
            "app_id": session.source_app_user_model_id or "",
            "title": (props.title or "").strip(),
            "artist": (props.artist or "").strip(),
            "album": (props.album_title or "").strip(),
            "playing": str(status).upper() == "PLAYING",
            "position": float(line.position.total_seconds()),
            "duration": float(line.end_time.total_seconds()),
            # 播放器到底报没报"时间轴"：网易云 position 和总时长恒为 0（实测），
            # 这种就只能显示歌名，别硬猜进度、也别去抓歌词了
            "has_timeline": (float(line.position.total_seconds()) > 0.0
                             or float(line.end_time.total_seconds()) > 0.0),
            "at": time.time(),
        }

    try:
        return asyncio.run(_read())
    except Exception:
        return None


def parse_mmss(text):
    """把「1:35」「01:35.5」「95」这种写法转成秒；看不懂返回 None。"""
    t = (text or "").strip().replace("：", ":")
    if not t:
        return None
    try:
        if ":" in t:
            parts = [p for p in t.split(":") if p != ""]
            if len(parts) == 2:
                return int(parts[0]) * 60 + float(parts[1])
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            return None
        return float(t)
    except (TypeError, ValueError):
        return None


def split_music_title(title, app_name=""):
    """把「歌名 - 歌手 - QQ音乐」这类窗口标题拆成 (歌名, 歌手)。"""
    text = (title or "").strip()
    for junk in (app_name, "QQ音乐", "网易云音乐", "QQMusic", "网易云音乐PC版"):
        if junk and text.endswith(junk):
            text = text[: -len(junk)].strip(" -—–|·")
    if not text:
        return "", ""
    parts = [x.strip() for x in re.split(r"\s+[-—–]\s+", text) if x.strip()]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def read_music_window():
    """退路：读不到媒体会话时，直接看 QQ音乐 / 网易云 的窗口标题。"""
    try:
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32.dll")
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def _visit(hwnd, _param):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = (buf.value or "").strip()
                if not title:
                    return True
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                exe = process_exe_by_pid(pid.value)
                app = music_app_name(exe)
                if app:
                    found.append((app, title, exe))
            except Exception:
                pass
            return True

        user32.EnumWindows(_visit, 0)
        for app, title, exe in found:
            song, artist = split_music_title(title, app)
            if song:
                return {"app": app, "app_id": exe, "title": song, "artist": artist,
                        "album": "", "playing": True, "position": None,
                        "duration": 0.0, "at": time.time(), "from_title": True}
    except Exception:
        pass
    return None


def merge_media_info(info, fallback):
    """媒体会话在、但没给歌名时，用窗口标题补上歌名 / 歌手（播放状态和进度以会话为准）。"""
    if fallback is None:
        return info
    if info is None:
        return fallback
    merged = dict(fallback)
    for key in ("playing", "position", "duration", "at"):
        if info.get(key) is not None:
            merged[key] = info[key]
    return merged


_LRC_TAG = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")


def parse_lrc(text):
    """LRC 歌词 → [(秒, 这一句)]，按时间排好；[ti:] 这类信息行丢掉。"""
    out = []
    for raw in (text or "").splitlines():
        stamps = _LRC_TAG.findall(raw)
        if not stamps:
            continue
        words = _LRC_TAG.sub("", raw).strip()
        if not words:
            continue
        for minute, second, frac in stamps:
            ms = int(frac) if frac else 0
            if len(frac) == 1:
                ms *= 100
            elif len(frac) == 2:
                ms *= 10
            out.append((int(minute) * 60 + int(second) + ms / 1000.0, words))
    out.sort(key=lambda item: item[0])
    return out


def lyric_pair(lines, pos):
    """pos 秒时该显示的（这一句, 下一句）；没有歌词返回两个空串。"""
    if not lines:
        return "", ""
    idx = lyric_index(lines, pos)
    nxt = lines[idx + 1][1] if idx + 1 < len(lines) else ""
    return lines[idx][1], nxt


def lyric_index(lines, pos):
    """pos 秒时该显示第几句（和 lyric_pair 用同一套判断，保证两者一致）。"""
    idx = 0
    for i, (when, _words) in enumerate(lines):
        if when <= pos + 0.15:
            idx = i
        else:
            break
    return idx


_YRC_LINE_RE = re.compile(r"^\[(\d+),(\d+)\](.*)$")
_YRC_WORD_RE = re.compile(r"\((\d+),(\d+),(\d+)\)")
_LRC_TIME_RE = re.compile(r"^\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_LRC_INLINE_RE = re.compile(r"<(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?>")


def _ms_or_sec(a, b, c):
    """[mm:ss.xx] / <mm:ss.xx> 三段 → 秒。"""
    return int(a) * 60 + int(b) + (int((c or "0").ljust(3, "0")) / 1000.0)


def parse_word_lyrics(text):
    """解析"逐字歌词"，返回 {这句的开始秒: [(字, 这个字的开始秒), ...]}。

    支持两种：
    · 网易云的 yrc：`[16250,2140](16250,430,0)有(16680,430,0)些(17110,430,0)话...`
    · 带行内时间戳的增强 LRC：`[00:16.25]有<00:16.68>些<00:17.11>话...`
    解析不出来就返回空 dict（那就退回"按这句的起止时间匀速推"）。
    """
    out = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _YRC_LINE_RE.match(line)
        if m and _YRC_WORD_RE.search(line):
            start = int(m.group(1)) / 1000.0
            body = m.group(3)
            marks = list(_YRC_WORD_RE.finditer(body))
            pairs = []
            for i, mk in enumerate(marks):
                end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
                piece = body[mk.end():end]          # 这个词的文字（可能不止一个字，比如 "OP"）
                if not piece:
                    continue
                t0 = int(mk.group(1)) / 1000.0
                dur = int(mk.group(2)) / 1000.0
                n = len(piece)
                for k, ch in enumerate(piece):      # 词内按字数均分时间，避免几个字一起跳
                    pairs.append((ch, t0 + dur * k / max(1, n)))
            if pairs:
                out[start] = pairs
            continue
        m = _LRC_TIME_RE.match(line)
        if m and _LRC_INLINE_RE.search(line):
            start = _ms_or_sec(m.group(1), m.group(2), m.group(3))
            body = line[m.end():]
            pairs, pos, cur = [], 0, start
            for im in _LRC_INLINE_RE.finditer(body):
                piece = body[pos:im.start()].strip()
                if piece:
                    pairs.extend((c, cur) for c in piece)
                cur = _ms_or_sec(im.group(1), im.group(2), im.group(3))
                pos = im.end()
            tail = body[pos:].strip()
            if tail:
                pairs.extend((c, cur) for c in tail)
            if pairs:
                out[start] = pairs
    return out


def sung_chars(words, pos):
    """逐字时间戳下，pos 秒时这句已经唱到第几个字（可以是小数，按当前字推进）。"""
    if not words:
        return 0.0
    n = 0
    for _c, t in words:
        if t <= pos:
            n += 1
        else:
            nxt_t = max(pos, t)
            prev_t = words[n - 1][1] if n > 0 else t
            span = max(0.05, nxt_t - prev_t)
            return float(n) + max(0.0, min(1.0, (pos - prev_t) / span))
    return float(n)


def _best_song(items, title, artist, name_of, artist_of):
    """在搜索结果里挑最像的那一首：歌名优先，歌手用来加分 / 排除。"""
    want_t = (title or "").strip().lower()
    want_a = (artist or "").strip().lower()
    best, best_score = None, 0
    for item in items[:8]:
        name = (name_of(item) or "").strip().lower()
        who = (artist_of(item) or "").strip().lower()
        score = 0
        if want_t and name == want_t:
            score += 4
        elif want_t and want_t in name:
            score += 3
        elif name and name in want_t:
            score += 2
        if want_a and who:
            if want_a == who:
                score += 3
            elif want_a in who or who in want_a:
                score += 2
            else:
                score -= 3
        if score > best_score:
            best, best_score = item, score
    return best


def _netease_lyric(title, artist):
    """网易云的公开搜索 + 歌词接口（不需要 Key）。"""
    r = requests.post("https://music.163.com/api/search/get/web",
                      data={"s": f"{title} {artist}".strip(), "type": 1,
                            "limit": 8, "offset": 0},
                      headers={"User-Agent": "Mozilla/5.0",
                               "Referer": "https://music.163.com/"},
                      timeout=10)
    songs = ((r.json() or {}).get("result") or {}).get("songs") or []
    song = _best_song(songs, title, artist,
                      lambda s: s.get("name"),
                      lambda s: " ".join(a.get("name", "")
                                         for a in (s.get("artists") or [])))
    if not song:
        return ""
    r2 = requests.get("https://music.163.com/api/song/lyric",
                      params={"id": song.get("id"), "lv": 1, "kv": 1, "tv": -1, "yv": 1},
                      headers={"User-Agent": "Mozilla/5.0",
                               "Referer": "https://music.163.com/"},
                      timeout=10)
    data = r2.json() or {}
    # 有逐字歌词（yrc）就用它：这样"唱到哪高亮到哪"能完全贴合真人演唱，而不是匀速推
    word = ((data.get("yrc") or {}).get("lyric") or "").strip()
    return word or ((data.get("lrc") or {}).get("lyric") or "")


def _qq_lyric(title, artist):
    """QQ音乐的公开搜索 + 歌词接口（不需要 Key）。"""
    r = requests.get("https://c.y.qq.com/soso/fcgi-bin/client_search_cp",
                     params={"w": f"{title} {artist}".strip(), "format": "json",
                             "n": 8, "cr": 1, "p": 1},
                     headers={"User-Agent": "Mozilla/5.0",
                              "Referer": "https://y.qq.com/"},
                     timeout=10)
    text = r.text
    data = json.loads(text[text.find("{"):text.rfind("}") + 1])
    songs = ((data.get("data") or {}).get("song") or {}).get("list") or []
    song = _best_song(songs, title, artist,
                      lambda s: s.get("songname") or s.get("title"),
                      lambda s: " ".join(x.get("name", "")
                                         for x in (s.get("singer") or [])))
    if not song:
        return ""
    r2 = requests.get("https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg",
                      params={"songmid": song.get("songmid"), "format": "json",
                              "nobase64": 1, "g_tk": 5381},
                      headers={"User-Agent": "Mozilla/5.0",
                               "Referer": "https://y.qq.com/portal/player.html"},
                      timeout=10)
    text2 = r2.text
    data2 = json.loads(text2[text2.find("{"):text2.rfind("}") + 1])
    return data2.get("lyric") or ""


def fetch_lyrics(title, artist):
    """联网找歌词：先网易云，再 QQ音乐；都找不到返回空串。"""
    if not (title or "").strip():
        return ""
    for finder in (_netease_lyric, _qq_lyric):
        try:
            lrc = finder(title, artist)
            if lrc and len(parse_lrc(lrc)) >= 3:
                return lrc
        except Exception:
            continue
    return ""


def load_lyric_cache():
    """歌词缓存：按「歌名|歌手」存，换歌不用每次都联网。"""
    data = load_json(LYRIC_CACHE_PATH, {})
    out = {}
    for key, value in (data or {}).items():
        if isinstance(value, dict):
            out[key] = {"v": int(value.get("v") or 1), "text": str(value.get("text") or "")}
        else:
            # 老版本缓存的是纯文本（那时候只存了行级歌词）→ 标记成旧版，回头再抓一次，
            # 这样有逐字歌词的歌能升级成"唱到哪高亮到哪"
            out[key] = {"v": 1, "text": str(value or "")}
    return out


def save_lyric_cache(cache):
    try:
        items = list(cache.items())[-LYRIC_CACHE_MAX:]
        with open(LYRIC_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(dict(items), f, ensure_ascii=False)
    except Exception:
        pass


def _wrap_tokens(text):
    """折行单位：英文单词（连同后面的空格）算一个，中文逐字。"""
    units, buf = [], ""
    for ch in text or "":
        if ch.isascii() and (ch.isalnum() or ch in "'’-"):
            buf += ch
            continue
        if buf:
            units.append(buf)
            buf = ""
        if ch == " " and units:
            units[-1] += ch          # 空格跟着前一个词，避免行首出现空格
        else:
            units.append(ch)
    if buf:
        units.append(buf)
    return units


WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x80000, 0x20


def click_through_style(style, on, user_passthrough=False):
    """算窗口的扩展样式：菜单开着时加 WS_EX_TRANSPARENT（鼠标事件穿过去给菜单）。

    on 为假时按用户自己的「鼠标穿透」设置还原——用户开着穿透就别给关掉。
    """
    style |= WS_EX_LAYERED
    if on or user_passthrough:
        return style | WS_EX_TRANSPARENT
    return style & ~WS_EX_TRANSPARENT


def wrap_text(fm, text, max_w):
    """按像素宽度折行：中文逐字折，英文整词折（别把单词劈两半）。"""
    lines, cur = [], ""
    for unit in _wrap_tokens(text):
        if cur and fm.horizontalAdvance(cur + unit) > max_w:
            lines.append(cur.rstrip())
            cur = unit.lstrip()
        else:
            cur += unit
        while fm.horizontalAdvance(cur) > max_w and len(cur) > 1:
            cut = len(cur)                 # 单个词就超宽：只能硬拆
            while cut > 1 and fm.horizontalAdvance(cur[:cut]) > max_w:
                cut -= 1
            lines.append(cur[:cut])
            cur = cur[cut:]
    lines.append(cur.rstrip())
    return lines


def wrap_text_hanging(fm, text, first_w, rest_w):
    """折行**但第一行窄一点**：右边那一条要留给气泡上那几颗按钮（⏮ ⏸▶ ⏭）。

    只有第一行会被按钮占掉一截，折到第二行起整行都能用 —— 不然按钮一多，
    顶行「♪ 应用 · 歌名」就会被整段省略成「♪ 网…」（主人反馈过"和文字打架"）。
    折行规矩跟 wrap_text 一样：中文逐字折，英文整词折。
    """
    lines, cur = [], ""
    limit = first_w
    for unit in _wrap_tokens(text):
        if cur and fm.horizontalAdvance(cur + unit) > limit:
            lines.append(cur.rstrip())
            cur = unit.lstrip()
            limit = rest_w
        else:
            cur += unit
        while fm.horizontalAdvance(cur) > limit and len(cur) > 1:
            cut = len(cur)                 # 单个词就超宽：只能硬拆
            while cut > 1 and fm.horizontalAdvance(cur[:cut]) > limit:
                cut -= 1
            lines.append(cur[:cut])
            cur = cur[cut:]
            limit = rest_w
    lines.append(cur.rstrip())
    return lines


def locate_city_by_ip():
    """按 IP 联网定位城市，失败返回空串（挂代理时拿到的是节点所在地）。"""
    for url in ("https://api.ip.sb/geoip", "https://myip.wtf/json"):
        try:
            data = requests.get(url, timeout=8,
                                headers={"User-Agent": "dafeiyu-pet/1.0"}).json() or {}
            city = (data.get("city") or data.get("YourFuckingCity")
                    or data.get("region") or "").strip()
            if city:
                return city
        except Exception:
            continue
    return ""


def has_chinese(text):
    return any("\u4e00" <= ch <= "\u9fff" for ch in (text or ""))


def to_chinese_city(name):
    """自动定位拿到的英文城市名尽量换成中文（比如 Singapore -> 新加坡）。"""
    if not name or has_chinese(name):
        return name
    try:
        for _label, city in lookup_city(name):
            if has_chinese(city):
                return city
    except Exception:
        pass
    return name


# ---------- 天气数据源 ----------
# 2026-09-14 换源。以前第一站是 wttr.in（墙外），实测从这台机器 4/4 全失败
# （3.0 秒被断连 / 12.9 秒读超时），而且它失败两次才轮到备用源 —— 这就是
# "每次看天气都要等十几秒"的根源。现在第一站是**国内直连的中国天气网**：
# 不要 Key，实测城市搜索 0.2~0.4 秒、实况 0.1 秒，回来的本来就是中文。
CN_WEATHER_SEARCH = "https://toy1.weather.com.cn/search"
CN_WEATHER_SK = "https://d1.weather.com.cn/sk_2d/{code}.html"
CN_WEATHER_HEADERS = {"User-Agent": "Mozilla/5.0",
                      "Referer": "https://www.weather.com.cn/"}


def _cn_body(resp):
    """中国天气网的响应头没写 charset，requests 会猜成 ISO-8859-1，这里按 UTF-8 读。"""
    if not resp.encoding or resp.encoding.lower() in ("iso-8859-1", "ascii"):
        resp.encoding = "utf-8"
    return resp.text or ""


def cn_city_search(name):
    """中国天气网：城市名 → [(城市代码, 中文名, 省份)]，查不到返回 []。

    接口回来的是 `([{"ref":"101280501~guangdong~汕头~Shantou~…~广东"}])` 这种
    "伪 JSON"：外面裹着一对括号，去掉再按 JSON 读。
    """
    q = (name or "").strip()
    if not q:
        return []
    r = requests.get(CN_WEATHER_SEARCH, params={"cityname": q},
                     headers=CN_WEATHER_HEADERS, timeout=6)
    body = _cn_body(r).strip().strip("()")
    rows = json.loads(body) if body else []
    out = []
    for row in rows or []:
        parts = str((row or {}).get("ref") or "").split("~")
        code = parts[0] if parts else ""
        cname = parts[2] if len(parts) > 2 else ""
        prov = parts[9] if len(parts) > 9 else ""
        if code and cname:
            out.append((code, cname, prov))
    return out


def cn_parse_sk(body):
    """中国天气网那行 `var dataSK={...}` → (温度, 中文描述)；不是实况就返回 None。

    单独拆出来是为了能离线自测（不用真联网）。
    """
    body = body or ""
    if "dataSK" not in body:
        # 国外城市（2 开头的代码）它只回一张"网页无法访问"的报错页，早点认出来
        return None
    i, j = body.find("{"), body.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        data = json.loads(body[i:j + 1]) or {}
    except Exception:
        return None
    temp = data.get("temp")
    if temp in (None, "", "999"):        # 999 是它自己的"这儿没数据"占位
        return None
    desc = (data.get("weather") or "").strip() or "未知天气"
    try:
        return str(round(float(temp))), desc
    except (TypeError, ValueError):
        return None


def cn_weather_now(code):
    """中国天气网实况：城市代码 → (温度, 中文描述)；没取到返回 None。"""
    r = requests.get(CN_WEATHER_SK.format(code=code),
                     headers=CN_WEATHER_HEADERS, timeout=6)
    return cn_parse_sk(_cn_body(r))


# open-meteo（WMO）天气代码 → 中文，做中国天气网取不到时的兜底
WMO_ZH = {
    0: "晴", 1: "晴间多云", 2: "多云", 3: "阴", 45: "雾", 48: "冻雾",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨", 56: "冻毛毛雨", 57: "强冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "小阵雨", 81: "中阵雨", 82: "强阵雨", 85: "小阵雪", 86: "大阵雪",
    95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "强雷阵雨伴冰雹",
}


def open_meteo_weather(name):
    """兜底源 open-meteo：地名 → 坐标 → 实况，返回 (温度, 中文描述) 或 None。"""
    g = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                     params={"name": name, "count": 1, "language": "zh"},
                     timeout=5).json() or {}
    found = g.get("results") or []
    if not found:
        return None
    w = requests.get("https://api.open-meteo.com/v1/forecast",
                     params={"latitude": found[0]["latitude"],
                             "longitude": found[0]["longitude"],
                             "current": "temperature_2m,weather_code"},
                     timeout=5).json() or {}
    cur = w.get("current") or {}
    if cur.get("temperature_2m") is None:
        return None
    code = cur.get("weather_code")
    desc = WMO_ZH.get(int(code), "未知天气") if code is not None else "未知天气"
    return str(round(float(cur["temperature_2m"]))), desc


def fetch_weather(city):
    """查天气：先走国内源（中国天气网），不行再用 open-meteo 兜底。

    返回 (温度, 中文描述)；都失败返回 None。
    """
    city = (city or "").strip()
    variants = city_query_variants(city)
    for attempt in range(2):        # 国内源偶尔也会抽一下，重试一次比退到墙外划算
        try:
            for q in variants:
                hits = cn_city_search(q)
                if hits:
                    got = cn_weather_now(hits[0][0])
                    if got:
                        return got
            break                   # 查询本身是通的（只是它这儿没有实况），不用重试
        except Exception:
            if attempt == 0:
                time.sleep(0.4)
    names = []
    for q in variants:
        names.append(q)
        if not q.endswith(("市", "县", "区")):
            # open-meteo 的中文库里多是"汕头市"这种全称，简称常搜不到，补一刀再试
            names.append(q + "市")
    for attempt in range(2):        # 兜底源偶尔抽一下（SSL 报错 / 超时），重试一次
        for name in names:
            try:
                got = open_meteo_weather(name)
                if got:
                    return got
            except Exception:
                pass
        if attempt == 0:
            time.sleep(0.4)
    return None


# ===== 合体新增：按「提问时段」播报的天气预报 =====
# 规则：上午/凌晨问 → 报今天中午、下午、晚上 + 会不会下雨；下午问 → 今天下午、晚上；
#      晚上（18 点后）问 → 报明天；只要明天会下雨，任何时候都补报明天。
# 数据源 open-meteo（逐时 + 每日，时区固定东八区），不要 Key。
OM_GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
OM_FORECAST = "https://api.open-meteo.com/v1/forecast"


def om_geocode(name):
    """open-meteo 地理编码：地名 → (纬度, 经度) 或 None。"""
    q = (name or "").strip()
    if not q:
        return None
    tries = [q]
    if q.endswith(("市", "县", "区")):        # 「北京市」也能退回「北京」再试一次
        tries.append(q[:-1])
    else:
        tries.append(q + "市")
    for candidate in tries:
        try:
            g = requests.get(OM_GEOCODE,
                             params={"name": candidate, "count": 1, "language": "zh"},
                             timeout=6).json() or {}
        except Exception:
            continue
        found = g.get("results") or []
        if found:
            try:
                return float(found[0]["latitude"]), float(found[0]["longitude"])
            except (KeyError, TypeError, ValueError):
                continue
    return None


def is_rain_code(code):
    """WMO 天气码算不算「会下东西」：毛毛雨 / 雨 / 雪 / 阵雨 / 雷暴。"""
    try:
        c = int(code)
    except (TypeError, ValueError):
        return False
    return 51 <= c <= 99


def weather_text(code):
    """WMO 天气码 → 中文（复用已有的 WMO_ZH 对照表）。"""
    try:
        return WMO_ZH.get(int(code), "未知天气")
    except (TypeError, ValueError):
        return "未知天气"


def om_forecast(lat, lon, days=3):
    """open-meteo 预报（东八区）：逐时温度/天气码/降水概率 + 每日高低温。"""
    w = requests.get(OM_FORECAST, params={
        "latitude": lat, "longitude": lon,
        "hourly": "temperature_2m,weather_code,precipitation_probability",
        "daily": ("temperature_2m_max,temperature_2m_min,weather_code,"
                  "precipitation_probability_max"),
        "timezone": "Asia/Shanghai", "forecast_days": days,
    }, timeout=8).json() or {}
    hourly = w.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return None
    temps = hourly.get("temperature_2m") or []
    codes = hourly.get("weather_code") or []
    pops = hourly.get("precipitation_probability") or []
    rows = {}
    for i, stamp in enumerate(times):
        day, _, hh = str(stamp).partition("T")
        try:
            hour = int(hh[:2])
        except ValueError:
            continue
        rows[(day, hour)] = (temps[i] if i < len(temps) else None,
                             codes[i] if i < len(codes) else None,
                             pops[i] if i < len(pops) else None)
    return {"hourly": rows, "daily": w.get("daily") or {}}


def _period_info(fc, day, start_h, end_h, rep_h):
    """某天某时段 → (代表温度, 中文描述, 会不会下雨)；没数据返回 None。"""
    rows = (fc or {}).get("hourly") or {}
    picked = [(h, rows[(day, h)]) for h in range(start_h, end_h + 1) if (day, h) in rows]
    if not picked:
        return None
    wet = [(h, v) for h, v in picked
           if is_rain_code(v[1]) or (v[2] is not None and v[2] >= 50)]
    rep = rows.get((day, rep_h)) or picked[len(picked) // 2][1]
    temp, desc = rep[0], weather_text(rep[1])
    if wet:
        # 有雨时描述用「下雨那一刻」的，免得写成「多云」又说有雨
        desc = weather_text(wet[0][1][1])
    return temp, desc, bool(wet)


def _daily_info(fc, day):
    """某天的每日概况 → (最低温, 最高温, 中文描述, 会不会下雨)；没数据 None。"""
    d = (fc or {}).get("daily") or {}
    days = d.get("time") or []
    if day not in days:
        return None
    i = days.index(day)

    def pick(key):
        arr = d.get(key) or []
        return arr[i] if i < len(arr) else None

    try:
        lo = round(float(pick("temperature_2m_min")))
        hi = round(float(pick("temperature_2m_max")))
    except (TypeError, ValueError):
        return None
    code = pick("weather_code")
    pop = pick("precipitation_probability_max")
    rain = is_rain_code(code) or (pop is not None and pop >= 50)
    return lo, hi, weather_text(code), rain


def _fmt_deg(temp):
    try:
        return f"{round(float(temp))}°"
    except (TypeError, ValueError):
        return ""


def _day_all_clear(fc, day):
    """某天是不是「一整天大晴天」：逐时天气码全是 0（晴）—— 既没云、也不会下雨。"""
    rows = (fc or {}).get("hourly") or {}
    codes = [v[1] for (d, _h), v in rows.items() if d == day and v[1] is not None]
    if not codes:
        return False
    try:
        return all(int(c) == 0 for c in codes)
    except (TypeError, ValueError):
        return False


def weather_report(city, now=None):
    """按「提问时段」拼天气播报文本；取不到返回 None。

    凌晨/上午 → 今天中午、下午、晚上；午后 → 今天剩下的时段；
    21 点之后 → 报明天；只要明天会下雨、或明天一整天大晴（可以晾衣服），
    任何时候都会补报一句明天。
    """
    now = now or datetime.now()
    geo = om_geocode(city)
    if not geo:
        return None
    fc = om_forecast(geo[0], geo[1])
    if not fc:
        return None
    today = now.strftime("%Y-%m-%d")
    tmr = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    where = (city or "").strip() or "本地"
    hour = now.hour

    tmr_daily = _daily_info(fc, tmr)
    tmr_clear = _day_all_clear(fc, tmr)
    today_spans = [("中午", 11, 13, 12), ("下午", 14, 17, 15), ("晚上", 18, 22, 20)]
    if hour >= 21:                         # 晚上（21 点之后）问 → 主要报明天
        if tmr_daily:
            lo, hi, desc, rain = tmr_daily
            msg = f"{where}明天{desc}，{lo}~{hi}°"
            if rain:
                msg += "，有雨记得带伞"
            elif tmr_clear:
                msg += "，一整天晴，可以晾衣服"
            else:
                msg += "，不下雨"
            return msg
        spans = today_spans[2:]            # 明天数据缺失 → 退回今天的晚上
    elif hour < 12:                        # 凌晨 / 上午
        spans = today_spans
    elif hour < 17:                        # 午后 → 下午、晚上
        spans = today_spans[1:]
    else:                                  # 17~21 点 → 只剩晚上
        spans = today_spans[2:]

    infos = [(label, _period_info(fc, today, a, b, c)) for label, a, b, c in spans]
    infos = [(label, got) for label, got in infos if got]
    if not infos:
        return None
    msg = f"{where}今天：" + "、".join(
        f"{label}{desc}{_fmt_deg(temp)}" for label, (temp, desc, _rain) in infos)
    wet = [label for label, (_t, _d, rain) in infos if rain]
    msg += "，" + ("、".join(wet) + "有雨" if wet else "不下雨")
    if tmr_daily:                          # 明天的提醒：会下雨 或 一整天大晴
        lo, hi, desc, rain = tmr_daily
        if rain:
            msg += f"；明天{desc}{lo}~{hi}°也有雨"
        elif tmr_clear:
            msg += "；明天一整天晴，可以晾衣服"
    return msg


# ===== 合体新增：DSH（DeepSeek Harness）联动 =====
# 每秒读最新会话的 session.v4.jsonl.zstd（zstd 压缩的 JSONL），推出「在干什么」，
# 再让桌宠做出反应。纯本地只读、不外传；可在右键菜单里关掉。
DSH_SESSIONS_ROOT = os.path.join(os.environ.get("USERPROFILE")
                                 or os.path.expanduser("~"), ".dsh", "sessions")
try:
    from compression import zstd as _zstd          # Python 3.14+ 标准库自带
    DSH_ZSTD = True
except Exception:
    try:
        import zstandard as _zstd                  # 老环境的兜底
        DSH_ZSTD = True
    except Exception:
        _zstd = None
        DSH_ZSTD = False

# 各种状态的台词（随机挑一句）
DSH_LINES = {
    "start": ["开工！看我的", "来活了来活了～", "有活干咯"],
    "approval": ["主人快点一下嘛，卡这儿等你批准呢！", "有个批准在等你，快点快点～",
                 "批一下嘛，我停在这儿了"],
    "error": ["哎哟，出错了…", "这步没跑通，我看看", "报错了，别慌"],
    "done": ["干完啦，收工！", "这轮完事了～", "搞定，歇会儿"],
    "tool_pwsh": ["又在敲命令", "命令行进行中…", "敲敲敲"],
    "tool_edit": ["改代码啦，别眨眼", "正在写文件…", "动手改咯"],
    "tool_read": ["翻文件呢，找点东西", "让我看看这文件写了啥"],
    "tool_web": ["上网查点东西", "让我搜一搜…"],
    "idle": ["没事干，我先睡会儿…", "发呆中…", "主人不在，我眯一会儿"],
}
# 工具名 → 台词分类
DSH_TOOL_KIND = {
    "pwsh": "tool_pwsh", "bash": "tool_pwsh", "shell": "tool_pwsh",
    "edit": "tool_edit", "write": "tool_edit",
    "read": "tool_read", "glob": "tool_read", "grep": "tool_read",
    "web_search": "tool_web", "web_fetch": "tool_web",
}
DSH_IDLE_SEC = 120.0        # 静这么久就算「闲着」，冒一句闲话
DSH_TOOL_COOLDOWN = 1.2     # 新命令之间的最小间隔（秒），只用来防刷屏
DSH_DEBUG = False           # 由 config 的 dsh_debug 打开
DSH_DEBUG_FILE = os.path.join(USER_DIR, "dsh-debug.log")


def dsh_log(text):
    """DSH 联动排查日志（只有开了 dsh_debug 才写）。"""
    if not DSH_DEBUG:
        return
    try:
        with open(DSH_DEBUG_FILE, "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (datetime.now().strftime("%H:%M:%S.%f")[:-3], text))
    except Exception:
        pass


def dsh_latest_session():
    """最近改动的 DSH 会话日志路径；没有就 None。"""
    root = DSH_SESSIONS_ROOT
    if not os.path.isdir(root):
        return None
    best, best_m = None, -1.0
    try:
        for dirpath, _dirs, files in os.walk(root):
            if "session.v4.jsonl.zstd" not in files:
                continue
            p = os.path.join(dirpath, "session.v4.jsonl.zstd")
            try:
                m = os.path.getmtime(p)
            except OSError:
                continue
            if m > best_m:
                best, best_m = p, m
    except Exception:
        return None
    return best


def dsh_blank_state():
    """DSH 联动的初始状态。"""
    return {"turn": False, "approval": False, "error": False,
            "last_tool": "", "events": 0, "last_ts": 0, "tool_calls": 0}


def dsh_apply_event(st, ev):
    """把一条事件并进状态里（增量更新，不用重头扫全部历史）。"""
    st["events"] += 1
    st["last_ts"] = ev.get("time") or st["last_ts"]
    kind = ev.get("type") or ""
    data = ev.get("data") or {}
    if kind == "turn/start":
        st["turn"] = True
        st["approval"] = False
        st["error"] = False
    elif kind == "turn/end":
        st["turn"] = False
        st["approval"] = False
    elif kind == "approval/asked":
        st["approval"] = True
    elif kind == "approval/decided":
        st["approval"] = False
    elif kind == "tool/call":
        st["last_tool"] = data.get("name") or ""
        st["tool_calls"] += 1          # 新命令计数：靠它判断"又敲了一条"
    elif kind == "tool/result":
        st["error"] = bool((data.get("message") or {}).get("isError"))


def dsh_read_new(path, offset):
    """从 offset 起**只解压新追加的完整帧** → (新文本, 新偏移)；失败 (None, offset)。

    为什么能这么快：DSH 每追加一次写一个独立的 zstd 帧（实测整份 1351 帧、
    每帧约 1.8KB）。整份解压要 450ms（8.8MB），只解新帧只要 0.09ms。
    帧写到一半时先跳过，下次再读。
    """
    if not DSH_ZSTD or not path:
        return None, offset
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            chunk = f.read()
    except Exception:
        return None, offset
    if not chunk:
        return "", offset
    parts = []
    off = 0
    while off < len(chunk):
        try:
            n = _zstd.get_frame_size(chunk[off:])
        except Exception:
            break
        if not n or n <= 0 or off + n > len(chunk):
            break                      # 帧还没写完，等下次
        try:
            parts.append(_zstd.decompress(chunk[off:off + n]).decode("utf-8", "replace"))
        except Exception:
            break
        off += n
    # 只把「完整的帧」算进偏移，保证下次一定从帧头开始（不会对不齐而漏事件）
    return "".join(parts), offset + off


def dsh_analyze(path):
    """整份解压并推出状态（给外部自测用；桌宠运行时走增量）。"""
    txt, _off = dsh_read_new(path, 0)
    if txt is None:
        return None
    st = dsh_blank_state()
    for ln in txt.splitlines():
        ln = ln.strip()
        if not ln or ln[0] != "{":
            continue
        try:
            ev = json.loads(ln)
        except Exception:
            continue
        dsh_apply_event(st, ev)
    return st


# 动作名 → (帧时长毫秒, 循环?)；图片放 sprites/dsh/<动作名>_<序号>.png
DSH_ACTS = {
    "start":     (180, True),
    "approval":  (140, True),
    "error":     (160, False),
    "done":      (220, False),
    "tool_pwsh": (200, True),
    "tool_edit": (200, True),
    "tool_read": (200, True),
    "tool_web":  (200, True),
    "idle":      (400, True),
    "sing":      (400, True),      # 放歌时的姿势（由音乐联动驱动，不是 DSH 事件）
    "working":   (400, True),      # DSH 思考中的姿势（「深度思考」那会儿的常驻态）
}
# 个别动作单独放大的倍数（唱歌图人物偏瘦，按统一高度会显得小）
# 注意：放大过头会顶进上方的台词气泡区（放歌时正好在显示歌词），所以别调太大
DSH_ACT_ZOOM = {"sing": 1.18}

# 动作名 → (中文名, 什么情况下触发) —— 设置窗口「DSH 联动」页展示用
DSH_ACT_INFO = {
    "start":     ("开工",   "DSH 开始一轮工作"),
    "approval":  ("等批准", "有工具在等你批准"),
    "error":     ("报错",   "工具执行出错"),
    "done":      ("收工",   "一轮工作结束"),
    "tool_pwsh": ("敲命令", "又执行了一条命令"),
    "tool_edit": ("改代码", "改文件 / 写文件"),
    "tool_read": ("翻文件", "读文件、搜索"),
    "tool_web":  ("上网查", "搜索、抓网页"),
    "idle":      ("发呆",   "静默超过 120 秒"),
    "sing":      ("放歌",   "音乐播放中（音乐联动驱动）"),
    "working":   ("思考中", "收到消息、正在深度思考（没有别的状态时）"),
}
DSH_ACTS_DIR = os.path.join(SPRITE_DIR, "dsh")
# 台词分类 → 动作名（有些分类共用同一个动作）
DSH_KIND_ACT = {"tool_pwsh": "tool_pwsh", "tool_edit": "tool_edit",
                "tool_read": "tool_read", "tool_web": "tool_web"}


def load_dsh_acts():
    """扫动作帧 → {动作名: {帧序号: [(源高度, QPixmap), ...]}}；没有就是空。

    两种放法都认：
      ① 子目录 dsh/<动作名>/<序号>.png        或  <序号>_<高度>.png   ← 推荐
      ② 扁平   dsh/<动作名>_<序号>.png        或  <动作名>_<序号>_<高度>.png
    同一序号有多张（不同档位）时按源高度排序，画的时候挑最接近当前大小的那张。
    """
    acts = {}
    if not os.path.isdir(DSH_ACTS_DIR):
        return acts

    def _split(stem):
        """'1' → (1, 0)；'1_122' → (1, 122)；返回 None 表示不是帧文件。"""
        parts = stem.split("_")
        if not parts or not parts[0].isdigit():
            return None
        idx = int(parts[0])
        hgt = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        return idx, hgt

    def _add(by_idx, path, stem):
        got = _split(stem)
        if not got:
            return
        idx, hgt = got
        pix = QPixmap(path)
        if pix.isNull():
            return
        by_idx.setdefault(idx, []).append((hgt or pix.height(), pix))

    try:
        entries = os.listdir(DSH_ACTS_DIR)
    except OSError:
        return acts

    for name in DSH_ACTS:
        by_idx = {}
        sub = os.path.join(DSH_ACTS_DIR, name)
        if os.path.isdir(sub):                       # ① 子目录
            try:
                names = os.listdir(sub)
            except OSError:
                names = []
            for fn in names:
                stem, ext = os.path.splitext(fn)
                if ext.lower() == ".png":
                    _add(by_idx, os.path.join(sub, fn), stem)
        if not by_idx:                               # ② 扁平
            for fn in entries:
                stem, ext = os.path.splitext(fn)
                if ext.lower() != ".png" or not stem.lower().startswith(name.lower() + "_"):
                    continue
                _add(by_idx, os.path.join(DSH_ACTS_DIR, fn), stem[len(name) + 1:])
        if by_idx:
            for i in by_idx:
                by_idx[i].sort(key=lambda t: t[0])
            acts[name] = by_idx
    return acts


def key_fingerprint(key):
    """Key 指纹：只用来认「还是不是同一个账号的账本」，不还原、不外传。"""
    key = (key or "").strip()
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:8] if key else ""


def balance_drop_reason(prev, delta, granted, gap_sec):
    """这次余额下降算不算用量？算用量返回 ""，不算就返回原因。

    不算用量的两种：
    1) 赠送额度整块消失（到期 / 被平台收回）——上一次 granted 有值，这次基本归零，
       而且下降额对得上那笔赠送；
    2) 一次刷新掉得太多（60 秒掉二十几块不可能是 API 用量），间隔长时按小时放宽。
    """
    pg = prev.get("lastGranted")
    if pg and granted is not None and delta >= 0.5:
        gone = float(pg) - float(granted)
        if gone > 0 and gone >= delta - 0.05 and float(granted) <= max(0.05, float(pg) * 0.02):
            return "赠送额度到期/被收回"
    limit = max(USAGE_JUMP_LIMIT, USAGE_JUMP_RATE * max(0.0, float(gap_sec)) / 3600.0)
    if delta > limit:
        return f"一次掉 ¥{delta:.2f}，超过 ¥{limit:.2f} 的可信上限"
    return ""


def record_balance_usage(path, total, currency, granted=None, topped_up=None,
                         key_id="", sample_ts=None):
    """小鲸鱼记账：只把余额下降记成当日消耗，跨天归零归档。

    币种变化、Key（账号）变化、赠额到期、异常跳变都只重置基准，不记成用量——
    否则平台侧的余额变动会变成"我今天用了两百多"。

    返回 {"today": 今日已用, "adjust": 今天没算进用量的余额变动,
          "amount": 这一次的变动额, "reason": 这一次的变动原因（没有就是空串）,
          "adjust_why": 今天最近一次变动的原因（给菜单说明用）}
    """
    now = (datetime.fromtimestamp(sample_ts) if sample_ts else datetime.now())
    today = now.strftime("%Y-%m-%d")
    prev = {}
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                prev = json.load(f) or {}
    except Exception:
        prev = {}

    prev_date = prev.get("date")
    last = prev.get("lastBalance")
    last_cur = prev.get("lastCurrency")
    prev_key = (prev.get("lastKeyId") or "").strip()
    today_usage = float(prev.get("todayUsage") or 0)
    today_adjust = float(prev.get("todayAdjust") or 0)
    hist = dict(prev.get("history") or {})
    log = list(prev.get("adjustLog") or [])[-20:]
    # 老账本没有 lastAdjustWhy 就从变动记录里补，菜单里那句说明才不会空着
    last_why = prev.get("lastAdjustWhy") or (log[-1].get("why", "") if log else "")
    last_at = prev.get("lastAdjustAt") or (log[-1].get("at", "") if log else "")
    reason = ""
    amount = 0.0

    if prev_date != today:
        # 跨天：把昨天的用量归档，今天的基准重新起
        if prev_date and today_usage:
            hist[prev_date] = round(today_usage, 4)
        hist = dict(sorted(hist.items())[-30:])
        today_usage, today_adjust, log, reason = 0.0, 0.0, [], ""
        last_why, last_at = "", ""        # 新的一天：昨天那笔变动的原因不再挂着
    elif last is not None and last_cur == currency and (not prev_key or not key_id or prev_key == key_id):
        delta = float(last) - float(total)
        if delta > 0:
            # 采样间隔：文件没写时间就用文件修改时间兜底
            try:
                last_ts = prev.get("lastSampleAt")
                prev_at = (datetime.fromisoformat(last_ts) if last_ts
                           else datetime.fromtimestamp(os.path.getmtime(path)))
            except Exception:
                prev_at = now
            why = balance_drop_reason(prev, delta, granted, (now - prev_at).total_seconds())
            if why:
                amount = delta
                reason = why
                last_why, last_at = why, now.isoformat(timespec="seconds")
                today_adjust = round(today_adjust + delta, 4)
                log.append({"at": now.isoformat(timespec="seconds"),
                            "amount": round(delta, 4), "why": why})
            else:
                today_usage = round(today_usage + delta, 4)

    # 以老账本为基础再覆盖我们管的字段：手工校准之类额外写进去的字段不会被抹掉
    data = dict(prev)
    data.update({
        "date": today,
        "lastBalance": total,
        "lastCurrency": currency,
        "lastGranted": granted,
        "lastToppedUp": topped_up,
        "lastKeyId": key_id or prev_key,
        "lastSampleAt": now.isoformat(timespec="seconds"),
        "todayUsage": round(today_usage, 4),
        "todayAdjust": round(today_adjust, 4),
        "history": hist,
        "adjustLog": log,
        "lastAdjustWhy": last_why,
        "lastAdjustAt": last_at,
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
    })
    try:
        # 先写临时文件再替换：中途出错也不会把账本写成半截（半截 JSON 会被当成空账本）
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        pass
    return {"today": float(data["todayUsage"]), "adjust": float(data["todayAdjust"]),
            "amount": amount, "reason": reason,
            "adjust_why": last_why, "adjust_at": last_at}


def calibrate_balance_usage(path, amount, why="手动校准"):
    """按主人看到的平台数字校准「今日已用」，账本里留一笔 calibrateLog。

    什么时候用：赠送额度到期、桌宠关着漏采了一段……这些情况下账本自己算不出当天真实用量，
    平台用量页的「消费金额」才是准的。只改 todayUsage，不动 todayAdjust 和余额基准。
    返回 {"today": 校准后的值, "was": 原来的值}。
    """
    amount = max(0.0, float(amount))
    prev = {}
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                prev = json.load(f) or {}
    except Exception:
        prev = {}

    now = datetime.now().isoformat(timespec="seconds")
    was = float(prev.get("todayUsage") or 0)
    log = list(prev.get("calibrateLog") or [])[-20:]
    log.append({"at": now, "from": round(was, 4), "to": round(amount, 4), "why": why})

    data = dict(prev)
    data.update({
        "date": prev.get("date") or datetime.now().strftime("%Y-%m-%d"),
        "todayUsage": round(amount, 4),
        "calibrateLog": log,
        "updatedAt": now,
    })
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        pass
    return {"today": round(amount, 4), "was": round(was, 4)}


def load_json(path, default):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                default,
                f,
                ensure_ascii=False,
                indent=4
            )
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception:
        return default


class ChatDialog(QDialog):
    """合体新增：DeepSeek 聊天输入框（自原版 1190fasheqi/dafeiyu-pet 移植）。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                            | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(420, 56)

        container = QFrame(self)
        container.setGeometry(0, 0, 420, 56)
        container.setStyleSheet("""
            QFrame {
                background: white;
                border-radius: 20px;
                border: 1px solid #e5e7eb;
            }
        """)

        layout = QHBoxLayout(container)
        layout.setContentsMargins(18, 0, 12, 0)
        layout.setSpacing(0)

        self.input = QLineEdit()
        self.input.setPlaceholderText("给大肥鱼发送消息")
        self.input.setStyleSheet("""
            QLineEdit {
                color: #1a1a1a;
                font-size: 15px;
                font-family: Arial, "Microsoft YaHei", sans-serif;
                border: none;
                background: transparent;
            }
        """)
        self.input.returnPressed.connect(self._on_submit)
        layout.addWidget(self.input)

        self.send_btn = QPushButton()
        self.send_btn.setFixedSize(32, 32)
        self.send_btn.setText("↑")
        self.send_btn.clicked.connect(self._on_submit)
        layout.addWidget(self.send_btn)
        self.input.textChanged.connect(lambda _t: self._set_btn_style(bool(self.input.text().strip())))
        self._set_btn_style(False)

    def _set_btn_style(self, active):
        color = "#5686fe" if active else "#b9c7ff"
        hover = "#4575ed" if active else "#a8b8f0"
        pressed = "#3a66d9" if active else "#9aacd9"
        self.send_btn.setStyleSheet(f"""
            QPushButton {{
                border-radius: 16px;
                background: {color};
                border: none;
                color: white;
                font-size: 20px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: {hover}; }}
            QPushButton:pressed {{ background: {pressed}; }}
        """)

    def _on_submit(self):
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.accept()
        if self.parent():
            self.parent()._call_ds(text)
            self.parent().chat_open = False

    def showEvent(self, event):
        self.input.setFocus()
        super().showEvent(event)

    def popup_at(self, x, y):
        self.move(int(x - self.width() / 2), int(y - self.height() - 10))
        self.show()
        self.raise_()

    def reject(self):
        if self.parent():
            self.parent().chat_open = False
        super().reject()


class FoodPanel(QWidget):
    """合体新增：喂食面板（自原版移植）。"""
    def __init__(self, on_pick):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(310, 64)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)
        for f in FOODS:
            b = QToolButton()
            b.setText(f)
            b.setFont(QFont("Segoe UI Emoji", 20))
            b.setFixedSize(44, 44)
            b.setStyleSheet(
                "QToolButton{background:rgba(255,255,255,235);border:2px solid #ffb3c8;"
                "border-radius:22px;} QToolButton:hover{background:#ffe3ec;border-color:#ff7fa8;}")
            b.clicked.connect(lambda _, x=f: on_pick(x))
            lay.addWidget(b)
        close = QToolButton()
        close.setText("✕")
        close.setFont(QFont("Microsoft YaHei UI", 12))
        close.setFixedSize(26, 26)
        close.setStyleSheet("QToolButton{background:rgba(255,255,255,200);border:none;border-radius:13px;color:#666;}"
                            "QToolButton:hover{background:#ff7fa8;color:#fff;}")
        close.clicked.connect(self.hide)
        lay.addWidget(close)
        self.setStyleSheet("FoodPanel{background:rgba(40,40,60,190);border-radius:14px;}")

    def popup_at(self, x, y):
        self.move(int(x - self.width() / 2), int(y - self.height() - 10))
        self.show()
        self.raise_()


class PetWindow(QWidget):
    # ---------- 城市（联网添加） ----------
    def auto_locate_city(self):
        """按 IP 联网定位城市（挂梯子时定位到的是节点所在地）。"""
        self.say("我上网找找你在哪儿哦…")
        threading.Thread(target=lambda: self._city_queue.append(to_chinese_city(locate_city_by_ip())),
                         daemon=True).start()

    def search_city_dialog(self):
        """联网搜索城市：先查地理编码，查不到就用天气接口验证这个名字能不能用。"""
        with self._ui_guard():
            name, ok = QInputDialog.getText(self, "添加城市", "输入城市名（联网搜索）:",
                                            QLineEdit.EchoMode.Normal, "",
                                            Qt.WindowType.WindowStaysOnTopHint)
        if not ok or not name.strip():
            return
        self.say("我查查这个城市哦…")
        threading.Thread(target=lambda: self._city_pick_queue.append(lookup_city(name)),
                         daemon=True).start()

    def _apply_city(self, name):
        self.cfg["city"] = name
        # 顺手记进"城市列表"，之后菜单里可以直接点着切换。
        # 刚选中的这个排**最前面**（列表的第一位永远是当前城市，一眼看到自己在用哪个）
        others = [c for c in (self.cfg.get("city_list") or []) if c and c != name]
        self.cfg["city_list"] = ([name] + others)[:12]   # 最多留 12 个，别越堆越长
        self.save_config()              # 立刻落盘，下次启动就是这个默认城市
        self.say(f"好咯，城市换成{name}啦")
        self._get_weather()
        self._notify_console()          # 设置窗口开着的话，那一排城市立刻跟上

    def cities_ordered(self):
        """城市列表：**当前城市永远排最前面**，其余保持原顺序、不重复。

        菜单和设置页都读这个 —— 不管 config.json 里是怎么排的（老配置的当前城市
        可能躺在最后），显示出来总是"选中的那个在第一"。
        """
        cur = (self.cfg.get("city") or "").strip()
        out = []
        for c in ([cur] if cur else "") + list(self.cfg.get("city_list") or []):
            if c and c not in out:
                out.append(c)
        return out

    def remove_city_dialog(self):
        """从城市列表里删掉一个（最后一个删不掉，总得留一个用）。"""
        cities = self.cities_ordered()
        if len(cities) <= 1:
            self.say("就剩这一个城市啦，删下去可要空咯")
            return
        with self._ui_guard():
            pick, ok = QInputDialog.getItem(self, "删除城市", "删掉哪个城市？", cities,
                                            0, False, Qt.WindowType.WindowStaysOnTopHint)
        if not ok or not pick:
            return
        left = [c for c in cities if c != pick]
        self.cfg["city_list"] = left
        if self.cfg.get("city") == pick:
            # 城市列表是"当前的在最前"，删掉当前的就顶最前面那个上来
            self.cfg["city"] = left[0] if left else self.cfg.get("city", "北京")
        self.save_config()
        self.say(f"{pick} 拿走咯")
        self._notify_console()

    def set_city_dialog(self):
        """手动设置默认城市：直接写进 config.json，不联网、不用等搜索。"""
        with self._ui_guard():
            city, ok = QInputDialog.getText(
                self,
                "设置默认城市",
                "输入城市名（中文英文都行，例如：汕头 / Shantou）:",
                QLineEdit.EchoMode.Normal,
                self.cfg.get("city", "北京"),
                Qt.WindowType.WindowStaysOnTopHint
            )
        if ok and city.strip():
            self._apply_city(city.strip())
        elif ok:
            self.say("城市名总得写一个嘛")

    # ---------- 配置 ----------
    def save_config(self):
        """把当前配置写回 config.json。"""
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, ensure_ascii=False, indent=2)
            self._cfg_snapshot = json.dumps(self.cfg, ensure_ascii=False, sort_keys=True)
        except Exception as ex:
            print("配置保存失败:", repr(ex))

    def autosave_config(self):
        """配置有变化就顺手存一下，不用等到退出（被杀掉也不丢设置）。"""
        try:
            now_snap = json.dumps(self.cfg, ensure_ascii=False, sort_keys=True)
        except Exception:
            return
        if now_snap != getattr(self, "_cfg_snapshot", None):
            self.save_config()

    def __init__(self):
        # 菜单排查日志：每次启动重新写，免得越积越大
        if MENU_DEBUG:
            try:
                with open(MENU_DEBUG_LOG, "w", encoding="utf-8") as f:
                    f.write(f"=== 大肥鱼桌宠 菜单日志 {datetime.now():%Y-%m-%d %H:%M:%S} ===\n")
            except Exception:
                pass

        # 默认配置；老 config.json 缺的新键会自动补上（免得升级后 KeyError）
        cfg_defaults = {
            "mode": "wander",
            "size": 0.7,
            "topmost": True,
            "passthrough": False,
            "autostart": False,
            "x": None,
            "y": None,
            "ds_api_key": "",
            "city": "北京",
            "city_list": [],
            "balance_always": False,
            "snap_on": True,
            "flip_on_left": True,
            "locked": False,          # 锁定位置：开了就拖不动（防误触），点击 / 菜单照旧
            "turn_cost_on": True,
            "skin": SKIN_PET,
            "sound_on": True,
            "sound_set": "小黄鸭",
            "volume": 0.9,
            "show_peak": True,
            "peak_style": "默认",
            "bubble_style": "auto",     # 气泡风格：跟随界面 / 浅色 / 深色
            "line_freq": LINE_FREQ_DEFAULT,
            "lyric_offset": LYRIC_OFFSET_DEFAULT,
            "layer": "top",
            "opacity": 1.0,
            "process_alerts": True,
            # 自动说话（都在「设置 → 应用联动」里改）：
            #   用久了提醒 / 到点说一句 / 全局快捷键
            "app_time_on": True,
            "app_time_lines": app_time_default_rules(),
            "timed_on": True,
            "timed_lines": clone_rules(CLOCK_LINES_DEFAULT),
            "hotkeys_on": True,
            "hotkeys": clone_rules(HOTKEYS_DEFAULT),
            # 说话时机：离开回来打招呼 / 全屏（打游戏看电影）时闭嘴
            "back_greet": True,
            "fullscreen_silent": True,
            # 百宝箱的小工具：免打扰默认时长
            "quiet_minutes": QUIET_DEFAULT_MIN,
            "music_link": True,
            "music_lyrics": True,
            "perf_mode": True,
            "custom_skins": {},
            "skin_library": {"pet": [], "widget": []},   # 两本分开：三维形象 / 挂件形象
            "skin_draft": {},                             # 三维形象没挑完的三张图
            "skin_pick_dir": "",
            "balance_source": "DeepSeek",
            "other_keys": [],
            "double_click": DOUBLE_CLICK_DEFAULT,     # 快速双击弹哪个窗口（余额/天气/在放什么/台词/喂食）
            "sys_monitor_on": True,               # 合体新增：CPU/内存/显卡超阈值提醒
            "dsh_link": True,                     # 合体新增：跟着 DSH 干活做反应
            "dsh_debug": False,                   # 合体新增：DSH 联动排查日志
            "sing_on": True,                      # 合体新增：放歌时换成唱歌立绘
            "custom_process_lines": {},
            "default_line_overrides": {},
            "custom_lines": {},
            "lines_off": [],                          # 关掉的「语录板块」（见 LINE_SECTIONS）
            "agent_name": "Codex",
            "agent_sessions_dir": "",
            "codex_sessions_dir": CODEX_SESSIONS_DIR,
            "menu_debug": False,
            "custom_sounds": {},
            "still_face_cursor": False,
            "mem_skip_foreground": True,    # 百宝箱·回收内存：不动前台程序（防卡顿）
            # 设置窗口自己的样子（背景 / 标题 / 图标）。跟桌宠本体无关，
            # 全是 ui_console.BACKDROP_DEFAULTS 里那几个键，界面那边负责读写。
            "console_bg_path": "",
            "console_bg_fit_window": True,
            "console_bg_focus": "cc",
            "console_bg_bright": 0,
            "console_bg_blur": 0,
            "console_bg_scrim": 34,
            "console_brand_title": "大肥鱼桌宠",
            "console_logo_path": "",
            "console_accent": "",
            "console_card_alpha": 100,
            "console_card_radius": 12,
            "console_remember_geo": True,
            "console_geo": "",
            "console_start_page": "balance"
        }
        self.cfg = load_json(CONFIG_PATH, dict(cfg_defaults))
        for cfg_key, cfg_value in cfg_defaults.items():
            self.cfg.setdefault(cfg_key, cfg_value)
        # 界面配色一上来就按配置定下来：气泡风格选「跟随界面」时要看这个亮暗，
        # 老对话框取主题色也走同一套 —— 以前是等设置窗口建出来才 set_mode，
        # 那样"刚启动、还没开过设置"的时候气泡会按系统的亮暗走，不是主人选的那档。
        if ui_console is not None:
            try:
                ui_console.set_mode(self.cfg.get("ui_theme", "system"))
            except Exception:
                pass
        # 菜单排查日志可以像开关一样存在 config.json 里（菜单里那一项用的）
        global MENU_DEBUG_RUNTIME
        MENU_DEBUG_RUNTIME = bool(self.cfg.get("menu_debug", False))
        # DSH 联动排查日志（config 里 dsh_debug 打开）
        global DSH_DEBUG
        DSH_DEBUG = bool(self.cfg.get("dsh_debug", False))
        if DSH_DEBUG:
            try:
                with open(DSH_DEBUG_FILE, "w", encoding="utf-8") as _f:
                    _f.write("=== DSH 调试日志 %s ===\n"
                             % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            except Exception:
                pass
        if MENU_DEBUG_RUNTIME:
            try:
                with open(MENU_DEBUG_LOG, "w", encoding="utf-8") as f:
                    f.write(f"=== 大肥鱼桌宠 菜单日志 {datetime.now():%Y-%m-%d %H:%M:%S} ===\n")
            except Exception:
                pass
        self._cfg_snapshot = None
        
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self.cfg.get("topmost", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # v1.0.10：二三级菜单点击的"摆渡"（这台 Windows 会把落在子菜单上的点击送给上层菜单）
        self._click_bridge = MenuClickBridge(self)
        _app = QApplication.instance()
        if _app is not None:
            _app.installNativeEventFilter(self._click_bridge)
            # 全局快捷键也走原生消息（WM_HOTKEY），跟菜单那套一样在过滤器里收
            self._hotkey_bridge = HotkeyBridge(self)
            _app.installNativeEventFilter(self._hotkey_bridge)
        self.setMouseTracking(True)      # 菜单开着时要靠这个收鼠标移动消息（见 _forward_mouse_to_menu）
        self.setWindowTitle("大肥鱼桌宠")
        
        # 精灵加载（三视图 + 挂件，每一张都可以被用户自定义图片替换）
        self.sprites = {}
        self.custom_skin_ok = {}
        self._base_cache = {}             # 原始大图（裁过透明边）的缓存：无级调节要反复缩放，不能每次都读盘
        self._migrate_skin_library()      # 老配置里直接存的图片路径 → 搬进「我的形象库」
        self._rebuild_sprites()
        self.icon = QIcon(os.path.join(SPRITE_DIR, "icon.png"))

        self.skin = self.cfg.get("skin", SKIN_PET)
        if self.skin not in (SKIN_PET, SKIN_WIDGET) or (self.skin == SKIN_WIDGET
                                                        and not self._has_sprite("挂件")):
            self.skin = SKIN_PET

        self.cfg["size"] = self._clamp_size(self.cfg["size"])
        self.cur_h = int(340 * self.cfg["size"])
        # 老配置里存的是无级调节调出来的高度（不在五档上）时，得把那个高度的精灵补上，
        # 否则第一帧就没图可画
        self._ensure_sprites(self.cur_h)
        self._apply_window_size()

        # 状态
        self.mode = self.cfg["mode"] if self.cfg["mode"] in ("wander", "follow", "still") else "wander"
        self.dir = "down"
        self.facing = 1
        # 「原地待着」时要不要跟着鼠标转（只管朝向、不挪窝；默认不要）
        self.still_face_cursor = bool(self.cfg.get("still_face_cursor", False))
        self.target = None
        self.rest_until = 0
        self.cur_speed = 0.0
        self.prev_key = None
        self.cross_t = 0.0
        self.action = None
        self.action_t = 0.0
        self.bubble_text = ""
        self.bubble_until = 0
        self.bubble_inner = False
        self.last_speak_tick = 0
        self.t = 0
        self.jump_t = 0
        self.dragging = False
        self._drag_blocked = False   # 锁定时按着划了一下（不算点击、也不挪窝）
        self.drag_offset = None
        self.drag_start_pos = None
        self.last_line = ""
        self.last_press_pos = None

        # 合体新增：AI 对话 / 喂食 / 系统监控 状态
        self.chat_history = []       # 对话历史（最近 40 条记忆）
        self.ds_busy = False         # 正在等 DeepSeek 回复
        self.chat_open = False       # 聊天框开着（预留，供停步使用）
        self.last_system_check = 0.0 # 系统监控上次检查的时刻（墙钟秒）
        self.chat_dialog = ChatDialog(self)
        self.food_panel = FoodPanel(self.on_food)

        # 合体新增：DSH 联动状态
        self.dsh_on = bool(self.cfg.get("dsh_link", True))
        self.sing_on = bool(self.cfg.get("sing_on", True))
        self._dsh_queue = []         # 后台线程 → 主线程
        self._dsh_busy = False
        self._dsh_file = None        # 当前盯着的会话日志
        self._dsh_mtime = 0.0
        self._dsh_state = None       # 上一次的状态
        self._dsh_said_at = 0.0      # 上次因 DSH 冒话的时刻（给工具台词限流）
        self._dsh_idle_said = False
        self._dsh_last_tool = None   # 上一次的工具名（换了就立刻反应）
        # 增量读取用（只有后台线程动它们）：读到哪、累计状态
        self._dsh_w_file = None
        self._dsh_w_off = 0
        self._dsh_w_st = dsh_blank_state()
        # 合体新增：动作帧（你画好的立绘放 sprites/dsh/）；没画就退回三视图
        self.dsh_acts = load_dsh_acts()
        self._apply_window_size()    # 动作帧可能更宽，这里按新宽度重算一次窗口
        self.dsh_act = None          # 当前在播的动作名
        self.dsh_act_t = 0.0         # 已经播了多久（毫秒）
        self.dsh_act_until = 0.0     # 播到什么时候结束（0 = 一直播）
        self._dsh_act_prev = None    # 上一个动作的当前帧（切动作时交叉淡化用）

        # 余额挂件状态
        self.balance = None          # {"total": 24.05, "currency": "CNY", "today": 0.0, "stale": False}
        self.bal_until = 0.0         # 余额泡泡显示截止时间（秒）
        self.balance_always = bool(self.cfg.get("balance_always", False))
        self.show_peak = bool(self.cfg.get("show_peak", True))
        self.peak_style = self.cfg.get("peak_style", "默认")
        self.bubble_style = self.cfg.get("bubble_style", "auto")
        if self.bubble_style not in dict(BUBBLE_STYLES):
            self.bubble_style = "auto"
        self.line_freq = (self.cfg.get("line_freq")
                          if self.cfg.get("line_freq") in LINE_FREQ_LEVELS else LINE_FREQ_DEFAULT)
        try:
            self.lyric_offset = float(self.cfg.get("lyric_offset", LYRIC_OFFSET_DEFAULT))
        except (TypeError, ValueError):
            self.lyric_offset = LYRIC_OFFSET_DEFAULT
        if self.peak_style not in PEAK_TEXT_STYLES:
            self.peak_style = "默认"
        self._peak_now = None
        self.layer = self.cfg.get("layer", "top")
        if self.layer not in ("top", "bottom", "normal"):
            self.layer = "top"
        self.opacity = float(self.cfg.get("opacity", 1.0) or 1.0)
        self.process_alerts = bool(self.cfg.get("process_alerts", True))
        self._running_procs = None      # 第一次扫描只记录，不冒泡
        self._last_proc_say = 0.0
        self._foreground_proc = None     # 上一次的前台应用
        self._proc_said_at = {}          # 每个应用上次吐槽的时间

        # 用久了提醒：连续在前台待的时间（只在"有人在动键鼠"的时候累计）
        self._fg_exe = None
        self._fg_accum = 0.0             # 这一轮累计了多少秒（换应用就清零）
        self._fg_clock = 0.0             # 上一次结算的时刻
        self._fg_count = 0               # 这一轮已经提醒过几次
        # 到点说一句：每条规则上次说的时刻（每天/每周记 "日期 时刻"，每隔记时间戳）
        self._timed_last = {}
        # 全局快捷键
        self._hotkey_ids = []            # 已经注册上的热键 id
        self._hotkey_slots = {}          # 热键 id → 那条规则（按键 / 动作 / 台词）
        self._hotkey_failed = []         # 注册失败（被别的程序占用）的键
        self._app_time_queue = []        # 扫到的应用列表（后台线程 → 主线程）

        # 音乐联动状态（QQ音乐 / 网易云）
        self.music_on = bool(self.cfg.get("music_link", True))
        self.music_lyrics = bool(self.cfg.get("music_lyrics", True))
        self.perf_mode = bool(self.cfg.get("perf_mode", True))   # True=性能模式（动画优先）
        # 每帧时长：性能模式 50 帧，休闲模式 25 帧（动作按同一个时钟换算，速度不变）
        self.tick_ms = TICK if self.perf_mode else TICK * 2
        self.now_playing = None          # {"app","title","artist","playing","position",...}
        self._music_queue = []           # 后台线程 → 主线程
        self._music_busy = False
        self._music_manual = False       # 菜单里点了"立刻看一眼"，结果要回话
        self._music_said_at = 0.0        # 换歌冒泡的节流
        self._music_played = 0.0         # 播放器不给进度时，按实际播放时长累加
        self._music_tick_at = 0.0        # 上一次累加的时刻
        self._bal_peek_until = 0.0       # 放歌时快速双击 → 临时看余额
        self._peek_pending = False        # 双击要的那一眼，等余额回来再冒泡
        self._key_hint_shown = False      # "没配 Key，双击看不了余额"这句每次启动只提醒一次
        self._last_click_ms = -99999     # 快速双击判定（墙上时间，毫秒）
        self._single_pending = None      # 单击欠着的那句台词：(到点秒, 说话函数)，双击就撤销
        self._dc_hold_until = 0.0        # 双击之后这几秒不让自言自语插嘴（别盖住刚弹的那一眼）
        self._trigger_until = 0.0        # 触发类的话说到什么时候：这段时间里闲话让位（见 say）
        self._bal_wait_until = 0.0       # 余额泡泡等"触发类的话"说完再顶上来（见 show_balance_bubble）
        self._bal_wait_secs = 0.0
        # 免打扰 / 全屏闭嘴：这期间"提醒"攒着，结束后汇报（见 _say_reminder）
        self._quiet_until = 0.0          # 免打扰到什么时候（内部时钟秒；0 = 没开）
        self._held_lines = []            # 免打扰 / 全屏期间攒下来的提醒
        self._fs_now = False             # 前台现在是不是全屏（游戏 / 电影）
        self._fs_since = 0.0
        # 离开回来打招呼
        self._away_flag = False
        self._away_at = 0.0
        # 番茄钟删了（主人 2026-09-14：「番茄钟这个功能好鸡肋，删了」）：
        # 老 config.json 里可能还留着这两个键，顺手清掉，别让配置里躺着死键
        self.cfg.pop("pomo_work", None)
        self.cfg.pop("pomo_break", None)
        # 应用时长账本（今天每个应用用了多久，给"每日小结"用）
        self._app_day, self._app_book = load_app_time(APP_TIME_PATH)
        self._app_flush_at = time.time() + APP_TIME_FLUSH_S
        self._proc_lines_cache = None    # 「打开应用时冒泡」的合并台词表（改了就作废）
        self._lyric_key = ""             # 当前歌「歌名|歌手」
        self._lyric_lines = []           # [(秒, 词)]
        self._lyric_words = {}           # {这句开始秒: [(字, 这个字的开始秒), ...]}（有逐字歌词时才有）
        self._lyric_queue = []           # 后台线程找回来的歌词
        self._lyric_fetching = ""        # 正在找歌词的那首
        self._lyric_cache = load_lyric_cache()
        self._lyric_retry_at = 0.0       # 歌词没抓到时的重试时间
        self._music_pos_memo = {}        # 歌 → 上次放到哪（暂停/切走再回来接着走）
        self._music_gone_at = 0.0        # 媒体会话消失的时刻（网易云暂停可能整个会话都没了）
        self._music_paused_at = 0.0      # 最近一次"看到暂停"的时刻（气泡留着 3 分钟好点继续）
        self._music_cmd_busy = False     # 正在切播放/暂停/上下首（连着点只算一次）
        self._music_cmd_queue = []       # [(点的是哪颗, 成没成)]（后台线程 → 主线程）
        self._lyric_btn_rects = {}       # 歌词气泡右上角那几颗按钮的位置（{kind: QRectF}）
        self._lyric_btn_hover = None     # 鼠标正划在哪颗按钮上（None = 都没划）
        self._lyric_btn_pressed = None   # 正按着哪颗按钮
        self._press_on_lyric_btn = None  # 这一下按在按钮上（不是点桌宠），存的是哪一颗
        self._music_no_progress = False   # 这个播放器不报时间轴（网易云）→ 只显示歌名，不猜歌词
        self._lyric_nudge = 0.0          # 这首歌的歌词微调（秒，正数=歌词往前赶）
        self._lyric_nudges = {}          # 歌 → 微调值（每首歌记住自己的）
        self._lyric_shown = ""           # 现在气泡里显示的是哪一句
        self._lyric_prev = ""            # 上一句（换句动画用）
        self._lyric_anim_t = 0.0         # 换句动画进度（1 → 0）
        self._lyric_prev_h = 0.0         # 上一句时气泡多高（过渡期间高度平滑变化）
        self._lyric_last_h = 0.0         # 最近一次画出来的气泡高度
        self._lyric_prev_w = 0.0         # 上一句时气泡多宽（过渡期间宽度也平滑变化）
        self._lyric_last_w = 0.0         # 最近一次画出来的气泡宽度
        self._bub_w = 0.0                # 气泡当前（动画中）的宽
        self._bub_h = 0.0                # 气泡当前（动画中）的高
        self._bub_target = (0.0, 0.0)    # 目标宽高（每帧由绘制算出来）
        self._bub_t = None               # 上一帧的时间（用来按真实帧间隔推进动画）
        self._lyric_timer = QTimer(self)  # 过渡期间专用：100 帧/秒
        self._lyric_timer.setInterval(LYRIC_ANIM_MS)
        self._lyric_timer.timeout.connect(self._lyric_anim_step)
        self._lyric_timer.stop()

        # 菜单悬停兜底（见 _menu_hover_watch）
        self._hover_key = None
        self._hover_since = 0.0
        self._hover_subs = {}            # 我替它弹出来的子菜单 → {"at": 上次光标在里面的时间, "pos": 弹出位置}
        self._sub_parent = {}            # 子菜单 → (上一层菜单, 触发它的那一项)，补弹时要用
        self._sub_of = {}                # 带子菜单的项 → 它的子菜单（Qt 那边已摘掉，改由浮窗显示）
        self._leave_at = 0.0             # 光标离开"项/子菜单"的时间（0.35 秒宽限用）
        self._keep = None                # 当前保持打开的是哪一项的子菜单（菜单, 项）
        self._sub_rect = {}              # 各子菜单最后一次显示的位置/大小（被 Qt 收掉后判断"光标还在不在附近"）
        self._resub = {}                 # 各子菜单"被收掉后补了几次"的计数
        self._flyout = None              # 二级/三级菜单的浮窗（普通窗口，点击一定生效）
        self._flyout_action = None       # 当前浮窗对应的是哪一项
        self._flyout_leave_at = 0.0      # 光标离开浮窗的时间（用来延时收起）
        self._menu_pool = []             # 最近建过的菜单，用来判断"还有菜单开着吗"
        self._dialog_open = False        # 对话框（设置 Key / 加城市…）开着
        self._through_applied = None     # 上一次实际设过的鼠标穿透状态
        self._forwarding_move = False    # 正在给菜单转发鼠标移动（防递归）

        self._last_pos = (0, 0)          # 卡住自检用
        self._stuck_ticks = 0
        self.snap_on = bool(self.cfg.get("snap_on", True))
        self.flip_on_left = bool(self.cfg.get("flip_on_left", True))
        self.locked = bool(self.cfg.get("locked", False))    # 锁定位置：拖不动，但点击 / 菜单照常
        self.turn_cost_on = bool(self.cfg.get("turn_cost_on", True))
        self.bal_busy = False
        self.bal_error = ""
        self._bal_queue = []         # 后台线程 → 主线程的余额结果
        self._pending_bubbles = []   # [(到点秒, 文本, 是否心声)]
        self.roll_shown = None       # 数字滚动当前值
        self.roll_from = None
        self.roll_to = None
        self.roll_t = 1.0
        self.press_t = 0.0           # 按压 Q 弹
        self.flip_x = False          # 整体水平翻转（左吸附）
        self.snap_h = None           # 吸附锚点：left / right
        self.snap_v = None           # top / bottom
        self.ui_open = False         # 右键菜单 / 对话框开着时，桌宠站住不动

        # 音效
        self.sound_on = bool(self.cfg.get("sound_on", True))
        self.sound_set = self.cfg.get("sound_set", "小黄鸭")
        self.volume = float(self.cfg.get("volume", 0.9))
        self._sounds = {}
        self._sound_idx = {}
        self._pending_sounds = []
        self._click_clips = pick_click_clips()
        # 主人自己加的音效（文件放在用户目录的 sounds/ 下，路径记在 config.json 里）
        self._custom_sounds = {}
        for _s_name, _s_path in (self.cfg.get("custom_sounds") or {}).items():
            if _s_path and os.path.exists(_s_path):
                self._custom_sounds[_s_name] = _s_path
                self._click_clips[_s_name] = _s_path
        # 常开音频流（首选）：设备一直是醒的，点下去立刻出声、开头不会被吞
        self._click_player = None
        if AUDIO_AVAILABLE:
            player = ClickPlayer(self)
            if player.ok:
                for clip_name, clip_path in self._click_clips.items():
                    player.load_clip(clip_name, clip_path)
                self._click_player = player
            else:
                player.deleteLater()
        self._init_sounds()
        # 系统默认播放设备变了（插耳机 / 切蓝牙音箱）→ 重开音频流，点击音跟着走。
        # 注意：这个 PySide6 版本的 QMediaDevices 没有 defaultAudioOutputChanged 信号，
        # 所以干脆每 2 秒自己查一次（有信号的话也顺手接上）。
        self._audio_dev_id = None
        self._audio_dev_watched = False
        self._audio_dev_timer = QTimer(self)
        self._audio_dev_timer.timeout.connect(self._check_audio_device)
        self._audio_dev_timer.start(500)          # 兜底轮询：0.5 秒一次（原来 2 秒，插耳机要等太久）
        # 有信号就直接用信号：插耳机 / 切蓝牙音箱时 QMediaDevices 会立刻发 audioOutputsChanged
        try:
            self._devices = QMediaDevices(self)
            self._devices.audioOutputsChanged.connect(self._on_audio_output_changed)
        except Exception:
            self._devices = None
        QTimer.singleShot(1200, self._check_audio_device)
        
        # 后台线程 → 主线程的结果队列
        self._say_queue = []          # 要冒泡的文本
        self._city_queue = []         # 自动定位结果
        self._city_pick_queue = []    # 城市搜索候选
        self._app_queue = []          # 扫描到的本机应用列表
        self._mem_queue = []          # 内存回收结果（后台线程 → 主线程）
        self._mem_trimming = False    # 正在回收：连着点就只提醒一句
        self._mem_last = None         # (程序数, 腾出字节)：菜单里那行"上次…"

        # 每轮 Codex 对话消耗（读 Codex 会话日志的 token 用量）
        self.agent_name = (self.cfg.get("agent_name") or "Codex").strip() or "Codex"
        self.agent_dir = (self.cfg.get("agent_sessions_dir")
                          or self.cfg.get("codex_sessions_dir") or CODEX_SESSIONS_DIR)
        self.codex_dir = self.agent_dir
        self._codex_file = None
        self._codex_pos = 0
        self._codex_turn = None
        self._codex_tokens = {}
        self._codex_reported = set()
        self._codex_last_change = 0.0
        self.cdx_timer = QTimer(self)
        self.cdx_timer.timeout.connect(self.scan_codex_usage)
        self.cdx_timer.start(CODEX_SCAN_MS)

        # 有些窗口（比如 Codex）自己也置顶，会盖住桌宠：定期把自己顶到置顶层最前面（不抢焦点）
        self.top_timer = QTimer(self)
        self.top_timer.timeout.connect(self._keep_on_top)
        self.top_timer.start(2000)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(self.tick_ms)

        # 余额：60 秒自动刷新 + 启动后先取一次
        self.bal_timer = QTimer(self)
        self.bal_timer.timeout.connect(lambda: self.refresh_balance(silent=True))
        self.bal_timer.start(BALANCE_TTL * 1000)
        QTimer.singleShot(1200, lambda: self.refresh_balance(silent=False))

        self.bubble_font = QFont("Microsoft YaHei UI", 11)

        # 设置窗口：懒加载，点「打开设置…」才建，别拖慢启动
        self._console = None

        # 托盘
        self.tray = QSystemTrayIcon(self.icon, self)
        # 注意：QSystemTrayIcon 不接管菜单所有权，这里必须自己留引用，
        # 否则菜单会被 Python 回收，托盘右键就再也弹不出来了（穿透也因此解不开）。
        self._tray_menu = self._make_menu()
        self.tray.setContextMenu(self._tray_menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

        x, y = self.cfg.get("x"), self.cfg.get("y")
        if x is None or y is None:
            screen = QApplication.primaryScreen().availableGeometry()
            x = screen.right() - self.width() - 80
            y = screen.bottom() - self.height() - 60
        self.move(int(x), int(y))
        self.show()
        self.snap_into_screen()
        QTimer.singleShot(1500, self.warm_up_sounds)   # 音频设备预热，消掉首次点击的延迟
        self.setWindowOpacity(self.opacity)
        QTimer.singleShot(300, self._apply_layer)       # 层级要在窗口真正显示之后再摆
        if self.cfg.get("passthrough", False):
            self._apply_passthrough(True)
            # 开机就是穿透状态的话，顺手提醒一下怎么解除
            QTimer.singleShot(2500, lambda: self.say(
                "我现在是穿透状态哦：右键托盘图标 → 鼠标穿透，或者双击托盘图标就能把我捞回来"))

        # 自定义形象的原图被删 / 被挪走了：启动时提醒一次（菜单和形象库里也会标出来）
        gone = []
        pet_now = self.pet_skin_entry()
        if pet_now:
            missing_pet = self.skin_missing_views("pet", pet_now)
            if missing_pet:
                gone.append("三维形象的" + "、".join(VIEW_SHORT[v] for v in missing_pet) + "那张")
        if self.custom_skin_missing("widget"):
            gone.append("挂件形象的那张")
        if gone:
            QTimer.singleShot(3400, lambda: self.say(
                f"{'、'.join(gone)}图找不到啦（被删掉或者挪走了）：右键 → 形象 → 我的形象库…",
                seconds=5.0))

        # 进程联动：打开某些应用时冒个泡
        self.proc_timer = QTimer(self)
        self.proc_timer.timeout.connect(self.check_processes)
        self.proc_timer.start(2000)

        # 合体新增：系统监控（CPU / 内存 / 显卡超阈值冒泡提醒，10 秒一次）
        self.sys_monitor_timer = QTimer(self)
        self.sys_monitor_timer.timeout.connect(self.check_system_status)
        if self.cfg.get("sys_monitor_on", True):
            self.sys_monitor_timer.start(10000)

        # 合体新增：DSH 联动（每 0.7 秒看一次会话日志，读文件在后台线程）
        self.dsh_timer = QTimer(self)
        self.dsh_timer.timeout.connect(self.poll_dsh)
        if self.dsh_on:
            self.dsh_timer.start(700)

        # 全局快捷键：注册到主线程（按下时走 HotkeyBridge，见文件开头那个类）
        self._register_hotkeys()

        # 音乐联动：定时看一眼 QQ音乐 / 网易云 在放什么（读取在后台线程，不卡界面）
        self.music_timer = QTimer(self)
        self.music_timer.timeout.connect(self.poll_music)
        self.music_timer.start(MUSIC_POLL_MS)
        QTimer.singleShot(2600, self.poll_music)

        # 菜单悬停兜底：Windows 有时不把鼠标移动消息送给弹出菜单（二级菜单因此不弹）
        self.hover_timer = QTimer(self)
        self.hover_timer.timeout.connect(self._menu_tick)
        self.hover_timer.start(MENU_HOVER_MS)

    # ---------- 音乐联动 ----------
    def poll_music(self):
        """后台线程读一次系统媒体会话。"""
        if not self.music_on or self._music_busy:
            return
        self._music_busy = True
        use_smtc = smtc_available()

        def worker():
            info = read_media_session() if use_smtc else None
            if info is None or not info.get("title"):
                # 退路：读不到媒体会话、或者会话没给歌名时，看播放器窗口标题
                info = merge_media_info(info, read_music_window())
            self._music_queue.append(info)

        threading.Thread(target=worker, daemon=True).start()

    def _song_label(self, info=None):
        info = info if info is not None else (self.now_playing or {})
        # 播放器给的信息可能不全（网易云实测会缺）：缺什么就用占位，命名风格保持一致
        title = (info.get("title") or "").strip() or TITLE_PLACEHOLDER
        artist = (info.get("artist") or "").strip() or ARTIST_PLACEHOLDER
        return f"《{title}》——{artist}"

    @staticmethod
    def _app_label(info=None):
        """气泡顶上那个应用名。

        三级兜底：认出来的中文名 → 原始标识再认一次 → 把标识收拾成人能看的样子。
        只有连标识都没有时才会是「未知应用」。
        """
        info = info or {}
        name = (info.get("app") or "").strip()
        if name:
            return name
        raw = (info.get("app_id") or "").strip()
        return music_app_name(raw) or app_name_from_id(raw) or APP_PLACEHOLDER

    def _music_playing(self):
        info = self.now_playing
        return bool(self.music_on and info and info.get("playing") and info.get("title"))

    def _music_paused(self):
        """放着一首歌、但现在是暂停。

        暂停之后**气泡先不撤**（`PAUSED_BUBBLE_SEC` 之内都留着），这样右上角那颗 ▶
        还有地方点；超过这个时间就照旧收起来，免得屏幕上一直挂着一块歌词。
        """
        info = self.now_playing
        if not (self.music_on and info and info.get("title") and not info.get("playing")):
            return False
        at = getattr(self, "_music_paused_at", 0.0)
        return bool(at) and (time.time() - at) < PAUSED_BUBBLE_SEC

    def music_command(self, kind):
        """气泡右上角那三颗按钮：⏮ 上一首 / ⏸▶ 播放暂停 / ⏭ 下一首。

        都走同一套系统媒体会话（SMTC），QQ音乐 / 网易云都认，点完由后台线程
        去问播放器，结果回到主线程再刷新气泡（图标才翻得过来）。
        """
        if kind not in ("prev", "toggle", "next"):
            return
        if not self.music_on or not self.now_playing:
            return
        if self._music_cmd_busy:
            return
        self._music_cmd_busy = True
        # 按一下晃晃尾巴，手感上有个回应（真结果等后台回来）
        self.action, self.action_t = "sway", 0.6
        threading.Thread(target=self._music_cmd_worker, args=(kind,),
                         daemon=True).start()

    def toggle_music_playpause(self):
        """气泡右上角那颗 ⏸ / ▶：切一下当前播放器的播放 / 暂停。"""
        self.music_command("toggle")

    def _music_cmd_worker(self, kind):
        try:
            if kind in ("prev", "next"):
                ok = bool(skip_media(kind))
            else:
                ok = bool(toggle_media_playpause())
        except Exception:
            ok = False
        finally:
            self._music_cmd_queue.append((kind, ok))

    def _music_cmd_tick(self):
        """处理"切播放/暂停 / 上下首"的结果（主线程里跑）。"""
        if not self._music_cmd_queue:
            return
        kind, ok = self._music_cmd_queue.pop(0)
        self._music_cmd_busy = False
        if not ok:
            self.say("诶…播放器没理我，你手动点一下吧", seconds=3.0, again=True)
            return
        self.poll_music()                # 立刻看一眼新状态（图标马上翻过来）
        self.update()
        if kind in ("prev", "next"):
            # 切歌是播放器自己去做的，刚切完那一下它可能还报着上一首的元信息，
            # 等它缓过神来再读一次（不然气泡和歌词会停在上一首上）。
            QTimer.singleShot(700, self.poll_music)

    def _lyric_btn_kind(self, pos):
        """这个坐标点在哪颗按钮上（"prev" / "toggle" / "next"）；没点着返回 None。"""
        for kind, rect in (getattr(self, "_lyric_btn_rects", None) or {}).items():
            if rect is not None and rect.contains(pos):
                return kind
        return None

    def _lyric_btn_at(self, pos):
        """这个坐标是不是点在歌词气泡那几颗按钮上。"""
        return self._lyric_btn_kind(pos) is not None

    def _music_position(self):
        """当前放到第几秒。

        媒体会话给的是"读取那一刻"的快照，往后按时间自己走；有些播放器只给 0，
        那种情况就按"这首歌实际放了多久"累加（暂停不会累加）。
        """
        info = self.now_playing or {}
        pos = info.get("position")
        playing = bool(info.get("playing"))
        if pos is not None and float(pos) > 0.5:
            if not playing:
                return max(0.0, float(pos))        # 暂停：播放器报的就是当前位置，别往前跑
            return max(0.0, float(pos) + (time.time() - float(info.get("at") or time.time())))
        # 报的是 0 / 垃圾值（网易云就是这样，连总时长都不给）：
        # 只能靠我们自己累加的"这首歌放到哪"——**暂停时不清零**，切走再回来也接着走。
        return max(0.0, self._music_played)

    def _word_times_for(self, start_sec):
        """这一句的逐字时间戳（没有就返回空）。"""
        table = getattr(self, "_lyric_words", None) or {}
        if not table:
            return []
        key = min(table, key=lambda k: abs(k - float(start_sec)))
        if abs(key - float(start_sec)) > 0.35:
            return []
        return table.get(key) or []

    def _current_lyric_pair(self):
        """按"当前进度 - 对时偏移"算出该显示的（这一句, 下一句）。"""
        return lyric_pair(self._lyric_lines, self._lyric_position())

    def _lyric_position(self):
        """算歌词用的时间：播放进度 − 对时偏移 ＋ 这首歌的微调（网易云不报进度时靠它手动对）。

        正数微调 = 歌词往前赶（显示更靠后的那句）；负数 = 往后压。
        """
        pos = (self._music_position()
               - float(getattr(self, "lyric_offset", 0.0))
               + float(getattr(self, "_lyric_nudge", 0.0)))
        return max(0.0, pos)

    def _lyric_progress(self):
        """当前这一句唱到几成了（0~1），用来做"唱到哪、字就变到哪"。"""
        lines = self._lyric_lines
        if not lines:
            return 0.0
        pos = self._lyric_position()
        idx = lyric_index(lines, pos)
        start = lines[idx][0]
        end = lines[idx + 1][0] if idx + 1 < len(lines) else start + 4.0
        span = max(0.4, float(end) - float(start))
        return max(0.0, min(1.0, (pos - start) / span))

    def _lyric_sung_total(self, text, start_sec):
        """这句已经唱到第几个字（可以是小数）。

        有**逐字歌词**（网易云 yrc / 增强 LRC）就按每个字的真实时间算 —— 这样能完全贴合
        真人演唱（唱歌不是匀速的）；没有就退回"按这句的起止时间匀速推"。
        """
        total = max(0, len(text))
        if total == 0:
            return 0.0
        pos = self._lyric_position()
        words = self._word_times_for(start_sec)
        if words:
            return max(0.0, min(float(total), sung_chars(words, pos) / max(1, len(words)) * total))
        return total * self._lyric_progress()

    @staticmethod
    def _karaoke_split(rows, sung_total):
        """把"已唱到第几个字"摊到每一行上：返回每行已经唱到的字数。"""
        total = sum(len(r) for r in rows)
        if total <= 0:
            return [0] * len(rows)
        sung = int(round(max(0.0, min(float(total), float(sung_total)))))
        out, used = [], 0
        for r in rows:
            n = max(0, min(len(r), sung - used))
            out.append(n)
            used += len(r)
        return out

    def _lyric_anim_step(self):
        """换句过渡期间专用的一帧：走得比主时钟密（100 帧/秒），所以更顺。"""
        if self._lyric_anim_t > 0:
            self._lyric_anim_t = max(
                0.0, self._lyric_anim_t - (LYRIC_ANIM_MS / 1000.0) / max(0.05, LYRIC_ANIM_SEC))
        rect = getattr(self, "_lyric_repaint_rect", None)
        if rect is not None and not rect.isEmpty():
            self.update(rect)           # 只重画气泡那一块
        else:
            self.update()
        bubble_moving = (abs(self._bub_target[0] - self._bub_w) > 0.6
                         or abs(self._bub_target[1] - self._bub_h) > 0.6)
        if self._lyric_anim_t <= 0 and not bubble_moving:
            self._lyric_timer.stop()

    def _apply_now_playing(self, info):
        now = time.time()
        # 播放器不给进度时，靠这里累计的"播放了多少秒"来对歌词
        if self.now_playing and self.now_playing.get("playing") and self._music_tick_at:
            self._music_played += max(0.0, min(now - self._music_tick_at, 5.0))
        self._music_tick_at = now
        if info is None:
            if self.now_playing is not None:
                self.now_playing = None
                # 注意：**别**清空歌词/进度。网易云一暂停就可能把整个媒体会话收掉，
                # 清掉的话恢复播放时歌词会从头开始（主人反馈的"暂停和开启直接清零"就是这个）。
                self._music_gone_at = time.time()
                self.update()
            return
        # 换歌前先把"上一首放到哪"记下来（注意：要在覆盖 now_playing **之前**算，
        # 不然算出来的会是新歌的位置 —— 之前就踩过这个坑）
        old_key = self._lyric_key
        old_pos = self._music_position() if self.now_playing else 0.0
        self.now_playing = info
        # 记一下"什么时候开始暂停"：气泡要留着给主人点 ▶（见 _music_paused）
        if info.get("playing"):
            self._music_paused_at = 0.0
        elif (info.get("title") or "").strip() and not self._music_paused_at:
            self._music_paused_at = time.time()
        # 排查用（开了「记菜单日志」才写）：记下播放器到底报了什么，方便诊断歌词对不上的原因
        menu_debug(f"[音乐] {info.get('app')} playing={info.get('playing')} "
                   f"position={info.get('position')} title={info.get('title')!r}")
        title = (info.get("title") or "").strip()
        key = f"{title}|{info.get('artist', '')}"
        if not title and self._lyric_key:
            # 暂停 / 缓冲时有些播放器（尤其网易云）会短暂不给歌名：
            # 这时候**不能**当成换歌，否则歌词会从头开始显示（主人反馈的 bug）。
            self.update()
            return
        if key != self._lyric_key:
            if old_key:                             # 记下上一首放到哪（回来时不用从头开始）
                self._music_pos_memo[old_key] = old_pos
                self._lyric_nudges[old_key] = float(getattr(self, "_lyric_nudge", 0.0))
                if len(self._music_pos_memo) > 30:  # 别无限涨
                    for k in list(self._music_pos_memo)[:-20]:
                        self._music_pos_memo.pop(k, None)
            self._lyric_key = key
            # 播放器不报进度时，用"记忆里的位置"接着走（暂停→放别的→切回来 不会从 0 开始）
            memo = self._music_pos_memo.get(key, 0.0)
            gone = getattr(self, "_music_gone_at", 0.0)
            if gone and time.time() - gone > 30.0:
                memo = 0.0                      # 消失超过 30 秒：当成重新开始，别用老位置
            self._music_gone_at = 0.0
            reported = info.get("position")
            pos_ok = reported is not None and float(reported) > 0.5
            self._music_played = max(0.0, float(reported)) if pos_ok else max(0.0, memo)
            self._lyric_nudge = float(self._lyric_nudges.get(key, 0.0))
            cached = self._lyric_cache.get(key) or {}
            if isinstance(cached, str):          # 兼容老格式（纯文本）
                cached = {"v": 1, "text": cached}
            self._setup_lyrics_for(key, info, cached)
            if info.get("playing") and info.get("title"):
                self._announce_song()
        else:
            # 同一首歌：如果播放器报的进度和我们自己推的差很多（拖动进度条 / 回退），
            # 就以播放器报的为准 —— 不然歌词不会跟着跳（主人反馈过这个问题）。
            pos = info.get("position")
            if (pos is not None and float(pos) > 0.5        # 只信"报了真实进度"的播放器
                and abs(float(pos) - self._music_played) > 2.5):
                self._music_played = max(0.0, float(pos))
            # 同一首歌换了个播放器（比如网易云 → QQ音乐），时间轴能力可能变：
            # 变了就按新播放器重新决定"显不显示歌词"
            if (info.get("has_timeline") is False) != bool(
                    getattr(self, "_music_no_progress", False)):
                cached = self._lyric_cache.get(key) or {}
                if isinstance(cached, str):
                    cached = {"v": 1, "text": cached}
                self._setup_lyrics_for(key, info, cached)
        # 放歌时看勤一点：网易云根本不报进度（实测 position 恒为 0），我们只能靠"什么时候
        # 开始放"起算，看得越勤误差越小
        want_ms = 800 if info.get("playing") else MUSIC_POLL_MS
        try:
            if self.music_timer.interval() != want_ms:
                self.music_timer.start(want_ms)
        except Exception:
            pass
        self.update()

    def _setup_lyrics_for(self, key, info, cached):
        """按"这个播放器报不报时间轴"决定这首歌显不显示歌词。

        网易云实测 position / 总时长恒为 0（不报时间轴）→ 只显示"歌名 + 歌手"，
        不抓歌词也不猜进度，一直保持到切歌为止；QQ音乐正常报，就照常显示歌词。
        """
        text = (cached or {}).get("text") or ""
        if info.get("has_timeline") is False:
            self._music_no_progress = True
            self._lyric_lines = []
            self._lyric_words = {}
            menu_debug(f"[音乐] {info.get('app')} 不报时间轴 → 只显示歌名")
            return
        self._music_no_progress = False
        self._lyric_lines = parse_lrc(text) if text else []
        self._lyric_words = parse_word_lyrics(text) if text else {}
        stale = bool(text) and int(cached.get("v", 1)) < LYRIC_CACHE_VERSION
        if (not text or stale) and self.music_lyrics and not self._lyric_fetching:
            self._start_lyric_fetch(key, info)

    def _announce_song(self):
        """换歌时冒一句（别连着刷）。"""
        now = time.time()
        if now - self._music_said_at < 6.0:
            return
        words = self.lines_for_say("MUSIC_START_LINES")
        if not words:
            return                    # 「换歌时」这块关着：安静换歌，不插话
        self._music_said_at = now
        # 换歌这句是"自动冒的"：正在说触发类的话时排在它后面，别打断
        self._say_when_free(
            random.choice(words).format(song=self._song_label()))

    def _start_lyric_fetch(self, key, info):
        self._lyric_fetching = key

        def worker():
            lrc = fetch_lyrics(info.get("title", ""), info.get("artist", ""))
            self._lyric_queue.append((key, lrc))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_lyric_result(self, key, lrc):
        self._lyric_fetching = ""
        if lrc:
            self._lyric_cache[key] = {"v": LYRIC_CACHE_VERSION, "text": lrc}
            save_lyric_cache(self._lyric_cache)
            if key == self._lyric_key:
                self._lyric_lines = parse_lrc(lrc)
                self._lyric_words = parse_word_lyrics(lrc)
                self.update()
        elif key == self._lyric_key:
            # 这次没抓到（网络抽风 / 这首歌没歌词）：**不要**把正在显示的歌词擦掉，
            # 过一会儿自己再试一次 —— 主人反馈过"歌词不显示，要切歌才恢复"。
            self._lyric_retry_at = time.time() + 15.0
            self.update()

    def _music_menu_label(self):
        info = self.now_playing or {}
        if not self.music_on:
            return "音乐联动：已关闭"
        if info and info.get("title"):
            state = "正在放" if info.get("playing") else "暂停在"
            return f"{state}：{info.get('app', '')} · {self._song_label()}"
        return "现在没在放歌"

    def check_music_now(self):
        """菜单「立刻看一眼在放什么」：马上刷新一次，并把结果直接冒出来。"""
        if not self.music_on:
            self.say("音乐联动没开哦，先勾上「放歌时看着」嘛", seconds=3.6, again=True)
            return
        self._music_manual = True
        self.poll_music()

    def _report_music_now(self, info):
        """把"立刻看一眼"的结果说出来：看得见 / 看不见，别让用户猜。"""
        if info and info.get("title"):
            tail = "" if info.get("playing") else "（现在是暂停的）"
            # 名字走同一套兜底（会话没给标识时也能认出 QQ音乐 / 网易云）
            self.say(f"♪ {self._app_label(info)} 正在放：{self._song_label(info)}{tail}",
                     seconds=4.0, again=True)
            return
        if not smtc_available():
            self.say("这台机器读不到系统媒体会话，只能看播放器窗口标题："
                     "把 QQ音乐 / 网易云 的窗口留在桌面上再试试", seconds=5.0, again=True)
            return
        self.say("没听见 QQ音乐 / 网易云 在放歌哦，先放一首试试嘛", seconds=4.0, again=True)

    # ---------- 余额 ----------
    def _api_key(self):
        """优先用配置里的 Key，其次用系统环境变量 DEEPSEEK_API_KEY。"""
        return (self.cfg.get("ds_api_key") or os.environ.get("DEEPSEEK_API_KEY", "") or "").strip()

    def _current_source(self):
        """当前余额来源 → (显示名, key)。"""
        name = self.cfg.get("balance_source") or "DeepSeek"
        if name != "DeepSeek":
            for item in (self.cfg.get("other_keys") or []):
                if item.get("name") == name:
                    return name, (item.get("key") or "").strip()
        return "DeepSeek", self._api_key()

    def refresh_balance(self, silent=True):
        """后台拉余额，结果丢进 _bal_queue 由主线程处理（Qt 界面只在主线程更新）。"""
        name, key = self._current_source()
        if not key:
            self.bal_error = f"未配置 {name} 的 Key"
            if not silent:
                self.say(f"先给 {name} 配个 Key 嘛～右键菜单里就有")
            return
        if self.bal_busy:
            return
        self.bal_busy = True

        def worker():
            low = name.lower()
            if low.startswith("deepseek"):
                res = query_deepseek_balance(key)
            elif "openrouter" in low:
                res = query_openrouter_balance(key)
            else:
                # OpenAI / ChatGPT 这类：官方没开放余额接口，如实告诉用户
                res = {"ok": False, "code": "NO_API",
                       "error": f"{name} 没有提供余额查询接口，看不到具体余额"}
            res["name"] = name
            res["silent"] = silent
            # 账本要认"这是不是同一个账号"：只存 Key 指纹，不存 Key 本身
            res["key_id"] = key_fingerprint(key)
            res["ts"] = time.time()
            self._bal_queue.append(res)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_balance(self, res):
        self.bal_busy = False
        if not res.get("ok"):
            self.bal_error = str(res.get("error") or "")
            if res.get("code") == "NO_API":
                # 这个服务压根没有余额接口：不报错，如实展示
                self.balance = {"name": res.get("name") or "?", "total": None,
                                "currency": "", "today": 0.0, "no_api": True}
                self.show_balance_bubble(8.0)
                return
            if not res.get("silent") and self.balance is None:
                self.say("余额没取到诶：" + self.bal_error[:14])
            return

        total, currency = float(res["total"]), res["currency"]
        name = res.get("name") or "DeepSeek"
        # 今日已用记账只对 DeepSeek 有意义（本地按余额差值记账）
        if name == "DeepSeek":
            book = record_balance_usage(USAGE_PATH, total, currency,
                                        granted=res.get("granted"),
                                        topped_up=res.get("topped_up"),
                                        key_id=res.get("key_id") or "",
                                        sample_ts=res.get("ts"))
        else:
            book = {"today": 0.0, "adjust": 0.0, "amount": 0.0, "reason": ""}
        old = self.balance["total"] if self.balance else None
        self.balance = {"name": name, "total": total, "currency": currency,
                        "today": book["today"], "adjust": book["adjust"],
                        "adjust_reason": book.get("adjust_why") or book.get("reason") or "",
                        "stale": False, "no_api": False}
        self.bal_error = ""
        self._start_roll(total)

        if book.get("reason"):
            # 余额掉了一大块但不是用量（赠额到期/接口抽风之类）：说清楚，别让主人以为自己乱花钱
            symbol = currency_symbol(currency)
            self.say(f"余额少了 {symbol}{book['amount']:.2f}，看着不像用掉的"
                     f"（{book['reason']}），这次没算进今日已用", seconds=6.0, again=True)

        if getattr(self, "_peek_pending", False):
            # 双击要的那一眼：不管是不是在放歌，都把余额顶上来显示 5 秒
            self._peek_pending = False
            self._peek_balance(PEEK_SEC)
            return
        if self._music_playing():
            return          # 放歌时不打断歌词；想看余额快速双击就行
        if not res.get("silent"):
            self.show_balance_bubble(6.0)
        elif old is None or abs(total - old) > 1e-9:
            # 余额变了就滚一次给主人看
            self.show_balance_bubble(4.0)

    def _start_roll(self, target):
        """余额变化时从旧值滚到新值。"""
        if self.roll_shown is None:
            self.roll_shown = float(target)
            self.roll_t = 1.0
            return
        if abs(float(target) - float(self.roll_shown)) < 1e-9:
            self.roll_t = 1.0
            return
        self.roll_from = float(self.roll_shown)
        self.roll_to = float(target)
        self.roll_t = 0.0

    def _display_amount(self):
        if self.balance is None:
            return 0.0
        if self.balance.get("total") is None:
            return 0.0
        if self.roll_shown is None or self.roll_t >= 1.0:
            return float(self.balance["total"])
        eased = 1 - (1 - self.roll_t) ** 3
        return self.roll_from + (self.roll_to - self.roll_from) * eased

    def show_balance_bubble(self, seconds=6.0, force=False):
        """把余额泡泡顶上来显示几秒。

        **触发类的话正在说的时候不抢**（余额每 60 秒自动刷一次，撞上就会把
        "用久了 / 到点 / 快捷键"那句顶掉）：先记着，等它说完再顶上来。
        主人自己点的那种（快速双击看一眼余额）传 force=True，直接顶。
        """
        if not force and self._trigger_speaking():
            self._bal_wait_until = self._trigger_until + 0.15
            self._bal_wait_secs = seconds
            return
        self._bal_wait_until = 0.0
        self.bal_until = self._secs() + seconds
        # 收起普通气泡，避免两层叠在一起
        self.bubble_text = ""
        self.bubble_until = 0.0
        self.update()

    def _say_later(self, seconds, text, inner=False):
        self._pending_bubbles.append((self._secs() + seconds, text, inner))

    def _trigger_speaking(self):
        """现在是不是"触发类"的话正在说（这段时间闲话让位，见 say）。"""
        return self._secs() < getattr(self, "_trigger_until", 0.0)

    # ---------- 免打扰 / 全屏：这段时间的"提醒"攒着 ----------
    def quiet_left(self):
        """免打扰还剩多少秒（0 = 没开）。"""
        return max(0, int(getattr(self, "_quiet_until", 0.0) - self._secs()))

    def _hold_now(self):
        """现在该不该闭嘴（免打扰中 / 前台是全屏游戏或电影）。"""
        return self.quiet_left() > 0 or bool(getattr(self, "_fs_now", False))

    def _say_reminder(self, text, **kw):
        """说一句"提醒"（开应用 / 用久了 / 到点）。

        免打扰、或者前台是全屏游戏/电影的时候：**这句先攒着**，等结束了再一起汇报；
        平时就交给 `say(queue=True)` —— 前面还有触发类的话在说时依次排着说，不互相盖。
        """
        if self._hold_now():
            self._held_lines.append(text)
            del self._held_lines[:-20]        # 攒太多就留最近 20 条
            return
        self.say(text, queue=True, **kw)

    def start_quiet(self, minutes=None):
        """免打扰：接下来这段时间不显示气泡，提醒暂存，结束后统一汇报。"""
        try:
            minutes = int(minutes or self.cfg.get("quiet_minutes") or QUIET_DEFAULT_MIN)
        except (TypeError, ValueError):
            minutes = QUIET_DEFAULT_MIN
        self.cfg["quiet_minutes"] = minutes
        self._quiet_until = self._secs() + max(1, minutes) * 60
        self._held_lines = []
        self.say(f"好嘛，我安静 {minutes} 分钟，有事我先攒着，绝对不吵你",
                 again=True, seconds=3.2)

    def stop_quiet(self, announce=True):
        """结束免打扰（时间到了也走这儿）：把攒下的提醒报一下。"""
        left = self.quiet_left()
        n = len(self._held_lines)
        last = self._held_lines[-1] if n else ""
        self._quiet_until = 0.0
        self._held_lines = []
        if not announce:
            return
        tail = (f"～刚才攒了 {n} 条提醒，最后一条是「{last}」" if n
                else "～我一句话都没吭哦")
        self.say(("我回来啦" if left <= 0 else "好啦，不憋着了") + tail,
                 again=True, seconds=4.5)

    def _hold_tick(self):
        """每秒看一眼：免打扰到点了没、前台是不是进/出全屏了。"""
        if self._quiet_until and self._secs() >= self._quiet_until:
            self.stop_quiet()
        if not self.cfg.get("fullscreen_silent", True):
            self._fs_now = False
            return
        full = foreground_is_fullscreen()
        if full and not self._fs_now:
            self._fs_now = True
            self._fs_since = self._secs()
        elif not full and self._fs_now:
            self._fs_now = False
            if self._secs() - getattr(self, "_fs_since", 0.0) >= FULLSCREEN_REPORT_MIN:
                n = len(self._held_lines)
                last = self._held_lines[-1] if n else ""
                self._held_lines = []
                if n:
                    self.say(f"退出来啦～刚才全屏那会儿攒了 {n} 条提醒，最后一条是「{last}」",
                             again=True, seconds=4.5)
            else:
                self._held_lines = []      # 只是切出去一下：攒的就不报了

    # ---------- 应用时长账本（给"每日小结"用）----------
    def _back_tick(self):
        """离开一阵子又回来：打个招呼（台词里可用 `{away}` 写离开了多久）。"""
        idle = idle_seconds()
        if idle is None:
            return
        if idle >= BACK_AWAY_SECONDS:
            if not self._away_flag:
                self._away_flag = True
                self._away_at = time.time()
            return
        if not self._away_flag or idle > 2.0:
            return
        self._away_flag = False
        away = max(0.0, time.time() - getattr(self, "_away_at", time.time()))
        if not self.cfg.get("back_greet", True) or self._hold_now():
            return
        lines = self.lines_for_say("BACK_LINES")
        if not lines:
            return                    # 「离开 / 返回时」这块关着：回来也不吭声
        self.say(fill_vars(random.choice(lines), away=fmt_duration(away)),
                 again=True, seconds=3.2)

    def _app_time_add(self, exe, seconds, now=None):
        """把这个应用今天用的时间累加上去（每 60 秒落一次盘，别一直写文件）。"""
        if not exe or seconds <= 0:
            return
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._app_day:          # 跨天了：重开一本
            self._app_day, self._app_book = today, {}
        self._app_book[exe] = self._app_book.get(exe, 0.0) + seconds
        stamp = time.time() if now is None else now
        if stamp >= self._app_flush_at:
            self._app_flush_at = stamp + APP_TIME_FLUSH_S
            save_app_time(APP_TIME_PATH, self._app_day, self._app_book)

    def app_time_flush(self):
        save_app_time(APP_TIME_PATH, self._app_day, self._app_book)

    def app_time_top(self, limit=SUMMARY_MAX_APPS):
        """今天用得最久的几个应用（至少 SUMMARY_MIN_SECONDS 才点名）。"""
        items = [(exe, secs) for exe, secs in (self._app_book or {}).items()
                 if secs >= SUMMARY_MIN_SECONDS]
        items.sort(key=lambda item: item[1], reverse=True)
        return [(self.app_label(exe), secs) for exe, secs in items[:limit]]

    @staticmethod
    def app_label(exe):
        """exe 名 → 人看得懂的名字。"""
        exe = (exe or "").lower()
        if exe in APP_LABELS:
            return APP_LABELS[exe]
        return (exe[:-4] if exe.endswith(".exe") else exe) or "?"

    def daily_summary(self):
        """今天的小结：余额用量（**没配 Key 就不提余额**）+ 用得最久的一两个应用。"""
        parts = []
        _name, key = self._current_source()
        if key:                             # 没配 API Key 就不报余额（主人指定的）
            used = read_today_usage(USAGE_PATH)
            if used > 0:
                symbol = currency_symbol(self.balance.get("currency")) if self.balance else ""
                parts.append(f"余额用了 {symbol}{used:.2f}")
        top = self.app_time_top()
        if top:
            parts.append("、".join(f"{label} {fmt_duration(secs)}" for label, secs in top))
        return ("今天：" + " · ".join(parts)) if parts else ""

    def _say_when_free(self, text, inner=False):
        """这句是自动冒的（比如换歌），但**别打断正在说的触发类的话**：排到它说完再说。"""
        if not self._trigger_speaking():
            self.say(text, inner=inner)
            return
        self._pending_bubbles.append((self._trigger_until + 0.25, text, inner))

    # ---------- 音效 / 形象 ----------
    @staticmethod
    def _crop_alpha(pix):
        """裁掉四周全透明空白（逐行扫描 alpha，避免逐像素 Python 调用）。"""
        img = pix.toImage().convertToFormat(QImage.Format.Format_ARGB32)
        w, h = img.width(), img.height()
        data = bytes(img.constBits())
        bpl = img.bytesPerLine()
        minx, miny, maxx, maxy = w, h, -1, -1
        for y in range(h):
            alphas = data[y * bpl: y * bpl + w * 4][3::4]
            if max(alphas) <= 8:
                continue
            x = 0
            while alphas[x] <= 8:
                x += 1
            x2 = w - 1
            while alphas[x2] <= 8:
                x2 -= 1
            minx, maxx = min(minx, x), max(maxx, x2)
            miny, maxy = min(miny, y), y
        if maxx < 0:
            return pix
        return pix.copy(minx, miny, maxx - minx + 1, maxy - miny + 1)

    def _init_sounds(self):
        """为每套音效准备多个播放实例。

        一次点击只播一声完整音效，不再区分按压/松手；多实例是为了连点时互不打断；
        没解码好的实例会先登记，等 Ready 立刻补播（避免「点了没声音」）。
        """
        if not AUDIO_AVAILABLE:
            return
        for name, clip in self._click_clips.items():
            url = QUrl.fromLocalFile(clip)
            instances = []
            for _ in range(SOUND_POOL):
                eff = QSoundEffect(self)
                eff.setSource(url)
                eff.setVolume(self.volume)
                instances.append(eff)
            self._sounds[name] = instances

    def play_click(self):
        """点一下播一声完整音效；池里轮着用，连点就按点击间隔自然响。"""
        if not self.sound_on:
            return
        if self.sound_set in self._click_clips:
            name = self.sound_set
        else:
            name = "小黄鸭"
        if self._click_player and self._click_player.has_clip(name):
            self._click_player.volume = self.volume
            self._click_player.play(name)
            return
        pool = self._sounds.get(name)
        if not pool:
            self._play_fallback_click()
            return
        idx = self._sound_idx.get(name, 0)
        eff = pool[idx % len(pool)]
        self._sound_idx[name] = (idx + 1) % len(pool)
        if eff.source().isEmpty():
            return
        try:
            eff.setVolume(self.volume)
            if eff.status() == QSoundEffect.Status.Ready:
                eff.play()
            else:
                # 还没解码好：先记下，等 Ready 立刻补播（比直接丢音好）
                self._pending_sounds.append((eff, time.time()))
        except Exception:
            pass

    def _flush_pending_sounds(self):
        if not self._pending_sounds:
            return
        now = time.time()
        keep = []
        for eff, ts in self._pending_sounds:
            if eff.status() == QSoundEffect.Status.Ready:
                try:
                    eff.setVolume(self.volume)
                    eff.play()
                except Exception:
                    pass
            elif now - ts < 1.5:      # 太久了就别补了，免得突然冒出来
                keep.append((eff, ts))
        self._pending_sounds = keep

    def warm_up_sounds(self):
        """启动后把音频设备先唤醒（0 音量静音放一遍），消掉第一次点击的延迟。"""
        if self._click_player:
            return                      # 常开流本来就在跑，不用预热
        for instances in self._sounds.values():
            for eff in instances:
                if eff.status() != QSoundEffect.Status.Ready:
                    continue
                try:
                    eff.setVolume(0.0)
                    eff.play()
                except Exception:
                    pass
        QTimer.singleShot(600, self._restore_sound_volume)

    def _restore_sound_volume(self):
        for instances in self._sounds.values():
            for eff in instances:
                eff.setVolume(self.volume)

    def preview_sounds(self):
        """试听当前这套点击音效。"""
        self.play_click()

    def _on_audio_output_changed(self, _device=None):
        """系统默认播放设备变了 → 缓一小拍就重开音频流（设备刚切换时马上开会失败）。

        主人反馈"插耳机要等近 2 秒才切过去"——那是 2 秒轮询的锅；现在有信号就立刻走这条，
        再留 0.5 秒轮询兜底（有些设备不触发信号）。
        """
        QTimer.singleShot(150, self._rebuild_audio_output)

    def _check_audio_device(self):
        """每 2 秒看一眼系统默认输出设备是不是换了；换了就把点击音切过去。"""
        try:
            dev = QMediaDevices.defaultAudioOutput()
            dev_id = bytes(dev.id()) if dev is not None and not dev.isNull() else b""
        except Exception:
            return
        if dev_id == self._audio_dev_id:
            return
        self._audio_dev_id = dev_id
        if not self._audio_dev_watched:          # 第一次只是记下来，不用重开
            self._audio_dev_watched = True
            return
        self._rebuild_audio_output()

    def _rebuild_audio_output(self):
        """把点击音切到当前默认输出设备上（插耳机后声音跟着进耳机）。"""
        if self._click_player is not None:
            ok = self._click_player.rebuild_output()
            menu_debug(f"[音频] 默认输出设备变了 → 重开音频流，成功={ok}")
            if not self._click_player.ok:
                # 新设备可能还没就绪：隔一小会儿再试两次，别直接退回 QSoundEffect 池
                tries = getattr(self, "_audio_retry", 0) + 1
                self._audio_retry = tries
                if tries <= 3:
                    QTimer.singleShot(400, self._rebuild_audio_output)
                else:
                    self._audio_retry = 0
                    self._click_player = None      # 实在开不了：退回 QSoundEffect 池
                    self._init_sounds()
            else:
                self._audio_retry = 0
        else:
            self._init_sounds()

    def _play_fallback_click(self):
        """Qt 音频不可用时的兜底：用系统 winsound 异步播 wav（没有音量控制）。"""
        try:
            import winsound
            name = self.sound_set if self.sound_set in self._click_clips else "小黄鸭"
            path = self._click_clips.get(name)
            if path and os.path.exists(path):
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC
                                   | winsound.SND_NODEFAULT)
        except Exception:
            pass

    def set_sound(self, on):
        self.sound_on = bool(on)
        self.cfg["sound_on"] = bool(on)

    def set_sound_set(self, name):
        if name not in self._sound_names():
            return
        self.sound_set = name
        self.cfg["sound_set"] = name
        self.play_click()          # 换音效顺手试听一声

    # ---------- 自己加音效 ----------
    def _sound_names(self):
        """可选音效名单：内置两套 + 主人自己加的（自己加的排在后面）。"""
        extra = [n for n in getattr(self, "_custom_sounds", {}) if n not in SOUND_SETS]
        return list(SOUND_SETS) + extra

    def _register_sound(self, name, path):
        """把一个已经转好格式的 wav 注册成可选音效（立刻生效，不用重启）。"""
        if not hasattr(self, "_custom_sounds"):
            self._custom_sounds = {}
        self._click_clips[name] = path
        self._custom_sounds[name] = path
        self.cfg.setdefault("custom_sounds", {})[name] = path
        if self._click_player is not None:
            try:
                self._click_player.load_clip(name, path)
            except Exception:
                pass
        if AUDIO_AVAILABLE:
            try:
                url = QUrl.fromLocalFile(path)
                pool = []
                for _ in range(SOUND_POOL):
                    eff = QSoundEffect(self)
                    eff.setSource(url)
                    eff.setVolume(self.volume)
                    pool.append(eff)
                self._sounds[name] = pool
            except Exception:
                pass
        self.save_config()

    def _add_sound_from_path(self, src, name=None, max_seconds=None):
        """把主人的音频转格式、存进 sounds/、注册成音效。返回 (名字, 真实秒数, 处理说明)。"""
        base = (name or os.path.splitext(os.path.basename(src))[0] or "我的音效").strip()[:16]
        base = base or "我的音效"
        if base in SOUND_SETS:                 # 别和内置的重名
            base += "（我的）"
        dest = os.path.join(SOUND_USER_DIR, base + ".wav")
        secs, note = make_click_wav(src, dest, max_seconds=max_seconds)
        self._register_sound(base, dest)
        return base, secs, note

    def add_custom_sound_dialog(self):
        """挑一个自己的音频当点击音：会自动转成"单声道 44.1k"，太长还会问你要不要裁。"""
        with self._ui_guard():
            path, _ = QFileDialog.getOpenFileName(
                self, "挑一个音效文件（wav）", "", "WAV 音频 (*.wav);;所有文件 (*)")
        if not path:
            return
        if not path.lower().endswith(".wav"):
            with self._ui_guard():
                QMessageBox.information(
                    self, "要 wav 格式",
                    "点击音现在只吃 wav 格式。\n\n" + SOUND_TIP +
                    "\n\n可以先用任意工具把它转成 WAV（16 位最好）再选一次。")
            return
        secs = wav_seconds(path)
        keep = None
        if secs and secs > SOUND_IDEAL[1] + 0.2:
            with self._ui_guard():
                btn = QMessageBox.question(
                    self, "这个有点长",
                    f"这个音效 {secs:.2f} 秒。\n\n{SOUND_TIP}\n\n"
                    f"要我帮你裁到 {SOUND_KEEP_MAX:.2f} 秒吗（只保留开头）？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    | QMessageBox.StandardButton.Cancel)
            if btn == QMessageBox.StandardButton.Cancel:
                return
            if btn == QMessageBox.StandardButton.Yes:
                keep = SOUND_KEEP_MAX
        elif secs and secs < SOUND_IDEAL[0]:
            with self._ui_guard():
                ok = QMessageBox.question(
                    self, "这个有点短",
                    f"这个音效只有 {secs:.2f} 秒，可能听不清。\n\n{SOUND_TIP}\n\n还是要用吗？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ok != QMessageBox.StandardButton.Yes:
                return
        try:
            name, real, note = self._add_sound_from_path(path, max_seconds=keep)
        except Exception as exc:
            with self._ui_guard():
                QMessageBox.warning(
                    self, "这个文件我处理不了",
                    f"{exc}\n\n{SOUND_TIP}\n\n建议先转成 WAV（16 位、44100Hz）再试。")
            return
        self.set_sound_set(name)               # 切过去，顺手试听一声
        fit = "正好在建议区间里" if SOUND_IDEAL[0] <= real <= SOUND_IDEAL[1] else "不在建议区间里，觉得别扭就再换一个"
        self.say(f"换上「{name}」啦：{real:.2f} 秒，{fit}" + (f"（{note}）" if note else ""))

    def remove_custom_sound_dialog(self):
        """删掉自己加的音效（内置两套动不了）。"""
        names = list(getattr(self, "_custom_sounds", {}))
        if not names:
            self.say("你还没加过自己的音效呢")
            return
        with self._ui_guard():
            pick, ok = QInputDialog.getItem(
                self, "删掉我加的音效", "选一个删掉（内置的动不了）：", names, 0, False,
                Qt.WindowType.WindowStaysOnTopHint)
        if not ok or not pick:
            return
        self._remove_sound(pick)
        self.say(f"「{pick}」删掉了")
        self.play_click()

    def _remove_sound(self, pick):
        """真正把某个自定义音效删掉（对话框和测试都走这里）。"""
        path = self._custom_sounds.pop(pick, None)
        self._click_clips.pop(pick, None)
        self._sounds.pop(pick, None)
        try:
            (self.cfg.get("custom_sounds") or {}).pop(pick, None)
        except Exception:
            pass
        if path:
            try:
                os.remove(path)
            except Exception:
                pass
        if self.sound_set == pick:
            self.sound_set = "小黄鸭"
            self.cfg["sound_set"] = "小黄鸭"
        self.save_config()

    def set_volume(self, vol):
        self.volume = max(0.0, min(1.0, float(vol)))
        self.cfg["volume"] = self.volume
        if self._click_player:
            self._click_player.volume = self.volume
        self._restore_sound_volume()

    # ---------- 形象加载 / 我的形象库（两本：三维形象 / 挂件形象）----------
    @staticmethod
    def _new_skin_id(*parts):
        """形象编号：按原图路径算，同一个文件永远同一个号（老配置迁移时也用这个）。"""
        key = "|".join(str(p) for p in parts if p)
        return "sk" + hashlib.md5(key.encode("utf-8", "ignore")).hexdigest()[:10]

    def skin_library(self, kind=None):
        """我的形象库，存在 config.json → skin_library，**两本分开**：

        {"pet": [三维形象…], "widget": [挂件形象…]}

        三维形象 = {"id","name","front","side","back","added"}（正面/侧面/背面三张齐了才算一条）；
        挂件形象 = {"id","name","path","added"}。存的都是**原图在硬盘上的位置**，
        桌宠只记路径、不搬文件 —— 所以原图不能删、不能挪（挪了就在库里标"文件找不到了"）。
        kind 给 "pet" / "widget" 就只返回那一本；不给就两本一起返回。
        """
        raw = self.cfg.get("skin_library")
        raw = raw if isinstance(raw, dict) else {}
        out = {}
        for name, keys in (("pet", PET_SLOTS), ("widget", ("path",))):
            out[name], seen = [], set()
            for item in (raw.get(name) or []):
                if not isinstance(item, dict):
                    continue
                paths = [(k, str(item.get(k) or "").strip()) for k in keys]
                if not any(p for _k, p in paths):
                    continue
                sid = str(item.get("id") or "").strip() or self._new_skin_id(
                    *[p for _k, p in paths])
                if sid in seen:                      # 同一个号只留一条
                    continue
                seen.add(sid)
                ent = {"id": sid, "name": str(item.get("name") or "").strip(),
                       "added": str(item.get("added") or "").strip()}
                for key, path in paths:
                    ent[key] = path
                if not ent["name"]:                  # 老数据没名字就用文件名顶上
                    ent["name"] = (os.path.splitext(
                        os.path.basename(ent[keys[0]] or ""))[0] or "我的形象")
                out[name].append(ent)
        return out.get(kind) if kind in out else out

    def _save_skin_library(self, kind, entries):
        lib = self.cfg.get("skin_library")
        lib = dict(lib) if isinstance(lib, dict) else {}
        lib[kind] = [dict(it) for it in entries]
        self.cfg["skin_library"] = lib
        self.save_config()

    def skin_entry(self, kind, ref):
        """按编号（或老配置里直接存的图片路径）找出库里的这一条。"""
        ref = str(ref or "").strip()
        if not ref:
            return None
        for it in self.skin_library(kind):
            if it["id"] == ref:
                return it
        if kind == "widget" and (os.path.isabs(ref) or os.sep in ref or "/" in ref):
            return {"id": self._new_skin_id(ref), "added": "",
                    "name": os.path.splitext(os.path.basename(ref))[0] or "我的形象",
                    "path": ref}
        return None

    def _current_skin_ref(self, kind):
        """现在登记用的是哪一条（三维 / 挂件各自的编号）。"""
        return str((self.cfg.get("custom_skins") or {}).get(kind) or "").strip()

    def pet_skin_entry(self):
        """现在用的三维形象（没自定义过就是 None）。"""
        return self.skin_entry("pet", self._current_skin_ref("pet"))

    def widget_skin_entry(self):
        """现在用的挂件形象（没自定义过就是 None）。"""
        return self.skin_entry("widget", self._current_skin_ref("widget"))

    def skin_view_path(self, kind, ent, view):
        """这条形象里某个视图的原图路径（三维是 front/side/back，挂件是 widget）。"""
        if not ent:
            return ""
        return str(ent.get("path" if view == "widget" else view) or "")

    def _custom_path(self, view):
        """该视图用户自定义的图片路径（没登记 / 文件不在了就返回空）。"""
        kind = "widget" if view == "widget" else "pet"
        ent = self.widget_skin_entry() if kind == "widget" else self.pet_skin_entry()
        path = self.skin_view_path(kind, ent, view)
        return path if path and os.path.exists(path) else ""

    def skin_missing_views(self, kind, ent):
        """这条形象里哪几张图现在找不到了（被删 / 改名 / 挪走）。"""
        keys = PET_SLOTS if kind == "pet" else ("widget",)
        return [v for v in keys
                if not self.skin_view_path(kind, ent, v)
                or not os.path.exists(self.skin_view_path(kind, ent, v))]

    def custom_skin_missing(self, view):
        """这个视图现在登记的那张图是不是找不到了。"""
        kind = "widget" if view == "widget" else "pet"
        ent = self.widget_skin_entry() if kind == "widget" else self.pet_skin_entry()
        return bool(ent) and view in self.skin_missing_views(kind, ent)

    def skin_in_use(self, kind, sid):
        """这条形象是不是"现在正用着"的那条。"""
        return bool(sid) and self._current_skin_ref(kind) == str(sid).strip()

    def skin_thumb_path(self, kind, ent):
        """列表 / 预览拿哪张当门面：三维默认**正面**那张（正面缺了才顺延），挂件就是它自己。"""
        if not ent:
            return ""
        keys = PET_SLOTS if kind == "pet" else ("widget",)
        first = ""
        for view in keys:
            path = self.skin_view_path(kind, ent, view)
            if not path:
                continue
            first = first or path
            if os.path.exists(path):
                return path
        return first

    def _make_skin(self, kind, name, **paths):
        """拼一条形象（三维：front/side/back；挂件：path），编号按路径算。"""
        keys = PET_SLOTS if kind == "pet" else ("path",)
        ent = {"id": self._new_skin_id(*[paths.get(k, "") for k in keys]),
               "name": (name or "").strip()[:24] or "我的形象",
               "added": datetime.now().strftime("%Y-%m-%d %H:%M")}
        for key in keys:
            ent[key] = str(paths.get(key) or "")
        return ent

    def add_pet_skin(self, name, front, side, back):
        """收一个三维形象（三张齐了才收录；同样的三张图再收一次 = 只换名字）。"""
        ent = self._make_skin("pet", name, front=front, side=side, back=back)
        lib = [it for it in self.skin_library("pet") if it["id"] != ent["id"]]
        lib.append(ent)
        self._save_skin_library("pet", lib)
        return ent

    def add_widget_skin(self, name, path):
        """收一个挂件形象（单张图）。"""
        ent = self._make_skin("widget", name, path=path)
        lib = [it for it in self.skin_library("widget") if it["id"] != ent["id"]]
        lib.append(ent)
        self._save_skin_library("widget", lib)
        return ent

    def update_skin(self, kind, sid, name, **paths):
        """改名字 / 换图：**编号不变**，所以已经用着它的地方不用重挑。"""
        keys = PET_SLOTS if kind == "pet" else ("path",)
        ent = {"id": str(sid), "name": (name or "").strip()[:24] or "我的形象", "added": ""}
        for key in keys:
            ent[key] = str(paths.get(key) or "")
        for old in self.skin_library(kind):
            if old["id"] == sid:
                ent["added"] = old["added"]
        lib = [it for it in self.skin_library(kind) if it["id"] != sid] + [ent]
        self._save_skin_library(kind, lib)
        return ent

    def _refresh_skins(self):
        """换完图 / 换完形象：重新加载精灵、按当前档位缩放、写回配置。"""
        self._rebuild_sprites()
        self.set_size(self.cfg.get("size", SIZE_DEFAULT))
        self.save_config()

    def _migrate_skin_library(self):
        """老配置升级：以前是"一个视图一张图"，现在分成三维 / 挂件两本库。

        - 挂在挂件上的那张 → 挂件形象库；
        - 正面 / 侧面 / 背面**三张都有** → 收成一个三维形象（名字取正面那张的名字）；
        - 只挑过一两张 → 记成"还没挑完的三维形象"（skin_draft），下次点上传接着挑，
          不硬凑一个形象出来（主人要求：三张齐了才算一个形象）；
        - 老库里没被任何视图用过的图 → 兜底放进挂件库（单张语义最稳妥）。
        """
        raw = self.cfg.get("skin_library")
        if isinstance(raw, dict):                    # 已经是新格式：只补齐缺的那本
            fixed = dict(raw)
            for kind in ("pet", "widget"):
                if not isinstance(fixed.get(kind), list):
                    fixed[kind] = []
            if fixed != raw:
                self.cfg["skin_library"] = fixed
                self.save_config()
            return
        old = []
        for item in (raw if isinstance(raw, list) else []):
            if isinstance(item, dict) and str(item.get("path") or "").strip():
                path = str(item["path"]).strip()
                old.append((str(item.get("id") or "").strip() or self._new_skin_id(path),
                            str(item.get("name") or "").strip(), path))
        by_id = {i: (n, p) for i, n, p in old}
        by_path = {os.path.normcase(p): (i, n, p) for i, n, p in old}
        skins = dict(self.cfg.get("custom_skins") or {})

        def resolve(ref):
            """老登记值（库编号 或 图片路径）→ (名字, 路径)。"""
            ref = str(ref or "").strip()
            if not ref:
                return None
            if ref in by_id:
                return by_id[ref][0], by_id[ref][1]
            if os.path.isabs(ref) or os.sep in ref or "/" in ref:
                hit = by_path.get(os.path.normcase(ref))
                if hit:
                    return hit[1], hit[2]
                return os.path.splitext(os.path.basename(ref))[0], ref
            return None

        pet_paths, widget_paths = {}, {}
        for view in tuple(PET_SLOTS) + ("widget",):
            got = resolve(skins.get(view))
            if got:
                (widget_paths if view == "widget" else pet_paths)[view] = got
        pet_lib, widget_lib = [], []
        for _view, (name, path) in widget_paths.items():
            widget_lib.append(self._make_skin("widget", name, path=path))
        pet_ent = None
        if len(pet_paths) == len(PET_SLOTS):         # 三张齐了才算一个三维形象
            pet_ent = self._make_skin(
                "pet", pet_paths.get("front", ("", ""))[0] or "我的三维形象",
                **{v: pet_paths[v][1] for v in PET_SLOTS})
            pet_lib.append(pet_ent)
        elif pet_paths:                              # 没齐：存成"还没挑完"
            draft = {"name": pet_paths.get("front", ("", ""))[0]}
            draft.update({v: pet_paths[v][1] for v in pet_paths})
            self.cfg["skin_draft"] = draft
        used = {os.path.normcase(p) for _n, p in pet_paths.values()}
        used |= {os.path.normcase(it["path"]) for it in widget_lib}
        for _sid, name, path in old:                 # 老库里没人用的图 → 挂件库兜底
            if os.path.normcase(path) not in used:
                used.add(os.path.normcase(path))
                widget_lib.append(self._make_skin("widget", name, path=path))
        new_skins = {}
        if pet_ent:
            new_skins["pet"] = pet_ent["id"]
        if widget_lib:
            new_skins["widget"] = widget_lib[0]["id"]
        self.cfg["skin_library"] = {"pet": pet_lib, "widget": widget_lib}
        self.cfg["custom_skins"] = new_skins
        self.save_config()

    def _dialog_guard(self, parent=None):
        """进窗口时让桌宠站住不动；父窗口已经是我们的对话框时不用再套一层。"""
        return self._ui_guard() if parent is None else contextlib.nullcontext()

    def _warn(self, parent, title, text):
        """警告窗口（QMessageBox 的静态方法不认"置顶"标志，只能自己搭一个）。"""
        box = QMessageBox(parent or self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(title)
        box.setText(text)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        with self._dialog_guard(parent):
            box.exec()

    def _has_sprite(self, key):
        return any(k[0] == key for k in self.sprites)

    def _load_view_pixmap(self, view, h):
        """加载某个视图的某个高度：优先用户自定义图片，其次自带素材。

        注：无级调节会一路拖出几十个不同的高度，所以"原图（裁掉透明边）"走 `_view_base`
        的缓存，每次只是从缓存缩放到目标高度 —— 不用反复读盘、反复裁边。
        """
        custom = self._custom_path(view)
        if custom:
            base = self._view_base(custom)
            if base is not None and not base.isNull():
                self.custom_skin_ok[view] = True
                return base.scaledToHeight(h, Qt.TransformationMode.SmoothTransformation)
        self.custom_skin_ok[view] = False
        if view == "widget":
            base = self._view_base(os.path.join(ASSET_DIR, WIDGET_SKIN_FILE))
            return None if base is None else base.scaledToHeight(
                h, Qt.TransformationMode.SmoothTransformation)
        name = SPRITE_VIEWS[view]
        # 自带素材正好有这个高度的现成文件（原来那五档就是）→ 直接用，省一次缩放
        sized = os.path.join(SPRITE_DIR, f"{name}_{h}.png")
        if os.path.exists(sized):
            return QPixmap(sized)
        full = os.path.join(SPRITE_DIR, f"{name}.png")
        base = self._view_base(full)
        if base is None:
            return None
        return base.scaledToHeight(h, Qt.TransformationMode.SmoothTransformation)

    def _view_base(self, path):
        """某个视图"原图裁掉透明边"之后的那份，按「路径 + 修改时间」缓存。

        换过图（或者把原图改名换回来）时，修改时间一变缓存自然失效，不用手工清。
        """
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            return None
        key = (path, stamp)
        base = self._base_cache.get(key)
        if base is None:
            raw = QPixmap(path)
            if raw.isNull():
                return None
            base = self._crop_alpha(raw)
            if len(self._base_cache) >= 8:      # 撑死了几 MB，超了就整批丢掉重来
                self._base_cache.clear()
            self._base_cache[key] = base
        return base

    def _rebuild_sprites(self):
        """重新加载各尺寸精灵（换了自定义图片后调用）。

        除了五档标准高度，**当前高度也要建**：v1.0.18 起大小能无级调（比如 40%），
        那不是五档里的任何一档；漏了它，换完形象在当前高度上就没图可画。
        """
        heights = [int(340 * mult) for mult in SIZE_LEVELS.values()]
        cur = getattr(self, "cur_h", None)
        if cur:
            heights.append(int(cur))
        self.sprites = {}
        for h in heights:
            for view, key in VIEW_SHORT.items():
                pix = self._load_view_pixmap(view, h)
                if pix is not None and not pix.isNull():
                    self.sprites[(key, h)] = pix
        self.widget_skin_ok = self._has_sprite("挂件")

    @staticmethod
    def _clamp_size(mult):
        """把大小倍率收进允许范围（老配置里可能存着奇怪的值）。"""
        try:
            mult = float(mult)
        except (TypeError, ValueError):
            mult = SIZE_DEFAULT
        return max(SIZE_MIN, min(SIZE_MAX, mult))

    def _ensure_sprites(self, h):
        """把某个高度的精灵补进 self.sprites（已经有了就跳过）。

        无级调节会用到五档以外的高度，这里现补：只缩放缓存好的原图，很快。
        """
        h = int(h)
        for view, key in VIEW_SHORT.items():
            if (key, h) not in self.sprites:
                pix = self._load_view_pixmap(view, h)
                if pix is not None and not pix.isNull():
                    self.sprites[(key, h)] = pix
        self.widget_skin_ok = self._has_sprite("挂件")

    def _prune_sprites(self, keep_h):
        """只留五档 + 当前高度：无级调节一路拖过去会产生几十个高度，
        不清理的话它们会一直占着内存。
        """
        keep = {int(340 * m) for m in SIZE_LEVELS.values()} | {int(keep_h)}
        for key in [k for k in self.sprites if k[1] not in keep]:
            del self.sprites[key]

    def _skin_pick_dir(self):
        """上次挑图的那个文件夹（没有就用"图片"文件夹）。"""
        start = str(self.cfg.get("skin_pick_dir") or "")
        if start and os.path.isdir(start):
            return start
        pics = os.path.join(os.path.expanduser("~"), "Pictures")
        return pics if os.path.isdir(pics) else os.path.expanduser("~")

    def upload_skin(self, kind, parent=None):
        """上传一个新形象：三维挑三张（齐了才收录）、挂件挑一张。"""
        prefill = self.cfg.get("skin_draft") if kind == "pet" else None
        if not isinstance(prefill, dict):
            prefill = None
        return self._skin_edit(kind, None, prefill, parent)

    def edit_skin(self, kind, sid, parent=None):
        """改一个已经收录的形象（换其中几张图 / 改回原来那张）。"""
        ent = self.skin_entry(kind, sid)
        return self._skin_edit(kind, ent, None, parent) if ent else None

    def _skin_edit(self, kind, entry, prefill=None, parent=None):
        """上传 / 编辑窗口的公共路子：挑图 → 起名字 → 收录或更新 → 换上。"""
        dlg = SkinEditDialog(self, kind, entry=entry, prefill=prefill)
        with self._dialog_guard(parent):
            ok = dlg.exec()
        if not ok or not dlg.result_data:
            if kind == "pet" and entry is None:
                # 半途取消：已经挑好的几张记下来，下次点上传接着挑（不白挑）
                picked = {v: p for v, p in dlg.slots.items() if p}
                if picked:
                    self.cfg["skin_draft"] = dict(picked, name=dlg.name_edit.text().strip())
                else:
                    self.cfg.pop("skin_draft", None)
                self.save_config()
            return None
        res = dlg.result_data
        paths = res["paths"]
        if kind == "pet":
            ent = (self.update_skin("pet", entry["id"], res["name"], **paths) if entry
                   else self.add_pet_skin(res["name"], paths["front"], paths["side"], paths["back"]))
        else:
            ent = (self.update_skin("widget", entry["id"], res["name"], path=paths["widget"])
                   if entry else self.add_widget_skin(res["name"], paths["widget"]))
        self.cfg.pop("skin_draft", None)
        if entry is None or self.skin_in_use(kind, ent["id"]):
            self.apply_skin(kind, ent["id"], parent=parent, fresh=entry is None)
        else:
            self._refresh_skins()
        return ent

    def apply_skin(self, kind, sid, parent=None, fresh=False):
        """换上一个形象：三维整套换上（顺手切到「大肥鱼」），挂件切到「小鲸鱼挂件」。"""
        ent = self.skin_entry(kind, sid)
        if not ent:
            return False
        missing = self.skin_missing_views(kind, ent)
        if missing:
            self._warn(parent, "这张图找不到了" if len(missing) == 1 else "这几张图找不到了",
                       f"「{ent['name']}」的" + "、".join(VIEW_SHORT[v] for v in missing)
                       + "那张图在硬盘上找不到了：\n"
                       + "\n".join(self.skin_view_path(kind, ent, v) for v in missing)
                       + "\n\n多半是被删掉、改名、或者挪到别的文件夹了。\n"
                       "把文件放回原来的位置就行；也可以在「形象 → 我的形象库…」里点"
                       "「换图…」重新指一张。")
            return False
        skins = dict(self.cfg.get("custom_skins") or {})
        skins[kind] = ent["id"]
        self.cfg["custom_skins"] = skins
        self._refresh_skins()
        tail = "（别删原图哦）" if fresh else ""
        if kind == "pet":
            self.set_skin(SKIN_PET)
            self.say(f"三维形象「{ent['name']}」整套换上啦{tail}")
        else:
            self.set_skin(SKIN_WIDGET)
            self.say(f"挂件形象「{ent['name']}」换上啦{tail}")
        return True

    def skin_library_dialog(self, kind=None):
        """「我的形象库…」：三维 / 挂件两本库 + 上传 / 换图 / 改名 / 删掉，全在这一个窗口里。"""
        if kind not in ("pet", "widget"):
            kind = "widget" if self.skin == SKIN_WIDGET else "pet"   # 默认先看你正用着的那本
        with self._ui_guard():
            SkinLibraryDialog(self, kind).exec()

    def rename_skin(self, kind, sid, parent=None):
        """给库里的一条改名字（编号不变，正在用它的一点不受影响）。"""
        ent = self.skin_entry(kind, sid)
        if not ent:
            return False
        with self._dialog_guard(parent):
            name, ok = QInputDialog.getText(
                parent or self, "给形象改个名字", f"「{ent['name']}」改成什么？",
                QLineEdit.EchoMode.Normal, ent["name"],
                Qt.WindowType.WindowStaysOnTopHint)
        name = (name or "").strip()[:24]
        if not ok or not name or name == ent["name"]:
            return False
        keys = PET_SLOTS if kind == "pet" else ("path",)
        self.update_skin(kind, sid, name, **{k: ent[k] for k in keys})
        self.say(f"改好啦，以后叫「{name}」")
        return True

    def remove_skin(self, kind, sid, parent=None):
        """从库里删掉一条（正用着它就退回自带形象；硬盘上的原图不动）。"""
        ent = self.skin_entry(kind, sid)
        if not ent:
            return False
        used = self.skin_in_use(kind, sid)
        tip = f"把「{ent['name']}」从{SKIN_KIND_LABELS[kind]}库里删掉？"
        if used:
            tip += "\n\n它现在正用着 —— 删了会退回自带形象。"
        tip += "\n\n只删库里这条记录，硬盘上那几张原图我不动。"
        with self._dialog_guard(parent):
            ok = QMessageBox.question(parent or self, "删掉这个形象", tip,
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ok != QMessageBox.StandardButton.Yes:
            return False
        self._save_skin_library(kind, [it for it in self.skin_library(kind) if it["id"] != sid])
        if used:
            skins = dict(self.cfg.get("custom_skins") or {})
            skins.pop(kind, None)
            self.cfg["custom_skins"] = skins
            self._refresh_skins()
        self.say(f"「{ent['name']}」从{SKIN_KIND_LABELS[kind]}库里删掉了（原图我没动）")
        return True

    def clear_custom_skin(self, kind=None):
        """恢复自带形象（kind：pet=三维 / widget=挂件；不给就两个都恢复）。库里的都留着。"""
        skins = dict(self.cfg.get("custom_skins") or {})
        if kind in ("pet", "widget"):
            skins.pop(kind, None)
        else:
            skins = {}
        self.cfg["custom_skins"] = skins
        self._rebuild_sprites()
        if self.skin == SKIN_WIDGET and not self._has_sprite("挂件"):
            self.skin = SKIN_PET
            self.cfg["skin"] = SKIN_PET
        self.set_size(self.cfg.get("size", SIZE_DEFAULT))
        self.save_config()
        self.say(f"{SKIN_KIND_LABELS[kind]}恢复成自带的啦（库里的还留着）"
                 if kind in SKIN_KIND_LABELS else "已恢复自带形象（上传过的还在「我的形象库」里）")

    def set_skin(self, name):
        """切换形象：大肥鱼（三视图）/ 小鲸鱼挂件（单张）。"""
        if name == SKIN_WIDGET and not self.widget_skin_ok:
            self.say("小鲸鱼形象没找到图片")
            return
        self.skin = name
        self.cfg["skin"] = name
        self.prev_key = None
        self.cross_t = 0.0
        self._apply_window_size()
        self._settle()
        self.update()

    # ---------- 吸附 / 翻转 ----------
    def _snap_to_edge(self):
        """松手后按四分之一区域吸附屏幕四边（角落可组合），左吸附时整体水平翻转。"""
        if not self.snap_on:
            self.snap_h = self.snap_v = None
            self.flip_x = False
            return
        geo = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        cx, cy = self.x() + self.width() / 2, self.y() + self.height() / 2
        self.snap_h = ("left" if cx < geo.left() + geo.width() / 4
                       else "right" if cx > geo.right() - geo.width() / 4 else None)
        self.snap_v = ("top" if cy < geo.top() + geo.height() / 4
                       else "bottom" if cy > geo.bottom() - geo.height() / 4 else None)
        self._settle(geo)

    def _settle(self, geo=None):
        if not self.snap_on or (self.snap_h is None and self.snap_v is None):
            return
        geo = geo or (self.screen() or QApplication.primaryScreen()).availableGeometry()
        x, y = self.x(), self.y()
        if self.snap_h == "left":
            x = geo.left()
        elif self.snap_h == "right":
            x = geo.right() - self.width() + 1
        if self.snap_v == "top":
            y = geo.top()
        elif self.snap_v == "bottom":
            y = geo.bottom() - self.height() + 1
        # 吸附轴已经是精确贴边，只有没吸附的轴才需要钳制在屏幕内
        if self.snap_h is None:
            x = max(geo.left(), min(geo.right() - self.width(), x))
        if self.snap_v is None:
            y = max(geo.top(), min(geo.bottom() - self.height(), y))
        self.flip_x = bool(self.flip_on_left and self.snap_h == "left")
        self.move(int(x), int(y))

    # ---------- 绘制 ----------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        now = self._secs()

        mode = self._bubble_mode(now)
        if mode != "lyric":
            # 这会儿画的不是歌词气泡 → 那几颗按钮也没了。
            # 位置一起清掉，免得气泡收起来之后原地还留着"看不见但能点"的死区。
            self._lyric_btn_rects = {}
            if getattr(self, "_lyric_btn_hover", None) is not None:
                self._lyric_btn_hover = None
                self.setCursor(Qt.CursorShape.ArrowCursor)
        if mode == "text":
            ink = self._bubble_ink()
            if self.bubble_inner:
                bfont = QFont(self.bubble_font)
                bfont.setItalic(True)
                bg, fg = ink["inner_bg"], ink["inner_fg"]
            else:
                bfont = QFont(self.bubble_font)
                bg, fg = ink["bg"], ink["fg"]
            fm = QFontMetrics(bfont)
            max_w = min(240, self.width() - 16)
            words = self.bubble_text
            lines = []
            cur = ""
            for ch in words:
                if fm.horizontalAdvance(cur + ch) > max_w - 20:
                    lines.append(cur)
                    cur = ch
                else:
                    cur += ch
            lines.append(cur)
            bw = max(fm.horizontalAdvance(l) for l in lines) + 28
            bh = len(lines) * fm.height() + 16
            bx = (self.width() - bw) / 2
            by = self._bubble_top(bh)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(QRectF(bx, by, bw, bh), 14, 14)
            tail = QPointF(self.width() / 2, by + bh)
            p.drawPolygon(QPolygonF([tail, QPointF(tail.x() - 7, tail.y() + 9),
                                     QPointF(tail.x() + 7, tail.y() + 9)]))
            p.setPen(fg)
            p.setFont(bfont)
            for i, l in enumerate(lines):
                p.drawText(QRectF(bx, by + 8 + i * fm.height(), bw, fm.height()),
                           Qt.AlignmentFlag.AlignCenter, l)
        elif mode == "balance":
            # 余额气泡：余额 / 今日已用（数字带滚动动画）
            ink = self._bubble_ink()
            f_small = QFont(self.bubble_font)
            f_small.setPointSize(9)
            f_big = QFont(self.bubble_font)
            f_big.setPointSize(15)
            f_big.setBold(True)
            fm_s, fm_b = QFontMetrics(f_small), QFontMetrics(f_big)
            src = self.balance.get("name") or "DeepSeek"
            symbol = currency_symbol(self.balance.get("currency"))
            peak_now = is_peak()
            show_peak_line = bool(self.show_peak and src == "DeepSeek")
            if self.balance.get("no_api"):
                # 这个服务不提供余额接口，直接说清楚
                l1 = src
                l2 = "无法查询"
                l3 = "该服务不提供余额接口"
                show_peak_line = False
            else:
                l1 = f"{src} 余额"
                l2 = f"{symbol} {self._display_amount():.2f}".strip()
                l3 = (f"今日已用 {symbol} {self.balance['today']:.2f}".strip()
                      if src == "DeepSeek" else "今日已用 仅 DeepSeek 支持")
            l4 = f"现在 {peak_label(peak_now, self.peak_style)}"
            bw = max(fm_b.horizontalAdvance(l2), fm_s.horizontalAdvance(l1),
                     fm_s.horizontalAdvance(l3), fm_s.horizontalAdvance(l4)) + 28
            bh = fm_s.height() + fm_b.height() + fm_s.height() + 16
            if show_peak_line:
                bh += fm_s.height()
            bx = (self.width() - bw) / 2
            by = self._bubble_top(bh)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(ink["bg"])
            p.drawRoundedRect(QRectF(bx, by, bw, bh), 14, 14)
            tail = QPointF(self.width() / 2, by + bh)
            p.drawPolygon(QPolygonF([tail, QPointF(tail.x() - 7, tail.y() + 9),
                                     QPointF(tail.x() + 7, tail.y() + 9)]))
            ty = by + 8
            p.setFont(f_small)
            p.setPen(ink["bal_title"])
            p.drawText(QRectF(bx, ty, bw, fm_s.height()), Qt.AlignmentFlag.AlignCenter, l1)
            ty += fm_s.height()
            p.setFont(f_big)
            p.setPen(ink["bal_big"])
            p.drawText(QRectF(bx, ty, bw, fm_b.height()), Qt.AlignmentFlag.AlignCenter, l2)
            ty += fm_b.height()
            p.setFont(f_small)
            p.setPen(ink["bal_sub"])
            p.drawText(QRectF(bx, ty, bw, fm_s.height()), Qt.AlignmentFlag.AlignCenter, l3)
            if show_peak_line:
                ty += fm_s.height()
                p.setFont(f_small)
                # 高峰暖色、空闲绿色，一眼看出现在贵不贵
                warm, cool = BUBBLE_PEAK_COLORS[self._bubble_theme()]
                p.setPen(warm if peak_now else cool)
                p.drawText(QRectF(bx, ty, bw, fm_s.height()), Qt.AlignmentFlag.AlignCenter, l4)

        elif mode == "lyric":
            self._paint_lyric_bubble(p)

        cx = self.width() / 2
        walking = self.target is not None and not self.dragging
        if walking:
            sway = math.sin(now * 9.0) * 3.5
            bob = -abs(math.sin(now * 4.5)) * 7.0
        else:
            sway = math.sin(now * 2.5) * 1.5
            bob = 0.0
        breath = 1.0 + 0.02 * math.sin(now * 2.5)
        scale = breath
        jump = -abs(math.sin(self.jump_t * 3.14159)) * 14 * self.jump_t if self.jump_t > 0 else 0
        act_rot = act_sx = act_sy = 0.0
        if self.action == "sway":
            act_rot = math.sin(self.action_t * 3.14159 * 2) * 10 * self.action_t
        elif self.action == "stretch":
            act_sy = 0.06 * math.sin(self.action_t * 3.14159)
            act_sx = -0.03 * math.sin(self.action_t * 3.14159)
        # 合体新增：唱歌时只轻轻摇晃 —— 不蹦不跳、幅度小、节奏慢
        if self.dsh_act == "sing":
            sway = math.sin(now * 1.8) * 1.1      # 幅度小、慢
            bob = 0.0                             # 不上下颠（去掉"跳跃感"）
            jump = 0                              # 不蹦
            act_rot = act_sx = act_sy = 0.0       # 不再叠加反应动作

        # 按压 Q 弹：底部坐标不变，横向撑开、纵向压扁
        press_sx = 1 + 0.13 * self.press_t
        press_sy = 1 - 0.13 * self.press_t

        def draw_one(key, opacity):
            if key is None:
                return
            name, h, facing = key
            pix = self.sprites[(name, h)]
            ph = pix.height() * scale * (1 + act_sy) * press_sy
            pw = pix.width() * scale * (1 + act_sx) * press_sx
            dx = cx - pw / 2
            bottom = BUBBLE_H + MARGIN + self.cur_h
            dy = bottom - ph + jump + bob
            p.save()
            p.setOpacity(opacity)
            p.translate(cx, bottom)
            p.rotate(sway + act_rot)
            p.translate(-cx, -bottom)
            # 行走朝向 与 左吸附整体翻转 叠加（异或）
            if (facing < 0) != bool(self.flip_x):
                p.translate(cx, 0)
                p.scale(-1, 1)
                p.translate(-cx, 0)
            p.drawPixmap(QRectF(dx, dy, pw, ph), pix, QRectF(0, 0, pix.width(), pix.height()))
            p.restore()

        def draw_act(pix, opacity):
            """画 DSH 动作帧（自己画的立绘），统一按「当前显示高度」缩放。

            源图是哪一档、当前用的哪一档都不影响：角色大小始终跟三视图一致。
            """
            bh = (float(self.cur_h) or 1.0) * DSH_ACT_ZOOM.get(self.dsh_act or "", 1.0)
            aspect = (pix.width() / float(pix.height())) if pix.height() else 1.0
            ph = bh * scale * (1 + act_sy) * press_sy
            pw = bh * aspect * scale * (1 + act_sx) * press_sx
            dx = cx - pw / 2
            bottom = BUBBLE_H + MARGIN + self.cur_h
            dy = bottom - ph + jump + bob
            p.save()
            p.setOpacity(opacity)
            p.translate(cx, bottom)
            p.rotate(sway + act_rot)
            p.translate(-cx, -bottom)
            if bool(self.flip_x):
                p.translate(cx, 0)
                p.scale(-1, 1)
                p.translate(-cx, 0)
            p.drawPixmap(QRectF(dx, dy, pw, ph), pix, QRectF(0, 0, pix.width(), pix.height()))
            p.restore()

        act_pix = self._dsh_act_pix()
        cur_key = self._sprite_key()
        if act_pix is not None:
            # 有画好的动作帧就用它；切动作时和上一张做交叉淡化
            if self.cross_t > 0 and self._dsh_act_prev is not None:
                draw_act(self._dsh_act_prev, self.cross_t)
                draw_act(act_pix, 1.0 - self.cross_t)
            else:
                draw_act(act_pix, 1.0)
        elif self.cross_t > 0:
            draw_one(self.prev_key, self.cross_t)
            draw_one(cur_key, 1.0 - self.cross_t)
        else:
            draw_one(cur_key, 1.0)

    def _bubble_top(self, bh):
        """气泡贴着鱼头顶：尾巴尖落在精灵上沿附近。"""
        return max(2.0, BUBBLE_H + MARGIN - 10 - bh)

    def _secs(self):
        """内部时钟（秒）。按当前每帧时长换算，两种流畅度下动作速度一致。"""
        return self.t * self.tick_ms / 1000.0

    def _bubble_mode(self, now):
        """气泡区这会儿该显示什么：text（说话）/ balance（余额）/ lyric（歌词）。

        放歌时歌词优先于「余额常显」——想瞄一眼余额就快速双击（显示 5 秒）。
        """
        if self.bubble_text and now < self.bubble_until:
            return "text"
        if self.now_playing and now < self._bal_peek_until and self.balance is not None:
            return "balance"
        # 放歌期间一直显示这一块：有歌词就显示歌词，没有（或网易云不报进度）就显示「♪ 应用 · 歌名」
        # —— 主人要求"歌名信息要持续一整首歌"。刚按暂停的那几分钟也留着（好点 ▶ 继续放）。
        if self._music_playing() or self._music_paused():
            return "lyric"
        if self.balance is not None and (self.balance_always or now < self.bal_until):
            return "balance"
        return None

    def _bubble_theme(self):
        """气泡现在该用亮色还是深色那套（bubble_style="auto" 时跟着设置界面的主题）。"""
        style = getattr(self, "bubble_style", "auto")
        if style in ("light", "dark"):
            return style
        try:
            # 主人自己挑的亮 / 暗是定死的，直接算（这就是个字符串比较，便宜）
            if ui_console.get_mode() in ("light", "dark"):
                return "dark" if ui_console.is_dark() else "light"
        except Exception:                      # 界面模块没起来 → 还是老样子（浅色）
            return "light"
        # 剩下的只有"跟随系统"：那条路要读注册表，而画气泡时每帧都要问一次，
        # 所以结果缓存 1 秒（Windows 切深色模式时最多晚一秒跟上）
        now = time.time()
        cached = getattr(self, "_bubble_theme_cache", None)
        if cached is not None and now - cached[0] < 1.0:
            return cached[1]
        try:
            theme = "dark" if ui_console.is_dark() else "light"
        except Exception:
            theme = "light"
        self._bubble_theme_cache = (now, theme)
        return theme

    def _bubble_ink(self):
        """气泡那套颜色（底 / 字）。每帧都取一次，就是个字典查表，不重新算。"""
        return BUBBLE_INK[self._bubble_theme()]

    def _lyric_rows(self, head, cur, nxt, max_w, ink=None):
        """把歌词折成"要画的几行"。

        一句太长就先把字号往下缩（11 → 8 磅）；缩到底还超才截到 LYRIC_MAX_ROWS 行 ——
        主人反馈过"歌词显示不全"，所以尽量别丢掉半句话。
        ink 是当前气泡那套颜色（见 _bubble_ink）—— 颜色烘在结果里，换风格要连带重算。
        不给就按现在生效的那套来（老用例只关心折行，不传这个参数）。
        返回 (rows, 折好的当前句, 当前句用的字体, 它的 QFontMetrics)。
        """
        if ink is None:
            ink = self._bubble_ink()
        f_small = QFont(self.bubble_font)
        f_small.setPointSize(9)
        f_main = QFont(self.bubble_font)
        f_main.setPointSize(11)
        # 顶行右边那条要留给 ⏮ ⏸▶ ⏭（见 LYRIC_BTN_PAD），**只有第一行窄**：
        # 折到第二行起整行都能用。一行塞不下就折两行；两行还塞不下才丢"——歌手"，
        # 最后才省略 —— 以前是"只取第一行"，歌手甚至歌名会无声无息地消失。
        fm_s = QFontMetrics(f_small)
        head_w = max_w - LYRIC_BTN_PAD
        head_lines = wrap_text_hanging(fm_s, head, head_w, max_w)
        if len(head_lines) > LYRIC_HEAD_ROWS:
            # 先丢"——歌手"那截（唱到谁不重要，谁的什么歌才重要）
            head_lines = wrap_text_hanging(fm_s, head.split("——")[0].strip(),
                                           head_w, max_w)
        if len(head_lines) > LYRIC_HEAD_ROWS:
            head_lines = [elide_text(fm_s, head.split("——")[0].strip(), head_w)]
        head_lines = head_lines[:LYRIC_HEAD_ROWS]
        # 折行时别让「·」「——」孤零零留在行尾：挪到下一行开头（看着是故意换行的）
        for _i in range(len(head_lines) - 1):
            for _sep in ("——", "·"):
                if head_lines[_i].endswith(_sep):
                    head_lines[_i] = head_lines[_i][:-len(_sep)].rstrip()
                    head_lines[_i + 1] = _sep + " " + head_lines[_i + 1]
                    break
        cur_lines = wrap_text(QFontMetrics(f_main), cur, max_w)
        pt = 11
        while len(cur_lines) > LYRIC_MAX_ROWS and pt > LYRIC_MIN_PT:
            pt -= 1
            f_main.setPointSize(pt)
            cur_lines = wrap_text(QFontMetrics(f_main), cur, max_w)
        total = len(cur_lines)
        fm_m = QFontMetrics(f_main)
        if total > LYRIC_MAX_ROWS:
            # 字号已经缩到底还是装不下（比如迷你尺寸下遇到很长的英文句）：
            # 再多给两行，同时把顶部那行「♪ 应用 · 歌名」去掉，腾出高度，
            # 尽量让整句歌词都看得见（主人反馈过"歌词显示不全"）。
            keep = cur_lines[:LYRIC_OVERFLOW_ROWS]
            rows = [(line, f_main, ink["ly_main"]) for line in keep]
            return rows, keep, f_main, fm_m, 0
        cur_lines = cur_lines[:LYRIC_MAX_ROWS]
        # 下一句一直显示（主人要求：不要因为这一句长就不显示下一句）
        nxt_lines = wrap_text(QFontMetrics(f_small), nxt, max_w)[:1] if nxt else []
        rows = ([(line, f_small, ink["ly_head"]) for line in head_lines]
                + [(line, f_main, ink["ly_main"]) for line in cur_lines]
                + [(line, f_small, ink["ly_next"]) for line in nxt_lines])
        return rows, cur_lines, f_main, fm_m, len(head_lines)

    def _draw_lyric_btn(self, p, rect, ink, playing=True, kind="toggle"):
        """歌词气泡右上角那几颗小按钮。

        kind="prev" / "next" 画「⏮」「⏭」；kind="toggle" 在放歌时画「⏸」、
        暂停了画「▶」。鼠标划过 / 按下的那颗才透出一圈底色。
        """
        color = QColor(ink["ly_head"])
        hover = getattr(self, "_lyric_btn_hover", None) == kind
        pressed = getattr(self, "_lyric_btn_pressed", None) == kind
        if hover or pressed:
            soft = QColor(color)
            soft.setAlpha(80 if pressed else 46)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(soft)
            p.drawEllipse(rect)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        cx, cy = rect.center().x(), rect.center().y()
        if kind == "toggle":
            if playing:                   # ⏸：两根小竖条
                w, h, gap = 2.6, 9.0, 3.2
                for dx in (-(w + gap) / 2, (w + gap) / 2):
                    p.drawRoundedRect(QRectF(cx + dx - w / 2, cy - h / 2, w, h), 1.2, 1.2)
            else:                         # ▶：小三角
                r = 4.6
                p.drawPolygon(QPolygonF([QPointF(cx - r + 0.8, cy - r),
                                         QPointF(cx - r + 0.8, cy + r),
                                         QPointF(cx + r + 0.8, cy)]))
            return
        # ⏮ / ⏭：一个小三角 + 一根小竖条（上一首竖条在左，下一首竖条在右）
        r, bar_w = 4.3, 1.8
        sgn = -1.0 if kind == "prev" else 1.0
        apex, base = cx + sgn * (r - 0.6), cx - sgn * (r - 0.6)
        p.drawPolygon(QPolygonF([QPointF(base, cy - r), QPointF(base, cy + r),
                                 QPointF(apex, cy)]))
        bar_x = cx + sgn * (r + 0.1) - bar_w / 2
        p.drawRoundedRect(QRectF(bar_x, cy - r, bar_w, r * 2), 0.8, 0.8)

    def _paint_lyric_bubble(self, p):
        """歌词气泡：小字「应用 · 歌名」，大字当前这句，再淡一行下一句。"""
        info = self.now_playing or {}
        max_w = min(300, self.width() - 12) - 22
        who = (info.get("artist") or "").strip()
        title = (info.get("title") or "").strip()
        # 播放器给的信息可能不全（网易云实测会缺）：缺了就用占位，命名风格保持一致
        # 注意：_app_label() 是静态方法，**必须把 info 传进去**（不传就是空字典 →
        # 顶上永远显示「未知应用」，2026-09-14 主人报的就是这个）
        # 顶行还要给右上角那颗 ⏸ / ▶ 让出一条（见 LYRIC_BTN_PAD）
        head = f"♪ {self._app_label(info)} · {title or TITLE_PLACEHOLDER}"
        if who:
            head += f"—— {who}"
        # 对时：正数 = 文字延后（等一下声音）；不同输出设备（外放 / 蓝牙耳机）延迟不一样
        cur, nxt = self._current_lyric_pair()
        if not cur:
            # 还没找到歌词 / 用户关了歌词 → 就挂个「♪ 歌名」
            cur, nxt = self._song_label(), ""
        # 排版缓存：换句 / 换宽度 / 换字号才重算 —— 每帧算一次 wrap_text 要 ~1ms，100 帧就掉帧了
        # 气泡风格也算在 key 里：颜色是烘在排版结果里的，换了风格得跟着重算
        theme = self._bubble_theme()
        ink = BUBBLE_INK[theme]
        layout_key = (head, cur, nxt, max_w, theme)
        if getattr(self, "_lyric_layout_key", None) != layout_key:
            self._lyric_layout_key = layout_key
            self._lyric_layout_cache = self._lyric_rows(head, cur, nxt, max_w, ink)
        rows, cur_lines, f_main, fm_m, n_head = self._lyric_layout_cache
        real_lyric = bool(self._lyric_lines) and self._current_lyric_pair()[0] == cur
        # 换句时的过渡：新的一句淡入、旧的淡出并往上滑一点（不然"啪"一下太生硬）
        anim = max(0.0, min(1.0, getattr(self, "_lyric_anim_t", 0.0)))
        prev_text = getattr(self, "_lyric_prev", "")
        prev_rows = []
        if anim > 0 and prev_text and prev_text != cur:
            prev_key = (prev_text, max_w, theme)
            if getattr(self, "_lyric_prev_key", None) != prev_key:
                self._lyric_prev_key = prev_key
                self._lyric_prev_cache = [
                    (line, f_main, ink["ly_main"])
                    for line in wrap_text(fm_m, prev_text, max_w)[:LYRIC_MAX_ROWS]]
            prev_rows = self._lyric_prev_cache
        widths = [QFontMetrics(font).horizontalAdvance(text) for text, font, _c in rows]
        if prev_rows:
            widths += [fm_m.horizontalAdvance(t) for t, _f, _c in prev_rows]
        # 顶行右边要站那颗 ⏸ / ▶：把它算成"顶行宽度 + 按钮那一条"，气泡才不会把标题挤掉
        if n_head and widths:
            widths[0] += LYRIC_BTN_PAD
        # 万一这版把顶行"♪ 应用·歌名"让出来给歌词了（超长歌词），那颗按钮就没地方站：
        # 在顶上多留一条给它，免得压在歌词上
        extra_top = 0.0 if n_head else float(LYRIC_BTN_SIZE + 4)
        height = sum(QFontMetrics(font).height() for _t, font, _c in rows) + 20 + extra_top
        bw = max(widths) + 28
        # 气泡"窗口"自己也会平滑变大/变小（0.15 秒、100 帧/秒那套），
        # 不然换到字数不同的那句时会"啪"地换一个框，看着像窗口重新弹了一次。
        now = time.time()
        dt = 0.0 if self._bub_t is None else max(0.0, min(0.12, now - self._bub_t))
        self._bub_t = now
        self._bub_target = (bw, height)
        if abs(bw - self._bub_w) < 0.6 and abs(height - self._bub_h) < 0.6:
            self._bub_w, self._bub_h = bw, height
        else:
            k = min(1.0, dt / max(0.05, BUBBLE_ANIM_SEC))
            self._bub_w += (bw - self._bub_w) * k
            self._bub_h += (height - self._bub_h) * k
        bw, height = self._bub_w, self._bub_h
        self._lyric_last_w = bw
        self._lyric_last_h = height
        bx = (self.width() - bw) / 2
        by = self._bubble_top(height)
        # 记下气泡占的矩形：过渡动画刷新时只重画这一块，别把整个窗口（含桌宠）都重画，
        # 不然 100 帧/秒会把合成器压住 —— 拖窗口就掉帧了（主人反馈的卡顿）。
        self._lyric_repaint_rect = QRectF(bx - 6, by - 6, bw + 12, height + 20).toRect()
        self._lyric_bubble_rect = QRectF(bx, by, bw, height)   # 气泡本体（量按钮位置用）
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ink["bg"])
        p.drawRoundedRect(QRectF(bx, by, bw, height), 14, 14)
        tail = QPointF(self.width() / 2, by + height)
        p.drawPolygon(QPolygonF([tail, QPointF(tail.x() - 7, tail.y() + 9),
                                 QPointF(tail.x() + 7, tail.y() + 9)]))
        # 右上角那三颗按钮：⏮ 上一首 / ⏸▶ 播放暂停 / ⏭ 下一首
        # （这块气泡就是个迷你播放器，放歌时不用切回播放器）
        btn, gap = float(LYRIC_BTN_SIZE), float(LYRIC_BTN_GAP)
        right, top = bx + bw - 6, by + 6
        self._lyric_btn_rects = {}
        for kind in ("next", "toggle", "prev"):     # 从右往左摆：⏭ | ⏸▶ | ⏮
            self._lyric_btn_rects[kind] = QRectF(right - btn, top, btn, btn)
            right -= btn + gap
        for kind in ("prev", "toggle", "next"):     # 从左往右画，叠不到一起
            self._draw_lyric_btn(p, self._lyric_btn_rects[kind], ink,
                                 playing=bool(info.get("playing")), kind=kind)
        ty = by + 10 + extra_top
        if prev_rows:                    # 旧的这句：往上滑出去 + 淡出
            p.setOpacity(anim)
            oy = ty - (1.0 - anim) * 8
            for text, font, color in prev_rows:
                fm = QFontMetrics(font)
                p.setFont(font)
                p.setPen(color)
                p.drawText(QRectF(bx, oy, bw, fm.height()), Qt.AlignmentFlag.AlignCenter, text)
                oy += fm.height()
            p.setOpacity(1.0)
        if anim > 0:                     # 新的一句：从下面 8px 滑上来 + 淡入
            p.setOpacity(max(0.15, 1.0 - anim * 0.85))
            ty += anim * 8
        # "唱到哪、字就变到哪"：当前这句按进度给已唱到的部分换颜色
        if LYRIC_KARAOKE_ON and real_lyric:
            line_start = self._lyric_lines[lyric_index(self._lyric_lines,
                                                       self._lyric_position())][0]
            sung_total = self._lyric_sung_total("".join(cur_lines), line_start)
            sung = self._karaoke_split(cur_lines, sung_total)
        else:
            sung = [0] * len(cur_lines)
        for i, (text, font, color) in enumerate(rows):
            fm = QFontMetrics(font)
            p.setFont(font)
            p.setPen(color)
            k = i - n_head                                  # 这一行是当前句的第几行
            if i < n_head:
                # 顶行左对齐；**只有第一行**要给右上角那颗 ⏸ / ▶ 让出一条，
                # 折到第二行的时候整行都能用（不然那一行会被硬生生切掉）
                pad = LYRIC_BTN_PAD if i == 0 else 0
                slack = 3 if i == 0 else 0        # 给气泡缩放动画留点余量
                p.drawText(QRectF(bx + 14, ty, bw - 28 - pad + slack, fm.height()),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
            elif 0 <= k < len(cur_lines):
                w_row = fm.horizontalAdvance(text)
                x0 = bx + (bw - w_row) / 2
                p.drawText(QRectF(bx, ty, bw, fm.height()),
                           Qt.AlignmentFlag.AlignCenter, text)
                n = sung[k] if k < len(sung) else 0
                if n > 0:                                   # 已唱到的部分：裁剪后重画成高亮色
                    w_pre = fm.horizontalAdvance(text[:n])
                    p.save()
                    p.setClipRect(QRectF(x0, ty, max(1.0, w_pre), fm.height()))
                    p.setPen(QColor(*LYRIC_KARAOKE_COLOR))
                    p.drawText(QRectF(bx, ty, bw, fm.height()),
                               Qt.AlignmentFlag.AlignCenter, text)
                    p.restore()
            else:
                p.drawText(QRectF(bx, ty, bw, fm.height()),
                           Qt.AlignmentFlag.AlignCenter, text)
            ty += fm.height()
        p.setOpacity(1.0)

    def _sprite_key(self):
        if self.skin == SKIN_WIDGET:
            return ("挂件", self.cur_h,
                    self.facing if self.dir in ("left", "right") else 1)
        name = {"left": "侧面", "right": "侧面", "up": "背面", "down": "正面"}[self.dir]
        return (name, self.cur_h, self.facing if self.dir in ("left", "right") else 1)

    def _set_dir(self, d, facing=None):
        if d != self.dir:
            self.prev_key = self._sprite_key()
            self.cross_t = 1.0
            self.dir = d
        if facing is not None and facing != self.facing:
            self.facing = facing

    def _face_travel(self, dx, dy, ratio=2):
        """按"这一步往哪走"给朝向（dx/dy 是窗口中心 → 目标点的位移）。

        明显横向（横向位移是纵向的 ratio 倍以上）→ 侧面（自动镜像）；
        其余只要往上走 → 背影（等于往屏幕里走、背对着你）；往下走 → 正面。

        以前这里是"只要横向超过 4px 就侧面，只有几乎笔直向上才给背影"，而散步的随机
        目标几乎不可能笔直向上，于是背影再也没出现过（主人反馈"我这么久没见过背面"）。
        阈值取 2 倍（不是对半分）是因为屏幕是宽屏：横向位移天然比纵向大一截，
        真按 |dx|>=|dy| 分的话背影只占 1/7 左右（实机 90 秒一次都没出现）。
        现在宽屏上大约 45% 侧面、25% 背影、30% 正面。

        ratio 只给"走路"用；跟着鼠标转头用的是 1（见 `_face_cursor`）——鼠标是看着走的，
        45 度就该算侧面，不该按宽屏那套偏袒横向。
        """
        if abs(dx) >= ratio * abs(dy):
            self._set_dir("left" if dx < 0 else "right", 1 if dx < 0 else -1)
        elif dy < 0:
            self._set_dir("up")
        else:
            self._set_dir("down")

    # ---------- 逻辑 ----------
    def tick(self):
        self.t += 1

        # 歌词换句的过渡动画：发现"该显示的那一句"变了就淡入淡出一下
        if self._music_playing() and self.music_lyrics and self._lyric_lines:
            cur_line = self._current_lyric_pair()[0]
            if cur_line and cur_line != self._lyric_shown:
                self._lyric_prev = self._lyric_shown
                self._lyric_shown = cur_line
                self._lyric_prev_h = self._lyric_last_h or 0.0
                self._lyric_prev_w = self._lyric_last_w or 0.0
                self._lyric_anim_t = 1.0
        # 过渡期间（换句动画、或者气泡正在变大变小）换成 100 帧/秒的密帧重绘
        bubble_moving = (abs(self._bub_target[0] - self._bub_w) > 0.6
                         or abs(self._bub_target[1] - self._bub_h) > 0.6)
        if (self._lyric_anim_t > 0 or bubble_moving) and not self._lyric_timer.isActive():
            self._lyric_timer.start()

        # 歌词没抓到就自己重试（原来要等切歌才会重抓，主人反馈过"歌词不显示"）
        if (self.music_on and self.music_lyrics and self._lyric_key
                and not self._lyric_lines and not self._lyric_fetching
                and not getattr(self, "_music_no_progress", False)
                and time.time() >= self._lyric_retry_at):
            self._lyric_retry_at = time.time() + 15.0
            self._start_lyric_fetch(self._lyric_key, self.now_playing or {})

        # 大约每 5 秒顺手存一次配置：改了城市/大小/音效这些不用等退出也不会丢
        if self.t % 250 == 0:
            self.autosave_config()

        # 峰谷切换提醒：每秒看一次，跨进新时段就说一声
        if self.t % 50 == 0:
            self.check_timed_lines()        # 到点说一句（每天 / 每周 / 每隔）
            self._hold_tick()               # 免打扰到点了没 / 进没进全屏
            self._back_tick()               # 离开一阵子回来打个招呼
            peak_now = is_peak()
            if self._peak_now is None:
                self._peak_now = peak_now
            elif peak_now != self._peak_now:
                self._peak_now = peak_now
                self.say("进入" + peak_label(peak_now, self.peak_style)
                         + ("，这会儿聊起来贵一点" if peak_now else "，这会儿便宜"))

        # 合体新增：处理 DSH 联动读回来的状态
        self._dsh_apply()
        self._dsh_tick_act(TICK)

        # 处理后台线程排队的气泡消息，Qt 界面必须在主线程更新
        if self._say_queue:
            # 放歌时气泡被歌词占着，这些后台结果（天气等）就多停一会儿
            hold = MUSIC_HOLD_SEC if self._music_playing() else 0.0
            for text in self._say_queue:
                self.say(text, seconds=hold or 2.8)
            self._say_queue.clear()

        # 余额结果（后台线程 → 主线程）
        if self._bal_queue:
            self._apply_balance(self._bal_queue.pop(0))

        # 在放什么歌 / 找回来的歌词（后台线程 → 主线程）
        if self._music_queue:
            info = self._music_queue.pop(0)
            self._apply_now_playing(info)
            self._sync_music_act()
            self._music_busy = False
            if self._music_manual:          # 菜单里手动点的那次：回一句话
                self._music_manual = False
                self._report_music_now(info)
        if self._lyric_queue:
            key, lrc = self._lyric_queue.pop(0)
            self._apply_lyric_result(key, lrc)
        self._music_cmd_tick()           # 气泡上那几颗 ⏮ / ⏸▶ / ⏭ 的结果

        # 余额数字滚动 + 按压回弹 + 音效补播
        if self.roll_t < 1.0:
            self.roll_t = min(1.0, self.roll_t + 0.07)
            if self.roll_t >= 1.0 and self.balance:
                self.roll_shown = float(self.balance["total"])
        if self.press_t > 0:
            self.press_t = max(0.0, self.press_t - 0.12)
        self._flush_pending_sounds()

        # 延迟气泡（每轮消耗等）
        if self._bal_wait_until and self._secs() >= self._bal_wait_until:
            self.show_balance_bubble(self._bal_wait_secs, force=True)
        if self._pending_bubbles:
            now_s = self._secs()
            due = [i for i, x in enumerate(self._pending_bubbles) if x[0] <= now_s]
            if due:
                # 一次只说一条（原来是"到点的一批一起丢掉、只留第一条"，排队的会丢）
                _, text, inner = self._pending_bubbles.pop(due[0])
                self.say(text, inner=inner)

        # 单击欠着的那句台词：等双击判定窗口过去才冒（窗口内来了第二下就撤销）
        if self._single_pending and self._secs() >= self._single_pending[0]:
            _when, speak = self._single_pending
            self._single_pending = None
            try:
                speak()
            except Exception:
                pass

        # 城市定位 / 搜索结果
        if self._city_queue:
            city = self._city_queue.pop(0)
            if city:
                self._apply_city(city)
            else:
                self.say("没定位到，右键「天气 → 添加城市」搜一个吧")
        if self._city_pick_queue:
            items = self._city_pick_queue.pop(0)
            labels = [x[0] for x in items]
            with self._ui_guard():
                pick, ok = QInputDialog.getItem(self, "选择城市", "选一个城市：", labels,
                                                0, False, Qt.WindowType.WindowStaysOnTopHint)
            if ok and pick:
                self._apply_city(dict(items)[pick])
        if self._app_queue:
            self._pick_app_dialog(self._app_queue.pop(0))
        if self._app_time_queue:          # 「用久了提醒」扫到的应用列表
            self.app_time_dialog(self._app_time_queue.pop(0))
        if self._mem_queue:
            self._mem_trim_done(self._mem_queue.pop(0))

        if self.jump_t > 0:
            self.jump_t = max(0.0, self.jump_t - 0.06)
        if self.cross_t > 0:
            self.cross_t = max(0.0, self.cross_t - 0.15)
        if self.action_t > 0:
            self.action_t = max(0.0, self.action_t - 0.03)
            if self.action_t == 0:
                self.action = None

        if self.ui_open:        # 菜单 / 对话框开着：站住不动，免得跳上去把设置面板遮住
            if self.perf_mode:
                self.update()           # 性能模式：动画照跑，菜单开着也不掉帧
            elif self.t % 5 == 0:
                self.update()           # 休闲模式：几帧刷一次，省点资源
            return

        if self.dragging:
            self.update()
            return
        now_ms = self.t * self.tick_ms

        if self.mode == "follow":
            cursor = self.cursor().pos()
            screen = QApplication.screenAt(cursor) or self.screen() or QApplication.primaryScreen()
            geo = screen.availableGeometry()
            near = (self.x() - 100 <= cursor.x() <= self.x() + self.width() + 100 and
                    self.y() - 100 <= cursor.y() <= self.y() + self.height() + 100)
            if near:
                self.target = None
            else:
                # 目标点按"窗口中心"算，并且夹在可达范围内，否则贴边时会永远够不到
                half_w, half_h = self.width() / 2, self.height() / 2
                tx = max(geo.left() + half_w, min(geo.right() - half_w, cursor.x()))
                ty = max(geo.top() + half_h, min(geo.bottom() - half_h, cursor.y() + 60))
                self.target = (tx, ty)
        elif self.mode == "wander":
            if self.target is None:
                if now_ms < self.rest_until:
                    self._maybe_idle_action()
                    self.update()
                    return
                geo = (self.screen() or QApplication.primaryScreen()).availableGeometry()
                # 同样按窗口中心取点，保证这个点在"窗口不出屏"的钳制范围内可达
                half_w, half_h = self.width() / 2, self.height() / 2
                self.target = (random.randint(int(geo.left() + half_w), int(geo.right() - half_w)),
                               random.randint(int(geo.top() + half_h), int(geo.bottom() - half_h)))
        else:
            # 原地待着：一直维持正面形象，不再转头看鼠标、也不会背过身
            # （拖动过程中的朝向逻辑照旧走 mouseMoveEvent，不受这里影响）
            self._still_face_front()
            self._maybe_idle_action()
            self.update()
            return

        if self.target is not None:
            # 卡住保护：有目标却几乎没挪窝（比如贴着屏幕边），2 秒就换个目标
            moved = abs(self.x() - self._last_pos[0]) + abs(self.y() - self._last_pos[1])
            self._last_pos = (self.x(), self.y())
            self._stuck_ticks = 0 if moved >= 2 else self._stuck_ticks + 1
            if self._stuck_ticks > 100:
                self._stuck_ticks = 0
                self.target = None
                self.rest_until = self.t * self.tick_ms + random.randint(2000, 6000)
                self._set_dir("down")
                self.update()
                return

            cx, cy = self.x() + self.width() / 2, self.y() + self.height() / 2
            dx, dy = self.target[0] - cx, self.target[1] - cy
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < 12:
                self.target = None
                self.rest_until = self.t * self.tick_ms + random.randint(8000, 18000)
                self._set_dir("down")
            else:
                step = self.cur_speed * self.tick_ms / 1000.0
                nx, ny = cx + dx / dist * step, cy + dy / dist * step
                # 整个窗口都要留在屏幕内，否则气泡会被顶出屏幕
                geo = (self.screen() or QApplication.primaryScreen()).availableGeometry()
                mx = max(geo.left(), min(geo.right() - self.width() + 1, int(nx - self.width() / 2)))
                my = max(geo.top(), min(geo.bottom() - self.height() + 1, int(ny - self.height() / 2)))
                self.move(mx, my)
                self._face_travel(dx, dy)
            if random.random() < 0.002 and self.jump_t == 0:
                self.jump_t = 0.5
        target_speed = SPEED if self.target is not None else 0.0
        self.cur_speed += (target_speed - self.cur_speed) * 0.3
        self.update()

    def check_processes(self):
        """切到（或刚打开）某个应用时冒一句吐槽。

        改成看"前台窗口"而不是"新出现的进程"：这样已经开着的微信 / 浏览器 /
        QQ 也算数，不会像以前那样只有刚启动的 Steam 会触发。同一个应用
        10 分钟（ChatGPT 15 分钟）只吐槽一次，避免刷屏。
        """
        name = foreground_process_name()
        if not name:
            return
        # 桌宠自己在前台（开着设置窗口 / 右键菜单）：不算"切到别的应用" ——
        # 既不打断了「用久了」那一段连续计时，也不拿自己当触发对象
        if foreground_pid() == os.getpid():
            return
        # 「用久了提醒」跟「打开时冒泡」是两个开关，各管各的
        self._track_fg_usage(name)
        if not self.process_alerts:
            return
        lines_map = self._process_lines_map()
        if name not in lines_map:
            self._foreground_proc = name
            return
        if name == self._foreground_proc:
            return
        self._foreground_proc = name
        now = time.time()
        cooldown = 900 if name == "chatgpt.exe" else 600
        if now - self._proc_said_at.get(name, 0) < cooldown:
            return
        self._proc_said_at[name] = now
        self._say_reminder(random.choice(lines_map[name]))

    def _process_lines_map(self):
        """默认台词表 → 用户改写的默认台词 → 用户自己加的应用。

        结果按**内容指纹**缓存：这个函数每 2 秒被问一次，没必要每次都把 18 条重建一遍。
        指纹就是这两张表本身 —— 菜单里改、对话框里改、甚至直接手改 config.json，
        指纹一变就重算，不会出现"台词改了菜单里还是旧的"（第一版按"谁改谁作废"写，
        漏了一条路就会读到旧表，改用指纹以后这条路彻底没有）。
        """
        custom = self.cfg.get("custom_process_lines") or {}
        overrides = self.cfg.get("default_line_overrides") or {}
        key = (repr(custom), repr(overrides))
        if self._proc_lines_cache and self._proc_lines_cache[0] == key:
            return self._proc_lines_cache[1]
        merged = {k: list(v) for k, v in PROCESS_LINES.items()}
        for exe, lines in overrides.items():
            exe = (exe or "").strip().lower()
            if exe and lines:
                merged[exe] = [t for t in lines if t]      # 改写内置台词（整组替换）
        for exe, lines in custom.items():
            exe = (exe or "").strip().lower()
            if not exe or not lines:
                continue
            if exe in PROCESS_LINES:
                continue        # 内置应用只走 override，不在这里追加，避免"重复添加"
            merged[exe] = list(merged.get(exe, [])) + [t for t in lines if t]
        self._proc_lines_cache = (key, merged)
        return merged

    def _invalidate_proc_lines(self):
        """用户改了"打开应用时冒泡"的台词 → 直接把缓存丢掉（指纹那条路也能兜住）。"""
        self._proc_lines_cache = None

    # ---------- 用久了提醒 ----------
    def app_time_rules(self):
        """{exe: {minutes, repeat, on, lines}}。规则表就在 config.json 里。"""
        box = self.cfg.get("app_time_lines")
        return dict(box) if isinstance(box, dict) else {}

    def set_app_time_rules(self, rules):
        self.cfg["app_time_lines"] = rules

    def _usage_rule(self, exe):
        """这个应用连续用满多久该说话？没配 / 已关 / 没台词都返回 None。"""
        rule = self.app_time_rules().get((exe or "").lower())
        if not isinstance(rule, dict) or not rule.get("on", True):
            return None
        lines = [str(t) for t in (rule.get("lines") or []) if str(t).strip()]
        if not lines:
            return None
        try:
            minutes = max(1, int(rule.get("minutes") or 60))
        except (TypeError, ValueError):
            minutes = 60
        try:
            repeat = max(0, int(rule.get("repeat") or 0))
        except (TypeError, ValueError):
            repeat = 0
        return minutes, repeat, lines

    def _track_fg_usage(self, name, now=None):
        """记"这个应用连续在前台待了多久"，到点说一句。

        只在**本人在用**的时候累计：连着 FG_IDLE_FREEZE 秒没人动键鼠
        （看电影、挂机、人走开了），这段时间不算进去 —— 不然回来会被冤枉。
        台词里可以用 `{app}`（应用名）和 `{minutes}` / `{hm}`（用了多久）。
        """
        now = time.time() if now is None else now
        if name != self._fg_exe:            # 换应用了：这一轮从头开始
            self._fg_exe = name
            self._fg_accum = 0.0
            self._fg_clock = now
            self._fg_count = 0
            return
        gap = now - self._fg_clock
        self._fg_clock = now
        idle = idle_seconds()
        if idle is not None and idle > FG_IDLE_FREEZE:
            return                          # 人没在用：不累计，也不提醒
        if gap > 0:
            self._fg_accum += gap
            self._app_time_add(name, gap, now=now)     # 顺手记进"今天用了多久"的账本
        rule = self._usage_rule(name)
        if rule is None:
            return
        minutes, repeat, lines = rule
        used = self._fg_accum / 60.0
        if used < minutes:
            return
        due = 1 if not repeat else 1 + int((used - minutes) // repeat)
        if due <= self._fg_count:
            return
        self._fg_count = due                # 关着开关也记上：免得一打开就补一串旧提醒
        if self.cfg.get("app_time_on", True):
            text = fill_vars(random.choice(lines), app=self.app_label(name),
                             minutes=int(used), hm=fmt_duration(used * 60))
            self._say_reminder(text)

    def app_time_dialog(self, apps=None):
        """用久了提醒。第一次进来先把本机应用扫出来（后台扫，扫完自己弹）。"""
        if apps is None:
            self.say("我翻翻你电脑里的应用哦…")
            threading.Thread(target=lambda: self._app_time_queue.append(scan_apps()),
                             daemon=True).start()
            return
        if not apps:
            apps = sorted((exe, exe, "") for exe in PROCESS_LINES)
        with self._ui_guard():
            AutoSayDialog(self, "apptime", apps).exec()
        self._notify_console()

    # ---------- 到点说一句 ----------
    def clock_rules(self):
        rules = self.cfg.get("timed_lines")
        return [r for r in rules if isinstance(r, dict)] if isinstance(rules, list) else []

    def set_clock_rules(self, rules):
        self.cfg["timed_lines"] = rules

    def check_timed_lines(self):
        """到点说一句。跟峰谷提醒同一个地方调（每秒看一次）。

        `summary: true` 的那几条（内置的 23:30 就是）会先说一句**今天的小结**
        （余额用量 + 用得最久的一两个应用），再接一句台词；今天没什么可说的就只说台词。
        """
        if not self.cfg.get("timed_on", True):
            return
        now = datetime.now()
        hm = now.strftime("%H:%M")
        today = now.strftime("%Y-%m-%d")
        stamp = time.time()
        for i, rule in enumerate(self.clock_rules()):
            if not rule.get("on", True):
                continue
            lines = [str(t) for t in (rule.get("lines") or []) if str(t).strip()]
            if not lines:
                continue
            rid = rule.get("id") or f"#{i}"
            when = (rule.get("when") or "daily").lower()
            if when == "interval":          # 每隔 N 分钟
                try:
                    every = max(1, int(rule.get("every") or 60))
                except (TypeError, ValueError):
                    every = 60
                last = self._timed_last.get(rid)
                if last is None:
                    self._timed_last[rid] = stamp     # 刚启动先记一笔，别一开桌宠就炸
                elif stamp - last >= every * 60:
                    self._timed_last[rid] = stamp
                    self._say_clock_rule(rule, lines)
                continue
            if (rule.get("time") or "").strip() != hm:
                continue
            if when == "weekly":            # 每周：得今天正好勾上
                try:
                    days = {int(d) for d in (rule.get("days") or [])}
                except (TypeError, ValueError):
                    days = set()
                if now.weekday() not in days:
                    continue
            mark = f"{today} {hm}"
            if self._timed_last.get(rid) == mark:     # 这一分钟已经说过了
                continue
            self._timed_last[rid] = mark
            self._say_clock_rule(rule, lines)

    def _say_clock_rule(self, rule, lines):
        """一条到点规则该说的话：可选"今天的小结" + 一句台词。"""
        text = random.choice(lines)
        if rule.get("summary"):
            head = self.daily_summary()
            if head:
                text = head + "。" + text
        self._say_reminder(text)

    def timed_lines_dialog(self):
        with self._ui_guard():
            AutoSayDialog(self, "clock").exec()
        self._notify_console()

    # ---------- 全局快捷键 ----------
    def hotkey_rules(self):
        rules = self.cfg.get("hotkeys")
        return [r for r in rules if isinstance(r, dict)] if isinstance(rules, list) else []

    def set_hotkey_rules(self, rules):
        self.cfg["hotkeys"] = rules
        self._register_hotkeys()          # 改了键 / 台词，立刻按新的注册

    def hotkey_failed_texts(self):
        return list(getattr(self, "_hotkey_failed", []))

    def _unregister_hotkeys(self):
        ids = list(getattr(self, "_hotkey_ids", []))
        self._hotkey_ids = []
        self._hotkey_slots = {}
        if not ids:
            return
        try:
            user32 = ctypes.WinDLL("user32.dll")
            for hid in ids:
                try:
                    user32.UnregisterHotKey(None, hid)
                except Exception:
                    pass
        except Exception:
            pass

    def _register_hotkeys(self):
        """按配置注册全局快捷键。注册不上（键被别的程序占用）的记在 _hotkey_failed 里。"""
        self._unregister_hotkeys()
        self._hotkey_failed = []
        if not self.cfg.get("hotkeys_on", True):
            return
        try:
            user32 = ctypes.WinDLL("user32.dll")
        except Exception:
            return
        for i, rule in enumerate(self.hotkey_rules()):
            if not rule.get("on", True):
                continue
            seq = (rule.get("seq") or "").strip()
            parsed = hotkey_parse(seq)
            lines = [str(t) for t in (rule.get("lines") or []) if str(t).strip()]
            act = rule.get("act") or "lines"
            if act == "lines" and not lines:
                continue
            if not parsed:
                if seq:
                    self._hotkey_failed.append(seq)
                continue
            mods, vk = parsed
            hid = HOTKEY_BASE + i
            try:
                ok = bool(user32.RegisterHotKey(None, hid, mods | HOTKEY_NOREPEAT, vk))
            except Exception:
                ok = False
            if ok:
                self._hotkey_ids.append(hid)
                self._hotkey_slots[hid] = dict(rule)
            else:
                self._hotkey_failed.append(seq)

    def _on_hotkey(self, hid):
        """原生消息里收到 WM_HOTKEY：按这条规则的动作来一下。"""
        rule = (getattr(self, "_hotkey_slots", None) or {}).get(hid)
        if not rule:
            return
        act = rule.get("act") or "lines"
        if act == "balance":
            self._double_click_balance()
        elif act == "weather":
            self._get_weather()
        elif act == "music":
            self.check_music_now()
        else:
            lines = [str(t) for t in (rule.get("lines") or []) if str(t).strip()]
            if lines:
                self.say(random.choice(lines), again=True, seconds=3.2, queue=True)

    def hotkeys_dialog(self):
        with self._ui_guard():
            AutoSayDialog(self, "hotkey").exec()
        self._notify_console()

    def scan_apps_dialog(self):
        """扫描本机应用，然后让用户挑一个加"打开时触发的文字"。"""
        self.say("我翻翻你电脑里的应用哦…")
        threading.Thread(target=lambda: self._app_queue.append(scan_apps()),
                         daemon=True).start()

    def _pick_app_dialog(self, apps):
        if not apps:
            self.say("一个都没扫到诶，等会儿再试嘛")
            return
        # 带图标 + 可搜索的应用列表，像「设置 → 应用」那样一眼能认出来
        with self._ui_guard():
            AppScanDialog(self, apps).exec()

    def remove_custom_app_dialog(self):
        """清理：删掉自己加的应用台词，或把改写过的内置应用恢复成原版。"""
        custom = dict(self.cfg.get("custom_process_lines") or {})
        overrides = dict(self.cfg.get("default_line_overrides") or {})
        if not custom and not overrides:
            self.say("还没有自己加的应用呢")
            return
        labels = ([f"{exe}（你自己加的）" for exe in sorted(custom)]
                  + [f"{exe}（改写过内置台词）" for exe in sorted(overrides)])
        with self._ui_guard():
            pick, ok = QInputDialog.getItem(self, "清理自定义文字", "要清掉哪一条？",
                                            labels, 0, False,
                                            Qt.WindowType.WindowStaysOnTopHint)
        if not ok or not pick:
            return
        exe = pick.split("（", 1)[0].strip()
        custom.pop(exe, None)
        overrides.pop(exe, None)
        self.cfg["custom_process_lines"] = custom
        self.cfg["default_line_overrides"] = overrides
        self.save_config()
        self._invalidate_proc_lines()
        self.say(f"已清理 {exe} 的文字")

    def set_agent_name_dialog(self):
        """设置"每轮消耗"里显示的 agent 名称（不是每个人都用 Codex）。"""
        with self._ui_guard():
            name, ok = QInputDialog.getText(
                self, "Agent 名称",
                "你用的 agent 叫什么？\n（会显示成「上一轮 XX 消耗 ¥…」，例如 Codex / Claude / Cursor）",
                QLineEdit.EchoMode.Normal, self.agent_name,
                Qt.WindowType.WindowStaysOnTopHint)
        if ok and name.strip():
            self.agent_name = name.strip()
            self.cfg["agent_name"] = self.agent_name
            self.save_config()
            self.say(f"好，以后就说「上一轮 {self.agent_name} 消耗」")

    def set_agent_dir_dialog(self):
        """设置会话日志目录（放 .jsonl 的那个目录，别的 agent 也能指向自己的日志）。"""
        start = self.agent_dir if os.path.isdir(self.agent_dir) else os.path.expanduser("~")
        with self._ui_guard():
            path = QFileDialog.getExistingDirectory(
                self, "选择会话日志目录（里面是 .jsonl）", start,
                QFileDialog.Option.DontUseNativeDialog)
        if not path:
            return
        self.agent_dir = path
        self.codex_dir = path
        self.cfg["agent_sessions_dir"] = path
        self.save_config()
        self._codex_file = None          # 重新对齐到最新日志
        self._codex_pos = 0
        self._codex_turn = None
        self._codex_tokens = {}
        self.say("日志目录换好了，我从现在开始盯")

    def _face_cursor(self):
        """跟着鼠标转（只转头、不挪窝）。规则是主人定的：

          - 鼠标在**右边** → 往右转（侧面 + 镜像）
          - 鼠标在**左边** → 往左转（侧面）
          - 鼠标在**身上/附近**（STILL_FACE_NEAR 这个圈里）→ 正对着你
          - **没有背影**：鼠标跑到上方也只是正面，绝不背过身去

        「原地待着」默认不做这个动作（固定正面），只有挂件形象 + 菜单里那条开关打开时才会。
        """
        if self.dragging or self.target is not None:
            return
        cursor = self.cursor().pos()
        dx = cursor.x() - (self.x() + self.width() / 2)
        dy = cursor.y() - (self.y() + self.height() / 2)
        if dx * dx + dy * dy <= STILL_FACE_NEAR * STILL_FACE_NEAR:
            self._set_dir("down", 1)                 # 贴身上：正对
        elif abs(dx) >= abs(dy):                     # 偏左右：按左右转
            self._set_dir("left" if dx < 0 else "right", 1 if dx < 0 else -1)
        else:                                        # 偏上下：正对（不背过身）
            self._set_dir("down", 1)

    def _still_face_front(self):
        """「原地待着」模式的朝向：默认一直维持正面（三维外观给正面，挂件也不左右翻面）。

        只影响"静止待着"时；拖动过程中的朝向照旧（mouseMoveEvent 里该翻就翻，
        松手回正面），所以拖起来的感觉和以前一样。

        例外：菜单里打开了「原地待着时也跟着鼠标转」的话，**当前形象**（大肥鱼/挂件都一样）
        就实时盯着鼠标 —— `_face_cursor`：鼠标在右往右转、在左往左转、贴身上/附近就正对着你，
        **不会背过身**。
        """
        if self.still_face_cursor:
            self._face_cursor()
            return
        if self.dir != "down" or self.facing != 1:
            self._set_dir("down", 1)

    def _maybe_idle_action(self):
        # 闲着时的"小动作"概率固定 0.03；发呆时说什么、说多勤由主人选的「语录频率」决定
        # （安静 / 正常 / 话多 / 话痨，见 LINE_FREQ_LEVELS）
        preset = LINE_FREQ_LEVELS.get(getattr(self, "line_freq", LINE_FREQ_DEFAULT),
                                      LINE_FREQ_LEVELS[LINE_FREQ_DEFAULT])
        if random.random() < 0.03:
            pick = random.random()
            if pick < 0.35:
                self.jump_t = 1.0
            elif pick < 0.6:
                self.action, self.action_t = "sway", 1.0
            elif pick < 0.7:
                self.action, self.action_t = "stretch", 1.0
            else:
                # 剩下 30% 的机会拿来冒话，两句之间按主人在「语录频率」里选的间隔隔开
                if self._music_playing():
                    return      # 放歌时不插嘴，把位置让给歌词
                if self._hold_now():
                    return      # 免打扰中 / 正在全屏打游戏看电影：一个字都不说
                if self._secs() < getattr(self, "_dc_hold_until", 0.0):
                    return      # 刚快速双击过：让它把选好的那一眼（余额/天气/台词）先说完
                if self._secs() < getattr(self, "_trigger_until", 0.0):
                    return      # 刚有触发类的话在说（开应用 / 用久了 / 到点 / 快捷键 / 回嘴…）：
                                # 让它先把话说完，闲话等下再说，不许盖掉它
                if self.t - self.last_speak_tick >= preset["cooldown"]:
                    self.last_speak_tick = self.t
                    # 「心声」占四成、「日常台词」占其余；关掉的板块直接不参与
                    # （两块都关了 = 闲着的时候一句话都不说，见 LINE_SECTIONS）
                    if random.random() < 0.4:
                        words = self.lines_for_say("INNER_LINES")
                        if words:
                            self.say(random.choice(words), inner=True, idle=True)
                            return
                    words = self.lines_for_say("LINES")
                    if not words:
                        return
                    if not self._double_click_sees_balance():
                        # 双击已经不归余额管了：别让它嘴上还挂着"双击我给你看余额"
                        words = [w for w in words if w != DOUBLE_CLICK_HINT_LINE] or words
                    self.say(random.choice(words), idle=True)

    def _queue_say(self, text):
        """后台线程调用：只入队，由主线程 tick 统一弹出显示（线程安全）"""
        self._say_queue.append(text)

    # ---------- 台词（用户可自定义 / 可改写内置）----------
    # ---------- 语录板块：哪几块参与说话（设置 → 文案和语录 → 语录板块）----------
    def line_sections_off(self):
        """现在关着的板块 id 集合。配置写坏了也不怕：认不出的 id 直接忽略。"""
        raw = self.cfg.get("lines_off") or []
        if not isinstance(raw, (list, tuple, set)):
            return set()
        return {str(x) for x in raw if str(x) in LINE_SECTION_IDS}

    def line_section_on(self, section):
        """这个板块现在是开着的吗（认不出的 id 一律当"开着"，别把人家的台词吞了）。"""
        return section not in self.line_sections_off()

    def set_line_section(self, section, on):
        """开 / 关一块语录：关掉 = 这一块整个不再说话（台词还在，随时能再打开）。

        定死的一条：**快速双击不受影响** —— 它不是板块，双击照旧做它那一件事
        （看余额 / 看天气 / 看在放什么 / 说一句我写的台词）。
        """
        if section not in LINE_SECTION_IDS:
            return
        off = self.line_sections_off()
        if on:
            off.discard(section)
        else:
            off.add(section)
        # 按 LINE_SECTIONS 的顺序存：配置文件里看着整齐，也不会越存越乱
        self.cfg["lines_off"] = [sid for sid, _n, _d, _k in LINE_SECTIONS if sid in off]
        self.save_config()
        if on:
            self.say("好，这块我接着说", seconds=2.2, again=True)

    def lines_for_say(self, key):
        """要开口时取某类台词：**这一块关掉了就返回空**（调用方自己别说话）。

        跟 `lines_for()` 的区别只有这一句 —— 台词编辑器照样用 `lines_for()` 读全部台词，
        "该不该开口"才问这里（见 LINE_SECTIONS）。
        """
        section = LINE_SECTION_OF.get(key)
        if section is not None and not self.line_section_on(section):
            return []
        return self.lines_for(key)

    def lines_for(self, key):
        """取某一类台词：用户改过就用用户那套，否则用内置默认。"""
        default = globals().get(key) or []
        if not default and key in FREQ_LINE_KEYS:
            default = FREQ_LINES[FREQ_LINE_KEYS[key]]      # 说多勤那四档的话
        custom = (self.cfg.get("custom_lines") or {}).get(key)
        if isinstance(custom, list):
            words = [str(t).strip() for t in custom if str(t).strip()]
            if words:
                return words
        return list(default)

    def set_lines(self, key, words):
        """写回某一类台词；words 为空 = 恢复内置默认。"""
        box = dict(self.cfg.get("custom_lines") or {})
        words = [str(t).strip() for t in (words or []) if str(t).strip()]
        if words:
            box[key] = words
        else:
            box.pop(key, None)
        self.cfg["custom_lines"] = box
        self.save_config()

    def lines_customized(self, key):
        return bool((self.cfg.get("custom_lines") or {}).get(key))

    def edit_lines_dialog(self, initial_key=None):
        """一个窗口里改所有台词：上面选类别，下面一行一句；可一键恢复默认。

        initial_key 用来直接停在某一类上（菜单里「快速双击 → 改写这几句…」用它）。
        """
        from PySide6.QtWidgets import QPlainTextEdit
        dlg = QDialog(self)
        dlg.setWindowTitle("台词内容（自定义或改写内置）")
        dlg.resize(560, 460)
        if ui_console:                      # 跟设置窗口用同一套配色
            ui_console.style_dialog(dlg, BUNDLE_DIR)
        lay = QVBoxLayout(dlg)
        # 语录频率也放这个窗口里（和菜单「文案 → 语录频率」是同一个设置）
        row0 = QHBoxLayout()
        row0.addWidget(QLabel("语录频率："))
        freq_combo = QComboBox()
        for _fname, _fpreset in LINE_FREQ_LEVELS.items():
            freq_combo.addItem(f"{_fname}（{_fpreset['hint']}）", _fname)
        try:
            freq_combo.setCurrentIndex(list(LINE_FREQ_LEVELS).index(self.line_freq))
        except ValueError:
            pass
        row0.addWidget(freq_combo, 1)
        lay.addLayout(row0)
        freq_hint = QLabel("语录频率只影响闲置时的自动说话；点击、拖拽、换歌等反应不受影响，"
                           "播放音乐时也不会说话。")
        freq_hint.setWordWrap(True)
        freq_hint.setObjectName("dim")
        lay.addWidget(freq_hint)
        row = QHBoxLayout()
        row.addWidget(QLabel("改哪一类："))
        combo = QComboBox()
        for key, label in LINE_GROUPS:
            _sec = LINE_SECTION_OF.get(key)
            if _sec is not None and not self.line_section_on(_sec):
                label += "〔已关闭〕"      # 这一类现在不参与说话（关它的开关在设置里）
            combo.addItem(label, key)
        if initial_key:
            _idx = combo.findData(initial_key)
            if _idx >= 0:
                combo.setCurrentIndex(_idx)
        row.addWidget(combo, 1)
        lay.addLayout(row)
        hint = QLabel("下面这些就是这一类的台词：一行一句（空行自动忽略）；"
                      "放歌那两类里可以写 %s 代表当前歌名；"
                      "保存时留空 = 恢复这一类默认。" % "{song}")
        hint.setWordWrap(True)
        hint.setObjectName("dim")
        lay.addWidget(hint)
        edit = QPlainTextEdit()
        lay.addWidget(edit, 1)
        state = QLabel("")
        state.setObjectName("dim")
        lay.addWidget(state)
        btns = QHBoxLayout()
        btn_restore = QPushButton("恢复这一类默认")
        btn_ok = QPushButton("保存")
        btn_cancel = QPushButton("取消")
        btn_ok.setObjectName("primary")
        btns.addWidget(btn_restore)
        btns.addStretch(1)
        btns.addWidget(btn_ok)
        btns.addWidget(btn_cancel)
        lay.addLayout(btns)

        def current_key():
            return combo.currentData()

        def load(_=None):
            key = current_key()
            edit.setPlainText("\n".join(self.lines_for(key)))
            who = ("这一类：自定义（保存时留空 = 恢复默认）"
                   if self.lines_customized(key)
                   else "这一类：当前用内置默认台词")
            _sec = LINE_SECTION_OF.get(key)
            if _sec is not None and not self.line_section_on(_sec):
                who += "　·　这个板块现在是关着的（设置 → 文案和语录 → 语录板块）"
            state.setText(who)

        def restore():
            self.set_lines(current_key(), [])
            load()
            self.say("这一类恢复成内置台词了", seconds=2.2, again=True)

        def save():
            self.set_lines(current_key(), edit.toPlainText().splitlines())
            load()
            self.say("台词存好啦", seconds=2.2, again=True)

        def freq_changed(_=None):
            name = freq_combo.currentData()
            if name and name != self.line_freq:
                self.set_line_freq(name)      # 立刻生效 + 写进 config（顺手冒一句）

        combo.currentIndexChanged.connect(load)
        freq_combo.currentIndexChanged.connect(freq_changed)
        btn_restore.clicked.connect(restore)
        btn_ok.clicked.connect(save)
        btn_cancel.clicked.connect(dlg.reject)
        load()
        with self._ui_guard():
            dlg.exec()

    def say(self, text, inner=False, seconds=2.8, again=False, idle=False, queue=False):
        """冒一句话。

        `idle=True` 只有"闲着时自己冒话"会用（见 `_maybe_idle_action`）：
        **触发类的话优先级最高** —— 开应用 / 用久了 / 到点 / 快捷键 / 双击 / 点它 / 拖它 /
        换歌 / 各种操作提示，说的时候"闲话"不许插嘴、也不许盖掉它（说完闲话自己接着冒）；
        反过来触发类的话可以立刻盖掉正在说的闲话（这条本来就该这样，主人点名要的）。
        `idle` 还顺带绕开下面这条去重：触发类的话即使跟上一句一模一样也要正常显示，
        不能因为"刚说过"就被憋回去（闲话才需要去重）。

        `queue=True`：**自动类的触发**（开应用 / 用久了 / 到点 / 快捷键）用这个。
        如果这会儿已经有触发类的话在说、或者队列里还排着，这句就**排在后面依次说**，
        不跟它抢（两条几乎同时来的时候，两句都能看见）。
        """
        if idle and text == self.last_line and not again and not text.startswith("天气"):
            return
        if queue:
            when = self._queue_behind()
            if when is not None:
                self._pending_bubbles.append((when, text, inner))
                del self._pending_bubbles[:-6]        # 排太长了就丢掉最早的
                return
        self.last_line = text
        self.bubble_inner = inner
        self.bubble_text = f"（{text}）" if inner else text
        self.bubble_until = self._secs() + seconds
        if not idle:
            # 这段时间归"触发类"的话：闲着冒话先憋着（见 _maybe_idle_action 里那个判断）
            self._trigger_until = self._secs() + seconds
        self.update()

    def _queue_behind(self):
        """要排队的话该排在什么时候（没人说话、队列也空就返回 None = 可以直接说）。"""
        now = self._secs()
        busy = max([now, getattr(self, "_trigger_until", 0.0)]
                   + [item[0] for item in self._pending_bubbles])
        return busy + 0.3 if busy > now + 0.01 else None

    # ---------- 合体新增：AI 对话 ----------
    def _chat_key(self):
        """聊天用的 DeepSeek Key：优先 config.json，其次系统环境变量（和余额同源）。"""
        return (self.cfg.get("ds_api_key") or os.environ.get("DEEPSEEK_API_KEY", "") or "").strip()

    def _call_ds(self, user_msg):
        if self.ds_busy:
            self.say("等等，上一句还没回完呢")
            return
        key = self._chat_key()
        if not key:
            self.say("请先在右键菜单里设置 DeepSeek Key！")
            return
        self.ds_busy = True
        messages = [{"role": "system", "content": DS_SYSTEM}]
        messages.extend(self.chat_history[-CHAT_MAX_HISTORY:])
        messages.append({"role": "user", "content": user_msg})

        def worker():
            url = DS_BASE_URL + "/chat/completions"
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            payload = {"model": DS_MODEL, "messages": messages,
                       "max_tokens": 100, "temperature": 0.9}
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=10)
                if resp.status_code == 200:
                    reply = resp.json()["choices"][0]["message"]["content"].strip()
                    if len(reply) > 30:
                        reply = reply[:28] + "…"
                    self.chat_history.append({"role": "user", "content": user_msg})
                    self.chat_history.append({"role": "assistant", "content": reply})
                    if len(self.chat_history) > CHAT_MAX_HISTORY:
                        self.chat_history = self.chat_history[-CHAT_MAX_HISTORY:]
                    self._queue_say(reply)
                else:
                    err = resp.json().get("error", {}).get("message", str(resp.status_code))
                    self._queue_say(f"API错误: {err[:12]}")
            except requests.exceptions.Timeout:
                self._queue_say("请求超时，检查网络")
            except requests.exceptions.ConnectionError:
                self._queue_say("连接失败，检查网络")
            except Exception as e:
                self._queue_say(f"请求失败: {str(e)[:12]}")
            finally:
                self.ds_busy = False

        threading.Thread(target=worker, daemon=True).start()

    def _show_chat_dialog(self):
        if not self._chat_key():
            self.say("请先在右键菜单里设置 DeepSeek Key！")
            return
        self.chat_open = True
        self.chat_dialog.popup_at(self.x() + self.width() / 2, self.y() + BUBBLE_H)

    # ---------- 合体新增：喂食 ----------
    def _open_food_panel(self):
        self.food_panel.popup_at(self.x() + self.width() / 2, self.y() + BUBBLE_H)

    def on_food(self, food):
        self.food_panel.hide()
        self.jump_t = 0.6
        self.action, self.action_t = "stretch", 1.0
        lines = FOOD_LINES.get(food, ["好吃！"])
        self.say(random.choice(lines))

    # ---------- 合体新增：系统监控 ----------
    def check_system_status(self):
        if not self.cfg.get("sys_monitor_on", True):
            return
        now = time.time()
        if now - self.last_system_check < 10:
            return
        self.last_system_check = now
        try:
            cpu = psutil.cpu_percent()
        except Exception:
            return
        if cpu >= 90:
            self.say("CPU跑满了，再这样下去我就卡死了")
            return
        try:
            ram = psutil.virtual_memory().percent
        except Exception:
            return
        if ram >= 95:
            self.say("内存爆了，快关掉几个没用的东西吧，注意，别把我关了")
            return
        if GPU_AVAILABLE:
            try:
                handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                if temp > 80:
                    self.say("我感觉我的鱼鳍快熟了")
            except Exception:
                pass

    # ---------- 合体新增：DSH 联动 ----------
    def poll_dsh(self):
        """后台线程读一次 DSH 会话日志（别卡界面）。"""
        if not self.dsh_on or self._dsh_busy:
            return
        self._dsh_busy = True
        threading.Thread(target=self._dsh_worker, daemon=True).start()

    def _dsh_worker(self):
        """后台线程：只读新追加的帧，增量更新状态（不再整份解压）。"""
        try:
            path = dsh_latest_session()
            if not path:
                return
            try:
                stt = os.stat(path)
            except OSError:
                return
            size, mtime = stt.st_size, stt.st_mtime
            # 换了会话、或文件被重写变小 → 从头来
            is_new = (path != self._dsh_w_file or size < self._dsh_w_off)
            if is_new:
                self._dsh_w_file = path
                self._dsh_w_off = 0
                self._dsh_w_st = dsh_blank_state()
            elif size == self._dsh_w_off:
                self._dsh_queue.append((path, mtime, "same", False))
                return
            txt, new_off = dsh_read_new(path, self._dsh_w_off)
            if txt is None:
                return
            for ln in txt.splitlines():
                ln = ln.strip()
                if not ln or ln[0] != "{":
                    continue
                try:
                    ev = json.loads(ln)
                except Exception:
                    continue
                dsh_apply_event(self._dsh_w_st, ev)
            self._dsh_w_off = new_off
            dsh_log("worker %s | 新增 %d 字 | turn=%s tool=%s 命令数=%s"
                    % ("换会话" if is_new else "增量",
                       len(txt), self._dsh_w_st.get("turn"),
                       self._dsh_w_st.get("last_tool"),
                       self._dsh_w_st.get("tool_calls")))
            self._dsh_queue.append((path, mtime, dict(self._dsh_w_st), is_new))
        except Exception:
            pass
        finally:
            self._dsh_busy = False

    def _dsh_apply(self):
        """主线程：处理后台读回来的状态（只在「状态变化」时冒泡，不刷屏）。"""
        if not self._dsh_queue:
            return
        path, mtime, state, is_new = self._dsh_queue[-1]   # 只认最新一条，别积压
        self._dsh_queue.clear()
        if state == "same":
            self._dsh_idle_check(mtime)
            return
        if state is None:
            return
        old = self._dsh_state or {}
        self._dsh_file = path
        self._dsh_mtime = mtime
        self._dsh_state = state
        if is_new:
            # 换会话这一拍不反应，免得拿上一条会话的旧状态去比（会误报 start / done）
            self._dsh_idle_said = False
            self._dsh_last_tool = None
            dsh_log("切换到会话 %s，状态重置（这一拍不反应）"
                    % os.path.basename(os.path.dirname(path)))
            return
        self._dsh_react(state, old, mtime)
        # 没在演任何反应、但这一轮还在跑 → 摆出「思考中」的姿势
        if self.dsh_act is None:
            self._dsh_act_revert()

    def _dsh_idle_check(self, mtime):
        """静了一会儿就冒一句闲话。"""
        state = self._dsh_state or {}
        if (state.get("events") and not state.get("turn")
                and not state.get("approval")
                and time.time() - mtime > DSH_IDLE_SEC
                and not self._dsh_idle_said):
            self._dsh_say("idle", 4.0)
            self._dsh_idle_said = True

    def _dsh_react(self, state, old, mtime):
        now = time.time()
        ago = now - self._dsh_said_at
        dsh_log("react 新:t=%s a=%s e=%s tool=%s | 旧:t=%s a=%s e=%s tool=%s | 距上句%.1fs"
                % (state.get("turn"), state.get("approval"), state.get("error"),
                   state.get("last_tool"), old.get("turn"), old.get("approval"),
                   old.get("error"), old.get("last_tool"), ago))
        said = False
        if state.get("approval") and not old.get("approval"):
            dsh_log("  → 命中 approval")
            self._dsh_say("approval", 5.0)     # 等你批准：最高优先级
            said = True
        elif state.get("error") and not old.get("error"):
            dsh_log("  → 命中 error")
            self._dsh_say("error", 4.0)
            said = True
        elif state.get("turn") and not old.get("turn"):
            dsh_log("  → 命中 start")
            self._dsh_say("start", 3.0)        # 开工
            said = True
        elif not state.get("turn") and old.get("turn"):
            dsh_log("  → 命中 done")
            self._dsh_say("done", 3.5)         # 收工
            said = True
        elif state.get("turn"):
            key = DSH_TOOL_KIND.get(state.get("last_tool") or "")
            # 判据改成「又出现了新的 tool/call」—— 一敲命令就反应，
            # 不再靠"等够时间"，也不用管工具名有没有变。
            new_call = state.get("tool_calls", 0) > old.get("tool_calls", 0)
            if key and new_call and ago > DSH_TOOL_COOLDOWN:
                dsh_log("  → 命中工具 %s（新命令 %d→%d，距上句%.1fs）"
                        % (key, old.get("tool_calls", 0), state.get("tool_calls", 0), ago))
                self._dsh_say(key, 3.0)
                said = True
            else:
                dsh_log("  → 工具被跳过：key=%r 新命令=%s ago=%.1fs"
                        % (key, new_call, ago))
        else:
            dsh_log("  → 不在干活中（turn=False），走闲话检查")
        self._dsh_last_tool = state.get("last_tool") or ""
        if said:
            self._dsh_idle_said = False
        else:
            self._dsh_idle_check(mtime)

    # ---------- 合体新增：动作帧播放 ----------
    def _dsh_act_pix(self):
        """当前该画哪一帧（没画动作图就返回 None，交给三视图兜底）。

        同一帧有多档尺寸时，挑「源高度最接近当前显示高度」的那张 —— 越接近越清晰。
        """
        if not self.dsh_act:
            return None
        by_idx = self.dsh_acts.get(self.dsh_act) or {}
        if not by_idx:
            return None
        idxs = sorted(by_idx.keys())
        ms, loop = DSH_ACTS.get(self.dsh_act, (200, True))
        i = max(0, int(self.dsh_act_t // ms))
        i = (i % len(idxs)) if loop else min(i, len(idxs) - 1)
        variants = by_idx[idxs[i]]
        if not variants:
            return None
        want = self.cur_h
        return min(variants, key=lambda t: abs(t[0] - want))[1]

    def _dsh_tick_act(self, dt_ms):
        """推进动作时钟；单次动作播完就回默认站姿。"""
        if not self.dsh_act:
            return
        self.dsh_act_t += dt_ms
        if self.dsh_act_until and time.time() >= self.dsh_act_until:
            self._dsh_act_revert()

    def _dsh_act_revert(self):
        """动作演完 → 回到「该有的常态」。

        优先级：DSH 还在思考（深度思考那会儿）→ working；
                在放歌 → sing；都没有 → 三视图。
        """
        want = None
        if self.dsh_acts.get("working") and (self._dsh_state or {}).get("turn"):
            want = "working"
        elif self.sing_on and self.dsh_acts.get("sing") and self._music_playing():
            want = "sing"
        self.play_dsh_act(want)

    def _sync_music_act(self):
        """音乐状态变了 → 重新决定「常态」该摆哪张图。

        只在当前摆的是常态图（没动作 / 唱歌图 / 思考图）时动手，
        正在演 DSH 反应就不抢；具体换成什么交给 _dsh_act_revert 按优先级定：
        思考中 > 放歌 > 三视图。
        """
        if not self.sing_on and not self.dsh_acts.get("working"):
            return
        if self.dsh_act in (None, "sing", "working"):
            self._dsh_act_revert()

    def play_dsh_act(self, name, hold=None):
        """切到某个动作（None = 回默认站姿）。没画对应图片时静默忽略。

        hold：这个动作显示几秒后自动收回（单帧动作靠它，不然会一直挂着像卡住）。
              循环类动作（多帧）不传 hold，就会一直播到下一个动作。
        """
        if name and name not in self.dsh_acts:
            name = None
        if name == self.dsh_act and not hold:
            return
        self._dsh_act_prev = self._dsh_act_pix() if self.dsh_act else None
        self.dsh_act = name
        self.dsh_act_t = 0.0
        frames = len(self.dsh_acts.get(name) or {}) if name else 0
        loop = DSH_ACTS.get(name, (200, True))[1] if name else False
        if name and (hold or not loop):
            if hold:
                secs = float(hold)
            else:                                    # 单次动作：整段播完
                secs = DSH_ACTS[name][0] * max(1, frames) / 1000.0
            self.dsh_act_until = time.time() + secs
        else:
            self.dsh_act_until = 0.0
        if self._dsh_act_prev is not None and name is not None:
            self.cross_t = 1.0
        dsh_log("播放动作 %s（帧数=%d，保持=%s，收回时机=%.1fs）"
                % (name, frames, hold,
                   (self.dsh_act_until - time.time()) if self.dsh_act_until else 0.0))
        self.update()

    def _dsh_say(self, key, seconds):
        if self.quiet_left() > 0:              # 免打扰期间不吵
            return
        lines = DSH_LINES.get(key) or []
        if not lines:
            return
        self._dsh_said_at = time.time()
        text = random.choice(lines)
        dsh_log("say [%s] 「%s」台词时长%.1fs" % (key, text, seconds))
        self.say(text, seconds=seconds, again=True)
        # 合体新增：切到对应的动作帧（没画图就退回原来的摇摆/蹦跳）
        self.play_dsh_act(DSH_KIND_ACT.get(key, key), hold=seconds)
        if key in ("approval", "error"):
            self.jump_t = max(self.jump_t, 0.7)      # 催批准 / 报错：蹦一下
        else:
            self.action, self.action_t = random.choice(("sway", "stretch")), 1.0

    def set_dsh_on(self, on):
        """开关「DSH 联动」（右键菜单 / 设置窗口都走这里）。"""
        self.dsh_on = bool(on)
        self.cfg["dsh_link"] = bool(on)
        self._dsh_file = None
        self._dsh_mtime = 0.0
        self._dsh_state = None
        self._dsh_idle_said = False
        self._dsh_w_file = None      # 增量读取也重置，重开时从头读一遍
        self._dsh_w_off = 0
        self._dsh_w_st = dsh_blank_state()
        if self.dsh_on:
            if not self.dsh_timer.isActive():
                self.dsh_timer.start(700)
        else:
            self.dsh_timer.stop()
            # 关掉时别把「思考中」立绘留在屏幕上（_dsh_state 已清空，会落到唱歌/三视图）
            if self.dsh_act == "working":
                self._dsh_act_revert()
        self.save_config()
        self.say("好，我盯着你干活了～" if on else "行，不打扰你啦",
                 seconds=3.0, again=True)

    def set_dsh_debug(self, on):
        """DSH 联动排查日志（写到 dsh-debug.log）。"""
        global DSH_DEBUG
        DSH_DEBUG = bool(on)
        self.cfg["dsh_debug"] = bool(on)
        self.save_config()
        if on:
            try:
                with open(DSH_DEBUG_FILE, "w", encoding="utf-8") as f:
                    f.write("=== DSH 调试日志 %s ===\n"
                            % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            except Exception:
                pass
        self.say("开始记 DSH 日志了" if on else "DSH 日志关掉了",
                 seconds=3.0, again=True)

    def set_sing_on(self, on):
        """放歌时要不要换成唱歌立绘。"""
        self.sing_on = bool(on)
        self.cfg["sing_on"] = bool(on)
        self.save_config()
        if not on and self.dsh_act == "sing":
            self.play_dsh_act(None)
        elif on:
            self._sync_music_act()
        self.say("放歌时换姿势，开着呢" if on else "放歌时不换姿势了",
                 seconds=3.0, again=True)

    def set_sys_monitor(self, on):
        """系统状态监控（CPU / 内存 / 显卡超阈值冒泡提醒）。"""
        self.cfg["sys_monitor_on"] = bool(on)
        if on:
            if not self.sys_monitor_timer.isActive():
                self.sys_monitor_timer.start(10000)
        else:
            self.sys_monitor_timer.stop()
        self.save_config()
        self.say("我盯着电脑状态了" if on else "不管电脑状态了",
                 seconds=3.0, again=True)

    # ---------- 鼠标事件 ----------
    def _forward_mouse_to_menu(self, e):
        """菜单开着时，把桌宠收到的鼠标移动转发给菜单。

        这台 Windows 经常不把鼠标移动消息送给弹出菜单（只送给桌宠窗口），
        Qt 的菜单因此以为"鼠标跑出去了"，二三级菜单会莫名其妙自己关掉。
        把移动事件转过去以后，Qt 的悬停高亮 / 展开 / 收起就都恢复正常。
        """
        if not self.ui_open:
            return False
        root = getattr(self, "_menu_keepalive", None)
        if root is None or not root.isVisible():
            return False
        pos = e.globalPosition().toPoint()
        menu = root
        for _ in range(4):                       # 找到光标所在的那一层菜单
            act = menu.actionAt(menu.mapFromGlobal(pos))
            if act is None or act.menu() is None or not act.menu().isVisible():
                break
            menu = act.menu()
        local = menu.mapFromGlobal(pos)
        if not menu.rect().contains(local):
            return False
        QApplication.sendEvent(menu, QMouseEvent(
            QEvent.Type.MouseMove, QPointF(local), e.globalPosition(),
            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, e.modifiers()))
        return True

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            # 点在歌词气泡那几颗 ⏮ / ⏸▶ / ⏭ 上：不进"蹦一下 + 响一声"那套，
            # 等松手再看点的是哪一颗（切歌 / 切播放暂停）
            kind = self._lyric_btn_kind(e.position())
            if kind:
                self._press_on_lyric_btn = kind
                self._lyric_btn_pressed = kind
                self.update()
                return
            self._press_on_lyric_btn = None
            self.press_t = 1.0          # 按压 Q 弹
            self.play_click()           # 点一次响一声完整音效（不再区分松手）
            self.last_press_pos = e.globalPosition().toPoint()
            self.dragging = False
            self._drag_blocked = False
            self.drag_start_pos = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e):
        if self._forward_mouse_to_menu(e):
            return
        # 鼠标划过那几颗按钮：亮一下 + 变成小手（其余时候不弄光标）
        if not self.dragging:
            over = self._lyric_btn_kind(e.position())
            if over != self._lyric_btn_hover:
                self._lyric_btn_hover = over
                self.setCursor(Qt.CursorShape.PointingHandCursor if over
                               else Qt.CursorShape.ArrowCursor)
                self.update()
        if e.buttons() & Qt.MouseButton.LeftButton and self.drag_start_pos is not None:
            delta = e.globalPosition().toPoint() - self.drag_start_pos
            if not self.dragging and delta.manhattanLength() > 6:
                if self.locked:
                    # 锁定位置：按住拖也不挪窝（防误触）；松手时这一次也不算点击
                    self._drag_blocked = True
                    return
                self.dragging = True
                self.drag_offset = e.globalPosition().toPoint() - QPoint(self.x(), self.y())
            if self.dragging and self.drag_offset is not None:
                pos = e.globalPosition().toPoint() - self.drag_offset
                self.move(pos)
                if abs(delta.x()) > 10:
                    self._set_dir("left" if delta.x() < 0 else "right", 1 if delta.x() < 0 else -1)
                self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            pressed = getattr(self, "_press_on_lyric_btn", None)
            if pressed:
                self._press_on_lyric_btn = None
                self._lyric_btn_pressed = None
                self._last_click_ms = -99999    # 这一下不算点击，别带出假的单击 / 双击
                self._single_pending = None     # 点按钮也不是单击：欠着的那句台词撤销
                self.last_press_pos = None
                self.drag_start_pos = None
                # 按的哪颗、松手时还在哪颗上，才算真的点了它
                # （按着划出去再松手 = 反悔，什么都不做）
                if self._lyric_btn_kind(e.position()) == pressed:
                    self.music_command(pressed)
                self.update()
                return
            if self.dragging:
                self.dragging = False
                self.drag_offset = None
                self.drag_start_pos = None
                self._set_dir("down", 1)
                self.target = None
                self.rest_until = self.t * self.tick_ms + random.randint(6000, 14000)
                self._snap_to_edge()    # 松手后吸附到最近的边
                words = self.lines_for_say("DRAG_LINES")
                if words and random.random() < 0.5:
                    self.say(random.choice(words))
            elif self._drag_blocked:
                # 锁定着按住了乱划：什么都不做（不然会被当成单击/双击，蹦一句话或者弹窗口）
                self._drag_blocked = False
                self._last_click_ms = -99999      # 这一下也不算"上一次点击"，免得带出假双击
                self._single_pending = None       # 同上：拖了一把，就不算单击
            else:
                # 用**墙上时间**判双击：以前用桌宠自己的动画时钟（self.t × tick_ms），
                # 一旦动画停一下 / 卡一下，时钟就走得比真实时间慢，两次隔了 0.8 秒的点击
                # 也会被当成"快速双击"。
                now_ms = time.time() * 1000.0
                quick = (now_ms - self._last_click_ms) <= self._double_click_window_ms()
                self._last_click_ms = now_ms
                if quick:
                    self._last_click_ms = -99999      # 双击只算一次
                    self._single_pending = None       # 上一拍欠着的那句单击台词，撤销
                    self._on_double_click()
                else:
                    self._on_single_click()
            self.last_press_pos = None
            self.drag_start_pos = None

    def _on_single_click(self):
        """单击：蹦跳 + 回嘴 + 顺手刷一下余额。

        蹦跳和静默刷新**立刻**做（手感不能等），**台词压到双击判定窗口之后**
        才冒 —— 想快速双击的人不会再被先顶一句台词。这就是"分得开、又没感觉"：
        看得见的部分是零延迟，只有那句可能在 0.3~0.8 秒内被撤销的话在等。
        """
        self.refresh_balance(silent=True)      # 点一下顺手刷新余额
        if self._music_playing():
            # 放歌时报"在放什么"，不用随机台词把歌词顶掉
            self.jump_t = 1.0
            words = self.lines_for_say("MUSIC_CLICK_LINES")
            if words:
                line = random.choice(words)
                self._defer_single_line(lambda: self.say(
                    line.format(song=self._song_label()), seconds=3.6, again=True))
            return
        if random.random() < 0.7:
            self.jump_t = 1.0
        words = self.lines_for_say("REACT_LINES")
        if words and random.random() < 0.6:
            line = random.choice(words)
            self._defer_single_line(lambda: self.say(line))

    def _double_click_window_ms(self):
        """双击判定窗口：跟系统设的双击间隔走，下限 500 毫秒、上限 800 毫秒。

        2026-09-14 之前这里写死 **380 毫秒** —— 比系统还严，手速慢一点的人双击
        会被拆成两次单击（多冒一句台词），误触很高。现在跟系统走，并且**下限提到
        500 毫秒**：这台机器控制面板里设的是 400 毫秒，只照系统来几乎等于没改。
        比窗口短 = 快速双击（撤销欠着的那句单击台词）；比窗口长 = 两次独立单击。
        """
        ms = 500
        try:
            ms = int(QApplication.doubleClickInterval()) or 500
        except Exception:
            pass
        return max(500, min(800, ms))

    def _defer_single_line(self, speak):
        """把单击要说的那句话记下来，等判定窗口过去再冒（窗口内双击就撤销）。"""
        self._single_pending = (self._secs() + self._double_click_window_ms() / 1000.0, speak)

    def _on_double_click(self):
        """快速双击：按一级菜单「快速双击」里选的那样冒一下（默认看 5 秒余额）。

        可选的四种：看一眼余额 / 看一眼天气 / 看一眼在放什么 / 说一句我写的台词。
        「看一眼余额」要配了 Key 才算数 —— 没配 Key 时**不会弹余额窗口**，
        还是原来的"换姿势"，并且只在本次启动里提醒一次怎么配。
        """
        choice = self._double_click_choice()
        # 这几秒里先别自言自语（闲话会盖住刚弹出来的那一眼）；点它 / 拖它照旧有反应
        self._dc_hold_until = self._secs() + DOUBLE_CLICK_HOLD_SEC.get(choice, 3.0)
        if choice == "balance":
            self._double_click_balance()
            return
        if choice == "feed":
            self.action, self.action_t = random.choice(("sway", "stretch")), 1.0
            self.jump_t = max(self.jump_t, 0.6)
            self._open_food_panel()
            return
        # 其它三种：先把动作做出来（蹦一下 / 换个姿势），结果回来再冒泡
        self.action, self.action_t = random.choice(("sway", "stretch")), 1.0
        self.jump_t = max(self.jump_t, 0.6)
        if choice == "weather":
            self._get_weather()          # 后台查，回来冒 5 秒（放歌时也一样）
            return
        if choice == "music":
            self.check_music_now()
            return
        words = self.lines_for("DOUBLE_CLICK_LINES")
        if words:
            self.say(random.choice(words), seconds=4.0, again=True)

    def _double_click_choice(self):
        """快速双击这一项现在选的是哪个（老配置 / 手改坏了都退回默认）。"""
        choice = self.cfg.get("double_click") or DOUBLE_CLICK_DEFAULT
        return choice if choice in dict(DOUBLE_CLICK_CHOICES) else DOUBLE_CLICK_DEFAULT

    def _double_click_effect_label(self):
        """菜单里「快速双击=…」那句说明（跟着用户选的走）。"""
        choice = self._double_click_choice()
        if choice == "balance" and not self._double_click_sees_balance():
            return "看余额（要先配 Key，现在双击只换姿势）"
        return dict(DOUBLE_CLICK_CHOICES).get(choice, "")

    def _double_click_sees_balance(self):
        """双击现在是不是真的能看到余额（选了余额 + 配了 Key 才算）。"""
        return self._double_click_choice() == "balance" and bool(self._current_source()[1])

    def _double_click_menu_title(self):
        """一级菜单里「快速双击」那一项的标题（带着现在选的是什么）。"""
        if self._double_click_choice() == "balance" and not self._double_click_sees_balance():
            return "快速双击（现在：还没配 Key，双击只换姿势）"
        return "快速双击（现在：" + self._double_click_effect_label() + "）"

    def _double_click_balance(self):
        """双击要的那一眼余额：配了 Key 才给看（显示 5 秒）。"""
        name, key = self._current_source()
        if not key:
            self.action, self.action_t = random.choice(("sway", "stretch")), 1.0
            self.jump_t = max(self.jump_t, 0.6)
            if not self._key_hint_shown:
                self._key_hint_shown = True
                self.say(f"双击看余额要先填 {name} 的 Key：右键 →「余额 → 设置 Key」；"
                         f"也可以右键 →「快速双击」换成别的",
                         seconds=4.0, again=True)
            return
        if self.balance is not None:
            self._peek_balance(PEEK_SEC)                # 顶上来显示 5 秒
            return
        # 还没取到过：拉一把，结果回来会自动冒 5 秒（放歌时也一样）
        self._peek_pending = True
        self.refresh_balance(silent=False)

    def _peek_balance(self, seconds=PEEK_SEC):
        """把余额泡泡临时顶上来显示几秒（快速双击用它；放歌时优先于歌词）。"""
        self.show_balance_bubble(seconds, force=True)
        self._bal_peek_until = self._secs() + seconds
        self.action, self.action_t = random.choice(("sway", "stretch")), 1.0
        self.jump_t = max(self.jump_t, 0.6)

    def _get_weather(self):
        """联网查天气（后台线程，别卡住桌宠）。

        合体新增：优先按「提问时段」报预报 —— 上午/凌晨报今天中午、下午、晚上并
        说明会不会下雨，晚上报明天，明天有雨就补报；预报源不通时退回原来的实况播报。
        """
        city = self.cfg.get("city", "北京")

        def worker():
            text = None
            try:
                text = weather_report(city)
            except Exception as ex:
                print("预报失败:", repr(ex))
            if not text:
                got = fetch_weather(city)
                if got:
                    temp, desc = got
                    text = f"{city}今天{temp}°，天气{desc}"
            self._queue_say(text or "天气没查到，等会儿再试试")

        threading.Thread(target=worker, daemon=True).start()

    # ---------- 每轮 Codex 对话消耗 ----------
    def scan_codex_usage(self):
        """尾巴式读最新的 Codex 会话日志，按 turn 汇总 token 用量。"""
        if not self.turn_cost_on:
            return
        newest = None
        try:
            for root, _dirs, files in os.walk(self.codex_dir):
                for fn in files:
                    if not fn.endswith(".jsonl"):
                        continue
                    p = os.path.join(root, fn)
                    try:
                        m = os.path.getmtime(p)
                    except OSError:
                        continue
                    if newest is None or m > newest[0]:
                        newest = (m, p)
        except Exception:
            return
        if not newest:
            return

        path = newest[1]
        if path != self._codex_file:
            # 换文件了：从末尾开始，别把历史轮次当成本轮
            self._codex_file = path
            try:
                self._codex_pos = os.path.getsize(path)
            except OSError:
                self._codex_pos = 0
            self._codex_turn = None
            self._codex_tokens = {}
            return

        try:
            size = os.path.getsize(path)
            if size < self._codex_pos:      # 文件被截断/轮转
                self._codex_pos = 0
            if size > self._codex_pos:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(self._codex_pos)
                    for line in f:
                        self._ingest_codex_line(line)
                    self._codex_pos = f.tell()
        except OSError:
            return
        self._report_codex_turn()

    def _ingest_codex_line(self, line):
        if '"usage"' not in line and '"token_usage_record"' not in line and '"turn_context"' not in line:
            return
        try:
            obj = json.loads(line)
        except Exception:
            return
        payload = obj.get("payload") or {}
        # 轮次 id：Codex 用 turn_id；别的 agent 用 message.id / uuid / requestId
        turn = (payload.get("turn_id") or obj.get("turn_id")
                or payload.get("uuid") or obj.get("uuid") or obj.get("requestId"))
        if not turn:
            msg = obj.get("message")
            if isinstance(msg, dict):
                turn = msg.get("id")
        if not turn:
            turn = self._codex_turn or "current"      # 认不出轮次就靠"安静 20 秒"结算
        if turn != self._codex_turn:
            if self._codex_turn:                  # 上一轮结束了
                self._report_codex_turn(force=True)
            self._codex_turn = turn
        usage = (payload.get("turn_token_usage") or payload.get("usage")
                 or extract_usage(obj))
        if usage:
            prev = self._codex_tokens.get(turn)
            if not prev or (usage.get("total_tokens") or 0) >= (prev.get("total_tokens") or 0):
                self._codex_tokens[turn] = usage      # 累计值：取最大的那份
            else:
                merged = dict(prev)
                for k, v in usage.items():
                    if isinstance(v, (int, float)):
                        merged[k] = (prev.get(k) or 0) + v
                self._codex_tokens[turn] = merged
            self._codex_last_change = time.time()

    def _report_codex_turn(self, force=False):
        turn = self._codex_turn
        if not turn or turn in self._codex_reported:
            return
        if not force and time.time() - self._codex_last_change < CODEX_QUIET_S:
            return
        self._codex_reported.add(turn)
        if len(self._codex_reported) > 50:
            self._codex_reported = set(list(self._codex_reported)[-25:])
        amount, tokens = codex_usage_cost(self._codex_tokens.get(turn))
        if tokens:
            self.say(f"上一轮 {self.agent_name} 消耗 ¥{amount:.4f}（{tokens / 1000:.1f}k token）")

    def _build_quick_menu(self):
        """右键菜单（v1.1.0 起瘦身版）：**一条子菜单都没有**，全是点一下就走。

        设置都搬进「打开设置…」那个窗口了，这里只留两类东西：
        「看一眼」（余额 / 天气 / 在放什么）和几条随手要用的开关与救命通道。
        菜单里没有子菜单，也就没有那套"悬停展开 / 点击摆渡"的老毛病。
        （完整版老菜单的入口挪到设置窗口「通用 → 排查问题」里去了。）
        """
        m = QMenu()
        m.addAction("查看余额", lambda: self.refresh_balance(silent=False))
        m.addAction("查看天气", self._get_weather)
        m.addAction("看一眼在放什么", self.check_music_now)
        m.addSeparator()
        m.addAction("聊天", self._show_chat_dialog)
        m.addAction("喂食", self._open_food_panel)
        m.addSeparator()
        m.addAction("打开设置…", defer_dialog(self.open_console))
        m.addSeparator()
        # 合体新增：移动模式（原来只在设置窗口 / 经典菜单里，右键快捷菜单找不到）
        for label, key in [("自由散步", "wander"), ("跟随鼠标", "follow"), ("原地待着", "still")]:
            a = m.addAction(label)
            a.setCheckable(True)
            a.setChecked(self.mode == key)
            a.triggered.connect(lambda _, k=key: self.set_mode(k))
        dsh = m.addAction("DSH 联动（跟着我干活）")
        dsh.setCheckable(True)
        dsh.setChecked(self.dsh_on)
        dsh.triggered.connect(self.set_dsh_on)
        m.addSeparator()
        # 「显示/隐藏」和「经典菜单」都不放菜单里了：设置窗口「通用」页里有
        # （菜单只留"看一眼"和"救命"两类）
        lk = m.addAction("锁定位置（拖不动·防误触）")
        lk.setCheckable(True)
        lk.setChecked(self.locked)
        lk.triggered.connect(self.set_locked)
        pa = m.addAction("鼠标穿透（点不到它）")
        pa.setCheckable(True)
        pa.setChecked(self.cfg["passthrough"])
        pa.triggered.connect(lambda on: self.set_passthrough(on))
        m.addAction("救急恢复（点不到它 / 它不见了）", self.force_recover)
        m.addSeparator()
        self._add_tool_actions(m)      # 免打扰 / 今日汇总
        m.addSeparator()
        m.addAction("退出", self.quit_app)
        self._iconize_menu(m)          # 每条前面的小图标（跟设置窗口同一套）
        return m

    def _add_tool_actions(self, menu, with_lengths=False):
        """免打扰 / 今日汇总 这两条（快捷菜单和经典菜单「百宝箱」共用）。

        with_lengths=True 时免打扰给几档时长（经典菜单位置宽裕），
        否则就一条"免打扰 N 分钟"（快捷菜单要保持短）。
        """
        if self.quiet_left() > 0:
            menu.addAction(f"结束免打扰（剩余 {fmt_duration(self.quiet_left())}）",
                           lambda: self.stop_quiet())
        elif with_lengths:
            for mins in (15, 30, 60, 120):
                menu.addAction(f"免打扰 {mins} 分钟",
                               lambda _=False, m=mins: self.start_quiet(m))
        else:
            mins = int(self.cfg.get("quiet_minutes") or QUIET_DEFAULT_MIN)
            menu.addAction(f"免打扰 {mins} 分钟",
                           lambda: self.start_quiet())
        menu.addAction("今日汇总", self.show_daily_summary)

    def show_daily_summary(self):
        """菜单里点「今日汇总」：把今天的小结冒出来看一眼。"""
        self.say(self.daily_summary() or "今天还没什么好总结的哦，先干点活嘛",
                 again=True, seconds=5.0)

    def _build_menu(self):
        """**完整版菜单**（老样子，一条没少）。

        v1.1.0 起右键桌宠弹的是瘦身后的 `_build_quick_menu()`，这一份退到
        「经典菜单…」那条后面当兜底 —— 等新界面用稳一版，这里连同下面那 1000 行
        子菜单补丁一起删。
        """
        # 菜单不挂在桌宠窗口下面（用无父窗口的弹出菜单）：
        # 依附桌宠时，子菜单的悬停/收起会受桌宠那个"无边框+半透明+置顶"窗口影响，
        # 靠屏幕边缘往左弹的子菜单尤其容易被误判成"鼠标离开了菜单"而收起来。
        m = QMenu()
        # ---------- 快速查看（独立区域，放最上面）----------
        # 这三个是平时最常用的："看一眼余额 / 看一眼天气 / 看一眼在放什么"，
        # 从各自的子菜单里挪到一级菜单，单独一块，不用再一层层点进去。
        m.addAction("查看余额", lambda: self.refresh_balance(silent=False))
        # （原来这里还有一行灰色的「今天另有 ¥x 余额变动，没算进今日已用」；
        #   主人 2026-09-13 看了一眼说"把这个灰色小字删了，奇奇怪怪的" → 去掉。
        #   真发生这种变动时，气泡里照旧会解释一句"余额少了…看着不像用掉的"。）
        m.addAction("查看天气", self._get_weather)
        m.addAction("看一眼在放什么", self.check_music_now)
        # 新界面：v1.1.0 起设置都搬进这个窗口（老菜单先全留着当兜底，跑稳一版再收）
        m.addAction("聊天", self._show_chat_dialog)
        m.addAction("喂食", self._open_food_panel)
        m.addAction("打开设置…", defer_dialog(self.open_console))
        # 快速双击弹哪个窗口：也放在这块最常用的区域里（一级菜单点一下就能换）
        dc_menu = m.addMenu(self._double_click_menu_title())
        dc_picked = self._double_click_choice()
        dc_has_key = bool(self._current_source()[1])
        for dc_key, dc_label in DOUBLE_CLICK_CHOICES:
            if dc_key == "balance" and not dc_has_key:
                # 没配 Key：这一项不给选（双击也不会弹余额窗口）
                dc_label += "（要先配 Key）"
            a = dc_menu.addAction(dc_label)
            a.setCheckable(True)
            a.setChecked(dc_picked == dc_key and (dc_key != "balance" or dc_has_key))
            a.setEnabled(dc_key != "balance" or dc_has_key)
            a.triggered.connect(lambda _, k=dc_key: self.set_double_click(k))
        dc_menu.addSeparator()
        n_dc = len(self.cfg.get("custom_lines", {}).get("DOUBLE_CLICK_LINES") or [])
        dc_menu.addAction("改写这几句…" + (f"（已改 {n_dc} 句）" if n_dc else ""),
                          defer_dialog(lambda: self.edit_lines_dialog("DOUBLE_CLICK_LINES")))
        m.addSeparator()

        mode_menu = m.addMenu("模式")
        for label, key in [("自由散步", "wander"), ("跟随鼠标", "follow"), ("原地待着", "still")]:
            a = mode_menu.addAction(label)
            a.setCheckable(True)
            a.setChecked(self.mode == key)
            a.triggered.connect(lambda _, k=key: self.set_mode(k))
        mode_menu.addSeparator()
        # 「原地待着」默认固定正面；想让桌宠实时盯着鼠标（只转头、不挪窝）就打开这条
        a = mode_menu.addAction("原地待着时也跟着鼠标转")
        a.setCheckable(True)
        a.setChecked(self.still_face_cursor)
        a.triggered.connect(self.set_still_face_cursor)
        size_menu = m.addMenu("大小")
        for label, mult in SIZE_LEVELS.items():
            a = size_menu.addAction(label)
            a.setCheckable(True)
            a.setChecked(abs(self.cur_h - 340 * mult) < 2)
            a.triggered.connect(lambda _, v=mult: self.set_size(v))
        size_menu.addSeparator()
        # 无级调节：滑块弹窗（菜单里内嵌滑块在这台机器上拖不动，见 _slider_dialog）
        size_menu.addAction(
            f"精确调节…（现在 {size_percent(self.cfg.get('size', SIZE_DEFAULT))}%）",
            defer_dialog(self.size_dialog))
        skin_menu = m.addMenu("形象")
        # v1.0.16：二级菜单就四条 —— 切三维 / 切挂件 / 形象库 / 全部恢复默认。
        # （原来那两套三级菜单去掉了：上传、换图、单套恢复都收进形象库窗口里，留着是重复）
        a = skin_menu.addAction(f"{SKIN_PET}（三视图）")
        a.setCheckable(True)
        a.setChecked(self.skin == SKIN_PET)
        a.triggered.connect(lambda _, n=SKIN_PET: self.set_skin(n))
        a = skin_menu.addAction(f"{SKIN_WIDGET}（单张）")
        a.setCheckable(True)
        a.setChecked(self.skin == SKIN_WIDGET)
        a.triggered.connect(lambda _, n=SKIN_WIDGET: self.set_skin(n))
        skin_menu.addSeparator()
        # 形象库：三维 / 挂件两本分开，上传·换图·改名·删掉·挑回来用都在这个窗口里
        n_pet = len(self.skin_library("pet"))
        n_wid = len(self.skin_library("widget"))
        skin_menu.addAction(
            (f"我的形象库…（三维 {n_pet} 个 · 挂件 {n_wid} 个）" if (n_pet or n_wid)
             else "我的形象库…（还没上传过）"),
            defer_dialog(self.skin_library_dialog))
        skin_menu.addAction("全部恢复默认形象", lambda: self.clear_custom_skin(None))
        layer_menu = m.addMenu("层级")
        for key, label in self.LAYER_LABELS.items():
            a = layer_menu.addAction(label)
            a.setCheckable(True)
            a.setChecked(self.layer == key)
            a.triggered.connect(lambda _, k=key: self.set_layer(k))
        # 透明度：改成"点开小窗口拖滑块"——菜单里内嵌滑块在这台机器上拖不动（弹出子菜单收不到鼠标）
        m.addAction(f"透明度…（现在 {int(self.opacity * 100)}%）",
                    defer_dialog(self.opacity_dialog))
        weather_menu = m.addMenu("天气")
        weather_menu.addAction("设置默认城市（手动输入）", self.set_city_dialog)
        # （「查看天气」挪到一级菜单最上面那块的"快速查看"里了）
        weather_menu.addAction("自动定位城市（按 IP，挂梯子会不准）", self.auto_locate_city)
        weather_menu.addAction("添加城市（联网搜索）", self.search_city_dialog)
        weather_menu.addSeparator()
        # 城市列表：加过的城市都在这儿，点一下就切过去（√ 是当前用的）
        # 顺序固定成"当前城市排第一"（选谁谁就上第一，见 _apply_city / cities_ordered）
        cur_city = self.cfg.get("city", "北京")
        city_list = self.cities_ordered()
        for city in city_list:
            a = weather_menu.addAction(city)
            a.setCheckable(True)
            a.setChecked(city == cur_city)
            a.triggered.connect(lambda _, n=city: self._apply_city(n))
        if len(city_list) > 1:
            weather_menu.addAction("从列表里删掉城市…", self.remove_city_dialog)
        bal_menu = m.addMenu("余额")
        # （「查看余额」挪到一级菜单最上面那块"快速查看"里了）
        bal_menu.addAction("设置 Key", self._set_key_dialog)
        src_menu = bal_menu.addMenu("余额来源")
        for name in ["DeepSeek"] + [k.get("name", "?") for k in (self.cfg.get("other_keys") or [])]:
            a = src_menu.addAction(name)
            a.setCheckable(True)
            a.setChecked((self.cfg.get("balance_source") or "DeepSeek") == name)
            a.triggered.connect(lambda _, n=name: self.set_balance_source(n))
        bal_menu.addAction("添加其他 API Key…", self.add_other_key_dialog)
        if self.cfg.get("other_keys"):
            bal_menu.addAction("删除其他 API Key…", self.remove_other_key_dialog)
        # 账本自己算不出当天真实用量时（赠送额度到期、桌宠关着漏采）用来对齐平台那个数
        bal_menu.addAction("校准今日已用…（按平台用量页）",
                           defer_dialog(self.calibrate_usage_dialog))
        bal_menu.addSeparator()
        baa = bal_menu.addAction("余额常显")
        baa.setCheckable(True)
        baa.setChecked(self.balance_always)
        baa.triggered.connect(self.set_balance_always)

        # 吸附：独立菜单，不再塞在「余额」下面
        snap_menu = m.addMenu("吸附")
        sna = snap_menu.addAction("拖拽吸附四边")
        sna.setCheckable(True)
        sna.setChecked(self.snap_on)
        sna.triggered.connect(self.set_snap)
        fka = snap_menu.addAction("左吸附时翻面")
        fka.setCheckable(True)
        fka.setChecked(self.flip_on_left)
        fka.triggered.connect(self.set_flip_on_left)

        # 文案：独立菜单（峰谷显示 + 三档文案）
        text_menu = m.addMenu("文案")
        pka = text_menu.addAction("显示峰谷时段")
        pka.setCheckable(True)
        pka.setChecked(self.show_peak)
        pka.triggered.connect(self.set_show_peak)
        peak_menu = text_menu.addMenu("峰谷文案")
        for style in PEAK_TEXT_STYLES:
            a = peak_menu.addAction(style)
            a.setCheckable(True)
            a.setChecked(self.peak_style == style)
            a.triggered.connect(lambda _, s=style: self.set_peak_style(s))
        freq_menu = text_menu.addMenu("语录频率" + f"（现在：{self.line_freq}）")
        for name, preset in LINE_FREQ_LEVELS.items():
            a = freq_menu.addAction(f"{name}（{preset['hint']}）")
            a.setCheckable(True)
            a.setChecked(self.line_freq == name)
            a.triggered.connect(lambda _, n=name: self.set_line_freq(n))
        text_menu.addSeparator()
        # 台词内容：换了形象之后默认台词可能不搭，这里让用户自己写 / 改写内置
        n_custom = len(self.cfg.get("custom_lines") or {})
        text_menu.addAction(
            "台词内容…（自己写 / 改写内置）" + (f"（已改 {n_custom} 类）" if n_custom else ""),
            defer_dialog(self.edit_lines_dialog))

        # 每轮消耗：自己的子菜单，Agent 名称/日志目录可配（不是每个人都用 Codex）
        turn_menu = bal_menu.addMenu("每轮消耗统计")
        tca = turn_menu.addAction(f"每轮对话后显示消耗（当前：{self.agent_name}）")
        tca.setCheckable(True)
        tca.setChecked(self.turn_cost_on)
        tca.triggered.connect(self.set_turn_cost)
        turn_menu.addSeparator()
        turn_menu.addAction("设置 Agent 名称…", self.set_agent_name_dialog)
        turn_menu.addAction("设置会话日志目录…", self.set_agent_dir_dialog)
        turn_menu.addSeparator()
        turn_menu.addAction(f"日志目录：{os.path.basename(self.agent_dir.rstrip(os.sep)) or self.agent_dir}").setEnabled(False)

        # 进程联动：独立菜单，支持扫描本机应用并自定义触发文字
        proc_menu = m.addMenu("进程联动")
        pra = proc_menu.addAction("应用启动提醒")
        pra.setCheckable(True)
        pra.setChecked(self.process_alerts)
        pra.triggered.connect(self.set_process_alerts)
        proc_menu.addSeparator()
        proc_menu.addAction("扫描本机应用并添加…", self.scan_apps_dialog)
        if self.cfg.get("custom_process_lines") or self.cfg.get("default_line_overrides"):
            proc_menu.addAction("清理自定义文字…", self.remove_custom_app_dialog)
        proc_menu.addSeparator()
        proc_menu.addAction("使用时长提醒…",
                            defer_dialog(self.app_time_dialog))
        proc_menu.addAction("定时提醒…",
                            defer_dialog(self.timed_lines_dialog))
        proc_menu.addAction("全局快捷键…",
                            defer_dialog(self.hotkeys_dialog))

        # 音乐联动：QQ音乐 / 网易云 放歌时看歌词
        music_menu = m.addMenu("音乐联动")
        mla = music_menu.addAction("放歌时看着（放 QQ音乐 / 网易云 时联动）")
        mla.setCheckable(True)
        mla.setChecked(self.music_on)
        mla.triggered.connect(self.set_music_link)
        mlb = music_menu.addAction("显示歌词内容（关掉只报歌名）")
        mlb.setCheckable(True)
        mlb.setChecked(self.music_lyrics)
        mlb.triggered.connect(self.set_music_lyrics)
        off_menu = music_menu.addMenu("歌词对时" + self._lyric_offset_label())
        for label, off in LYRIC_OFFSET_LEVELS:
            a = off_menu.addAction(label)
            a.setCheckable(True)
            a.setChecked(abs(self.lyric_offset - off) < 1e-6)
            a.triggered.connect(lambda _, o=off: self.set_lyric_offset(o))
        # 网易云不报播放进度，中途才开始看（或拖过进度条）就只能手动对一次；按歌记住
        nud = music_menu.addMenu("这首歌对不上？微调" + self._lyric_nudge_label())
        nud.addAction("歌词太慢，往前赶 0.5 秒", lambda: self.nudge_lyric(0.5))
        nud.addAction("歌词太慢，往前赶 2 秒", lambda: self.nudge_lyric(2.0))
        nud.addAction("歌词太快，往后压 0.5 秒", lambda: self.nudge_lyric(-0.5))
        nud.addAction("歌词太快，往后压 2 秒", lambda: self.nudge_lyric(-2.0))
        nud.addSeparator()
        nud.addAction("按播放器显示的时间对齐…（最准）",
                      defer_dialog(self.align_lyric_dialog))
        nud.addAction("这首歌的微调清零", lambda: self.nudge_lyric(0.0, True))
        music_menu.addSeparator()
        music_menu.addAction(self._music_menu_label()).setEnabled(False)
        # （「看一眼在放什么」挪到一级菜单最上面那块"快速查看"里了）
        music_menu.addSeparator()
        music_menu.addAction("单击=回嘴（放歌时报歌名）· 快速双击="
                             + self._double_click_effect_label()).setEnabled(False)

        # 流畅度：动画优先 / 省资源，自己选
        perf_menu = m.addMenu("流畅度")
        for mode, label in ((True, "性能模式 · 动画优先（不掉帧）"),
                            (False, "休闲模式 · 省资源（可掉一点帧）")):
            a = perf_menu.addAction(label)
            a.setCheckable(True)
            a.setChecked(self.perf_mode == mode)
            a.triggered.connect(lambda _, k=mode: self.set_perf_mode(k))
        perf_menu.addSeparator()
        perf_menu.addAction("开设置菜单时：性能=动画照跑，休闲=降到约 5 帧").setEnabled(False)

        # 百宝箱：以后别的小工具都往这儿放（现在只有内存回收）
        box_menu = m.addMenu("百宝箱")
        box_menu.addAction("回收内存", self.mem_trim_now)
        mfg = box_menu.addAction("回收时不动前台程序（防卡顿）")
        mfg.setCheckable(True)
        mfg.setChecked(bool(self.cfg.get("mem_skip_foreground", True)))
        mfg.triggered.connect(self.set_mem_skip_foreground)
        box_menu.addSeparator()
        if self._mem_last:
            box_menu.addAction(
                f"上次：{self._mem_last[0]} 个程序腾出 {human_mb(self._mem_last[1])}"
            ).setEnabled(False)
        box_menu.addAction("系统 / 提权进程不回收（需要管理员权限）").setEnabled(False)

        # 百宝箱里再加两个小工具：免打扰 / 今日汇总
        box_menu.addSeparator()
        self._add_tool_actions(box_menu, with_lengths=True)

        snd_menu = m.addMenu("音效")
        so = snd_menu.addAction("按键音效")
        so.setCheckable(True)
        so.setChecked(self.sound_on)
        so.triggered.connect(self.set_sound)
        pick_menu = snd_menu.addMenu("音效选择")
        for idx, name in enumerate(self._sound_names()):
            if idx == len(SOUND_SETS):
                pick_menu.addSeparator()        # 下面开始是主人自己加的
            a = pick_menu.addAction(name)
            a.setCheckable(True)
            a.setChecked(self.sound_set == name)
            a.triggered.connect(lambda _, n=name: self.set_sound_set(n))
        snd_menu.addAction("添加我的音效…（自己挑 wav）",
                           defer_dialog(self.add_custom_sound_dialog))
        if getattr(self, "_custom_sounds", None):
            snd_menu.addAction("删掉我加的音效…",
                               defer_dialog(self.remove_custom_sound_dialog))
        # 音量：同样改成小窗口里拖滑块（菜单内嵌滑块在这台机器上拖不动）
        snd_menu.addAction(f"音量…（现在 {int(self.volume * 100)}%）",
                           defer_dialog(self.volume_dialog))
        snd_menu.addSeparator()
        snd_menu.addAction("试听音效", self.preview_sounds)
        m.addSeparator()
        m.addAction("显示/隐藏", self.toggle_visible)
        m.addAction("回到屏幕内", self.snap_into_screen)
        # 锁定位置：开了就拖不动（防误触），点击 / 双击 / 菜单照旧
        lk = m.addAction("锁定位置（拖不动·防误触）")
        lk.setCheckable(True)
        lk.setChecked(self.locked)
        lk.triggered.connect(self.set_locked)
        pa = m.addAction("鼠标穿透（点不到它）")
        pa.setCheckable(True)
        pa.setChecked(self.cfg["passthrough"])
        pa.triggered.connect(lambda on: self.set_passthrough(on))
        m.addAction("救急恢复（点不到它 / 它不见了）", self.force_recover)
        md = m.addAction("记菜单日志（菜单出问题时打开）")
        md.setCheckable(True)
        md.setChecked(bool(self.cfg.get("menu_debug", False)))
        md.triggered.connect(lambda on: self.set_menu_debug(on))
        aa = m.addAction("开机自启")
        aa.setCheckable(True)
        aa.setChecked(self.cfg["autostart"])
        aa.triggered.connect(lambda on: self.set_autostart(on))
        m.addSeparator()
        m.addAction("退出", self.quit_app)
        self._iconize_menu(m)          # 经典版也配同一套图标（两版菜单才叫统一）
        return m

    def _notify_console(self):
        """叫设置窗口把当前那一页重读一遍（城市这类"后台加进来"的东西要立刻反映）。

        窗口没开就是什么都不做 —— 下次打开它会自己现读（见 ConsoleWindow._refresh_page）。
        """
        win = getattr(self, "_console", None)
        if win is None:
            return
        try:
            win.refresh_pages()
        except Exception as exc:
            print("通知设置窗口刷新失败:", exc)

    def open_console(self):
        """打开设置窗口（菜单最上面那条「打开设置…」）。

        窗口是懒加载的：建一次就留着，再点只是抬到前面。
        """
        if ui_console is None:
            QMessageBox.warning(self, "设置", "界面模块没加载起来，看下启动时的报错。")
            return
        win = getattr(self, "_console", None)
        if win is not None:
            try:
                # 最小化着的话先播"还原动画"，别"啪"一下蹦出来
                win.restore_or_show()
                return
            except RuntimeError:          # 窗口已经被 Qt 收掉了，重建一个
                self._console = None
        ctx = {
            "ASSET_DIR": ASSET_DIR,
            "SPRITE_DIR": SPRITE_DIR,
            "BUNDLE_DIR": BUNDLE_DIR,
            "SIZE_LEVELS": SIZE_LEVELS,
            "size_percent": size_percent,
            "size_from_percent": size_from_percent,
            "SIZE_MIN": SIZE_MIN,
            "SIZE_MAX": SIZE_MAX,
            "LYRIC_OFFSET_LEVELS": LYRIC_OFFSET_LEVELS,
            "DOUBLE_CLICK_CHOICES": DOUBLE_CLICK_CHOICES,
            "PEAK_TEXT_STYLES": PEAK_TEXT_STYLES,
            "BUBBLE_STYLES": BUBBLE_STYLES,
            "LINE_FREQ_LEVELS": LINE_FREQ_LEVELS,
            "LINE_SECTIONS": LINE_SECTIONS,
            "SKIN_PET": SKIN_PET,
            "SKIN_WIDGET": SKIN_WIDGET,
            "LAYER_LABELS": dict(self.LAYER_LABELS),
            "currency_symbol": currency_symbol,
            "human_mb": human_mb,
            # 合体新增：设置窗口「DSH 联动」页要用
            "DSH_ACTS": DSH_ACTS,
            "DSH_ACT_INFO": DSH_ACT_INFO,
            "DSH_ACT_ZOOM": DSH_ACT_ZOOM,
        }
        self._console = ui_console.ConsoleWindow(self, ctx)
        # 设置窗口**不跟着桌宠的层级**：它就是个普通窗口，谁点谁在上面，
        # 不会被压在最上面碍事（打开时抬一下，够用了）。
        self._console.show()
        self._console.raise_()
        self._console.activateWindow()

    def set_balance_source(self, name):
        """切换余额来源（DeepSeek / 用户自己加的其他服务）。"""
        self.cfg["balance_source"] = name
        self.balance = None           # 换来源先清掉旧数据，免得数错
        self.save_config()
        self.refresh_balance(silent=False)

    def add_other_key_dialog(self):
        """添加别的服务的 API Key（例如 OpenRouter）。"""
        with self._ui_guard():
            name, ok = QInputDialog.getText(
                self, "添加其他 API Key",
                "服务名称（例如 OpenRouter / OpenAI / Kimi）:",
                QLineEdit.EchoMode.Normal, "", Qt.WindowType.WindowStaysOnTopHint)
        if not ok or not name.strip():
            return
        name = name.strip()
        with self._ui_guard():
            key, ok2 = QInputDialog.getText(
                self, f"{name} 的 API Key",
                f"粘贴 {name} 的 API Key（只存在本地 config.json）:",
                QLineEdit.EchoMode.Password, "", Qt.WindowType.WindowStaysOnTopHint)
        if not ok2 or not key.strip():
            return
        keys = [k for k in (self.cfg.get("other_keys") or []) if k.get("name") != name]
        keys.append({"name": name, "key": key.strip()})
        self.cfg["other_keys"] = keys
        self.cfg["balance_source"] = name
        self.save_config()
        self.say(f"记下 {name} 的 Key 了，我去看看")
        self.refresh_balance(silent=False)

    def remove_other_key_dialog(self):
        keys = list(self.cfg.get("other_keys") or [])
        if not keys:
            self.say("还没有添加别的 Key 呢")
            return
        names = [k.get("name", "?") for k in keys]
        with self._ui_guard():
            pick, ok = QInputDialog.getItem(self, "删除其他 API Key", "删掉哪个？",
                                            names, 0, False,
                                            Qt.WindowType.WindowStaysOnTopHint)
        if not ok or not pick:
            return
        self.cfg["other_keys"] = [k for k in keys if k.get("name") != pick]
        if (self.cfg.get("balance_source") or "DeepSeek") == pick:
            self.cfg["balance_source"] = "DeepSeek"
            self.balance = None
        self.save_config()
        self.say(f"已删除 {pick} 的 Key")
        self.refresh_balance(silent=True)

    def _set_key_dialog(self):
        with self._ui_guard():
            key, ok = QInputDialog.getText(
                self,
                "设置 DeepSeek Key",
                "输入你的 API Key（从 platform.deepseek.com 获取）:",
                QLineEdit.EchoMode.Normal,
                self.cfg.get("ds_api_key", ""),
                Qt.WindowType.WindowStaysOnTopHint
            )
        if ok and key.strip():
            self.cfg["ds_api_key"] = key.strip()
            self.say("Key 设置成功！我看看还剩多少钱")
            self.refresh_balance(silent=False)
        elif ok and not key.strip():
            self.say("Key 不能为空")

    def calibrate_usage_dialog(self):
        """按 DeepSeek 开放平台用量页的数字校准「今日已用」。

        余额差值记账遇到赠送额度到期 / 桌宠关着漏采就算不出真实用量，
        这里让主人把平台那个数填进来对齐（账本会留一笔 calibrateLog）。
        """
        cur = float((self.balance or {}).get("today") or 0.0)
        with self._ui_guard():
            text, ok = QInputDialog.getText(
                self,
                "校准今日已用",
                "输入 DeepSeek 开放平台 →「用量信息」页今天显示的消费金额（元）：\n"
                f"（桌宠现在记的是 ¥{cur:.2f}；平台那个数只在你账号里看得到，我拿不到）",
                QLineEdit.EchoMode.Normal,
                f"{cur:.2f}",
                Qt.WindowType.WindowStaysOnTopHint
            )
        if not ok:
            return
        raw = (text or "").strip().replace("¥", "").replace("￥", "").replace(",", "")
        try:
            amount = float(raw)
        except ValueError:
            self.say("这个数我没看懂，填个数字就行（例如 14.83）")
            return
        if amount < 0:
            self.say("金额不能是负的呀")
            return
        res = calibrate_balance_usage(USAGE_PATH, amount, "菜单里按平台用量页手动校准")
        if self.balance is not None:
            self.balance["today"] = res["today"]
        self.say(f"今日已用校准成 ¥{res['today']:.2f} 啦（原来记的是 ¥{res['was']:.2f}）",
                 seconds=4.5, again=True)
        self.show_balance_bubble(5.0)

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Context:
            self._tray_menu = self._make_menu()      # 留引用，别被回收
            self.tray.setContextMenu(self._tray_menu)
        elif reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_visible()
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            # 救急通道：万一穿透了又找不到菜单，双击托盘图标直接解除
            was_passthrough = self.cfg.get("passthrough", False)
            if was_passthrough:
                self.set_passthrough(False)
            self.force_recover()          # 顺手把可能残留的"让位"状态也清掉
            self.say("穿透解除了，我回来啦" if was_passthrough else "我在这儿呢")

    # ---------- 百宝箱：内存回收 ----------
    def mem_trim_now(self):
        """「百宝箱 → 回收内存」：后台把工作集收一遍，回来报个数（不卡住桌宠）。"""
        if self._mem_trimming:
            self.say("还在收拾呢，等我一下下嘛")
            return
        self._mem_trimming = True
        skip_fg = bool(self.cfg.get("mem_skip_foreground", True))
        self.say("我先给内存收拾收拾哦…")

        def worker():
            skip_exes = []
            if skip_fg:
                fg = foreground_process_name()     # 正在用的程序不动，收了它得重新读一遍
                if fg:
                    skip_exes.append(fg)
            try:
                got = trim_working_sets(skip_pids={os.getpid()}, skip_exes=skip_exes)
            except Exception as exc:               # 兜底：别让后台线程把桌宠带崩
                got = {"error": str(exc)}
            self._mem_queue.append(got)

        threading.Thread(target=worker, daemon=True).start()

    def _mem_trim_done(self, got):
        """回收结果回到主线程：冒个泡报数（菜单里那行"上次…"也在这儿记）。"""
        self._mem_trimming = False
        if not got or got.get("error"):
            self.say("没收拾成，等会儿再试试")
            return
        n = int(got.get("trimmed") or 0)
        freed = int(got.get("freed") or 0)
        extra = int(got.get("avail_after") or 0) - int(got.get("avail_before") or 0)
        self._mem_last = (n, freed)
        if not n:
            self.say("这会儿干干净净的，没什么好收拾")
            return
        line = f"收拾好啦：{n} 个程序腾出 {human_mb(freed)}"
        if extra > 16 * 1024 * 1024:
            line += f"，可用内存多出 {human_mb(extra)}"
        self.say(line, seconds=4.0, again=True)

    def set_mem_skip_foreground(self, on):
        """回收时要不要连前台程序一起收（默认不收：收了前台可能会顿一下）。"""
        self.cfg["mem_skip_foreground"] = bool(on)
        self.save_config()
        self.say("回收时不动你正在用的程序" if on else "回收时前台程序也一起收，可能会顿一下")

    def _make_menu(self, classic=None):
        """建右键菜单：打开期间桌宠让位（临时取消置顶）并站住不动。

        classic=None（默认）看配置：「通用 → 用经典版菜单」打开时用完整版老菜单，
        否则用瘦身版快捷菜单；显式传 True / False 可以强制某一份（用例里用得多）。
        """
        if classic is None:
            classic = bool(self.cfg.get("classic_menu", False))
        m = self._build_menu() if classic else self._build_quick_menu()
        self._menu_keepalive = m          # 菜单是纯 Python 对象，留个引用防回收
        self._menu_pool = ([m] + self._menu_pool)[:4]     # 留几份，用来看"还有菜单开着吗"
        self._sub_rect = {}               # 新的一份菜单：上次那些"子菜单位置/补弹次数"作废
        self._resub = {}
        self._install_place_fix(m)        # 让每层子菜单"一显示就摆正"（同一帧，看不见挪动）
        # 不给菜单强加置顶标志——改成让桌宠自己在菜单期间退到普通层，
        # 这样菜单天然在最上面，而且是 Qt 标准的弹出菜单，二级菜单悬停最稳。

        def on_show():
            self.ui_open = True
            self._demote_topmost(True)

        def on_hide():
            # 别急着解除：可能还有别的菜单开着（比如托盘菜单），交给 _sync_overlay_state 对账
            for sub in list(self._hover_subs):      # 悬停兜底弹出来的子菜单要一起收掉
                try:
                    sub.close()
                except Exception:
                    pass
            self._hover_subs.clear()
            self._sync_overlay_state()
            self._hover_key = None

        m.aboutToShow.connect(on_show)
        m.aboutToHide.connect(on_hide)
        self._iconize_menu(m)
        return m

    @staticmethod
    def _menu_icon_lookup(table, text):
        """在一张 (前缀, 图标) 表里挑最合适的一条（取最长的前缀；没有就空串）。"""
        best, name = -1, ""
        for prefix, icon_name in table:
            if text.startswith(prefix) and len(prefix) > best:
                best, name = len(prefix), icon_name
        return name

    def _menu_icon_name(self, text):
        return self._menu_icon_lookup(MENU_ICONS, text)

    def _iconize_menu(self, menu, color=None, inherit=""):
        """给一棵菜单（连各级子菜单）按 MENU_ICONS 配上图标。

        颜色取**菜单自己的文字色**：右键菜单是系统画的，亮 / 暗跟着系统走，
        写死一个颜色总有一边看不清。界面模块没起来就跳过（菜单照常能用）。

        inherit 是"父项那个图标"：子项没单独写在 MENU_ICONS 里就跟着父项
        （所以"大小"下面的迷你 / 小 / 中…也会带上同一个图案）。
        """
        if ui_console is None:
            return
        if color is None:
            try:
                from PySide6.QtGui import QPalette
                color = menu.palette().color(QPalette.ColorRole.WindowText).name()
            except Exception:
                color = "#5a5a64"
        for act in menu.actions():
            if act.isSeparator():
                continue
            sub = act.menu()
            name = self._menu_icon_name(act.text()) or inherit
            if not name:
                if sub is not None:
                    self._iconize_menu(sub, color, "")
                continue
            try:
                act.setIcon(ui_console.icon(name, color, ui_console.ICON_SM))
            except Exception:
                pass
            if sub is not None:
                child = self._menu_icon_lookup(MENU_ICON_CHILD, act.text()) or name
                self._iconize_menu(sub, color, child)

    def _install_place_fix(self, menu):
        """给这棵菜单树里每一层都装上"一显示就摆正"的过滤器（重复调用没关系）。"""
        if getattr(self, "_place_fix", None) is None:
            self._place_fix = SubmenuPlaceFix(self)
        for m in self._all_menus(menu):
            if getattr(m, "_dfy_placefix", False):
                continue
            m._dfy_placefix = True
            try:
                m.installEventFilter(self._place_fix)
            except RuntimeError:
                continue

    def _deepest_menu_at_cursor(self):
        """光标所在的最里面那层菜单（按窗口矩形找，不依赖"父项"链）。"""
        root = getattr(self, "_menu_keepalive", None)
        if root is None:
            return None
        pos = QCursor.pos()
        best, best_depth = None, -1
        for menu in self._all_menus(root):
            try:
                if not menu.isVisible():
                    continue
                top_left = menu.mapToGlobal(QPoint(0, 0))
            except RuntimeError:
                continue
            if (top_left.x() <= pos.x() <= top_left.x() + menu.width()
                    and top_left.y() <= pos.y() <= top_left.y() + menu.height()):
                depth = getattr(menu, "_dfy_depth", 0)
                if depth >= best_depth:
                    best, best_depth = menu, depth
        return best

    def _all_menus(self, menu, out=None):
        """把一棵菜单树里的所有菜单（含子菜单）列出来。"""
        out = out if out is not None else []
        out.append(menu)
        try:
            actions = menu.actions()
        except RuntimeError:
            return out
        for act in actions:
            child = act.menu()
            if child is not None:
                self._all_menus(child, out)
        return out

    def _send_move_to(self, menu):
        """给某一层菜单补一份鼠标移动事件。"""
        pos = QCursor.pos()
        self._send_move_point(menu, pos)

    def _menu_by_hwnd(self, hwnd):
        """按窗口句柄找到这是哪一层菜单（找不到返回 None）。"""
        root = getattr(self, "_menu_keepalive", None)
        if root is None:
            return None
        for m in self._all_menus(root):
            try:
                if int(m.winId()) == hwnd:
                    return m
            except RuntimeError:
                continue
        return None

    def _highlight_menu_item(self, menu, pos=None):
        """把"光标下这一条"设成菜单的选中项（也就是高亮那一行）。

        这台机器上 Qt 的弹出菜单收不到真正的鼠标移动，Qt 自己就不会更新高亮 ——
        表现就是"快速上下移动时选择卡住"。这里由我们按光标位置点一下。
        """
        try:
            if not menu.isVisible():
                return
        except RuntimeError:
            return
        act = self._menu_action_at(menu, pos or QCursor.pos(), self.MENU_TRIGGER_MARGIN_X)
        if act is None:
            return
        try:
            if menu.activeAction() is not act:
                menu.setActiveAction(act)
        except RuntimeError:
            pass

    def _send_move_point(self, menu, pos):
        """把某个坐标的鼠标移动塞给指定菜单。"""
        """往某一层菜单里塞一个指定位置（全局坐标）的鼠标移动。"""
        pos = QPoint(pos)
        local = menu.mapFromGlobal(pos)
        if not menu.rect().contains(local):
            return
        self._forwarding_move = True
        try:
            QApplication.sendEvent(menu, QMouseEvent(
                QEvent.Type.MouseMove, QPointF(local), QPointF(pos),
                Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier))
        except Exception:
            pass
        finally:
            self._forwarding_move = False

    def _show_submenu_window(self, sub, where):
        """悬停不再弹子菜单（改用点击后的选择框，见 _pick_submenu）。"""
        return

    def _show_flyout(self, sub, where):
        if self._flyout is None:
            self._build_flyout()
        if self._flyout_action is not sub:
            self._fill_flyout(sub)
            self._flyout_action = sub
        try:
            self._flyout.move(where)
            self._flyout.show()
            self._flyout.raise_()
        except RuntimeError:
            self._flyout = None
            return
        self._flyout_leave_at = 0.0

    def _build_flyout(self):
        w = QWidget(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                    | Qt.WindowType.WindowStaysOnTopHint)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(1)
        w.setStyleSheet(
            "QWidget#flyout { background: #ffffff; border: 1px solid #c8c8d0; border-radius: 8px; }"
            "QToolButton { border: none; text-align: left; padding: 5px 12px; background: transparent; }"
            "QToolButton:hover { background: #eaeaf2; border-radius: 5px; }"
            "QLabel { color: #8a8a99; padding: 3px 10px; }")
        w.setObjectName("flyout")
        self._flyout = w
        self._flyout_layout = lay

    def _fill_flyout(self, sub):
        lay = self._flyout_layout
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for act in sub.actions():
            if act.isSeparator():
                line = QFrame()
                line.setFrameShape(QFrame.Shape.HLine)
                line.setStyleSheet("color: #dcdce4;")
                lay.addWidget(line)
                continue
            nested = self._sub_of.get(act)
            if nested is not None:
                group = act.text().rstrip().rstrip("▸").strip()
                lay.addWidget(QLabel("— " + group + " —"))
                for sub_act in nested.actions():
                    if sub_act.isSeparator() or self._sub_of.get(sub_act) is not None:
                        continue
                    self._add_flyout_button(lay, sub_act, prefix=group)
                continue
            self._add_flyout_button(lay, act)
        self._flyout.adjustSize()

    def _add_flyout_button(self, lay, act, prefix=""):
        btn = QToolButton()
        txt = (prefix + "：" if prefix else "") + act.text()
        if act.isCheckable() and act.isChecked():
            txt = "✓ " + txt
        btn.setText(txt)
        btn.setEnabled(act.isEnabled())
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)

        def go():
            self._hide_flyout()
            try:
                act.trigger()
            except Exception:
                pass
            root = getattr(self, "_menu_keepalive", None)
            if root is not None:
                try:
                    root.close()
                except Exception:
                    pass

        btn.clicked.connect(go)
        lay.addWidget(btn)

    def _hide_flyout(self):
        if self._flyout is not None:
            try:
                self._flyout.hide()
            except RuntimeError:
                self._flyout = None
        self._flyout_action = None

    def submenu_under_cursor(self):
        """光标所在的子菜单（不含最上层那个菜单）；没有就返回 None。"""
        root = getattr(self, "_menu_keepalive", None)
        if root is None:
            return None
        pos = QCursor.pos()
        best, best_depth = None, 0
        for menu in self._all_menus(root):
            if menu is root:
                continue
            try:
                if not menu.isVisible():
                    continue
                top_left = menu.mapToGlobal(QPoint(0, 0))
            except RuntimeError:
                continue
            if (top_left.x() <= pos.x() <= top_left.x() + menu.width()
                    and top_left.y() <= pos.y() <= top_left.y() + menu.height()):
                depth = getattr(menu, "_dfy_depth", 1)
                if depth >= best_depth:
                    best, best_depth = menu, depth
        return best

    def activate_menu_item(self, menu):
        """点击落在子菜单上时，由我们自己执行那一项（Windows 不会把点击送给子菜单）。"""
        pos = QCursor.pos()
        act = menu.actionAt(menu.mapFromGlobal(pos))
        menu_debug(f"[点击] 层级{getattr(menu, '_dfy_depth', '?')} 光标={pos} "
                   f"光标下={'（没有项）' if act is None else act.text()}")
        if act is None or not act.isEnabled() or act.isSeparator():
            return
        menu_debug(f"[点击] 触发 {act.text()}")
        try:
            if act.menu() is not None:              # 还有下一层 → 展开它
                sub = act.menu()
                sub.popup(self._submenu_pos(menu, act, sub))     # 同样按"和本级重叠"放
                return
            # 先关菜单、下一拍再执行这一项：如果这一项要弹窗口（音量/透明度/加音效…），
            # 直接在原生消息回调里 exec() 会被菜单的关闭动作吃掉（窗口一闪就没）。
            root0 = getattr(self, "_menu_keepalive", None)
            if root0 is not None:
                try:
                    root0.close()
                except Exception:
                    pass
            QTimer.singleShot(0, act.trigger)
            return
        except Exception:
            return
        root = getattr(self, "_menu_keepalive", None)
        if root is not None:
            try:
                root.close()                        # 选完了，把菜单收起来
            except Exception:
                pass

    def _send_click_to(self, menu, ev):
        """把上层菜单收到的点击转给子菜单（Windows 会把点击送给持有捕获的上层菜单）。"""
        pos = QCursor.pos()
        local = menu.mapFromGlobal(pos)
        if not menu.rect().contains(local):
            return
        self._forwarding_move = True
        try:
            QApplication.sendEvent(menu, QMouseEvent(
                ev.type(), QPointF(local), QPointF(pos),
                ev.button(), ev.buttons(), ev.modifiers()))
        except Exception:
            pass
        finally:
            self._forwarding_move = False

    def _keep_submenu_alive(self, obj):
        """光标正从这一项往子菜单平移（短暂在菜单外面）时，给子菜单喂一个贴边的位置。

        Qt 靠"鼠标是不是还在子菜单里"来决定收不收；这台机器上子菜单收不到鼠标消息，
        Qt 就每 300ms 收一次 —— 用户根本来不及移过去点。这里替它把"鼠标还在"报上去。
        """
        pos = QCursor.pos()
        for act in obj.actions():
            sub = act.menu()
            if sub is None:
                continue
            try:
                if not sub.isVisible():
                    continue
                top_left = sub.mapToGlobal(QPoint(0, 0))
                size = sub.size()
            except RuntimeError:
                continue
            if self._point_near_rect(pos, top_left, size):
                cx = min(max(pos.x(), top_left.x() + 6), top_left.x() + size.width() - 6)
                cy = min(max(pos.y(), top_left.y() + 6), top_left.y() + size.height() - 6)
                self._send_move_point(sub, QPoint(cx, cy))
                return True
        return False

    @staticmethod
    def _point_near_rect(pos, top_left, size, margin=80):
        return (top_left.x() - margin <= pos.x() <= top_left.x() + size.width() + margin
                and top_left.y() - margin <= pos.y() <= top_left.y() + size.height() + margin)

    def _find_submenu_parent(self, sub, menu=None):
        """找出"这个子菜单是被哪一层菜单的哪一项打开的"。"""
        menu = menu or getattr(self, "_menu_keepalive", None)
        if menu is None:
            return None
        try:
            actions = menu.actions()
        except RuntimeError:
            return None
        for act in actions:
            child = act.menu()
            if child is None:
                continue
            if child is sub:
                return (menu, act)
            found = self._find_submenu_parent(sub, child)
            if found is not None:
                return found
        return None

    def _reshow_submenu(self, sub):
        """子菜单被 Qt 收掉后立刻补弹回来（光标还在附近才补）。"""
        """子菜单被 Qt 收掉后立刻补弹回来（光标还在附近才补）。"""
        parent, action = self._sub_parent.get(sub, (None, None))
        if parent is None or action is None:
            return
        try:
            if not parent.isVisible():
                self._sub_parent.pop(sub, None)
                return
            top_left = sub.mapToGlobal(QPoint(0, 0))
            size = sub.size()
            if not self._point_near_rect(QCursor.pos(), top_left, size, margin=120):
                self._sub_parent.pop(sub, None)
                self._hover_subs.pop(sub, None)
                return
            parent.setActiveAction(None)
            parent.setActiveAction(action)
            self._hover_subs[sub] = {"at": time.time(), "parent": parent, "action": action}
        except RuntimeError:
            self._sub_parent.pop(sub, None)

    def _detach_submenus(self, menu):
        """把带子菜单的项和它的子菜单拆开：Qt 不再弹子菜单，改由我们的浮窗显示。

        Qt 的弹出式子菜单在这台机器上收不到鼠标移动/点击 —— 会自己闪、点了没反应。
        所以这里把子菜单摘下来（setMenu(None)），只在项的文字后面加个 "▸" 提示，
        真正展开交给自绘的普通窗口（_show_flyout），点起来和普通窗口一样可靠。
        """
        for act in menu.actions():
            sub = act.menu()
            if sub is None:
                continue
            self._detach_submenus(sub)
            self._sub_of[act] = sub
            act.setMenu(None)
            if not act.text().rstrip().endswith("▸"):
                act.setText(act.text() + "  ▸")
            # 点它 → 弹一个小选择框（和"添加城市"用的是同一种组件，这台机器上点击没问题）
            act.triggered.connect(lambda _checked=False, a=act: self._pick_submenu(a))

    def _pick_submenu(self, act):
        """点带 ▸ 的项：弹一个选择框列出它下面的项目（含再往下一层）。"""
        sub = self._sub_of.get(act)
        if sub is None:
            return
        title = act.text().rstrip().rstrip("▸").strip()
        options, table = [], {}
        for child in sub.actions():
            if child.isSeparator():
                continue
            nested = self._sub_of.get(child)
            if nested is not None:
                group = child.text().rstrip().rstrip("▸").strip()
                for deep in nested.actions():
                    if deep.isSeparator() or self._sub_of.get(deep) is not None:
                        continue
                    label = f"{group}：{deep.text()}"
                    options.append(label)
                    table[label] = deep
                continue
            label = child.text()
            options.append(label)
            table[label] = child
        if not options:
            return
        with self._ui_guard():
            pick, ok = QInputDialog.getItem(self, title, "选一个：", options, 0, False,
                                            Qt.WindowType.WindowStaysOnTopHint)
        if ok and pick and pick in table:
            target = table[pick]
            QTimer.singleShot(0, target.trigger)     # 等对话框收掉再执行

    def _watch_menu_tree(self, menu, depth=0):
        """给菜单和它所有子菜单装事件过滤器：记录点击 / 展开 / 收起。"""
        if getattr(menu, "_dfy_watched", False):
            return
        menu._dfy_watched = True
        menu._dfy_depth = depth
        menu.installEventFilter(self)
        for act in menu.actions():
            if act.menu() is not None:
                self._watch_menu_tree(act.menu(), depth + 1)
            try:
                act.triggered.connect(
                    lambda _checked=False, a=act: menu_debug(f"[触发] {a.text()}"))
            except Exception:
                pass

    def eventFilter(self, obj, ev):
        """菜单事件的排查日志（只在 MENU_DEBUG 打开时写文件）。"""
        if (isinstance(obj, QMenu) and ev.type() == QEvent.Type.Show
                and getattr(obj, "_dfy_depth", 0) > 0 and obj not in self._sub_parent):
            found = self._find_submenu_parent(obj)
            if found is not None:
                self._sub_parent[obj] = found
        if (isinstance(obj, QMenu) and ev.type() == QEvent.Type.Hide
                and obj in self._sub_parent):
            # 子菜单被 Qt 收掉了：只要光标还在它附近，立刻原地弹回来
            QTimer.singleShot(0, lambda m=obj: self._reshow_submenu(m))
        if isinstance(obj, QMenu) and not self._forwarding_move:
            t = ev.type()
            if MENU_DEBUG and t in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                                    QEvent.Type.MouseMove, QEvent.Type.Show, QEvent.Type.Hide):
                try:
                    pos = (round(ev.position().x()), round(ev.position().y()))
                except Exception:
                    pos = None
                act = None
                try:
                    a = obj.actionAt(obj.mapFromGlobal(QCursor.pos()))
                    act = a.text() if a else None
                except Exception:
                    pass
                line = (f"[Qt菜单{getattr(obj, '_dfy_depth', '?')}] {t.name} pos={pos} "
                        f"光标={QCursor.pos()} 光标下={act} 可见={obj.isVisible()}")
                if t == QEvent.Type.MouseMove:
                    menu_debug_throttled(line, 250)
                else:
                    menu_debug(line)
            if t in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
                deepest = self._deepest_menu_at_cursor()
                if deepest is not None and deepest is not obj:
                    # 光标明明在子菜单上，但点击被 Windows 送给了上层菜单（捕获在上层）。
                    # 所以这里干脆自己处理：找到光标下那一项，放开时执行它 / 展开它的下一层。
                    if t == QEvent.Type.MouseButtonRelease:
                        self.activate_menu_item(deepest)
                    return True
            if t in (QEvent.Type.MouseMove, QEvent.Type.Leave):
                deepest = self._deepest_menu_at_cursor()
                if deepest is not None and deepest is not obj:
                    # 光标其实在最里面那层菜单里：把移动转给它，并且**别让外层菜单看到** ——
                    # 外层看到"光标跑到自己外面"就会把子菜单收掉。
                    self._send_move_to(deepest)
                    return True
                open_sub = any(a.menu() is not None and a.menu().isVisible()
                               for a in obj.actions())
                if t == QEvent.Type.MouseMove and open_sub:
                    # 光标可能正从这一项往子菜单平移：先给子菜单喂个"贴边"的位置，
                    # 让它知道鼠标还在附近，Qt 就不会急着收。
                    if self._keep_submenu_alive(obj):
                        return True
                if t == QEvent.Type.Leave and open_sub:
                    # 还有子菜单开着：光标是从这一项往子菜单平移的路上（多半会短暂跑到菜单外面），
                    # 这时候千万不能让上级菜单"因为光标离开"把子菜单收掉 —— 用户就是在这儿点不中的。
                    # 真要收，交给 _menu_hover_watch 的 0.5 秒宽限去判断。
                    return True
                if open_sub:
                    # 同理：光标不在这一层里（正往子菜单平移）时，连鼠标移动也压住，
                    # 否则上级菜单照样会把它当成"鼠标走了"。
                    try:
                        if not obj.rect().contains(obj.mapFromGlobal(QCursor.pos())):
                            return True
                    except Exception:
                        pass
        if MENU_DEBUG and isinstance(obj, QMenu):
            depth = getattr(obj, "_dfy_depth", 0)
            t = ev.type()
            if t in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                     QEvent.Type.Show, QEvent.Type.Hide):
                try:
                    pos = (round(ev.position().x()), round(ev.position().y()))
                except Exception:
                    pos = None
                act = None
                if pos is not None:
                    a = obj.actionAt(obj.mapFromGlobal(QCursor.pos()))
                    act = a.text() if a else None
                menu_debug(f"{'  ' * depth}[菜单{depth}] {t.name} pos={pos} 光标下={act} "
                           f"可见={obj.isVisible()}")
        return super().eventFilter(obj, ev)

    def _demote_topmost(self, on):
        """菜单打开期间把自己降到非置顶（菜单关了再按设定层级还原）。"""
        try:
            HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
            SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
            if on:
                after = HWND_NOTOPMOST
            elif self.layer == "top":
                after = HWND_TOPMOST
            else:
                after = None
            if after is None:
                return
            ctypes.windll.user32.SetWindowPos(
                ctypes.c_void_p(int(self.winId())), ctypes.c_void_p(after),
                0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
        except Exception:
            pass

    def _menu_click_through(self, on):
        """菜单/对话框开着时让桌宠不接收鼠标。

        二级菜单有时会弹到桌宠身上（靠屏幕右边、子菜单往左弹的时候最明显），
        点下去会被桌宠自己截住 —— 看起来就是"选项点不动"。菜单期间把窗口设成
        鼠标穿透，点击自然落到菜单上；菜单关了再按用户自己的设置还原。
        """
        try:
            hwnd = int(self.winId())
            GWL_EXSTYLE = -20
            style = ctypes.windll.user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            style = click_through_style(style, on, bool(self.cfg.get("passthrough", False)))
            ctypes.windll.user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    def _menu_tick(self):
        """每 120ms：先对账"让位状态"，再跑 v1.0.10 的"放宽触发范围 + 子菜单重叠"尝试。"""
        self._adopt_visible_menu()      # 托盘那条路是 Qt 自己弹的，先认准"屏幕上真正开着的那棵"
        self._sync_overlay_state()
        self._menu_hover_watch()
        self._prune_branches()
        self._close_orphan_submenus()
        # 菜单开着的时候跑勤一点（40ms）：万一某层子菜单被 Qt 摆歪，下 40ms 就纠回来，
        # 眼睛基本看不到"先摆一版再挪"；没菜单的时候回到 120ms，不白费电。
        want_ms = MENU_HOVER_FAST_MS if self.ui_open else MENU_HOVER_MS
        try:
            if self.hover_timer.interval() != want_ms:
                self.hover_timer.start(want_ms)
        except Exception:
            pass

    def _place_shown_submenu(self, sub):
        """子菜单刚显示：立刻摆到"贴住这一条"的位置（同一帧，不留位移痕迹）。"""
        found = self._find_submenu_parent(sub)
        if found is None:
            return
        parent, holder = found
        try:
            if not parent.isVisible():
                return
            want = self._submenu_pos(parent, holder, sub)
            cur = sub.pos()
            if abs(cur.x() - want.x()) > 2 or abs(cur.y() - want.y()) > 2:
                sub.move(want)
                menu_debug(f"[兜底] 子菜单一显示就摆正：{holder.text()} "
                           f"({cur.x()},{cur.y()}) → ({want.x()},{want.y()})")
        except RuntimeError:
            return

    def _close_orphan_submenus(self):
        """根菜单已经关了，却还有子菜单挂在屏幕上 → 收掉。

        实测：Qt 偶尔不跟着把子菜单一起收（`root.close()` 之后二级菜单还在），
        而这个残留弹窗会把**下一次右键**挡掉（右键没反应，菜单弹不出来）。
        """
        root = getattr(self, "_menu_keepalive", None)
        if root is None:
            return
        try:
            if root.isVisible():
                return              # 这棵树还开着，别动
        except RuntimeError:
            return
        for sub in self._all_menus(root)[1:]:
            try:
                if sub.isVisible():
                    sub.close()
                    menu_debug("[兜底] 收掉残留的子菜单")
            except RuntimeError:
                continue

    def _adopt_visible_menu(self):
        """把"屏幕上真正在显示的那棵菜单树"接到手里。

        托盘右键这条路的菜单是 Qt 自己弹的，而且每次右键都会重建一份（菜单里的勾选状态
        是按当前设置现画的）。万一 Qt 弹的是**上一次**那个对象，我们记着的 `_menu_keepalive`
        就跟屏幕上的对不上 —— 悬停兜底、收子菜单、点击摆渡会全部落空（表现就是
        "托盘里的二三级菜单还是老毛病"）。这里每 120ms 认一次，认错了就换过来。
        """
        root = getattr(self, "_menu_keepalive", None)
        if root is not None:
            try:
                if root.isVisible():
                    return          # 我们记着的那棵就在屏幕上 → 不用认
            except RuntimeError:
                pass
        try:
            all_menus = [w for w in QApplication.topLevelWidgets() if isinstance(w, QMenu)]
        except RuntimeError:
            return
        shown = []
        for m in all_menus:
            try:
                if m.isVisible():
                    shown.append(m)
            except RuntimeError:
                continue
        if not shown:
            return
        # 父关系要在**所有**菜单里找（包括已经关掉的上一层）：否则"上一层关了、子菜单还挂着"
        # 的时候，会把那个孤儿子菜单当成一棵树的根接管过来。
        inner = set()
        for m in all_menus:
            try:
                for a in m.actions():
                    child = a.menu()
                    if child is not None:
                        inner.add(id(child))
            except RuntimeError:
                continue
        roots = [m for m in shown if id(m) not in inner]
        if not roots:
            return
        popup = QApplication.activePopupWidget()      # 抓着鼠标的那个 = 当前这一支的根
        top = popup if popup in roots else roots[0]   # 都没有就按"最先建出来的"（根先于子菜单建）
        if root is top:
            return
        self._menu_keepalive = top
        if top not in self._menu_pool:
            self._menu_pool = ([top] + self._menu_pool)[:4]
        menu_debug("[兜底] 接管屏幕上真正显示的那棵菜单")

    def force_recover(self):
        """救急：把"给菜单让位"的状态强行收回来。

        万一哪个菜单窗口没关干净（残留一个"可见"的菜单），桌宠就会一直保持在
        "鼠标穿透 + 不置顶"里 —— 看起来就是"桌宠不见了、也点不到"。
        这个函数把残留菜单关掉、状态复位，再把自己亮出来。
        """
        for menu in list(self._menu_pool) + list(self._hover_subs):
            try:
                if menu.isVisible():
                    menu.close()
            except Exception:
                pass
        self._menu_pool = []
        self._hover_subs.clear()
        self._hover_key = None
        self._sub_rect = {}
        self._resub = {}
        self._dialog_open = False
        self.ui_open = False
        self._through_applied = False
        self._demote_topmost(False)
        self._apply_passthrough(bool(self.cfg.get("passthrough", False)))   # 按用户自己的设置还原
        if not self.isVisible():
            self.show()
        self.raise_()
        self._apply_layer()

    def _sync_overlay_state(self):
        """按"现在到底有没有菜单/对话框开着"纠正让位状态。

        只靠 aboutToShow / aboutToHide 信号不可靠：实测漏过一次 —— 菜单已经关了，
        aboutToHide 却没来，于是桌宠一直停在"鼠标穿透 + 不置顶"的状态，点也点不回来。
        这里每 120ms 按真实可见性对账，漏了信号也能自己恢复。
        """
        visible_menus = []
        for menu in self._menu_pool:
            try:
                if menu.isVisible():
                    visible_menus.append(menu)
            except RuntimeError:          # 老菜单对象可能已经被回收
                continue
        visible = bool(self._dialog_open) or bool(visible_menus)
        if visible != self.ui_open:
            self.ui_open = visible
            self._demote_topmost(visible)
        # 注意：**不要**让桌宠在菜单期间变成鼠标穿透。
        # 试过两版（整窗穿透 / 光标压在菜单上才穿透）都会出问题：右键桌宠时点击穿到桌面，
        # 弹出了 Windows 桌面的右键菜单。菜单压在桌宠上面的部分，靠"把桌宠降到非置顶"就够了。
        if self._through_applied:
            self._through_applied = False
            self._menu_click_through(False)

    def set_menu_debug(self, on):
        """菜单排查日志开关（菜单里那一项）：打开后菜单的动作、位置自愈都写进 menu-debug.log。"""
        global MENU_DEBUG_RUNTIME
        on = bool(on)
        MENU_DEBUG_RUNTIME = on
        self.cfg["menu_debug"] = on
        if on:
            try:
                with open(MENU_DEBUG_LOG, "w", encoding="utf-8") as f:
                    f.write(f"=== 大肥鱼桌宠 菜单日志 {datetime.now():%Y-%m-%d %H:%M:%S} ===\n")
            except Exception:
                pass
            self.say("菜单日志开着呢，出问题以后跟我说一声就行")
        else:
            self.say("菜单日志关啦")

    MENU_TRIGGER_MARGIN_X = 0       # 方案 1 已弃用（主人选方案 2）：不再放宽触发范围
    MENU_OVERLAP = 9                # v1.0.10 方案 2：子菜单和上一级菜单重叠的像素（16 → 12 → 9，两次各减 25%）

    def _menu_action_at(self, menu, pos, margin_x=0):
        """按（可横向放宽的）矩形找光标下那一项；纵向不放宽，免得串到相邻条目上。"""
        try:
            local = menu.mapFromGlobal(pos)
        except RuntimeError:
            return None
        if margin_x > 0:
            try:
                for a in menu.actions():
                    if a.isSeparator():
                        continue
                    r = menu.actionGeometry(a)
                    if (r.left() - margin_x <= local.x() <= r.right() + margin_x
                            and r.top() <= local.y() <= r.bottom()):
                        return a
            except RuntimeError:
                return None
        return menu.actionAt(local)

    def _submenu_pos(self, parent, holder, sub):
        """算子菜单该放哪儿：和一级菜单**重叠 MENU_OVERLAP 像素**，缩短鼠标要走的距离。

        关键：位置要在**弹出之前**算好（`sub.popup(位置)`），
        否则会"先出现在 Qt 算的位置、再跳过来"——主人一眼就看出来了。
        """
        try:
            item = parent.actionGeometry(holder)
            a = parent.mapToGlobal(item.topLeft())
            b = parent.mapToGlobal(item.bottomRight())
            screen = QApplication.screenAt(a) or QApplication.primaryScreen()
            geo = screen.availableGeometry()
            size = sub.size() if sub.isVisible() else sub.sizeHint()
            w, h = max(1, size.width()), max(1, size.height())
            # 这一层跟着上一层"往哪边弹"走：上一层是往左弹的，这一层也往左。
            # 不这样的话，孙子菜单会盖到爷爷（一级菜单）头上 —— 实测就是"三级菜单压住了
            # 一级菜单的「层级」那一条，于是悬停「层级」再也不出子菜单"。
            flip = bool(getattr(parent, "_dfy_flip_left", False))
            if flip:
                x = a.x() - w + self.MENU_OVERLAP
            else:
                x = b.x() - self.MENU_OVERLAP      # 先试右边（和这一条重叠）
                if x + w > geo.right():            # 右边放不下 → 放左边，同样重叠
                    x = a.x() - w + self.MENU_OVERLAP
                    flip = True
            sub._dfy_flip_left = flip
            y = a.y() - 4
            x = max(geo.left(), min(max(geo.left(), geo.right() - w), x))
            y = max(geo.top(), min(max(geo.top(), geo.bottom() - h), y))
            return QPoint(int(x), int(y))
        except Exception:
            return parent.mapToGlobal(QPoint(0, 0))

    def _menu_hover_watch(self):
        """菜单悬停的人为规则（用户定的，尽量贴近 Windows 原生）：

        · 光标在这一条的**任意位置**上 → 就弹这一条的子菜单
        · 移到下一条 → 上一个子菜单立刻换掉（不打架）
        · 光标进了子菜单 → 保持（并顺手把位置喂给 Qt，免得它以为鼠标跑了）
        · 既不在条上、也不在子菜单里 → 给 0.35 秒宽限（走过那条空档），超时才收
        """
        root = getattr(self, "_menu_keepalive", None)
        if not self.ui_open or root is None or not root.isVisible():
            self._hover_key = None
            self._keep = None
            self._leave_at = 0.0
            return
        pos = QCursor.pos()
        now = time.time()
        # 光标所在的菜单（含已经展开的子菜单）＋它下面的那一条
        menu = self._deepest_menu_at_cursor() or root
        # 让"光标停在哪一条"的高亮跟着手走：这台机器上 Qt 的弹出菜单收不到鼠标移动，
        # 高亮全靠我们喂（不然快速上下滑的时候高亮会停在老地方，看着就像卡住）。
        self._highlight_menu_item(menu, pos)
        act = self._menu_action_at(menu, pos, self.MENU_TRIGGER_MARGIN_X)

        # ① 光标压在某一条带子菜单的项上（这条的任意位置都算）→ 用它的子菜单
        if act is not None and act.menu() is not None:
            sub = act.menu()
            if self._keep is not None and self._keep[1] is not act:
                old_sub = None
                try:
                    old_sub = self._keep[1].menu()
                except RuntimeError:
                    old_sub = None
                # v1.0.10：如果"旧的子菜单"就是光标现在所在这一层（或它的上层），
                # 千万别关它 —— 关掉它等于把光标脚下的菜单收走（三级菜单一进去就没）。
                if old_sub is not None and not self._menu_covers(old_sub, menu):
                    self._close_submenu(old_sub)   # 移到别的条：旧的立刻关
                    menu_debug("[兜底] 换条 → 收掉上一个子菜单")
            self._keep = (menu, act)
            self._leave_at = 0.0
            self._hover_key = (id(menu), act.text())
            try:
                menu.setActiveAction(act)      # 这一条显成"选中"（高亮跟着手）
            except RuntimeError:
                pass
            self._ensure_chain_open(menu)      # 上层被 Qt 收掉了就补回来
            want = self._submenu_pos(menu, act, sub)
            if not sub.isVisible():
                # 方案 2：弹出前就把位置算成"和一级重叠"，中间不会有跳一下
                sub.popup(want)
                menu_debug(f"[兜底] 展开子菜单：{act.text()} @({want.x()},{want.y()}) "
                           f"这一条={menu.actionGeometry(act)}")
            else:
                # 自愈：不管是谁把子菜单放歪了（Qt 自己摆的、弹出时尺寸还没算准、
                # 或者被别的动作挪过），都挪回"贴住主人悬停的这一条"的位置。
                # 主人截图里"二级菜单位置/重叠忽上忽下"就是用这一条兜住的。
                try:
                    cur = sub.pos()
                except RuntimeError:
                    return
                dx, dy = abs(cur.x() - want.x()), abs(cur.y() - want.y())
                if dx > 2 or dy > 2:
                    sub.move(want)
                    menu_debug(f"[兜底] 子菜单挪回该在的位置：{act.text()} "
                               f"({cur.x()},{cur.y()}) → ({want.x()},{want.y()})")
            return

        # ② 光标已经在子菜单里 → 保持（喂一个位置给 Qt，免得它以为鼠标离开了）
        if self._keep is not None:
            deep_now = self._deepest_menu_at_cursor()
            if deep_now is not None:
                self._ensure_chain_open(deep_now)   # 上层被 Qt 收掉了就补回来
            parent, holder = self._keep
            sub = None
            try:
                sub = holder.menu()
            except RuntimeError:
                sub = None
            # v1.0.11：光标如果已经落到"同一个菜单里的另一条"上，就当成换条处理。
            # 不然下面那套"把被 Qt 收掉的子菜单顶回来"会把高亮又拽回旧的那一条 ——
            # 主人看到的就是"从「添加我的音效…」往旁边移，选中老是卡在「音效选择」上"。
            other = self._menu_action_at(parent, pos, self.MENU_TRIGGER_MARGIN_X)
            if other is not None and other is not holder:
                self._close_submenu(sub)
                if sub is not None:
                    self._resub.pop(sub, None)
                self._keep = (parent, other) if other.menu() is not None else None
                self._leave_at = 0.0
                self._highlight_menu_item(parent, pos)
                return
            if sub is not None:
                try:
                    if sub.isVisible() and sub.rect().contains(sub.mapFromGlobal(pos)):
                        self._leave_at = 0.0
                        self._sub_rect[sub] = (sub.mapToGlobal(QPoint(0, 0)), sub.size())
                        self._resub.pop(sub, None)
                        self._send_move_point(sub, pos)
                        return
                except RuntimeError:
                    pass
                try:
                    if not sub.isVisible():
                        # Qt 自己把它收了，而光标还停在它原来那一片 → 分三步往回捞：
                        # ① 让 Qt 按自己的流程重开（最干净）
                        # ② 还没开，就替 Qt 往这一条的中心塞一个鼠标移动（等于"手又停上去了"）
                        # ③ 连着几次都开不了，才自己补弹（最后手段，尽量不走到）
                        rect = self._sub_rect.get(sub)
                        near = rect is not None and self._point_near_rect(pos, rect[0], rect[1], 60)
                        tries = self._resub.get(sub, 0) + 1
                        self._resub[sub] = tries
                        if parent.isVisible():
                            parent.setActiveAction(None)
                            parent.setActiveAction(holder)
                            if near and tries >= 2:
                                self._send_move_point(parent, parent.mapToGlobal(
                                    parent.actionGeometry(holder).center()))
                            if near and tries >= 3:
                                self._resub[sub] = 0
                                sub.popup(self._submenu_pos(parent, holder, sub))
                        return
                except RuntimeError:
                    pass
            # ③ 既不在条上、也不在子菜单里 → 0.35 秒宽限（从条走到子菜单的空档），超时收
            if self._menu_action_at(parent, pos, self.MENU_TRIGGER_MARGIN_X) is holder:
                self._leave_at = 0.0        # v1.0.10：光标还在这一条的"放宽范围"里 → 保持
                return
            if self._leave_at == 0.0:
                self._leave_at = now
                return
            if now - self._leave_at <= 0.35:
                return
            # 光标可能落在更深一层（三级菜单）里：那就把"保持目标"跟下去，别手贱收掉
            deep = self._deepest_menu_at_cursor()
            if deep is not None and deep is not sub:
                self._ensure_chain_open(deep)      # Qt 会把上层收掉 → 逐个补回来
                found = self._find_submenu_parent(deep)
                if found is not None:
                    self._keep = found
                self._leave_at = 0.0
                return
            # 超时了，可光标还停在"这个子菜单原来那一片"上 → 说明是被 Qt 误收的，别放弃：
            # 自己把它弹回来（不然就成了"进去就没了"，实测 20 条里偶尔会中一条）。
            rect = self._sub_rect.get(sub)
            if rect is not None and self._point_near_rect(pos, rect[0], rect[1], 60):
                try:
                    if parent.isVisible():
                        sub.popup(self._submenu_pos(parent, holder, sub))
                        menu_debug("[兜底] 光标还在原地 → 重新弹出被误收的子菜单")
                        self._leave_at = 0.0
                        return
                except RuntimeError:
                    pass
            self._close_submenu(sub)
            self._keep = None
            self._leave_at = 0.0
        self._hover_key = None

    def _ensure_chain_open(self, deep):
        """把 deep 以上的祖先菜单逐个保住：Qt 把哪一层收掉了，就重新展开哪一层。"""
        chain = []
        cur = deep
        for _ in range(5):
            found = self._find_submenu_parent(cur)
            if found is None:
                break
            chain.append(found)
            cur = found[0]
        for parent, holder in reversed(chain):
            try:
                sub = holder.menu()
                if sub is not None and not sub.isVisible() and parent.isVisible():
                    sub.popup(self._submenu_pos(parent, holder, sub))   # 直接补弹（setActiveAction 不一定生效）
                    menu_debug(f"[兜底] 补回上一层：{holder.text()}")
            except RuntimeError:
                continue

    def _menu_covers(self, anc, menu):
        """anc 是不是 menu 本身、或者 menu 的某一层"上层菜单"。"""
        if anc is None or menu is None:
            return False
        cur = menu
        for _ in range(6):
            if cur is anc:
                return True
            found = self._find_submenu_parent(cur)
            if found is None:
                return False
            cur = found[0]
        return False

    def _prune_branches(self):
        """一次只留一支：光标所在的那一支留着，旁边那些残留的子菜单收掉。

        没有这条对账，会出现"光标已经跑到别的条目上、上一支的子菜单还挂在屏幕上"
        （实测：形象那一支挂在「层级」旁边，把「层级」的子菜单挡了个正着）。
        """
        root = getattr(self, "_menu_keepalive", None)
        if not self.ui_open or root is None:
            return
        deep = self._deepest_menu_at_cursor()
        if deep is None:
            return                      # 光标在空档里（0.35 秒宽限中）→ 什么都别动
        keep = None
        if self._keep is not None:
            try:
                keep = self._keep[1].menu()
            except RuntimeError:
                keep = None
        self._prune_menu(root, deep, keep)

    def _prune_menu(self, menu, deep, keep):
        for act in menu.actions():
            try:
                child = act.menu()
            except RuntimeError:
                continue
            if child is None:
                continue
            try:
                if not child.isVisible():
                    continue
            except RuntimeError:
                continue
            if self._menu_covers(child, deep) or self._menu_covers(child, keep):
                self._prune_menu(child, deep, keep)
            else:
                self._close_menu_tree(child)

    def _close_menu_tree(self, menu):
        """把这一支子菜单（含它下面的）全收掉。"""
        try:
            for act in menu.actions():
                child = act.menu()
                if child is not None:
                    self._close_menu_tree(child)
        except RuntimeError:
            return
        self._close_submenu(menu)

    @staticmethod
    def _close_submenu(sub):
        try:
            if sub is not None and sub.isVisible():
                sub.close()
        except Exception:
            pass

    def _open_classic_menu(self):
        """把完整版老菜单按老样子弹出来（设置窗口「通用」里那个"看一眼"用它）。"""
        m = self._make_menu(classic=True)
        try:
            m.exec(QCursor.pos())
        finally:
            self._sync_overlay_state()

    def set_classic_menu(self, on):
        """右键菜单用哪一份：瘦身版（默认）还是旧版那份完整菜单。"""
        self.cfg["classic_menu"] = bool(on)
        self.save_config()
        self.say("右键菜单换成旧版那份了（功能全，但很长）" if on
                 else "右键菜单回到瘦身版了", seconds=3.0, again=True)

    def set_minimize_target(self, point):
        """记下"设置窗口最小化动画往哪儿收"的屏幕坐标（在「通用」页校准）。"""
        try:
            x, y = int(point[0]), int(point[1])
        except (TypeError, ValueError, IndexError):
            return
        self.cfg["minimize_target"] = [x, y]
        self.save_config()

    def _open_menu(self, pos):
        """弹右键菜单。

        用 exec() 走 Qt 的弹出菜单模态循环：二级菜单能正常悬停展开、贴屏幕边缘时
        也会自动往反方向弹。之前用 popup + 定时 raise_() 会把子菜单顶掉，
        鼠标离开一级菜单整个菜单就消失，所以改回 exec()；菜单开着的时候
        桌宠本身也不再抢置顶（见 _keep_on_top），不会被压住。
        """
        m = self._make_menu()
        try:
            m.exec(pos)
        finally:
            # 保险：菜单没触发 aboutToHide 也要把状态收回来
            self._sync_overlay_state()

    def _ui_guard(self):
        """对话框期间用的上下文管理器：桌宠站住不动，免得盖住对话框。"""
        pet = self

        class _Guard:
            def __enter__(self):
                pet.ui_open = True
                pet._dialog_open = True
                pet._demote_topmost(True)

            def __exit__(self, *exc):
                pet._dialog_open = False
                pet._sync_overlay_state()
                return False

        return _Guard()

    def contextMenuEvent(self, e):
        self._open_menu(e.globalPos())

    # ---------- 功能 ----------
    def set_mode(self, mode):
        self.mode = mode
        self.target = None
        self.cfg["mode"] = mode
        if mode == "still":
            self._still_face_front()   # 切到「原地待着」立刻站正，不用等下一帧
        self.update()

    def set_still_face_cursor(self, on):
        """「原地待着时也跟着鼠标转」开关（当前形象都生效：大肥鱼会转侧面，挂件会左右翻）。"""
        self.still_face_cursor = bool(on)
        self.cfg["still_face_cursor"] = bool(on)
        self.update()

    def set_balance_always(self, on):
        self.balance_always = bool(on)
        self.cfg["balance_always"] = bool(on)
        if on and self.balance is None:
            self.refresh_balance(silent=False)
        self.update()

    def set_show_peak(self, on):
        self.show_peak = bool(on)
        self.cfg["show_peak"] = bool(on)
        self.update()

    def set_peak_style(self, style):
        if style not in PEAK_TEXT_STYLES:
            return
        self.peak_style = style
        self.cfg["peak_style"] = style
        self.update()

    def set_bubble_style(self, style):
        """气泡风格：跟随界面 / 浅色 / 深色（语录、余额、歌词三种气泡一起换）。"""
        if style not in dict(BUBBLE_STYLES):
            return
        self.bubble_style = style
        self.cfg["bubble_style"] = style
        # 歌词的颜色是烘在排版缓存里的，换了风格得让缓存重算一遍
        self._lyric_layout_key = None
        self._lyric_prev_key = None
        self._bubble_theme_cache = None        # auto 那个 1 秒的缓存也清掉，换风格立刻生效
        self.update()
        self.save_config()
        self.say("气泡换成"
                 + {"auto": "跟着界面走", "light": "浅色", "dark": "深色"}.get(style, "浅色")
                 + "啦")

    def set_line_freq(self, name):
        """语录频率：安静 / 正常 / 话多 / 话痨（管的是"闲着时自己冒话"的频率）。"""
        if name not in LINE_FREQ_LEVELS:
            return
        self.line_freq = name
        self.cfg["line_freq"] = name
        self.last_speak_tick = self.t          # 让新档位马上生效，不用等旧冷却
        # 切档时说的这句话本身也能在「台词内容…」里改写（LINE_GROUPS 里那四条）
        words = self.lines_for_say(f"FREQ_LINES_{name}")
        if words:
            self.say(random.choice(words), seconds=3.0, again=True)

    def set_double_click(self, key):
        """快速双击弹哪个窗口：余额 / 天气 / 在放什么 / 我写的台词。

        余额这一项**配了 Key 才能选** —— 没配 Key 时直接选了也不给存（双击不会弹余额窗口）。
        """
        if key not in dict(DOUBLE_CLICK_CHOICES):
            return
        if key == "balance" and not self._current_source()[1]:
            self.say("看余额要先配 Key：右键 →「余额 → 设置 Key」，配好再回来选这一项",
                     seconds=4.0, again=True)
            return
        self.cfg["double_click"] = key
        self.save_config()
        self.say(f"好，以后快速双击 → {dict(DOUBLE_CLICK_CHOICES)[key]}", seconds=3.0, again=True)

    # ---------- 层级 / 透明度 ----------
    LAYER_LABELS = {"top": "置顶", "bottom": "置底（在壁纸之上）", "normal": "普通层"}

    def set_layer(self, layer):
        """top = 始终置顶；bottom = 沉到所有窗口下面（但仍在壁纸/桌面之上）；normal = 普通。"""
        if layer not in self.LAYER_LABELS:
            return
        self.layer = layer
        self.cfg["layer"] = layer
        self.cfg["topmost"] = (layer == "top")
        self._apply_layer()
        self.say({"top": "我回到最上面啦",
                  "bottom": "我到最下面了（壁纸上面那种）",
                  "normal": "我站在普通层，谁点谁在上面"}[layer])

    def _apply_layer(self):
        """用 Win32 精确摆放层级：HWND_TOPMOST / HWND_BOTTOM / HWND_NOTOPMOST。"""
        try:
            HWND_TOPMOST, HWND_NOTOPMOST, HWND_BOTTOM = -1, -2, 1
            SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
            after = {"top": HWND_TOPMOST, "bottom": HWND_BOTTOM,
                     "normal": HWND_NOTOPMOST}.get(self.layer, HWND_TOPMOST)
            ctypes.windll.user32.SetWindowPos(
                ctypes.c_void_p(int(self.winId())), ctypes.c_void_p(after),
                0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
        except Exception:
            pass

    def set_opacity(self, value):
        """整体透明度 0.2 ~ 1.0（太低就看不见了，所以留个下限）。"""
        value = max(0.2, min(1.0, float(value)))
        self.opacity = value
        self.cfg["opacity"] = value
        self.setWindowOpacity(value)

    # ---------- 音量 / 透明度的小窗口（菜单里内嵌滑块在这台机器上拖不动，改成弹窗） ----------
    def _slider_dialog(self, title, tip_text, lo, hi, value, on_change, extra=None):
        """一个带滑块的小窗口：**拖动立刻生效**。

        为什么不用菜单里内嵌的滑块：这台机器上 Qt 的弹出子菜单收不到鼠标消息，
        嵌在里面的滑块拖不动（主人反馈"透明度和音效音量无法调整"就是这个原因）。
        """
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        dlg.setMinimumWidth(380)
        if ui_console:                      # 跟设置窗口用同一套配色
            ui_console.style_dialog(dlg, BUNDLE_DIR)
        lay = QVBoxLayout(dlg)
        tip = QLabel(tip_text)
        tip.setWordWrap(True)
        lay.addWidget(tip)
        row = QHBoxLayout()
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(lo, hi)
        slider.setValue(value)
        slider.setMinimumWidth(240)
        row.addWidget(slider, 1)
        num = QLabel(f"{value}%")
        num.setFixedWidth(52)
        row.addWidget(num)
        lay.addLayout(row)
        btns = QHBoxLayout()
        if extra:
            b = QPushButton(extra[0])
            b.clicked.connect(extra[1])
            btns.addWidget(b)
        btns.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dlg.accept)
        btns.addWidget(close_btn)
        lay.addLayout(btns)

        def changed(v):
            num.setText(f"{v}%")
            on_change(v / 100.0)

        slider.valueChanged.connect(changed)
        with self._ui_guard():
            dlg.exec()

    def volume_dialog(self):
        """音效音量：拖动立刻生效，顺手能试听一声。"""
        self._slider_dialog(
            "音效音量",
            f"拖动滑块调点击音效的音量（现在 {int(self.volume * 100)}%），拖的时候立刻生效。",
            0, 100, int(round(self.volume * 100)), self.set_volume,
            extra=("试听一声", self.preview_sounds))

    def opacity_dialog(self):
        """桌宠透明度：拖动立刻生效（20% 是下限，再低就看不见了）。"""
        self._slider_dialog(
            "桌宠透明度",
            f"拖动滑块调桌宠整体透明度（20% ~ 100%，现在 {int(self.opacity * 100)}%）。",
            20, 100, int(round(self.opacity * 100)), self.set_opacity)

    def size_dialog(self):
        """大小无级调节：滑块拖到哪儿就多大，原来那五档还在菜单里点一下就到。

        百分数以「大」档为 100%（也就是 306px 高）；范围 20% ~ 150%。
        """
        cur = size_percent(self.cfg.get("size", SIZE_DEFAULT))
        self._slider_dialog(
            "大小（无级调节）",
            f"拖动滑块无级调大小（{size_percent(SIZE_MIN)}% ~ {size_percent(SIZE_MAX)}%，"
            "100% 就是「大」那一档那么大）：拖着的时候它当场变大变小，"
            "而且是原地缩放（脚底和中心不动，不会满屏乱窜）；松手就记住，"
            "菜单里的「迷你 / 特小 / 小 / 中 / 大」五档照旧点一下就到。",
            size_percent(SIZE_MIN), size_percent(SIZE_MAX), cur,
            lambda pct: self.set_size(size_from_percent(pct)))

    def set_process_alerts(self, on):
        self.process_alerts = bool(on)
        self.cfg["process_alerts"] = bool(on)
        if on:
            self.say("好哦，你开什么我都盯着（才不是偷看呢）")

    def set_app_time_on(self, on):
        """用久了提醒的总开关（每个应用具体说多久、说什么在 app_time_lines 里）。"""
        self.cfg["app_time_on"] = bool(on)
        if on:
            self.say("好嘛，用久了我会喊你歇歇")

    def set_timed_on(self, on):
        """到点说一句的总开关。"""
        self.cfg["timed_on"] = bool(on)
        if on:
            self.say("到点我会吱一声的，放心")

    def set_hotkeys_on(self, on):
        """全局快捷键的总开关（关掉就把已经注册的键还给系统）。"""
        self.cfg["hotkeys_on"] = bool(on)
        self._register_hotkeys()
        if on:
            bad = self.hotkey_failed_texts()
            self.say("快捷键好啦，按一下试试嘛" if not bad
                     else f"快捷键里这几个被占用了：{'、'.join(bad)}")

    def set_back_greet(self, on):
        """离开一阵子回来打个招呼（台词在「台词内容 → 离开一阵子回来时」）。"""
        self.cfg["back_greet"] = bool(on)
        if on:
            self.say("好哦，你回来我一定第一时间发现", seconds=2.5)

    def set_fullscreen_silent(self, on):
        """全屏（打游戏 / 看电影）时闭嘴：提醒先攒着，退出全屏再报。"""
        self.cfg["fullscreen_silent"] = bool(on)
        if not on:
            self._fs_now = False
            self._held_lines = []

    def set_quiet_minutes(self, minutes):
        try:
            self.cfg["quiet_minutes"] = max(1, int(minutes))
        except (TypeError, ValueError):
            pass

    def set_perf_mode(self, on):
        """性能模式：动画优先，开设置菜单也不掉帧；休闲模式：省 CPU，可掉一点帧。

        休闲模式把帧间隔从 20ms 放到 40ms（50 帧 → 25 帧）；动作是按同一个内部时钟
        换算的，所以走的速度、气泡停留时间都不变，只是画面更"省"。
        """
        self.perf_mode = bool(on)
        self.cfg["perf_mode"] = bool(on)
        self.tick_ms = TICK if self.perf_mode else TICK * 2
        self.timer.setInterval(self.tick_ms)
        self.say("好，动画优先，菜单开着也不卡" if on else "行，省点资源，掉几帧没关系",
                 again=True)
        self.update()

    def set_music_link(self, on):
        """音乐联动总开关：关掉就不再读媒体会话。"""
        self.music_on = bool(on)
        self.cfg["music_link"] = bool(on)
        if on:
            self.say("好，你去放歌，我帮你看歌词")
            self.poll_music()
        else:
            self.now_playing = None
            self._lyric_key = ""
            self._lyric_lines = []
            self._lyric_words = {}
            self.say("行，那我不听了")
        self.update()

    def set_music_lyrics(self, on):
        """歌词内容开关：关掉只挂个歌名，不再请求歌词。"""
        self.music_lyrics = bool(on)
        self.cfg["music_lyrics"] = bool(on)
        if on and self.now_playing and self._lyric_key and not self._lyric_lines \
                and not self._lyric_fetching:
            self._start_lyric_fetch(self._lyric_key, self.now_playing)

    def _lyric_offset_label(self):
        """菜单标题里显示当前对时（例如「（文字延后 0.2 秒）」）。"""
        for label, off in LYRIC_OFFSET_LEVELS:
            if abs(getattr(self, "lyric_offset", 0.0) - off) < 1e-6:
                return "" if abs(off) < 1e-6 else f"（{label}）"
        return ""

    def set_lyric_offset(self, offset):
        """歌词对时：正数 = 文字延后（等一下声音），负数 = 文字提前。"""
        try:
            offset = float(offset)
        except (TypeError, ValueError):
            return
        self.lyric_offset = offset
        self.cfg["lyric_offset"] = offset
        self.update()
        tip = "歌词跟声音对齐啦" if abs(offset) < 1e-6 else (
            f"歌词{'延后' if offset > 0 else '提前'} {abs(offset):.1f} 秒")
        self.say(tip + "（觉得还对不上就再调一档）", seconds=3.2, again=True)
        self.update()

    # ---------- 这首歌的歌词微调（网易云不报播放进度，中途才开始看就只能手动对一次） ----------
    def _lyric_nudge_label(self):
        n = float(getattr(self, "_lyric_nudge", 0.0))
        if abs(n) < 1e-6:
            return ""
        return f"（现在{'往前赶' if n > 0 else '往后压'} {abs(n):.1f} 秒）"

    def align_lyric_dialog(self):
        """按播放器上显示的时间对一次表（网易云不报进度，这是最准的手动办法）。"""
        cur = self._music_position()
        tip = (f"输入播放器上现在显示的进度（例如 1:35）。\n"
               f"桌宠现在算的是 {int(cur // 60)}:{int(cur % 60):02d}，"
               f"填对了歌词立刻就对齐（这首歌会记住这个位置）。")
        with self._ui_guard():
            text, ok = QInputDialog.getText(
                self, "按播放器的时间对齐歌词", tip, QLineEdit.EchoMode.Normal, "",
                Qt.WindowType.WindowStaysOnTopHint)
        if not ok or not (text or "").strip():
            return
        secs = parse_mmss(text)
        if secs is None:
            self.say("这个时间没看懂，写成 1:35 这样就行", seconds=3.2, again=True)
            return
        self.set_lyric_anchor(secs)

    def set_lyric_anchor(self, seconds):
        """把"这首歌现在放到第几秒"设成指定值（网易云不给进度时的手动对表）。"""
        self._music_played = max(0.0, float(seconds))
        self._music_tick_at = time.time()
        if self._lyric_key:
            self._music_pos_memo[self._lyric_key] = self._music_played
        self.update()
        self.say(f"好，按 {int(self._music_played // 60)}:"
                 f"{int(self._music_played % 60):02d} 对齐啦", seconds=3.2, again=True)

    def nudge_lyric(self, delta, absolute=False):
        """把歌词整体往前赶 / 往后压几秒（只影响这一首歌，按歌记住）。"""
        try:
            delta = float(delta)
        except (TypeError, ValueError):
            return
        base = delta if absolute else float(getattr(self, "_lyric_nudge", 0.0)) + delta
        self._lyric_nudge = max(-20.0, min(20.0, base))
        if self._lyric_key:
            self._lyric_nudges[self._lyric_key] = self._lyric_nudge
        self.update()
        n = self._lyric_nudge
        tip = "这首歌的歌词微调清零了" if abs(n) < 1e-6 else (
            f"歌词{'往前赶' if n > 0 else '往后压'}了 {abs(n):.1f} 秒")
        self.say(tip + "（对上了就不用再动）", seconds=3.2, again=True)

    def set_snap(self, on):
        self.snap_on = bool(on)
        self.cfg["snap_on"] = bool(on)
        if not on:
            self.snap_h = self.snap_v = None
            self.flip_x = False
        self.update()

    def set_flip_on_left(self, on):
        self.flip_on_left = bool(on)
        self.cfg["flip_on_left"] = bool(on)
        if not on:
            self.flip_x = False
        self.update()

    def set_locked(self, on):
        """锁定位置：固定在原地 —— 点它、双击它、右键菜单都照常，就是拖着不动了。

        防的是"想点一下结果把桌宠拖跑了"这种误触。想让它连散步都不散，用
        模式 →「原地待着」；这里只管"拖不动"。
        """
        self.locked = bool(on)
        self.cfg["locked"] = bool(on)
        self.dragging = False
        self._drag_blocked = False
        self.drag_offset = None
        self.drag_start_pos = None
        self.save_config()
        self.say("锁定啦，我就在这儿不动了（右键 →「锁定位置」可以解锁）" if on
                 else "解锁了，又能拖着我走了",
                 seconds=3.0, again=True)
        self.update()

    def set_turn_cost(self, on):
        self.turn_cost_on = bool(on)
        self.cfg["turn_cost_on"] = bool(on)

    def set_size(self, mult):
        """设大小：菜单里那五档和"无级调节"的滑块都走这里。

        两个细节：
        · 五档以外的高度现补精灵（`_ensure_sprites`），顺手把多余的高度清掉（`_prune_sprites`）；
        · 变大小是"原地缩放"：脚底和中心不动，免得滑块一拖它整只往下出溜。
        """
        mult = self._clamp_size(mult)
        self.cfg["size"] = mult
        self.cross_t = 0.0
        self.prev_key = None
        old_x, old_y = self.x(), self.y()
        old_w, old_h = self.width(), self.height()
        self.cur_h = int(340 * mult)
        self._prune_sprites(self.cur_h)
        self._ensure_sprites(self.cur_h)
        self._apply_window_size()
        if old_w:                      # 建窗口那一趟（还没摆位）不用动位置
            self.move(int(old_x + old_w / 2 - self.width() / 2),
                      int(old_y + old_h - self.height()))
        self.snap_into_screen()

    def _dsh_act_width(self, h):
        """动作帧在显示高度 h 时需要多宽（取所有动作里最宽的那张）。

        动作立绘可能比三视图宽（张开手臂那种），窗口得放得下，否则会被裁掉。
        """
        best = 0.0
        # 注意：_apply_window_size 在 __init__ 里被调得比分帧加载更早，
        # 所以这里必须用 getattr 兜一下，不然启动就崩。
        for act, by_idx in (getattr(self, "dsh_acts", None) or {}).items():
            zoom = DSH_ACT_ZOOM.get(act, 1.0)
            for variants in by_idx.values():
                for _src_h, pix in variants:
                    ph = pix.height()
                    if ph:
                        best = max(best, h * zoom * pix.width() / float(ph))
        return int(best) + 1

    def _apply_window_size(self):
        """按当前档位摆好窗口：精灵宽度 + 两边留白，但不小于 MIN_WIN_W（气泡要放得下字）。

        为什么要有个最窄宽度：新加的「迷你 / 特小」两档精灵很窄（几十像素），
        如果窗口跟着一起变窄，余额气泡就会被挤成一列竖着的字。
        """
        try:
            spec_w = max(p.width() for k, p in self.sprites.items() if k[1] == self.cur_h)
        except ValueError:
            spec_w = 0
        # 合体新增：动作立绘可能更宽，窗口也要放得下
        spec_w = max(spec_w, self._dsh_act_width(self.cur_h))
        self.win_mx = int(self.cur_h * 0.062) + 6
        self.win_w = max(spec_w + self.win_mx * 2, MIN_WIN_W)
        self.setFixedSize(self.win_w, self.cur_h + BUBBLE_H + MARGIN * 2 + 10)

    def snap_into_screen(self):
        geo = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        x = max(geo.left(), min(geo.right() - self.width(), self.x()))
        y = max(geo.top(), min(geo.bottom() - self.height(), self.y()))
        self.move(x, y)
        self._settle(geo)

    def _keep_on_top(self):
        """定期把自己顶到置顶窗口的最前面（SWP_NOACTIVATE，不抢焦点）。

        有的窗口（例如 Codex 主窗口）本身也是置顶的，两个置顶窗口重叠时就按 z 序排，
        不主动提一下的话桌宠会被盖住。

        但每次 SetWindowPos 都会让合成器重排一次 Z 序 —— 按住鼠标拖动窗口时做这个，
        就会明显卡顿掉帧（主人反馈过）。所以这里加两道闸：
        ① 正在按住鼠标（拖窗口 / 拖文件）时什么都不做；
        ② 只有真的被另一个"置顶窗口"压住时才动，平时不白折腾。
        """
        if (not self.cfg.get("topmost", True) or not self.isVisible()
                or self.ui_open):     # 菜单/对话框开着时别抢，免得盖住设置面板
            return
        try:
            if ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000:   # 左键按着 = 正在拖
                return
        except Exception:
            pass
        try:
            GW_HWNDPREV, GWL_EXSTYLE, WS_EX_TOPMOST = 3, -20, 0x00000008
            user32 = ctypes.windll.user32
            user32.GetWindow.restype = ctypes.c_void_p
            above = user32.GetWindow(ctypes.c_void_p(int(self.winId())), GW_HWNDPREV)
            if above:
                ex = user32.GetWindowLongPtrW(ctypes.c_void_p(above), GWL_EXSTYLE)
                if not (int(ex) & WS_EX_TOPMOST):
                    return               # 上面那个不是置顶窗口 → 我们本来就是最上面的，不用动
        except Exception:
            pass
        try:
            self.raise_()          # 先把窗口抬到同类窗口最前面
        except Exception:
            pass
        try:
            SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
            ctypes.windll.user32.SetWindowPos(
                ctypes.c_void_p(int(self.winId())),
                ctypes.c_void_p(-1),          # HWND_TOPMOST（必须按指针传，直接传 -1 会被截断）
                0, 0, 0, 0,
                SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
        except Exception:
            pass

    def _apply_passthrough(self, on):
        hwnd = int(self.winId())
        GWL_EXSTYLE = -20
        style = ctypes.windll.user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        style = click_through_style(style, self.ui_open, bool(on))
        ctypes.windll.user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)

    def set_passthrough(self, on):
        self.cfg["passthrough"] = bool(on)
        self._apply_passthrough(bool(on))
        self.save_config()               # 立刻落盘，免得重启后又变回穿透状态
        if on:
            self.say("我隐身啦！右键托盘图标 → 鼠标穿透 可以解除（双击托盘图标也行）")

    def set_topmost(self, on):
        self.cfg["topmost"] = bool(on)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(on))
        self.show()

    def set_autostart(self, on):
        self.cfg["autostart"] = bool(on)
        lnk = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows",
                           "Start Menu", "Programs", "Startup", "大肥鱼桌宠.lnk")
        try:
            if on:
                ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{}');"
                      "$s.TargetPath='{}';$s.Arguments='\"{}\"';$s.WorkingDirectory='{}';$s.Save()"
                      .format(lnk, PYTHONW,
                              "" if getattr(sys, "frozen", False) else os.path.join(APP_DIR, "桌宠.py"),
                              APP_DIR))
                subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=True)
                self.say("已开机自启，明天见～")
            else:
                if os.path.exists(lnk):
                    os.remove(lnk)
                self.say("已取消开机自启")
        except Exception as ex:
            QMessageBox.warning(self, "开机自启", f"设置失败：{ex}")

    def toggle_visible(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()

    def quit_app(self):
        self._unregister_hotkeys()        # 全局快捷键要还给系统，不然退出后这个键就废了
        try:
            self.app_time_flush()         # 今天用了多久：退出前落一次盘
        except Exception:
            pass
        self.cfg["x"], self.cfg["y"] = self.x(), self.y()
        self.save_config()
        if getattr(self, "_console", None) is not None:
            try:
                self._console.close()
            except Exception:
                pass
        self.tray.hide()
        QApplication.quit()


SINGLE_INSTANCE_KEY = "dafeiyu-pet-whale-single-instance"


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    install_qt_translator(app)      # Qt 自带按钮（OK / Cancel…）显示中文
    # 滚轮别改滑块 / 下拉的值：鼠标划过去随手一滚就变了，那是误触
    if ui_console:
        ui_console.install_wheel_guard(app)
    # 窗口 / 任务栏图标：以前一个 setWindowIcon 都没有，任务栏上就是一只空白方块
    if ui_console:
        _ico = ui_console.bundle_icon(BUNDLE_DIR)
        if not _ico.isNull():
            app.setWindowIcon(_ico)

    # 单实例：已经在跑了就把那一只叫出来，不再开第二只（快捷方式 / 源码双击都一样）
    server = None
    try:
        from PySide6.QtNetwork import QLocalServer, QLocalSocket
        probe = QLocalSocket()
        probe.connectToServer(SINGLE_INSTANCE_KEY)
        if probe.waitForConnected(300):
            probe.write(b"show")
            probe.flush()
            probe.waitForBytesWritten(300)
            return 0
        QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
        server = QLocalServer()
        server.listen(SINGLE_INSTANCE_KEY)
    except Exception:
        server = None

    w = PetWindow()
    # 设置窗口里挑的强调色 / 卡片样式是"整个界面"的：这里先套一次，
    # 免得从右键菜单直接开形象库那种老对话框时用的还是默认配色。
    if ui_console:
        try:
            ui_console.set_accent(w.cfg.get("console_accent"))
            ui_console.set_card_style(w.cfg.get("console_card_alpha"),
                                      w.cfg.get("console_card_radius"))
        except Exception:
            pass

    if server is not None:
        def on_new_connection():
            sock = server.nextPendingConnection()
            if sock is not None:
                sock.disconnectFromServer()
            w.show()
            w.raise_()
            w.say("我在这儿呢，有我这只就够啦")
        server.newConnection.connect(on_new_connection)

    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        try:
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "大肥鱼桌宠出错", str(ex))
        except Exception:
            pass
        raise
