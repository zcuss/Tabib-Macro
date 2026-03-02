import ctypes
import json
import queue
import sys
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


def is_copyable(text: str) -> bool:
    t = (text or "").strip()
    return bool(t) and t.startswith("/")


def is_note(text: str) -> bool:
    t = (text or "").strip()
    return len(t) >= 2 and t.startswith("(") and t.endswith(")")


def is_me_or_do(text: str) -> bool:
    t = (text or "").strip().lower()
    return t.startswith("/me") or t.startswith("/do")


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Tabib Macro")
        self.root.geometry("780x420")

        self.data = {}
        self.active_name = ""
        self.items = []
        self.index = 0

        self.action_queue = queue.Queue()
        self.listener = None
        self.overlay_hwnd = 0

        self.prev_var = tk.StringVar(value="-")
        self.now_var = tk.StringVar(value="-")
        self.next_var = tk.StringVar(value="-")
        self.status_var = tk.StringVar(value="Ready")
        self.seq_var = tk.StringVar()
        self.overlay_prev_text = "-"
        self.overlay_now_text = "-"
        self.overlay_next_text = "-"

        self._ensure_files()
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
        self.root.after(250, self._set_overlay_clickthrough)
        self.root.after(1200, self._set_overlay_clickthrough)
        self.root.after(120, self._overlay_keepalive)

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

    def _build_main_ui(self):
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")

        ttk.Label(top, text="Sequence:").pack(side="left")
        self.seq_combo = ttk.Combobox(
            top, textvariable=self.seq_var, state="readonly", width=40
        )
        self.seq_combo.pack(side="left", padx=6)
        self.seq_combo.bind("<<ComboboxSelected>>", lambda e: self.change_sequence())
        ttk.Button(top, text="Reload", command=self._load_all).pack(side="left", padx=4)

        mid = ttk.LabelFrame(self.root, text="Preview", padding=(10, 8, 10, 8))
        mid.pack(fill="both", expand=True, padx=8, pady=(2, 6))
        bg = self.root.cget("bg")

        row_prev = ttk.Frame(mid)
        row_prev.pack(fill="x", pady=(0, 6))
        ttk.Label(row_prev, text="Prev:", width=8).pack(side="left")
        tk.Label(
            row_prev,
            textvariable=self.prev_var,
            anchor="w",
            justify="left",
            bg=bg,
            fg="#666666",
            font=("Consolas", 10),
        ).pack(side="left", fill="x", expand=True)

        row_now = ttk.Frame(mid)
        row_now.pack(fill="x", pady=(0, 6))
        ttk.Label(row_now, text="Now:", width=8).pack(side="left")
        tk.Label(
            row_now,
            textvariable=self.now_var,
            anchor="w",
            justify="left",
            bg=bg,
            fg="#1b8f3f",
            font=("Consolas", 10, "bold"),
        ).pack(side="left", fill="x", expand=True)

        row_next = ttk.Frame(mid)
        row_next.pack(fill="both", expand=True)
        ttk.Label(row_next, text="Next:", width=8).pack(side="left", anchor="n")
        tk.Label(
            row_next,
            textvariable=self.next_var,
            anchor="nw",
            justify="left",
            bg=bg,
            fg="#222222",
            font=("Consolas", 10),
            wraplength=650,
        ).pack(side="left", fill="both", expand=True)

        ctr = ttk.Frame(self.root, padding=8)
        ctr.pack(fill="x")
        ttk.Button(ctr, text="Prev (Num -)", command=lambda: self._enqueue_action("prev")).pack(
            side="left", padx=4
        )
        ttk.Button(ctr, text="Next (Num +)", command=lambda: self._enqueue_action("next")).pack(
            side="left", padx=4
        )
        ttk.Button(ctr, text="Reset (Num /)", command=lambda: self._enqueue_action("reset")).pack(
            side="left", padx=4
        )

        ttk.Label(self.root, textvariable=self.status_var, padding=(8, 0, 8, 8)).pack(
            fill="x"
        )

    def _build_overlay_ui(self):
        self.overlay = tk.Toplevel(self.root)
        self.overlay.overrideredirect(True)
        self.overlay.attributes("-topmost", True)
        self.overlay.geometry("620x320+8+8")
        self.overlay.configure(bg="#111111")

        wrap = tk.Frame(self.overlay, bg="#111111")
        wrap.pack(fill="both", expand=True, padx=10, pady=10)

        prev_row = tk.Frame(wrap, bg="#111111")
        prev_row.pack(fill="x", pady=(0, 4))
        tk.Label(
            prev_row,
            text="PREV:",
            width=7,
            justify="left",
            anchor="w",
            bg="#111111",
            fg="#8f8f8f",
            font=("Consolas", 10, "bold"),
        ).pack(side="left")
        self.overlay_prev_label = tk.Label(
            prev_row,
            text="-",
            justify="left",
            anchor="w",
            bg="#111111",
            fg="#d0d0d0",
            font=("Consolas", 10),
            wraplength=520,
        )
        self.overlay_prev_label.pack(side="left", fill="x", expand=True)

        now_row = tk.Frame(wrap, bg="#111111")
        now_row.pack(fill="x", pady=(0, 8))
        tk.Label(
            now_row,
            text="NOW:",
            width=7,
            justify="left",
            anchor="w",
            bg="#111111",
            fg="#39d353",
            font=("Consolas", 10, "bold"),
        ).pack(side="left")
        self.overlay_now_label = tk.Label(
            now_row,
            text="-",
            justify="left",
            anchor="w",
            bg="#111111",
            fg="#39d353",
            font=("Consolas", 10, "bold"),
            wraplength=520,
        )
        self.overlay_now_label.pack(side="left", fill="x", expand=True)

        next_box = tk.Frame(wrap, bg="#111111", highlightbackground="#2f2f2f", highlightthickness=1)
        next_box.pack(fill="both", expand=True)
        tk.Label(
            next_box,
            text="NEXT (10):",
            justify="left",
            anchor="w",
            bg="#111111",
            fg="#d9d9d9",
            font=("Consolas", 10, "bold"),
        ).pack(fill="x", padx=8, pady=(6, 2))
        self.overlay_next_label = tk.Label(
            next_box,
            text="-",
            justify="left",
            anchor="nw",
            bg="#111111",
            fg="#ffffff",
            font=("Consolas", 11, "bold"),
            wraplength=580,
        )
        self.overlay_next_label.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _set_overlay_clickthrough(self):
        if sys.platform != "win32":
            return
        self._set_overlay_clickthrough_enabled(True)

    def _set_overlay_clickthrough_enabled(self, enabled: bool):
        if sys.platform != "win32":
            return
        try:
            self.overlay.update_idletasks()
            hwnd = self.overlay.winfo_id()
            self.overlay_hwnd = hwnd
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_TOOLWINDOW = 0x00000080
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020

            exstyle = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            exstyle |= WS_EX_TOOLWINDOW
            if enabled:
                exstyle |= WS_EX_TRANSPARENT
            else:
                exstyle &= ~WS_EX_TRANSPARENT
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, exstyle)
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

    def _refresh_overlay(self):
        try:
            self.overlay_prev_text = self.prev_var.get() or "-"
            self.overlay_now_text = self.now_var.get() or "-"
            self.overlay_next_text = self.next_var.get() or "-"
            self.overlay_prev_label.config(text=self.overlay_prev_text)
            self.overlay_now_label.config(text=self.overlay_now_text)
            self.overlay_next_label.config(text=self.overlay_next_text)
            self.overlay.deiconify()
            self.overlay.lift()
            self.overlay.attributes("-topmost", True)
        except Exception:
            return
        self.overlay.update_idletasks()

    def _overlay_keepalive(self):
        self._refresh_overlay()
        self.root.after(120, self._overlay_keepalive)

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
    root = tk.Tk()
    try:
        ttk.Style(root).theme_use("vista")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
