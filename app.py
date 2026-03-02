import json
import sys
import ctypes
import queue
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from pynput import keyboard


def app_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

APP_DIR = app_dir()
SEQ_FILE = APP_DIR / 'sequences.json'
STATE_FILE = APP_DIR / 'state.json'

DEFAULT_SEQ = {
    'active': 'ritual_kepala',
    'sequences': {'ritual_kepala': ['/me memebuka baju korban', '/do baju berhasil dibuka']}
}


def is_copyable(text: str) -> bool:
    t = (text or '').strip()
    return bool(t) and t.startswith('/')


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title('Tabib Macro')
        self.root.geometry('780x420')

        self.data = {}
        self.active_name = ''
        self.items = []
        self.index = 0
        self.hotkey_queue = queue.Queue()

        self._ensure_files()
        self._build_ui()
        self._load_all()

        self.root.bind('<KP_Add>', lambda e: self.next_step())
        self.root.bind('<KP_Subtract>', lambda e: self.prev_step())
        self.root.bind('<KP_Divide>', lambda e: self.reset_step())

        self.listener = keyboard.Listener(on_press=self._on_global_press)
        self.listener.daemon = True
        self.listener.start()
        self.root.after(20, self._process_hotkeys)

    def _ensure_files(self):
        if not SEQ_FILE.exists():
            SEQ_FILE.write_text(json.dumps(DEFAULT_SEQ, ensure_ascii=False, indent=2), encoding='utf-8')
        if not STATE_FILE.exists():
            STATE_FILE.write_text(json.dumps({'active': '', 'index': 0}, ensure_ascii=False, indent=2), encoding='utf-8')

    def _read_json(self, p: Path, fallback):
        try:
            return json.loads(p.read_text(encoding='utf-8-sig'))
        except Exception:
            return fallback

    def _write_json(self, p: Path, obj):
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')

    def _set_overlay_clickthrough(self):
        if sys.platform != 'win32':
            return
        try:
            self.overlay.update_idletasks()
            hwnd = self.overlay.winfo_id()
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_TOOLWINDOW = 0x00000080
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020
            exstyle = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            exstyle |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW
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

    def _apply_action(self, action: str):
        if action == 'next':
            self.next_step()
        elif action == 'prev':
            self.prev_step()
        elif action == 'reset':
            self.reset_step()

    def _process_hotkeys(self):
        for _ in range(8):
            try:
                action = self.hotkey_queue.get_nowait()
            except queue.Empty:
                break
            try:
                self._apply_action(action)
            except Exception as exc:
                self.status_var.set(f'Hotkey error: {exc}')
        self.root.after(20, self._process_hotkeys)

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill='x')

        ttk.Label(top, text='Sequence:').pack(side='left')
        self.seq_var = tk.StringVar()
        self.seq_combo = ttk.Combobox(top, textvariable=self.seq_var, state='readonly', width=40)
        self.seq_combo.pack(side='left', padx=6)
        self.seq_combo.bind('<<ComboboxSelected>>', lambda e: self.change_sequence())
        ttk.Button(top, text='Reload', command=self._load_all).pack(side='left', padx=4)

        mid = ttk.LabelFrame(self.root, text='Preview', padding=(10, 8, 10, 8))
        mid.pack(fill='both', expand=True, padx=8, pady=(2, 6))
        bg = self.root.cget('bg')

        self.prev_var = tk.StringVar(value='-')
        self.now_var = tk.StringVar(value='-')
        self.next_var = tk.StringVar(value='-')

        row_prev = ttk.Frame(mid)
        row_prev.pack(fill='x', pady=(0, 6))
        ttk.Label(row_prev, text='Prev:', width=8).pack(side='left')
        tk.Label(
            row_prev,
            textvariable=self.prev_var,
            anchor='w',
            justify='left',
            bg=bg,
            fg='#666666',
            font=('Consolas', 10),
        ).pack(side='left', fill='x', expand=True)

        row_now = ttk.Frame(mid)
        row_now.pack(fill='x', pady=(0, 6))
        ttk.Label(row_now, text='Now:', width=8).pack(side='left')
        tk.Label(
            row_now,
            textvariable=self.now_var,
            anchor='w',
            justify='left',
            bg=bg,
            fg='#1b8f3f',
            font=('Consolas', 10, 'bold'),
        ).pack(side='left', fill='x', expand=True)

        row_next = ttk.Frame(mid)
        row_next.pack(fill='both', expand=True)
        ttk.Label(row_next, text='Next:', width=8).pack(side='left', anchor='n')
        tk.Label(
            row_next,
            textvariable=self.next_var,
            anchor='nw',
            justify='left',
            bg=bg,
            fg='#222222',
            font=('Consolas', 10),
            wraplength=650,
        ).pack(side='left', fill='both', expand=True)

        ctr = ttk.Frame(self.root, padding=8)
        ctr.pack(fill='x')
        ttk.Button(ctr, text='Prev (Num -)', command=self.prev_step).pack(side='left', padx=4)
        ttk.Button(ctr, text='Next (Num +)', command=self.next_step).pack(side='left', padx=4)
        ttk.Button(ctr, text='Reset (Num /)', command=self.reset_step).pack(side='left', padx=4)

        self.status_var = tk.StringVar(value='Ready')
        ttk.Label(self.root, textvariable=self.status_var, padding=(8, 0, 8, 8)).pack(fill='x')

        self.overlay = tk.Toplevel(self.root)
        self.overlay.overrideredirect(True)
        self.overlay.attributes('-topmost', True)
        self.overlay.attributes('-alpha', 0.72)
        self.overlay.geometry('620x320+8+8')
        self.overlay.configure(bg='#111111')

        overlay_wrap = tk.Frame(self.overlay, bg='#111111')
        overlay_wrap.pack(fill='both', expand=True, padx=10, pady=10)

        prev_row = tk.Frame(overlay_wrap, bg='#111111')
        prev_row.pack(fill='x', pady=(0, 4))
        tk.Label(
            prev_row,
            text='PREV:',
            width=7,
            justify='left',
            anchor='w',
            bg='#111111',
            fg='#8f8f8f',
            font=('Consolas', 10, 'bold'),
        ).pack(side='left')
        self.overlay_prev_label = tk.Label(
            prev_row,
            textvariable=self.prev_var,
            justify='left',
            anchor='w',
            bg='#111111',
            fg='#d0d0d0',
            font=('Consolas', 10),
            wraplength=520,
        )
        self.overlay_prev_label.pack(side='left', fill='x', expand=True)

        now_row = tk.Frame(overlay_wrap, bg='#111111')
        now_row.pack(fill='x', pady=(0, 8))
        tk.Label(
            now_row,
            text='NOW:',
            width=7,
            justify='left',
            anchor='w',
            bg='#111111',
            fg='#39d353',
            font=('Consolas', 10, 'bold'),
        ).pack(side='left')
        self.overlay_now_label = tk.Label(
            now_row,
            textvariable=self.now_var,
            justify='left',
            anchor='w',
            bg='#111111',
            fg='#39d353',
            font=('Consolas', 10, 'bold'),
            wraplength=520,
        )
        self.overlay_now_label.pack(side='left', fill='x', expand=True)

        next_box = tk.Frame(overlay_wrap, bg='#111111', highlightbackground='#2f2f2f', highlightthickness=1)
        next_box.pack(fill='both', expand=True)
        tk.Label(
            next_box,
            text='NEXT (10):',
            justify='left',
            anchor='w',
            bg='#111111',
            fg='#d9d9d9',
            font=('Consolas', 10, 'bold'),
        ).pack(fill='x', padx=8, pady=(6, 2))
        self.overlay_next_label = tk.Label(
            next_box,
            textvariable=self.next_var,
            justify='left',
            anchor='nw',
            bg='#111111',
            fg='#ffffff',
            font=('Consolas', 11, 'bold'),
            wraplength=580,
        )
        self.overlay_next_label.pack(fill='both', expand=True, padx=8, pady=(0, 8))

        self.root.after(80, self._set_overlay_clickthrough)

    def _load_all(self):
        self.data = self._read_json(SEQ_FILE, DEFAULT_SEQ)
        seqs = self.data.get('sequences', {})
        if not seqs:
            self.data = DEFAULT_SEQ
            seqs = self.data['sequences']

        names = list(seqs.keys())
        st = self._read_json(STATE_FILE, {'active': '', 'index': 0})
        active = st.get('active') or self.data.get('active') or names[0]
        if active not in seqs:
            active = names[0]

        self.seq_combo['values'] = names
        self.seq_var.set(active)
        self.active_name = active
        self.items = seqs.get(active, [])
        self.index = max(0, min(int(st.get('index', 0)), len(self.items)))
        self._save_state()
        self._refresh()
        self.status_var.set(f'Loaded: {active} ({len(self.items)} steps)')

    def _save_state(self):
        self._write_json(STATE_FILE, {'active': self.active_name, 'index': self.index})

    def change_sequence(self):
        name = self.seq_var.get().strip()
        seqs = self.data.get('sequences', {})
        if name not in seqs:
            return
        self.active_name = name
        self.items = seqs[name]
        self.index = 0
        self._save_state()
        self._refresh()
        self.status_var.set(f'Switched: {name}')

    def _get(self, i: int) -> str:
        if 0 <= i < len(self.items):
            return str(self.items[i])
        return '-'

    def _copy(self, text: str):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update_idletasks()

    def _is_note(self, text: str) -> bool:
        t = (text or '').strip()
        return len(t) >= 2 and t.startswith('(') and t.endswith(')')

    def _is_me_or_do(self, text: str) -> bool:
        t = (text or '').strip().lower()
        return t.startswith('/me') or t.startswith('/do')

    def _next_lines(self, start: int, limit: int = 10):
        out = []
        prev = ''
        if 0 < start <= len(self.items):
            prev = str(self.items[start - 1]).strip()
        end = min(len(self.items), start + limit)
        for i in range(start, end):
            t = str(self.items[i]).strip()
            if not t:
                continue
            if prev and self._is_note(prev) and self._is_me_or_do(t):
                out.append('')
            out.append(t)
            prev = t
        return out

    def _refresh(self):
        prev_t = self._get(self.index - 1)
        now_t = self._get(self.index)
        next_lines = self._next_lines(self.index + 1, 10)
        next_t = '\n'.join(next_lines) if next_lines else '-'

        self.prev_var.set(prev_t)
        self.now_var.set(now_t)
        self.next_var.set(next_t)
        try:
            self.root.update_idletasks()
        except Exception:
            pass

    def next_step(self):
        if self.index >= len(self.items):
            self.status_var.set('End of sequence')
            return

        line = str(self.items[self.index]).strip()
        self.index += 1
        self._save_state()
        self._refresh()

        if is_copyable(line):
            self._copy(line)
            self.status_var.set(f'Copied {self.index}/{len(self.items)}')
        else:
            self.status_var.set(f'Note {self.index}/{len(self.items)} (not copied)')

    def prev_step(self):
        if self.index > 0:
            self.index -= 1
        self._save_state()
        self._refresh()
        self.status_var.set('Back')

    def reset_step(self):
        self.index = 0
        self._save_state()
        self._refresh()
        self.status_var.set('Reset')

    def _on_global_press(self, key):
        vk = getattr(key, 'vk', None)
        ch = getattr(key, 'char', None)
        if vk in (107, 187) or ch == '+':
            self.hotkey_queue.put('next')
        elif vk in (109, 189) or ch == '-':
            self.hotkey_queue.put('prev')
        elif vk in (111, 191) or ch == '/':
            self.hotkey_queue.put('reset')


def main():
    root = tk.Tk()
    try:
        ttk.Style(root).theme_use('vista')
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()






