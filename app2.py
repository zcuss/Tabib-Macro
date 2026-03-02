import ctypes
import json
import queue
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from pynput import keyboard


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_DIR = app_dir()
SEQ_FILE = APP_DIR / "sequences.json"
STATE_FILE = APP_DIR / "state.json"

DEFAULT_DATA = {
    "active": "ritual_kepala",
    "sequences": {
        "ritual_kepala": ["/me memebuka baju korban", "/do baju berhasil dibuka"]
    },
}

MUTEX_NAME = "Global\\TabibMacro2SingleInstance"


def is_copyable(text: str) -> bool:
    t = (text or "").strip()
    return bool(t) and t.startswith("/")


def is_note(text: str) -> bool:
    t = (text or "").strip()
    return len(t) >= 2 and t.startswith("(") and t.endswith(")")


def is_me_or_do(text: str) -> bool:
    t = (text or "").strip().lower()
    return t.startswith("/me") or t.startswith("/do")


def _acquire_single_instance_mutex():
    if sys.platform != "win32":
        return None
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return None
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return None
    return handle


def _release_single_instance_mutex(handle):
    if sys.platform == "win32" and handle:
        ctypes.windll.kernel32.CloseHandle(handle)


def _close_stale_tabib_windows():
    if sys.platform != "win32":
        return
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    WM_CLOSE = 0x0010
    titles = {"Tabib Macro", "Tabib Macro Stepper"}
    current_pid = kernel32.GetCurrentProcessId()

    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    @EnumProc
    def _enum_proc(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = (buf.value or "").strip()
        if title not in titles:
            return True
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value and pid.value != current_pid:
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        return True

    user32.EnumWindows(_enum_proc, 0)
    time.sleep(0.15)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Tabib Macro")
        self.root.geometry("900x540")
        self.root.minsize(860, 500)
        self.overlay_alpha = 0.62
        self.overlay_key_color = "#ff00ff"
        self.main_bg = "#f3f6fb"
        self.panel_bg = "#ffffff"
        self.text_primary = "#1e293b"
        self.text_muted = "#64748b"
        self.accent = "#0f766e"
        self.accent_soft = "#14b8a6"
        self.border = "#dbe3ef"
        self.overlay_bg = "#000000"
        self.overlay_panel = "#000000"
        self.overlay_border = "#2a2a2a"
        self.overlay_text = "#e2e8f0"
        self.overlay_muted = "#94a3b8"
        self.overlay_now = "#34d399"

        self.data = {}
        self.active_name = ""
        self.items = []
        self.index = 0

        self.action_queue = queue.Queue()
        self.listener = None
        self.overlay_hwnd = 0
        self.move_mode = False
        self.drag_anchor = None

        self.prev_var = tk.StringVar(value="-")
        self.now_var = tk.StringVar(value="-")
        self.next_var = tk.StringVar(value="-")
        self.status_var = tk.StringVar(value="Ready")
        self.seq_var = tk.StringVar()
        self.overlay_prev_text = "-"
        self.overlay_now_text = "-"
        self.overlay_next_text = "-"

        self._ensure_files()
        self._init_styles()
        self._build_main_ui()
        self._build_overlay_ui()
        self._load_all()

        self.root.bind("<KP_Add>", lambda e: self._enqueue_action("next"))
        self.root.bind("<KP_Subtract>", lambda e: self._enqueue_action("prev"))
        self.root.bind("<KP_Divide>", lambda e: self._enqueue_action("reset"))
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.listener = keyboard.Listener(on_press=self._on_global_press)
        self.listener.daemon = True
        self.listener.start()

        self.root.after(15, self._drain_actions)

    def _ensure_files(self):
        if not SEQ_FILE.exists():
            SEQ_FILE.write_text(
                json.dumps(DEFAULT_DATA, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        if not STATE_FILE.exists():
            STATE_FILE.write_text(
                json.dumps({"active": "", "index": 0}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _read_json(self, path: Path, fallback):
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            return fallback

    def _write_json(self, path: Path, obj):
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

    def _init_styles(self):
        self.root.configure(bg=self.main_bg)
        style = ttk.Style(self.root)
        try:
            style.theme_use("vista")
        except Exception:
            pass

        style.configure("Root.TFrame", background=self.main_bg)
        style.configure("Panel.TFrame", background=self.panel_bg, relief="flat")
        style.configure("Soft.TLabel", background=self.main_bg, foreground=self.text_muted, font=("Segoe UI", 10))
        style.configure("Body.TLabel", background=self.panel_bg, foreground=self.text_primary, font=("Segoe UI", 10))
        style.configure("Title.TLabel", background=self.main_bg, foreground=self.text_primary, font=("Segoe UI Semibold", 16))
        style.configure("Subtitle.TLabel", background=self.main_bg, foreground=self.text_muted, font=("Segoe UI", 10))
        style.configure("Card.TLabelframe", background=self.panel_bg, bordercolor=self.border, relief="solid")
        style.configure("Card.TLabelframe.Label", background=self.panel_bg, foreground=self.text_muted, font=("Segoe UI Semibold", 9))
        style.configure("Main.TButton", font=("Segoe UI Semibold", 10), padding=(10, 6))
        style.configure("Warn.TButton", font=("Segoe UI Semibold", 10), padding=(10, 6))

    def _build_main_ui(self):
        shell = ttk.Frame(self.root, style="Root.TFrame", padding=(14, 14, 14, 12))
        shell.pack(fill="both", expand=True)

        header = ttk.Frame(shell, style="Root.TFrame")
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text="Tabib Macro Control", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Hotkey: Numpad + = Next, Numpad - = Prev, Numpad / = Reset",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        top = ttk.Frame(shell, style="Panel.TFrame", padding=(12, 10, 12, 10))
        top.pack(fill="x", pady=(0, 10))
        ttk.Label(top, text="Sequence", style="Body.TLabel").pack(side="left")
        self.seq_combo = ttk.Combobox(top, textvariable=self.seq_var, state="readonly", width=42)
        self.seq_combo.pack(side="left", padx=8)
        self.seq_combo.bind("<<ComboboxSelected>>", lambda e: self.change_sequence())
        ttk.Button(top, text="Reload", style="Main.TButton", command=self._load_all).pack(side="left")

        mid = ttk.LabelFrame(shell, text="Preview", style="Card.TLabelframe", padding=(12, 10, 12, 10))
        mid.pack(fill="both", expand=True)
        bg = self.panel_bg

        row_prev = ttk.Frame(mid, style="Panel.TFrame")
        row_prev.pack(fill="x", pady=(0, 8))
        ttk.Label(row_prev, text="Prev", width=8, style="Body.TLabel").pack(side="left")
        tk.Label(
            row_prev,
            textvariable=self.prev_var,
            anchor="w",
            justify="left",
            bg=bg,
            fg=self.text_muted,
            font=("Consolas", 10),
        ).pack(side="left", fill="x", expand=True)

        row_now = ttk.Frame(mid, style="Panel.TFrame")
        row_now.pack(fill="x", pady=(0, 8))
        ttk.Label(row_now, text="Now", width=8, style="Body.TLabel").pack(side="left")
        tk.Label(
            row_now,
            textvariable=self.now_var,
            anchor="w",
            justify="left",
            bg=bg,
            fg=self.accent,
            font=("Consolas", 10, "bold"),
        ).pack(side="left", fill="x", expand=True)

        row_next = ttk.Frame(mid, style="Panel.TFrame")
        row_next.pack(fill="both", expand=True)
        ttk.Label(row_next, text="Next", width=8, style="Body.TLabel").pack(side="left", anchor="n")
        tk.Label(
            row_next,
            textvariable=self.next_var,
            anchor="nw",
            justify="left",
            bg=bg,
            fg=self.text_primary,
            font=("Consolas", 10),
            wraplength=760,
        ).pack(side="left", fill="both", expand=True)

        ctr = ttk.Frame(shell, style="Root.TFrame", padding=(0, 10, 0, 6))
        ctr.pack(fill="x")
        ttk.Button(ctr, text="Prev (Num -)", style="Main.TButton", command=lambda: self._enqueue_action("prev")).pack(side="left")
        ttk.Button(ctr, text="Next (Num +)", style="Main.TButton", command=lambda: self._enqueue_action("next")).pack(side="left", padx=8)
        ttk.Button(ctr, text="Reset (Num /)", style="Main.TButton", command=lambda: self._enqueue_action("reset")).pack(side="left")
        self.move_btn = ttk.Button(ctr, text="Move Mini GUI", style="Warn.TButton", command=self._toggle_move_mode)
        self.move_btn.pack(side="left", padx=(12, 0))

        status_wrap = ttk.Frame(shell, style="Panel.TFrame", padding=(10, 8, 10, 8))
        status_wrap.pack(fill="x", pady=(4, 0))
        ttk.Label(status_wrap, textvariable=self.status_var, style="Body.TLabel").pack(anchor="w")

    def _build_overlay_ui(self):
        self.overlay = tk.Toplevel(self.root)
        self.overlay.withdraw()
        self.overlay.overrideredirect(True)
        self.overlay.attributes("-topmost", True)
        self.overlay.attributes("-alpha", self.overlay_alpha)
        self.overlay.geometry("620x320+8+8")
        self.overlay.configure(bg=self.overlay_bg)

        wrap = tk.Frame(
            self.overlay,
            bg=self.overlay_bg,
            highlightbackground=self.overlay_border,
            highlightthickness=1,
        )
        wrap.pack(fill="both", expand=True, padx=10, pady=10)

        prev_row = tk.Frame(wrap, bg=self.overlay_bg)
        prev_row.pack(fill="x", pady=(10, 4), padx=10)
        tk.Label(
            prev_row,
            text="PREV:",
            width=7,
            justify="left",
            anchor="w",
            bg=self.overlay_bg,
            fg=self.overlay_muted,
            font=("Consolas", 10),
        ).pack(side="left")
        self.overlay_prev_label = tk.Label(
            prev_row,
            text="-",
            justify="left",
            anchor="w",
            bg=self.overlay_bg,
            fg=self.overlay_text,
            font=("Consolas", 10),
            wraplength=520,
        )
        self.overlay_prev_label.pack(side="left", fill="x", expand=True)

        now_row = tk.Frame(wrap, bg=self.overlay_bg)
        now_row.pack(fill="x", pady=(0, 8), padx=10)
        tk.Label(
            now_row,
            text="NOW:",
            width=7,
            justify="left",
            anchor="w",
            bg=self.overlay_bg,
            fg=self.overlay_now,
            font=("Consolas", 10, "bold"),
        ).pack(side="left")
        self.overlay_now_label = tk.Label(
            now_row,
            text="-",
            justify="left",
            anchor="w",
            bg=self.overlay_bg,
            fg=self.overlay_now,
            font=("Consolas", 10, "bold"),
            wraplength=520,
        )
        self.overlay_now_label.pack(side="left", fill="x", expand=True)

        next_box = tk.Frame(
            wrap,
            bg=self.overlay_panel,
            highlightbackground=self.overlay_border,
            highlightthickness=1,
        )
        next_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        tk.Label(
            next_box,
            text="NEXT (10):",
            justify="left",
            anchor="w",
            bg=self.overlay_panel,
            fg=self.overlay_text,
            font=("Consolas", 10, "bold"),
        ).pack(fill="x", padx=10, pady=(8, 3))
        self.overlay_next_label = tk.Label(
            next_box,
            text="-",
            justify="left",
            anchor="nw",
            bg=self.overlay_panel,
            fg="#f8fafc",
            font=("Consolas", 11),
            wraplength=580,
        )
        self.overlay_next_label.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self._bind_overlay_drag(self.overlay)
        self._bind_overlay_drag(wrap)
        self._bind_overlay_drag(prev_row)
        self._bind_overlay_drag(now_row)
        self._bind_overlay_drag(next_box)
        self._bind_overlay_drag(self.overlay_prev_label)
        self._bind_overlay_drag(self.overlay_now_label)
        self._bind_overlay_drag(self.overlay_next_label)

        self.overlay.update_idletasks()
        if sys.platform == "win32":
            self._set_overlay_clickthrough_enabled(True)
        self.overlay.deiconify()

    def _set_overlay_clickthrough(self):
        if sys.platform != "win32":
            return
        self._set_overlay_clickthrough_enabled(True)

    def _get_overlay_top_hwnd(self):
        if sys.platform != "win32":
            return 0
        try:
            child = int(self.overlay.winfo_id())
        except Exception:
            return 0
        user32 = ctypes.windll.user32
        top = user32.GetParent(child)
        return int(top) if top else child

    def _set_overlay_clickthrough_enabled(self, enabled: bool):
        if sys.platform != "win32":
            return
        try:
            self.overlay.update_idletasks()
            hwnd = self._get_overlay_top_hwnd()
            if not hwnd:
                return
            self.overlay_hwnd = hwnd
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_NOACTIVATE = 0x08000000
            LWA_ALPHA = 0x00000002
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020

            exstyle = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            exstyle |= WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
            if enabled:
                exstyle |= WS_EX_TRANSPARENT
            else:
                exstyle &= ~WS_EX_TRANSPARENT
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, exstyle)
            alpha_byte = max(64, min(255, int(self.overlay_alpha * 255)))
            ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, alpha_byte, LWA_ALPHA)
            ctypes.windll.user32.SetWindowPos(
                hwnd,
                0,
                0,
                0,
                0,
                0,
                SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
            )
        except Exception:
            pass

    def _bind_overlay_drag(self, widget):
        widget.bind("<ButtonPress-1>", self._on_overlay_drag_start, add="+")
        widget.bind("<B1-Motion>", self._on_overlay_drag_move, add="+")

    def _on_overlay_drag_start(self, event):
        if not self.move_mode:
            return
        self.drag_anchor = (event.x_root, event.y_root, self.overlay.winfo_x(), self.overlay.winfo_y())

    def _on_overlay_drag_move(self, event):
        if not self.move_mode or not self.drag_anchor:
            return
        ax, ay, ox, oy = self.drag_anchor
        nx = ox + (event.x_root - ax)
        ny = oy + (event.y_root - ay)
        self.overlay.geometry(f"+{nx}+{ny}")

    def _toggle_move_mode(self):
        self.move_mode = not self.move_mode
        self.drag_anchor = None
        if self.move_mode:
            self.move_btn.config(text="Lock Mini GUI")
            self.status_var.set("Move mode ON: drag mini GUI, lalu klik Lock Mini GUI")
            if sys.platform == "win32":
                self._set_overlay_clickthrough_enabled(False)
            self.overlay.config(cursor="fleur")
            self.overlay.lift()
        else:
            self.move_btn.config(text="Move Mini GUI")
            self.status_var.set("Move mode OFF")
            if sys.platform == "win32":
                self._set_overlay_clickthrough_enabled(True)
            self.overlay.config(cursor="")

    def _refresh_overlay(self):
        try:
            self.overlay_prev_text = self.prev_var.get() or "-"
            self.overlay_now_text = self.now_var.get() or "-"
            self.overlay_next_text = self.next_var.get() or "-"
            self.overlay_prev_label.config(text=self.overlay_prev_text)
            self.overlay_now_label.config(text=self.overlay_now_text)
            self.overlay_next_label.config(text=self.overlay_next_text)
            if self.overlay.state() == "withdrawn":
                self.overlay.deiconify()
        except Exception:
            return
        self.overlay.update_idletasks()

    def _load_all(self):
        self.data = self._read_json(SEQ_FILE, DEFAULT_DATA)
        seqs = self.data.get("sequences", {})
        if not seqs:
            self.data = DEFAULT_DATA
            seqs = self.data["sequences"]

        names = list(seqs.keys())
        state = self._read_json(STATE_FILE, {"active": "", "index": 0})
        active = state.get("active") or self.data.get("active") or names[0]
        if active not in seqs:
            active = names[0]

        self.seq_combo["values"] = names
        self.seq_var.set(active)
        self.active_name = active
        self.items = seqs.get(active, [])
        self.index = max(0, min(int(state.get("index", 0)), len(self.items)))
        self._save_state()
        self._refresh()
        self.status_var.set(f"Loaded: {active} ({len(self.items)} steps)")

    def _save_state(self):
        self._write_json(STATE_FILE, {"active": self.active_name, "index": self.index})

    def change_sequence(self):
        name = self.seq_var.get().strip()
        seqs = self.data.get("sequences", {})
        if name not in seqs:
            return
        self.active_name = name
        self.items = seqs[name]
        self.index = 0
        self._save_state()
        self._refresh()
        self.status_var.set(f"Switched: {name}")

    def _raw(self, i: int) -> str:
        if 0 <= i < len(self.items):
            return str(self.items[i]).strip()
        return ""

    def _display(self, i: int) -> str:
        t = self._raw(i)
        return t if t else "-"

    def _copy(self, text: str):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update_idletasks()

    def _next_lines(self, start: int, limit: int = 10):
        out = []
        prev = self._raw(start - 1) if start > 0 else ""
        end = min(len(self.items), start + limit)
        for i in range(start, end):
            t = self._raw(i)
            if not t:
                continue
            if prev and is_note(prev) and is_me_or_do(t):
                out.append("")
            out.append(t)
            prev = t
        return out

    def _refresh(self):
        self.prev_var.set(self._display(self.index - 1))
        self.now_var.set(self._display(self.index))
        nxt = self._next_lines(self.index + 1, 10)
        self.next_var.set("\n".join(nxt) if nxt else "-")
        self.root.update_idletasks()
        self._refresh_overlay()

    def next_step(self):
        if self.index >= len(self.items):
            self.status_var.set("End of sequence")
            return

        line = self._raw(self.index)
        self.index += 1
        self._save_state()
        self._refresh()

        if is_copyable(line):
            self._copy(line)
            self.status_var.set(f"Copied {self.index}/{len(self.items)}")
        else:
            self.status_var.set(f"Note {self.index}/{len(self.items)} (not copied)")

    def prev_step(self):
        if self.index > 0:
            self.index -= 1
        self._save_state()
        self._refresh()
        self.status_var.set("Back")

    def reset_step(self):
        self.index = 0
        self._save_state()
        self._refresh()
        self.status_var.set("Reset")

    def _enqueue_action(self, action: str):
        self.action_queue.put(action)

    def _apply_action(self, action: str):
        if action == "next":
            self.next_step()
        elif action == "prev":
            self.prev_step()
        elif action == "reset":
            self.reset_step()

    def _drain_actions(self):
        for _ in range(8):
            try:
                action = self.action_queue.get_nowait()
            except queue.Empty:
                break
            try:
                self._apply_action(action)
            except Exception as exc:
                self.status_var.set(f"Hotkey error: {exc}")
        self.root.after(15, self._drain_actions)

    def _on_global_press(self, key):
        vk = getattr(key, "vk", None)
        if vk == 107:  # Numpad +
            self._enqueue_action("next")
        elif vk == 109:  # Numpad -
            self._enqueue_action("prev")
        elif vk == 111:  # Numpad /
            self._enqueue_action("reset")

    def _on_close(self):
        try:
            if self.listener is not None:
                self.listener.stop()
        except Exception:
            pass
        try:
            self.overlay.destroy()
        except Exception:
            pass
        self.root.destroy()


def main():
    _close_stale_tabib_windows()
    mutex = _acquire_single_instance_mutex()
    if sys.platform == "win32" and not mutex:
        ctypes.windll.user32.MessageBoxW(
            0,
            "Aplikasi sudah berjalan.\nTutup instance lama dulu.",
            "Tabib Macro",
            0x00000030,
        )
        return
    root = tk.Tk()
    try:
        ttk.Style(root).theme_use("vista")
    except Exception:
        pass
    try:
        App(root)
        root.mainloop()
    finally:
        _release_single_instance_mutex(mutex)


if __name__ == "__main__":
    main()
