"""
NAVIS — Desktop Navigation Assistant for Visually Impaired Users
================================================================
Keys:
  R              → scan / refresh current location
  H              → go to first item (top-left of grid)
  ← →            → left / right within a row
  ↑ ↓            → up / down between rows
  Enter          → open file / enter folder (confirm twice)
  Backspace / B  → close file/folder and go back
  P              → speak current path (breadcrumb)
  W              → full position info
  V              → toggle hover mode (move mouse to hear elements)
  D              → detect element under cursor (single shot)
  F+word+Enter   → search by name
  S              → top item suggestion + top path suggestionrh
  1              → jump to top item suggestion
  2              → jump to top path suggestion
  Q              → quit
"""

import os
import time
import queue
import ctypes
import threading

import pyttsx3
from pathlib    import Path
from pynput     import mouse, keyboard
from pynput.mouse    import Controller as MouseCtrl, Button
from pynput.keyboard import Key
from pywinauto  import Desktop
# ═══════════════════════════════════════════════════════════════════
#  SPEECH ENGINE
# ═══════════════════════════════════════════════════════════════════

_sq = queue.Queue()

def _speech_worker():
    while True:
        text = _sq.get()
        if text is None:
            _sq.task_done()
            break
        try:
            e = pyttsx3.init()
            e.setProperty("rate", 160)
            e.say(text)
            e.runAndWait()
            del e
        except Exception:
            pass
        _sq.task_done()

threading.Thread(target=_speech_worker, daemon=True).start()

def speak(text: str):
    with _sq.mutex:
        _sq.queue.clear()
    _sq.put(str(text))

# ═══════════════════════════════════════════════════════════════════
#  SCREEN METRICS
# ═══════════════════════════════════════════════════════════════════

_u32   = ctypes.windll.user32
SW     = _u32.GetSystemMetrics(0)
SH     = _u32.GetSystemMetrics(1)
_mouse = MouseCtrl()

# ═══════════════════════════════════════════════════════════════════
#  NAV ITEM
# ═══════════════════════════════════════════════════════════════════

class NavItem:
    __slots__ = ("name", "x", "y", "is_dir", "path")
    def __init__(self, name, x, y, is_dir=False, path=None):
        self.name   = name
        self.x      = x
        self.y      = y
        self.is_dir = is_dir
        self.path   = path

# ═══════════════════════════════════════════════════════════════════
#  DESKTOP PATHS
# ═══════════════════════════════════════════════════════════════════

_DESKTOPS = [
    Path(os.path.expanduser("~/Desktop")),
    Path(os.environ.get("PUBLIC", "C:/Users/Public")) / "Desktop",
]

def _name_to_path(name: str) -> Path | None:
    for desk in _DESKTOPS:
        if not desk.exists():
            continue
        for entry in desk.iterdir():
            stem = entry.stem if entry.suffix else entry.name
            if stem.lower() == name.lower() or entry.name.lower() == name.lower():
                return entry
    return None

# ═══════════════════════════════════════════════════════════════════
#  ELEMENT DETECTION  (used by D key and hover mode)
#
#  Strategy:
#  1. Try UIA backend first (modern apps — Chrome, Edge, VS Code)
#  2. If element has no name, walk UP the tree up to 5 levels
#     to find a named ancestor (title bars, toolbar buttons)
#  3. If still nothing, fall back to win32 backend
#  4. Build a descriptive spoken label from what we find
# ═══════════════════════════════════════════════════════════════════

def _read_element_at(x: int, y: int) -> str:
    """
    Returns a spoken description of the UI element at (x, y).
    Never raises — always returns a string.
    """
    # ── Attempt 1: UIA backend ──────────────────────────────────
    for backend in ("uia", "win32"):
        try:
            dt   = Desktop(backend=backend)
            el   = dt.from_point(x, y)
            info = el.element_info
            name = (info.name or "").strip()
            ctrl = (info.control_type or "").strip()

            # If element has no name, walk up the tree to find one
            if not name:
                parent = el
                for _ in range(5):
                    try:
                        parent = parent.parent()
                        pinfo  = parent.element_info
                        pname  = (pinfo.name or "").strip()
                        pctrl  = (pinfo.control_type or "").strip()
                        if pname and pctrl not in ("Pane", "Window", ""):
                            name = pname
                            ctrl = pctrl
                            break
                    except Exception:
                        break

            if name:
                label = f"{name}"
                if ctrl and ctrl not in ("Unknown", ""):
                    label += f", {ctrl}"
                return label

        except Exception:
            continue

    return "No element detected here"

