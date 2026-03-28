"""
Hex Tic-Tac-Toe — local + networked multiplayer
------------------------------------------------
Single-player / local:  just launch and play.
Host a game  : click "Host Game", share your IP + port with the other player.
Join a game  : click "Join Game", enter the host's IP + port.

Only the host can restart or change settings.
Players stay connected across restarts.
"""

import tkinter as tk
from tkinter import messagebox, simpledialog
import math
import socket
import threading
import json
import queue


# ── Network helpers ──────────────────────────────────────────────────────────

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def send_msg(sock, obj):
    """Send a JSON-encoded message prefixed with a 4-byte length."""
    data = json.dumps(obj).encode()
    sock.sendall(len(data).to_bytes(4, "big") + data)


def recv_msg(sock):
    """Receive a length-prefixed JSON message. Returns None on disconnect."""
    try:
        raw = _recvn(sock, 4)
        if not raw:
            return None
        length = int.from_bytes(raw, "big")
        data = _recvn(sock, length)
        if not data:
            return None
        return json.loads(data.decode())
    except Exception:
        return None


def _recvn(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


# ── Lobby window ─────────────────────────────────────────────────────────────

class LobbyWindow:
    """
    Shown before the game starts.
    Returns a net_config dict (or None for local play) via self.result.

    All background-thread → UI communication goes through self._lobby_queue
    polled via root.after(), so we never call Tk from a non-main thread.
    """
    def __init__(self, root):
        self.root = root
        self.result = None
        self._server_sock = None
        self._lobby_queue = queue.Queue()

        self._build()
        self._poll()   # start polling the queue on the main thread

    def _poll(self):
        """Drain the lobby queue on the main thread."""
        try:
            while True:
                fn = self._lobby_queue.get_nowait()
                fn()
        except queue.Empty:
            pass
        # Keep polling only while the lobby window still exists
        if self.win.winfo_exists():
            self.root.after(50, self._poll)

    def _schedule(self, fn):
        """Post a callable to be run on the main thread."""
        self._lobby_queue.put(fn)

    def _build(self):
        self.win = tk.Toplevel(self.root)
        self.win.title("Hex Tic-Tac-Toe — Lobby")
        self.win.resizable(False, False)
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

        bg = "#1e1e1e"
        self.win.configure(bg=bg)

        tk.Label(self.win, text="HEX TIC-TAC-TOE", bg=bg, fg="white",
                 font=("Arial", 16, "bold")).pack(pady=(24, 4))
        tk.Label(self.win, text="Choose how to play", bg=bg, fg="#aaa",
                 font=("Arial", 10)).pack(pady=(0, 20))

        btn_cfg = dict(relief="flat", font=("Arial", 11, "bold"),
                       pady=10, width=18, activeforeground="white")

        tk.Button(self.win, text="▶  Local Game",
                  bg="#2e8b2e", fg="white", activebackground="#3aad3a",
                  command=self._local, **btn_cfg).pack(padx=40, pady=6)

        tk.Button(self.win, text="⬆  Host Game",
                  bg="#1a6abf", fg="white", activebackground="#2281e8",
                  command=self._host, **btn_cfg).pack(padx=40, pady=6)

        tk.Button(self.win, text="⬇  Join Game",
                  bg="#7b3fbf", fg="white", activebackground="#9b55e0",
                  command=self._join, **btn_cfg).pack(padx=40, pady=6)

        self.status = tk.Label(self.win, text="", bg=bg, fg="#f0a500",
                               font=("Arial", 9), wraplength=300)
        self.status.pack(pady=(12, 20))

    # ── lobby actions ────────────────────────────────────────────────────────

    def _local(self):
        self.result = {"mode": "local"}
        self.win.destroy()

    def _host(self):
        port = simpledialog.askinteger(
            "Host", "Port to listen on:", initialvalue=54321,
            minvalue=1024, maxvalue=65535, parent=self.win)
        if port is None:
            return

        assign = self._ask_assignment()
        if assign is None:
            return

        self.status.config(text=f"Waiting for opponent to connect…\n"
                               f"Your IP: {get_local_ip()}   Port: {port}")
        self.win.update()

        def listen():
            try:
                srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                srv.bind(("", port))
                srv.listen(1)
                self._server_sock = srv
                conn, addr = srv.accept()
                # Hand off to main thread via queue — never touch Tk from here
                self._schedule(lambda: self._host_connected(conn, addr, assign))
            except Exception as e:
                err = str(e)
                self._schedule(lambda: self.status.config(text=f"Error: {err}"))

        threading.Thread(target=listen, daemon=True).start()

    def _ask_assignment(self):
        dlg = tk.Toplevel(self.win)
        dlg.title("Player assignment")
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.configure(bg="#1e1e1e")

        tk.Label(dlg, text="You are playing as:", bg="#1e1e1e", fg="white",
                 font=("Arial", 11)).pack(padx=24, pady=(20, 8))

        choice = tk.StringVar(value="X")
        f = tk.Frame(dlg, bg="#1e1e1e")
        f.pack()
        for val, col in [("X", "#FF5733"), ("O", "#33C1FF")]:
            tk.Radiobutton(f, text=f"  Player {val}", variable=choice, value=val,
                           bg="#1e1e1e", fg=col, selectcolor="#333",
                           activebackground="#1e1e1e", activeforeground=col,
                           font=("Arial", 12, "bold")).pack(anchor="w", padx=10, pady=4)

        result = [None]

        def confirm():
            result[0] = choice.get()
            dlg.destroy()

        def cancel():
            dlg.destroy()

        tk.Button(dlg, text="Confirm", command=confirm,
                  bg="#2e8b2e", fg="white", relief="flat",
                  font=("Arial", 10, "bold"), pady=6
                  ).pack(fill="x", padx=24, pady=(12, 4))
        tk.Button(dlg, text="Cancel", command=cancel,
                  bg="#444", fg="white", relief="flat",
                  font=("Arial", 10), pady=6
                  ).pack(fill="x", padx=24, pady=(0, 16))

        self.win.wait_window(dlg)
        return result[0]

    def _host_connected(self, conn, addr, host_player):
        """Called on the main thread once a client has connected."""
        client_player = "O" if host_player == "X" else "X"
        send_msg(conn, {"type": "assign", "player": client_player})
        self.result = {
            "mode": "host",
            "sock": conn,
            "my_player": host_player,
        }
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass
        self.win.destroy()

    def _join(self):
        host = simpledialog.askstring(
            "Join", "Host IP address:", initialvalue="", parent=self.win)
        if not host:
            return
        port = simpledialog.askinteger(
            "Join", "Port:", initialvalue=54321,
            minvalue=1024, maxvalue=65535, parent=self.win)
        if port is None:
            return

        self.status.config(text=f"Connecting to {host}:{port}…")
        self.win.update()

        def connect():
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.connect((host, port))
                self._schedule(lambda: self._join_connected(s))
            except Exception as e:
                err = str(e)
                self._schedule(lambda: self.status.config(
                    text=f"Could not connect: {err}"))

        threading.Thread(target=connect, daemon=True).start()

    def _join_connected(self, sock):
        """Called on the main thread once connected to host."""
        msg = recv_msg(sock)
        if msg and msg.get("type") == "assign":
            self.result = {
                "mode": "client",
                "sock": sock,
                "my_player": msg["player"],
            }
            self.win.destroy()
        else:
            self.status.config(text="Unexpected response from host.")
            sock.close()

    def _on_close(self):
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass
        self.win.destroy()


# ── Main game ─────────────────────────────────────────────────────────────────

class HexTicTacToeGUI:
    def __init__(self, root, net_config):
        self.root = root
        self.root.title("Hex Tic-Tac-Toe")

        self.net_mode  = net_config["mode"]
        self.net_sock  = net_config.get("sock")
        self.my_player = net_config.get("my_player", "X")
        self.is_host   = self.net_mode in ("local", "host")
        self._net_queue = queue.Queue()

        # ---- Grid appearance ------------------------------------------------
        # Change these three values to customise the grid look:
        self.GRID_COLOR = "#2e8b2e"
        self.GRID_WIDTH = 2
        self.GRID_BG    = "white"
        # ---------------------------------------------------------------------

        self.base_size   = 30
        self.zoom_level  = 1.0
        self.offset_x    = 0.0
        self.offset_y    = 0.0

        self.win_length         = 5
        self.pending_win_length = 5
        self.current_player     = "X"
        self.board              = {}
        self.colors             = {"X": "#FF5733", "O": "#33C1FF"}
        self.grid_items: dict[tuple, int] = {}
        self._pan_last_x = 0
        self._pan_last_y = 0

        self.setup_ui()
        self._redraw_grid()

        if self.net_sock:
            threading.Thread(target=self._net_recv_loop, daemon=True).start()
            self.root.after(50, self._poll_net_queue)

    # ------------------------------------------------------------------ UI
    def setup_ui(self):
        sidebar = tk.Frame(self.root, bg="#1e1e1e", width=200)
        sidebar.pack(side="right", fill="y")
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="HEX\nTIC-TAC-TOE",
                 bg="#1e1e1e", fg="white",
                 font=("Arial", 14, "bold"), justify="center"
                 ).pack(pady=(20, 4))

        if self.net_mode == "host":
            badge_text = f"🔗 Hosting  (you are {self.my_player})"
            badge_col  = "#1a6abf"
        elif self.net_mode == "client":
            badge_text = f"🔗 Connected  (you are {self.my_player})"
            badge_col  = "#7b3fbf"
        else:
            badge_text = "Local game"
            badge_col  = "#444"

        tk.Label(sidebar, text=badge_text, bg=badge_col, fg="white",
                 font=("Arial", 8), pady=3
                 ).pack(fill="x", padx=16, pady=(0, 6))

        tk.Frame(sidebar, bg="#444", height=1).pack(fill="x", padx=16, pady=4)

        tk.Label(sidebar, text="CURRENT TURN",
                 bg="#1e1e1e", fg="#aaa", font=("Arial", 8)).pack(pady=(12, 0))

        self.turn_frame = tk.Frame(sidebar, bg="#1e1e1e")
        self.turn_frame.pack(pady=(4, 0))
        self.turn_swatch = tk.Label(self.turn_frame, width=2,
                                    bg=self.colors["X"], relief="flat")
        self.turn_swatch.pack(side="left", padx=(0, 6))
        self.turn_label = tk.Label(self.turn_frame, text="Player X",
                                   bg="#1e1e1e", fg="white",
                                   font=("Arial", 13, "bold"))
        self.turn_label.pack(side="left")

        self.your_turn_label = tk.Label(sidebar, text="",
                                        bg="#1e1e1e", fg="#f0a500",
                                        font=("Arial", 8, "italic"))
        self.your_turn_label.pack()

        tk.Frame(sidebar, bg="#444", height=1).pack(fill="x", padx=16, pady=12)

        tk.Label(sidebar, text="WIN LENGTH",
                 bg="#1e1e1e", fg="#aaa", font=("Arial", 8)).pack()

        wl_frame = tk.Frame(sidebar, bg="#1e1e1e")
        wl_frame.pack(pady=(4, 0))

        self.wl_dec_btn = tk.Button(
            wl_frame, text="−", command=self._dec_win_length,
            bg="#333", fg="white", relief="flat",
            font=("Arial", 12, "bold"), width=2,
            activebackground="#555", activeforeground="white")
        self.wl_dec_btn.pack(side="left")

        self.wl_label = tk.Label(wl_frame, text=str(self.win_length),
                                 bg="#1e1e1e", fg="white",
                                 font=("Arial", 18, "bold"), width=3)
        self.wl_label.pack(side="left")

        self.wl_inc_btn = tk.Button(
            wl_frame, text="+", command=self._inc_win_length,
            bg="#333", fg="white", relief="flat",
            font=("Arial", 12, "bold"), width=2,
            activebackground="#555", activeforeground="white")
        self.wl_inc_btn.pack(side="left")

        self.wl_pending_label = tk.Label(sidebar, text="",
                                         bg="#1e1e1e", fg="#f0a500",
                                         font=("Arial", 8))
        self.wl_pending_label.pack(pady=(0, 8))

        self.restart_btn = tk.Button(
            sidebar, text="⟳  Restart",
            command=self._restart,
            bg="#2e8b2e", fg="white",
            font=("Arial", 11, "bold"),
            relief="flat", pady=8,
            activebackground="#3aad3a", activeforeground="white")
        self.restart_btn.pack(fill="x", padx=16)

        tk.Label(sidebar, text="Right-drag to pan\nScroll to zoom",
                 bg="#1e1e1e", fg="#666", font=("Arial", 8),
                 justify="center").pack(side="bottom", pady=16)

        if not self.is_host:
            for w in (self.wl_dec_btn, self.wl_inc_btn, self.restart_btn):
                w.config(state="disabled", bg="#2a2a2a", fg="#555",
                         activebackground="#2a2a2a", activeforeground="#555")

        self.canvas = tk.Canvas(self.root, bg=self.GRID_BG)
        self.canvas.pack(side="left", fill="both", expand=True)

        self.canvas.bind("<Button-1>",        self.handle_click)
        self.canvas.bind("<Button-3>",        self.start_pan)
        self.canvas.bind("<B3-Motion>",       self.do_pan)
        self.canvas.bind("<ButtonRelease-3>", self._on_pan_end)
        self.canvas.bind("<MouseWheel>",      self.handle_zoom)
        self.canvas.bind("<Button-4>",        self.handle_zoom)
        self.canvas.bind("<Button-5>",        self.handle_zoom)
        self.canvas.bind("<Configure>",       lambda e: self._redraw_grid())

    BASE_FONT_SIZE = 12

    # ------------------------------------------------------------------ net
    def _net_recv_loop(self):
        while True:
            msg = recv_msg(self.net_sock)
            if msg is None:
                self._net_queue.put({"type": "disconnect"})
                break
            self._net_queue.put(msg)

    def _poll_net_queue(self):
        try:
            while True:
                msg = self._net_queue.get_nowait()
                self._handle_net_msg(msg)
        except queue.Empty:
            pass
        self.root.after(50, self._poll_net_queue)

    def _handle_net_msg(self, msg):
        t = msg.get("type")

        if t == "move":
            q, r, player = msg["q"], msg["r"], msg["player"]
            self.board[(q, r)] = player
            cx, cy = self.hex_to_canvas(q, r)
            self.draw_hexagon(q, r, color=self.colors[player])
            font_size = max(6, int(self.BASE_FONT_SIZE * self.zoom_level))
            self.canvas.create_text(cx, cy, text=player, fill="white",
                                    font=("Arial", font_size, "bold"),
                                    tags="piece_label")
            if self.check_win(q, r):
                self.root.after(100, lambda p=player: self._on_win(p))
            else:
                self.current_player = "O" if player == "X" else "X"
                self._update_turn_ui()

        elif t == "restart":
            self._do_restart(win_length=msg.get("win_length", self.win_length),
                             first_player=msg.get("first_player", "X"))

        elif t == "win_length":
            self.pending_win_length = msg["value"]
            self.wl_label.config(text=str(self.pending_win_length))
            self._update_pending_label()

        elif t == "disconnect":
            messagebox.showwarning("Disconnected",
                                   "The other player has disconnected.")

    def _send(self, obj):
        if self.net_sock:
            try:
                send_msg(self.net_sock, obj)
            except Exception:
                pass

    # ------------------------------------------------------------------ turn
    def _update_turn_ui(self):
        self.turn_label.config(text=f"Player {self.current_player}")
        self.turn_swatch.config(bg=self.colors[self.current_player])
        if self.net_mode != "local":
            if self.current_player == self.my_player:
                self.your_turn_label.config(text="← your turn")
            else:
                self.your_turn_label.config(text="waiting for opponent…")
        else:
            self.your_turn_label.config(text="")

    def _is_my_turn(self):
        return self.net_mode == "local" or self.current_player == self.my_player

    # ------------------------------------------------------------------ win length
    def _dec_win_length(self):
        if self.pending_win_length > 3:
            self.pending_win_length -= 1
            self.wl_label.config(text=str(self.pending_win_length))
            self._update_pending_label()
            self._send({"type": "win_length", "value": self.pending_win_length})

    def _inc_win_length(self):
        self.pending_win_length += 1
        self.wl_label.config(text=str(self.pending_win_length))
        self._update_pending_label()
        self._send({"type": "win_length", "value": self.pending_win_length})

    def _update_pending_label(self):
        if self.pending_win_length != self.win_length:
            self.wl_pending_label.config(text="takes effect on restart")
        else:
            self.wl_pending_label.config(text="")

    # ------------------------------------------------------------------ restart
    def _restart(self):
        self._send({
            "type": "restart",
            "win_length": self.pending_win_length,
            "first_player": "X",
        })
        self._do_restart(win_length=self.pending_win_length, first_player="X")

    def _do_restart(self, win_length=None, first_player="X"):
        if win_length is not None:
            self.win_length = win_length
            self.pending_win_length = win_length
            self.wl_label.config(text=str(self.win_length))
        self._update_pending_label()
        self.board = {}
        self.current_player = first_player
        self._update_turn_ui()
        self.canvas.delete("all")
        self.grid_items.clear()
        self.zoom_level = 1.0
        self.offset_x   = 0.0
        self.offset_y   = 0.0
        self._redraw_grid()

    # ------------------------------------------------------------------ zoom
    def handle_zoom(self, event):
        factor = 1.1 if (event.num == 4 or event.delta > 0) else 0.9
        new_zoom = self.zoom_level * factor
        if not (0.3 < new_zoom < 5.0):
            return
        cx, cy = event.x, event.y
        self.offset_x = cx - (cx - self.offset_x) * factor
        self.offset_y = cy - (cy - self.offset_y) * factor
        self.zoom_level = new_zoom
        self.canvas.scale("all", cx, cy, factor, factor)
        font_size = max(6, int(self.BASE_FONT_SIZE * new_zoom))
        for item in self.canvas.find_withtag("piece_label"):
            self.canvas.itemconfig(item, font=("Arial", font_size, "bold"))
        self._redraw_grid()

    # ------------------------------------------------------------------ pan
    def start_pan(self, event):
        self._pan_last_x = event.x
        self._pan_last_y = event.y

    def do_pan(self, event):
        dx = event.x - self._pan_last_x
        dy = event.y - self._pan_last_y
        self._pan_last_x = event.x
        self._pan_last_y = event.y
        self.canvas.move("all", dx, dy)
        self.offset_x += dx
        self.offset_y += dy

    def _on_pan_end(self, event):
        self._redraw_grid()

    # ------------------------------------------------------------------ hex math
    def hex_to_pixel_base(self, q, r):
        x = self.base_size * (3 / 2 * q)
        y = self.base_size * (math.sqrt(3) / 2 * q + math.sqrt(3) * r)
        return x, y

    def hex_to_canvas(self, q, r):
        bx, by = self.hex_to_pixel_base(q, r)
        return bx * self.zoom_level + self.offset_x, by * self.zoom_level + self.offset_y

    def canvas_to_hex(self, cx, cy):
        bx = (cx - self.offset_x) / self.zoom_level
        by = (cy - self.offset_y) / self.zoom_level
        q = (2 / 3 * bx) / self.base_size
        r = (-1 / 3 * bx + math.sqrt(3) / 3 * by) / self.base_size
        return self._hex_round(q, r)

    def _hex_round(self, q, r):
        s = -q - r
        rq, rr, rs = round(q), round(r), round(s)
        dq, dr, ds = abs(rq - q), abs(rr - r), abs(rs - s)
        if dq > dr and dq > ds:
            rq = -rr - rs
        elif dr > ds:
            rr = -rq - rs
        return int(rq), int(rr)

    # ------------------------------------------------------------------ grid
    def _visible_hex_range(self):
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        pad = self.base_size * self.zoom_level * 2
        corners = [
            (0 - pad,  0 - pad), (w + pad,  0 - pad),
            (0 - pad,  h + pad), (w + pad,  h + pad),
            (w / 2,    h / 2),
        ]
        qs, rs = zip(*[self.canvas_to_hex(x, y) for x, y in corners])
        extra = 3
        return min(qs) - extra, max(qs) + extra, min(rs) - extra, max(rs) + extra

    def _redraw_grid(self):
        q_min, q_max, r_min, r_max = self._visible_hex_range()
        needed = {(q, r) for q in range(q_min, q_max + 1)
                          for r in range(r_min, r_max + 1)}
        for cell in needed:
            if cell not in self.grid_items and cell not in self.board:
                self.grid_items[cell] = self._draw_empty_hex(*cell)
        cull_pad = 10
        to_delete = [
            c for c in list(self.grid_items)
            if (c[0] < q_min - cull_pad or c[0] > q_max + cull_pad or
                c[1] < r_min - cull_pad or c[1] > r_max + cull_pad)
        ]
        for c in to_delete:
            self.canvas.delete(self.grid_items.pop(c))

    def _draw_empty_hex(self, q, r):
        cx, cy = self.hex_to_canvas(q, r)
        rs = self.base_size * self.zoom_level
        pts = []
        for i in range(6):
            a = math.pi / 3 * i
            pts.extend([cx + rs * math.cos(a), cy + rs * math.sin(a)])
        item = self.canvas.create_polygon(
            pts, outline=self.GRID_COLOR, fill=self.GRID_BG,
            width=self.GRID_WIDTH, tags="grid_hex")
        self.canvas.tag_lower(item)
        return item

    def draw_hexagon(self, q, r, color, outline="black"):
        if (q, r) in self.grid_items:
            self.canvas.delete(self.grid_items.pop((q, r)))
        cx, cy = self.hex_to_canvas(q, r)
        rs = self.base_size * self.zoom_level
        pts = []
        for i in range(6):
            a = math.pi / 3 * i
            pts.extend([cx + rs * math.cos(a), cy + rs * math.sin(a)])
        return self.canvas.create_polygon(
            pts, outline=outline, fill=color, width=self.GRID_WIDTH)

    # ------------------------------------------------------------------ game
    def handle_click(self, event):
        if not self._is_my_turn():
            return
        q, r = self.canvas_to_hex(event.x, event.y)
        if (q, r) in self.board:
            return

        player = self.current_player
        self.board[(q, r)] = player
        cx, cy = self.hex_to_canvas(q, r)
        self.draw_hexagon(q, r, color=self.colors[player])
        font_size = max(6, int(self.BASE_FONT_SIZE * self.zoom_level))
        self.canvas.create_text(cx, cy, text=player, fill="white",
                                font=("Arial", font_size, "bold"),
                                tags="piece_label")

        self._send({"type": "move", "q": q, "r": r, "player": player})

        if self.check_win(q, r):
            self.root.after(100, lambda p=player: self._on_win(p))
        else:
            self.current_player = "O" if player == "X" else "X"
            self._update_turn_ui()

    def _on_win(self, player):
        messagebox.showinfo("Victory!", f"Player {player} wins!")
        if self.is_host:
            self._restart()

    def check_win(self, q, r):
        player = self.board[(q, r)]
        for dq, dr in [(1, 0), (0, 1), (1, -1)]:
            count = 1
            for direction in [1, -1]:
                cq, cr = q + dq * direction, r + dr * direction
                while self.board.get((cq, cr)) == player:
                    count += 1
                    cq += dq * direction
                    cr += dr * direction
            if count >= self.win_length:
                return True
        return False


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    root = tk.Tk()
    root.withdraw()

    lobby = LobbyWindow(root)
    root.wait_window(lobby.win)

    if lobby.result is None:
        root.destroy()
        return

    root.deiconify()
    root.geometry("1000x640")
    HexTicTacToeGUI(root, lobby.result)
    root.mainloop()


if __name__ == "__main__":
    main()