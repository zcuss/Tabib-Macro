import json
import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from pynput import keyboard
from pynput.keyboard import Key, Controller

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "sequences.json")

kb = Controller()
lock = threading.Lock()

state = {
    "active": "ritual_kepala",
    "index": 0,
    "sequences": {},
    "enabled": True,
}


def load_data():
    if not os.path.exists(DATA_FILE):
        return
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    state["active"] = data.get("active", "ritual_kepala")
    state["sequences"] = data.get("sequences", {})


def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({"active": state["active"], "sequences": state["sequences"]}, f, ensure_ascii=False, indent=2)


def current_seq():
    return state["sequences"].get(state["active"], [])


def send_line(line: str):
    kb.type(line)
    kb.press(Key.enter)
    kb.release(Key.enter)


def next_step():
    with lock:
        if not state["enabled"]:
            return
        seq = current_seq()
        if not seq:
            return
        if state["index"] >= len(seq):
            state["index"] = len(seq) - 1
        line = seq[state["index"]]
        send_line(line)
        state["index"] += 1
        if state["index"] > len(seq):
            state["index"] = len(seq)
    refresh_ui()


def prev_step():
    with lock:
        if state["index"] > 0:
            state["index"] -= 1
    refresh_ui()


def reset_step():
    with lock:
        state["index"] = 0
    refresh_ui()


def set_active(name):
    with lock:
        state["active"] = name
        state["index"] = 0
        save_data()
    refresh_ui()


def toggle_enabled():
    with lock:
        state["enabled"] = not state["enabled"]
    refresh_ui()


def add_sequence():
    name = seq_name_var.get().strip()
    if not name:
        messagebox.showwarning("Warning", "Nama sequence kosong")
        return
    if name in state["sequences"]:
        messagebox.showwarning("Warning", "Nama sequence sudah ada")
        return
    state["sequences"][name] = []
    save_data()
    refresh_dropdown()
    set_active(name)


def save_editor():
    name = active_var.get().strip()
    if not name:
        return
    lines = editor.get("1.0", "end").splitlines()
    lines = [x for x in lines if x.strip()]
    state["sequences"][name] = lines
    state["active"] = name
    state["index"] = 0
    save_data()
    refresh_ui()
    messagebox.showinfo("Saved", f"Sequence '{name}' disimpan ({len(lines)} baris).")


def load_editor_from_active(*_):
    name = active_var.get()
    if name in state["sequences"]:
        set_active(name)
        editor.delete("1.0", "end")
        editor.insert("1.0", "\n".join(state["sequences"][name]))


def refresh_dropdown():
    names = sorted(state["sequences"].keys())
    active_combo["values"] = names
    if state["active"] in names:
        active_var.set(state["active"])
    elif names:
        active_var.set(names[0])


def refresh_ui():
    seq = current_seq()
    idx = state["index"]
    total = len(seq)
    status_var.set(f"Active: {state['active']} | Step: {idx}/{total} | {'ON' if state['enabled'] else 'PAUSE'}")
    if idx < total:
        next_var.set(seq[idx])
    else:
        next_var.set("(Selesai - tekan Reset)")


def on_press(key):
    try:
        if key == Key.num_lock:
            return
        # Numpad + => next send
        if hasattr(key, "vk") and key.vk == 107:
            next_step()
        # Numpad - => previous step (no send)
        elif hasattr(key, "vk") and key.vk == 109:
            prev_step()
        # Numpad * => reset step
        elif hasattr(key, "vk") and key.vk == 106:
            reset_step()
        # Numpad / => pause/resume
        elif hasattr(key, "vk") and key.vk == 111:
            toggle_enabled()
    except Exception:
        pass


load_data()
if not state["sequences"]:
    state["sequences"] = {"ritual_kepala": []}

root = tk.Tk()
root.title("Tabib Macro Stepper")
root.geometry("760x560")

status_var = tk.StringVar()
next_var = tk.StringVar()
seq_name_var = tk.StringVar()
active_var = tk.StringVar(value=state["active"])

frame_top = ttk.Frame(root, padding=10)
frame_top.pack(fill="x")

active_combo = ttk.Combobox(frame_top, textvariable=active_var, state="readonly", width=28)
active_combo.pack(side="left", padx=(0, 8))
active_combo.bind("<<ComboboxSelected>>", load_editor_from_active)

entry_new = ttk.Entry(frame_top, textvariable=seq_name_var, width=20)
entry_new.pack(side="left", padx=(0, 8))

ttk.Button(frame_top, text="Tambah Sequence", command=add_sequence).pack(side="left", padx=(0, 8))
ttk.Button(frame_top, text="Save Sequence", command=save_editor).pack(side="left")

frame_mid = ttk.Frame(root, padding=(10, 0, 10, 0))
frame_mid.pack(fill="x")

ttk.Label(frame_mid, textvariable=status_var).pack(anchor="w", pady=(6, 2))
ttk.Label(frame_mid, text="Next line:").pack(anchor="w")
ttk.Label(frame_mid, textvariable=next_var, foreground="blue").pack(anchor="w", pady=(0, 8))

ttk.Label(frame_mid, text="Hotkey: Numpad+ Next/Send | Numpad- Prev | Numpad* Reset | Numpad/ Pause").pack(anchor="w")

frame_editor = ttk.Frame(root, padding=10)
frame_editor.pack(fill="both", expand=True)

editor = tk.Text(frame_editor, wrap="word")
editor.pack(fill="both", expand=True)

refresh_dropdown()
load_editor_from_active()
refresh_ui()

listener = keyboard.Listener(on_press=on_press)
listener.daemon = True
listener.start()

root.mainloop()