# ═══════════════════════════════════════════════════════════════════
#  COLLECTION
# ═══════════════════════════════════════════════════════════════════

SKIP_TYPES = {"Pane", "Window", "Unknown", ""}

def _collect_desktop() -> list:
    """UIA scan of Progman/WorkerW only — never touches Explorer windows."""
    dt   = Desktop(backend="uia")
    raw  = []
    seen = set()
    win  = None
    for cls in ("Progman", "WorkerW"):
        try:
            win = dt.window(class_name=cls)
            break
        except Exception:
            continue
    if not win:
        return raw
    try:
        kids = win.descendants()
    except Exception:
        return raw
    for el in kids:
        try:
            info = el.element_info
            name = (info.name or "").strip()
            ctrl = info.control_type or ""
            if not name or ctrl in SKIP_TYPES:
                continue
            rect = info.rectangle
            cx   = (rect.left  + rect.right)  // 2
            cy   = (rect.top   + rect.bottom) // 2
            k    = (name, cx, cy)
            if k in seen:
                continue
            seen.add(k)
            real = _name_to_path(name)
            raw.append(NavItem(name, cx, cy,
                               is_dir = real.is_dir() if real else False,
                               path   = real))
        except Exception:
            continue
    return raw

def _collect_folder(path: Path) -> list:
    items = []
    try:
        entries = sorted(path.iterdir(),
                         key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        speak("Permission denied")
        return items
    for entry in entries:
        if entry.name.startswith("."):
            continue
        items.append(NavItem(
            name   = entry.name,
            x      = SW // 2,
            y      = SH // 2,
            is_dir = entry.is_dir(),
            path   = entry,
        ))
    return items

# ═══════════════════════════════════════════════════════════════════
#  GRID BUILDER
#  Compares each item to bucket[0].y (row anchor) — prevents drift.
# ═══════════════════════════════════════════════════════════════════

ROW_TOL = 50

def _build_desktop_grid(raw: list) -> list:
    if not raw:
        return []
    raw.sort(key=lambda i: (i.y, i.x))
    rows   = []
    bucket = [raw[0]]
    for item in raw[1:]:
        if abs(item.y - bucket[0].y) <= ROW_TOL:
            bucket.append(item)
        else:
            rows.append(sorted(bucket, key=lambda i: i.x))
            bucket = [item]
    rows.append(sorted(bucket, key=lambda i: i.x))
    return rows

def _build_folder_grid(raw: list) -> list:
    return [[item] for item in raw]

# ═══════════════════════════════════════════════════════════════════
#  WHAT-TO-CLOSE STACK
#  Tracks how to close each opened window on back-press.
# ═══════════════════════════════════════════════════════════════════

_close_stack: list = []

def _push_close_folder(path: Path):
    _close_stack.append({"kind": "folder", "path": path})

def _push_close_file(path: Path):
    _close_stack.append({"kind": "file", "stem": path.stem, "name": path.name})

def _close_top():
    """Find and close the most recently opened window (file or folder)."""
    if not _close_stack:
        return
    entry = _close_stack.pop()
    kind  = entry["kind"]
    try:
        dt = Desktop(backend="uia")
        if kind == "folder":
            title = entry["path"].name
            wins  = dt.windows(class_name="CabinetWClass")
            for w in reversed(wins):
                try:
                    wname = (w.element_info.name or "").strip()
                    if title.lower() in wname.lower():
                        w.close()
                        return
                except Exception:
                    continue
            if wins:
                wins[-1].close()

        elif kind == "file":
            stem = entry["stem"].lower()
            name = entry["name"].lower()
            # All major viewers (Edge, Adobe, Word, Excel) put filename in title
            for w in dt.windows():
                try:
                    wname = (w.element_info.name or "").lower()
                    if stem in wname or name in wname:
                        w.close()
                        return
                except Exception:
                    continue
    except Exception:
        pass

# ═══════════════════════════════════════════════════════════════════
#  NAVIGATION STATE
# ═══════════════════════════════════════════════════════════════════

_grid         : list       = []
_gr           : int        = 0
_gc           : int        = 0
_lock         = threading.Lock()

_in_folder    : bool        = False
_current_path : Path | None = None

_nav_stack    : list        = []   # grid state before each open

_item_usage   : dict        = {}
_path_usage   : dict        = {}
_top_item     : str | None  = None
_top_path     : str | None  = None

_confirm_name : str | None  = None

_kb_nav       : bool                    = False
_kb_nav_timer : threading.Timer | None  = None

_searching    : bool = False
_search_buf   : str  = ""

# ── HOVER MODE ───────────────────────────────────────────────────────
# When True, moving the mouse speaks the element under the cursor.
# Debounced — only fires after cursor is still for 0.4 s.
_hover_mode   : bool                    = False
_hover_timer  : threading.Timer | None  = None
_hover_last   : str                     = ""   # last spoken label (suppress repeats)

def _toggle_hover():
    global _hover_mode, _hover_last
    _hover_mode = not _hover_mode
    _hover_last = ""
    speak("Hover mode on. Move mouse to hear elements."
          if _hover_mode else "Hover mode off.")

def _hover_detect(x: int, y: int):
    """Called after cursor settles — speaks element if it changed."""
    global _hover_last
    if not _hover_mode:
        return
    label = _read_element_at(x, y)
    if label != _hover_last:
        _hover_last = label
        speak(label)

def on_move(x, y):
    """Mouse move handler — debounced to 0.4 s of stillness."""
    global _hover_timer
    if not _hover_mode:
        return
    if _hover_timer:
        _hover_timer.cancel()
    _hover_timer = threading.Timer(0.4, _hover_detect, args=(x, y))
    _hover_timer.start()

# ─── helpers ────────────────────────────────────────────────────────

def _cur() -> NavItem | None:
    with _lock:
        if not _grid:
            return None
        r = min(_gr, len(_grid) - 1)
        c = min(_gc, len(_grid[r]) - 1)
        return _grid[r][c]

def _record_item(name: str):
    global _top_item
    _item_usage[name] = _item_usage.get(name, 0) + 1
    _top_item = max(_item_usage, key=_item_usage.__getitem__)

def _record_path(path: Path):
    global _top_path
    key = str(path)
    _path_usage[key] = _path_usage.get(key, 0) + 1
    _top_path = max(_path_usage, key=_path_usage.__getitem__)

def _move_cursor(item: NavItem):
    if _in_folder:
        _mouse.position = (SW // 2, SH // 2)
    else:
        _mouse.position = (item.x, item.y)

def _clear_kb_nav():
    global _kb_nav
    _kb_nav = False

def _set_kb_nav():
    global _kb_nav, _kb_nav_timer
    _kb_nav = True
    if _kb_nav_timer:
        _kb_nav_timer.cancel()
    _kb_nav_timer = threading.Timer(1.0, _clear_kb_nav)
    _kb_nav_timer.start()

def _breadcrumb() -> str:
    if not _in_folder or _current_path is None:
        return "Desktop"
    parts = ["Desktop"]
    try:
        rel   = _current_path.relative_to(_DESKTOPS[0])
        parts += list(rel.parts)
    except ValueError:
        parts = [_current_path.name]
    return " > ".join(parts)

# ─── load functions ─────────────────────────────────────────────────

def _load_desktop():
    """
    Scan desktop icons from UIA and rebuild the grid.
    Always resets _in_folder=False and _current_path=None.
    """
    global _grid, _gr, _gc, _in_folder, _current_path
    raw = _collect_desktop()
    g   = _build_desktop_grid(raw)
    with _lock:
        _grid         = g
        _gr           = 0
        _gc           = 0
        _in_folder    = False       # ← always forced False here
        _current_path = None        # ← always forced None here

def _load_folder(path: Path):
    """
    Load folder contents from filesystem and rebuild the grid.
    Always sets _in_folder=True and _current_path=path.
    """
    global _grid, _gr, _gc, _in_folder, _current_path
    raw = _collect_folder(path)
    g   = _build_folder_grid(raw)
    with _lock:
        _grid         = g
        _gr           = 0
        _gc           = 0
        _in_folder    = True        # ← always forced True here
        _current_path = path        # ← always set here

def _refresh():
    if _in_folder and _current_path:
        _load_folder(_current_path)
    else:
        _load_desktop()

# ═══════════════════════════════════════════════════════════════════
#  HOME  (H)
# ═══════════════════════════════════════════════════════════════════

def _go_home():
    global _gr, _gc, _confirm_name
    with _lock:
        if not _grid:
            speak("No items. Press R to scan first.")
            return
        _gr           = 0
        _gc           = 0
        _confirm_name = None
        item          = _grid[0][0]
    _move_cursor(item)
    speak(f"Home. {item.name}")

# ═══════════════════════════════════════════════════════════════════
#  ARROW KEY NAVIGATION
# ═══════════════════════════════════════════════════════════════════

def _navigate(direction: str):
    global _gr, _gc, _confirm_name

    _set_kb_nav()

    with _lock:
        if not _grid:
            speak("No items. Press R to scan.")
            return

        rows    = len(_grid)
        row_len = len(_grid[_gr])

        if direction == "right":
            if _gc < row_len - 1:
                _gc += 1
            elif _gr < rows - 1:
                _gr += 1
                _gc  = 0
            else:
                speak("End of all items")
                return

        elif direction == "left":
            if _gc > 0:
                _gc -= 1
            elif _gr > 0:
                _gr -= 1
                _gc  = len(_grid[_gr]) - 1
            else:
                speak("Start of all items")
                return

        elif direction == "down":
            if _gr < rows - 1:
                _gr += 1
                _gc  = min(_gc, len(_grid[_gr]) - 1)
            else:
                speak("Last row")
                return

        elif direction == "up":
            if _gr > 0:
                _gr -= 1
                _gc  = min(_gc, len(_grid[_gr]) - 1)
            else:
                speak("First row")
                return

        _confirm_name = None
        item          = _grid[_gr][_gc]

    _move_cursor(item)
    _record_item(item.name)
    speak(f"{item.name}, folder" if item.is_dir else item.name)

# ═══════════════════════════════════════════════════════════════════
#  POSITION AWARENESS  (W / P)
# ═══════════════════════════════════════════════════════════════════

def _where():
    with _lock:
        if not _grid:
            speak("No items. Press R to scan.")
            return
        item     = _grid[_gr][_gc]
        total    = sum(len(r) for r in _grid)
        flat_idx = sum(len(_grid[i]) for i in range(_gr)) + _gc + 1
        row_len  = len(_grid[_gr])
        rows     = len(_grid)
        crumb    = _breadcrumb()
    speak(f"{item.name}, item {flat_idx} of {total}, "
          f"row {_gr+1} of {rows}, column {_gc+1} of {row_len}. "
          f"Location: {crumb}")

def _speak_path():
    speak(_breadcrumb())

# ═══════════════════════════════════════════════════════════════════
#  ENTER — OPEN FILE OR ENTER FOLDER
# ═══════════════════════════════════════════════════════════════════

def _enter_action():
    global _confirm_name

    item = _cur()
    if not item:
        speak("No item selected. Press R then H first.")
        return

    if _confirm_name != item.name:
        _confirm_name = item.name
        speak(f"Open folder {item.name}? Press Enter again."
              if item.is_dir
              else f"Open {item.name}? Press Enter again.")
        return

    _confirm_name = None

    if item.path is None:
        _mouse.position = (item.x, item.y)
        time.sleep(0.1)
        _mouse.double_click(Button.left)
        speak(f"Opening {item.name}")
        return

    # Save current state before diving in
    _nav_stack.append({
        "path"      : _current_path,
        "gr"        : _gr,
        "gc"        : _gc,
        "in_folder" : _in_folder,    # where we ARE now (before opening)
    })

    if item.is_dir:
        _push_close_folder(item.path)
        speak(f"Opening {item.name}")
        try:
            os.startfile(str(item.path))
            time.sleep(0.6)
        except Exception:
            pass
        _load_folder(item.path)
        with _lock:
            total = sum(len(r) for r in _grid)
        speak(f"{item.name}. {total} items. Arrows to navigate, B to go back.")
    else:
        _push_close_file(item.path)
        try:
            os.startfile(str(item.path))
            speak(f"Opening {item.name}. Press B to close.")
            _record_path(item.path.parent)
        except Exception:
            speak(f"Could not open {item.name}")
            _nav_stack.pop()
            _close_stack.pop()

# ═══════════════════════════════════════════════════════════════════
#  BACK NAVIGATION  (Backspace / B)
#
#  Step 1: close the window that was opened
#  Step 2: reload the grid for where we came from
#  Step 3: restore cursor to where it was
# ═══════════════════════════════════════════════════════════════════

def _go_back():
    global _gr, _gc, _confirm_name

    if not _nav_stack:
        speak("Already at desktop")
        return

    _confirm_name = None

    # Step 1 — close opened window
    _close_top()

    # Step 2 — restore grid
    state = _nav_stack.pop()

    if not state["in_folder"]:
        # We came from the desktop
        speak("Desktop")
        _load_desktop()
    else:
        # We came from a parent folder
        speak(f"Back to {state['path'].name}")
        _load_folder(state["path"])

    # Step 3 — restore position (clamped to actual grid size)
    with _lock:
        if _grid:
            _gr  = min(state["gr"], len(_grid) - 1)
            _gc  = min(state["gc"], len(_grid[_gr]) - 1)
        else:
            _gr = 0
            _gc = 0
        item = _grid[_gr][_gc] if _grid else None

    if item:
        _move_cursor(item)
        speak(item.name)

# ═══════════════════════════════════════════════════════════════════
#  SUGGESTIONS  (S / 1 / 2)
#  S → speaks top item + top path
#  1 → jump to top item
#  2 → jump to top path
# ═══════════════════════════════════════════════════════════════════

def _speak_suggestions():
    parts = []
    parts.append(f"1: {_top_item}"       if _top_item else "No item suggestion yet")
    parts.append(f"2: {Path(_top_path).name}" if _top_path else "No path suggestion yet")
    speak(". ".join(parts))

def _jump_item():
    global _gr, _gc
    if not _top_item:
        speak("No item suggestion yet")
        return
    with _lock:
        for ri, row in enumerate(_grid):
            for ci, item in enumerate(row):
                if item.name == _top_item:
                    _gr = ri
                    _gc = ci
                    _move_cursor(item)
                    _record_item(item.name)
                    speak(f"Navigated to {_top_item}")
                    return
    speak(f"{_top_item} not in current view")

def _jump_path():
    if not _top_path:
        speak("No path suggestion yet")
        return
    path = Path(_top_path)
    if not path.exists():
        speak("That path no longer exists")
        return
    _nav_stack.append({
        "path"      : _current_path,
        "gr"        : _gr,
        "gc"        : _gc,
        "in_folder" : _in_folder,
    })
    _push_close_folder(path)
    speak(f"Jumping to {path.name}")
    try:
        os.startfile(str(path))
        time.sleep(0.6)
    except Exception:
        pass
    _load_folder(path)
    with _lock:
        total = sum(len(r) for r in _grid)
    speak(f"{path.name}. {total} items.")

# ═══════════════════════════════════════════════════════════════════
#  WORD SEARCH  (F → type → Enter)
# ═══════════════════════════════════════════════════════════════════

def _start_search():
    global _searching, _search_buf
    _searching  = True
    _search_buf = ""
    speak("Type to search, Enter to confirm, Escape to cancel")

def _commit_search(query: str):
    global _gr, _gc
    q = query.strip().lower()
    if not q:
        speak("Empty search")
        return
    with _lock:
        for ri, row in enumerate(_grid):
            for ci, item in enumerate(row):
                if item.name.lower().startswith(q):
                    _gr = ri
                    _gc = ci
                    _move_cursor(item)
                    _record_item(item.name)
                    speak(item.name)
                    return
    speak(f"No item matching {query}")

# ═══════════════════════════════════════════════════════════════════
#  SINGLE-SHOT DETECTION  (D key)
# ═══════════════════════════════════════════════════════════════════

def _detect():
    if _kb_nav:
        return
    x, y = _mouse.position
    speak(_read_element_at(x, y))

# ═══════════════════════════════════════════════════════════════════
#  CLICK FEEDBACK
# ═══════════════════════════════════════════════════════════════════

def on_click(x, y, button, pressed):
    if pressed:
        if button == Button.right:
            speak("Options menu")
    else:
        if button == Button.right:
            _bg(_quit)

# ═══════════════════════════════════════════════════════════════════
#  QUIT
# ═══════════════════════════════════════════════════════════════════

def _quit():
    speak("Exiting NAVIS")
    _sq.join()
    os._exit(0)

# ═══════════════════════════════════════════════════════════════════
#  KEYBOARD HANDLER
# ═══════════════════════════════════════════════════════════════════

def _bg(fn, *args):
    threading.Thread(target=fn, args=args, daemon=True).start()

def on_press(key):
    global _searching, _search_buf

    if _searching:
        if key == Key.enter:
            buf        = _search_buf
            _searching  = False
            _search_buf = ""
            _bg(_commit_search, buf)
        elif key == Key.backspace:
            _search_buf = _search_buf[:-1]
            speak(_search_buf if _search_buf else "empty")
        elif key == Key.esc:
            _searching  = False
            _search_buf = ""
            speak("Search cancelled")
        else:
            try:
                _search_buf += key.char
                speak(key.char)
            except AttributeError:
                pass
        return

    if key == Key.right:     _bg(_navigate, "right"); return
    if key == Key.left:      _bg(_navigate, "left");  return
    if key == Key.down:      _bg(_navigate, "down");  return
    if key == Key.up:        _bg(_navigate, "up");    return
    if key == Key.enter:     _bg(_enter_action);      return
    if key == Key.backspace: _bg(_go_back);           return

    try:
        ch = key.char
    except AttributeError:
        return

    if   ch == 'h': _bg(_go_home)
    elif ch == 'r': _bg(_refresh_announce)
    elif ch == 'w': _bg(_where)
    elif ch == 'p': _bg(_speak_path)
    elif ch == 'v': _bg(_toggle_hover)          # ← hover mode toggle
    elif ch == 'b': _bg(_go_back)
    elif ch == 'd': _bg(_detect)
    elif ch == 's': _bg(_speak_suggestions)
    elif ch == 'f': _bg(_start_search)
    elif ch == '1': _bg(_jump_item)
    elif ch == '2': _bg(_jump_path)
    elif ch == 'q': _bg(_quit)

def _refresh_announce():
    speak("Scanning")
    _refresh()
    with _lock:
        total = sum(len(r) for r in _grid)
        rows  = len(_grid)
    crumb = _breadcrumb()
    speak(f"{crumb}. {total} items in {rows} rows.")

# ═══════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════

BANNER = """
╔═══════════════════════════════════════════════════╗
║   NAVIS  —  Desktop Navigation Assistant         ║
╠═══════════════════════════════════════════════════╣
║  R              → scan / refresh                 ║
║  H              → first item (top-left)          ║
║  ← →            → move left / right              ║
║  ↑ ↓            → move up / down                 ║
║  Enter×2        → open file / enter folder       ║
║  Backspace / B  → close file/folder, go back     ║
║  V              → toggle hover mode              ║
║  D              → detect element (single shot)   ║
║  P              → speak current path             ║
║  W              → full position info             ║
║  F+word+Enter   → search by name                 ║
║  S              → top item + top path suggestion ║
║  1              → jump to top item               ║
║  2              → jump to top path               ║
║  Q              → quit                           ║
╚═══════════════════════════════════════════════════╝
"""
print(BANNER)

threading.Thread(target=_load_desktop, daemon=True).start()
speak("NAVIS ready. Press R to scan, then H for first item.")

kb_listener = keyboard.Listener(on_press=on_press)
kb_listener.daemon = True
kb_listener.start()

ms_listener = mouse.Listener(
    on_move  = on_move,     # needed for hover mode
    on_click = on_click,
)
ms_listener.daemon = True
ms_listener.start()

kb_listener.join()
ms_listener.join()