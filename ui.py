"""Explicit-color desktop primitives for the approved macOS utility design.

Classic Tk labels avoid Aqua button background overrides. Controls remain
keyboard reachable; all drawing is vector Canvas work, without bundled fonts.
"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk

DARK = dict(window="#202124", sidebar="#26272b", raised="#2c2e33", panel="#242529",
            text="#f2f3f5", secondary="#b4b6bd", line="#41444b", accent="#80bcff",
            selected="#344a65", success="#82dfa2", warning="#ffd17c", info="#28313e",
            button="#3b3e45", on_primary="#14263b")
LIGHT = dict(window="#fafafa", sidebar="#eff0f2", raised="#eceef1", panel="#f4f5f7",
             text="#202329", secondary="#59616d", line="#c5c9cf", accent="#145ca5",
             selected="#dbe9fa", success="#21683e", warning="#835106", info="#e8eef6",
             button="#e4e7ec", on_primary="#ffffff")
FONT = "Helvetica Neue"


class UI:
    def __init__(self, theme="dark"):
        self.colors = LIGHT if theme == "light" else DARK

    def frame(self, parent, role="window", **options):
        return tk.Frame(parent, bg=self.colors[role], **options)

    def label(self, parent, text="", size=12, weight="normal", role="text", surface="window", **options):
        options = {"borderwidth": 0, "padx": 0, "pady": 0, **options}
        return tk.Label(parent, text=text, font=(FONT, size, weight), fg=self.colors[role],
                        bg=self.colors[surface], anchor="w", justify="left", **options)

    def button(self, parent, text, action, *, surface="button", role="text", icon=None, **options):
        return Control(parent, self, text, action, surface, role, icon=icon, **options)

    def entry(self, parent, variable, width=24):
        c = self.colors
        return tk.Entry(parent, textvariable=variable, font=(FONT, 12), width=width,
                        bg=c["raised"], fg=c["text"], insertbackground=c["accent"],
                        selectbackground=c["selected"], selectforeground=c["text"],
                        disabledbackground=c["raised"], disabledforeground=c["secondary"],
                        highlightbackground=c["line"], highlightcolor=c["accent"],
                        highlightthickness=2, relief="flat", borderwidth=4)

    def text(self, parent, height=10, surface="panel"):
        c = self.colors
        text = tk.Text(parent, font=(FONT, 12), bg=c[surface], fg=c["text"],
                       insertbackground=c["accent"], selectbackground=c["selected"],
                       selectforeground=c["text"], highlightbackground=c["line"],
                       highlightcolor=c["accent"], highlightthickness=1, relief="flat",
                       borderwidth=0, padx=12, pady=10, height=height, width=20,
                       wrap="word", cursor="arrow", takefocus=True)
        text.tag_configure("heading", foreground=c["text"], font=(FONT, 12, "bold"), spacing1=8, spacing3=4)
        text.tag_configure("muted", foreground=c["secondary"])
        text.tag_configure("warning", foreground=c["warning"])
        return text

    def tree_style(self, root):
        c = self.colors
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("Tracker.Treeview", background=c["panel"], fieldbackground=c["panel"],
                        foreground=c["text"], bordercolor=c["line"], lightcolor=c["line"],
                        darkcolor=c["line"], rowheight=32, font=(FONT, 12))
        style.map("Tracker.Treeview", background=[("selected", c["selected"])],
                  foreground=[("selected", c["text"])])
        style.configure("Tracker.Treeview.Heading", background=c["raised"], foreground=c["secondary"],
                        font=(FONT, 11), relief="flat", padding=6)
        style.map("Tracker.Treeview.Heading", background=[("active", c["button"])])


class Control(tk.Frame):
    """Focusable control with explicit hover/selected/disabled appearance."""
    def __init__(self, parent, ui, text, action, surface, role, icon=None, padx=10, pady=6):
        self.ui, self.action, self.surface, self.role = ui, action, surface, role
        self.enabled = True
        c = ui.colors
        super().__init__(parent, bg=c[surface], padx=padx, pady=pady, cursor="hand2", takefocus=True,
                         highlightthickness=2, highlightbackground=c[surface], highlightcolor=c["accent"])
        self.icon = Icon(self, icon, c[surface], c[role]) if icon else None
        if self.icon:
            self.icon.pack(side="left", padx=(0, 8))
        self.label = ui.label(self, text, role=role, surface=surface)
        self.label.pack(side="left", fill="x", expand=True)
        for child in (self, self.label, self.icon):
            if child:
                child.bind("<Button-1>", self._activate)
                child.bind("<Enter>", lambda event: self._paint("raised"))
                child.bind("<Leave>", lambda event: self._paint(self.surface))
        self.bind("<Return>", self._activate)
        self.bind("<space>", self._activate)

    def _activate(self, event=None):
        if self.enabled:
            self.focus_set()
            self.action()
        return "break"

    def invoke(self):
        return self._activate()

    def _paint(self, surface):
        color = self.ui.colors[surface]
        self.configure(bg=color, highlightbackground=color)
        self.label.configure(bg=color)
        if self.icon:
            self.icon.configure(bg=color)

    def set_text(self, text):
        self.label.configure(text=text)

    def set_selected(self, selected):
        self.surface = "selected" if selected else "sidebar"
        self.label.configure(fg=self.ui.colors["text" if selected else "secondary"])
        self._paint(self.surface)


class Icon(tk.Canvas):
    """Authored stroke icons, kept decorative beside a visible control label."""
    def __init__(self, parent, kind, background, color):
        super().__init__(parent, width=18, height=18, bg=background, highlightthickness=0)
        line = lambda *points: self.create_line(*points, fill=color, width=1.5, capstyle="round", joinstyle="round")
        if kind == "live":
            self.create_rectangle(2, 3, 16, 15, outline=color, width=1.5)
            line(5, 7, 13, 7); line(5, 11, 10, 11)
        elif kind == "history":
            self.create_oval(3, 3, 16, 16, outline=color, width=1.5)
            line(9, 5, 9, 10, 12, 12); line(1, 3, 1, 7, 5, 7)
        elif kind == "reference":
            line(2, 3, 8, 4, 9, 6, 10, 4, 16, 3, 16, 15, 10, 16, 9, 17, 8, 16, 2, 15, 2, 3)
            line(9, 6, 9, 16)
        elif kind == "settings":
            for y, x in ((4, 6), (9, 12), (14, 8)):
                line(2, y, 16, y); line(x, y-2, x, y+2)
        elif kind == "chevron":
            line(6, 4, 12, 9, 6, 14)


class ScrollArea(tk.Frame):
    def __init__(self, parent, ui):
        c = ui.colors
        super().__init__(parent, bg=c["window"])
        self.canvas = tk.Canvas(self, bg=c["window"], highlightthickness=0, takefocus=False)
        self.scrollbar = tk.Scrollbar(self, command=self.canvas.yview, bg=c["sidebar"],
                                     activebackground=c["button"], troughcolor=c["window"],
                                     highlightbackground=c["window"], highlightcolor=c["accent"], relief="flat")
        self.canvas.configure(yscrollcommand=self._position)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1); self.columnconfigure(0, weight=1)
        self.inner = ui.frame(self)
        self.window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(self.window, width=event.width))

    def _position(self, first, last):
        self.scrollbar.set(first, last)
        if float(first) <= 0 and float(last) >= 1:
            self.scrollbar.grid_remove()
        else:
            self.scrollbar.grid()
