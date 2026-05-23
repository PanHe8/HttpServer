from __future__ import annotations

import json
import logging
import queue
import tkinter as tk
from tkinter import messagebox, ttk
from typing import List, Optional

from models.mapping import Mapping, RequestInfo, PendingRequest
from server.http_server import (
    MockServer,
    get_pending_queue,
    set_mappings as server_set_mappings,
    set_auto_reply as server_set_auto_reply,
    get_mappings as server_get_mappings,
)
from storage.store import ConfigStore

logger = logging.getLogger(__name__)


# ======================================================================
# Mapping Editor Dialog
# ======================================================================

class MappingDialog(tk.Toplevel):
    """Dialog for adding or editing a request→response mapping."""

    def __init__(self, parent: tk.Widget, mapping: Optional[Mapping] = None):
        super().__init__(parent)
        self.result: Optional[Mapping] = None
        self._mapping = mapping

        self.title("Edit Mapping" if mapping else "Add Mapping")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        # --- form variables ------------------------------------------
        self._var_name = tk.StringVar(value=mapping.name if mapping else "")
        self._var_method = tk.StringVar(value=mapping.method if mapping else "ANY")
        self._var_path = tk.StringVar(value=mapping.url_path if mapping else "")
        self._var_req_body = tk.StringVar(value=mapping.request_body if mapping else "")
        self._var_resp_status = tk.IntVar(value=mapping.response_status if mapping else 200)
        self._var_resp_ct = tk.StringVar(
            value=mapping.response_content_type if mapping else "application/json"
        )
        self._var_enabled = tk.BooleanVar(value=mapping.enabled if mapping else True)

        # response body is multiline – handled separately
        self._resp_body_text: Optional[tk.Text] = None

        self._build_ui()

        if mapping:
            self._resp_body_text.insert("1.0", mapping.response_body)

        self.wait_window()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        frame = ttk.Frame(self, padding=10)
        frame.pack(fill="both", expand=True)

        row = 0

        # Name
        ttk.Label(frame, text="Name:").grid(row=row, column=0, sticky="w", pady=2)
        ttk.Entry(frame, textvariable=self._var_name, width=50).grid(
            row=row, column=1, sticky="ew", pady=2, padx=(5, 0)
        )
        row += 1

        # Method
        ttk.Label(frame, text="Method:").grid(row=row, column=0, sticky="w", pady=2)
        method_cb = ttk.Combobox(
            frame, textvariable=self._var_method,
            values=["ANY", "GET", "POST", "PUT", "DELETE", "PATCH"],
            state="readonly", width=10,
        )
        method_cb.grid(row=row, column=1, sticky="w", pady=2, padx=(5, 0))
        row += 1

        # URL Path
        ttk.Label(frame, text="URL Path:").grid(row=row, column=0, sticky="w", pady=2)
        ttk.Entry(frame, textvariable=self._var_path, width=50).grid(
            row=row, column=1, sticky="ew", pady=2, padx=(5, 0)
        )
        row += 1

        # Request Body (matching)
        ttk.Label(frame, text="Match Body:").grid(row=row, column=0, sticky="nw", pady=2)
        req_frame = ttk.Frame(frame)
        req_frame.grid(row=row, column=1, sticky="ew", pady=2, padx=(5, 0))
        self._req_body_text = tk.Text(req_frame, height=4, width=50)
        self._req_body_text.pack(fill="x")
        if self._var_req_body.get():
            self._req_body_text.insert("1.0", self._var_req_body.get())
        row += 1

        # Response Status
        ttk.Label(frame, text="Resp Status:").grid(row=row, column=0, sticky="w", pady=2)
        ttk.Spinbox(
            frame, textvariable=self._var_resp_status,
            from_=100, to=599, width=6,
        ).grid(row=row, column=1, sticky="w", pady=2, padx=(5, 0))
        row += 1

        # Content-Type
        ttk.Label(frame, text="Content-Type:").grid(row=row, column=0, sticky="w", pady=2)
        ttk.Entry(frame, textvariable=self._var_resp_ct, width=50).grid(
            row=row, column=1, sticky="ew", pady=2, padx=(5, 0)
        )
        row += 1

        # Response Body
        ttk.Label(frame, text="Response Body:").grid(row=row, column=0, sticky="nw", pady=2)
        resp_frame = ttk.Frame(frame)
        resp_frame.grid(row=row, column=1, sticky="ew", pady=2, padx=(5, 0))
        self._resp_body_text = tk.Text(resp_frame, height=6, width=50)
        self._resp_body_text.pack(fill="x")
        row += 1

        # Enabled
        ttk.Checkbutton(frame, text="Enabled", variable=self._var_enabled).grid(
            row=row, column=1, sticky="w", pady=6, padx=(5, 0)
        )
        row += 1

        # Buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=row, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(btn_frame, text="Save", command=self._on_save).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side="left", padx=5)

    # ------------------------------------------------------------------
    def _on_save(self) -> None:
        name = self._var_name.get().strip()
        if not name:
            messagebox.showwarning("Validation", "Name is required.", parent=self)
            return

        path = self._var_path.get().strip()
        if not path:
            messagebox.showwarning("Validation", "URL Path is required.", parent=self)
            return

        self.result = Mapping(
            id=self._mapping.id if self._mapping else "",
            name=name,
            method=self._var_method.get(),
            url_path=path,
            request_body=self._req_body_text.get("1.0", "end-1c").strip(),
            response_body=self._resp_body_text.get("1.0", "end-1c").strip(),
            response_status=self._var_resp_status.get(),
            response_content_type=self._var_resp_ct.get().strip(),
            enabled=self._var_enabled.get(),
        )
        self.destroy()


# ======================================================================
# Main Application Window
# ======================================================================

class MockServerGUI:
    """Main GUI for the HTTP Mock Server."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("HTTP Mock Server")
        self.root.geometry("1100x780")
        self.root.minsize(900, 650)

        self._server = MockServer()
        self._store = ConfigStore()
        self._mappings: List[Mapping] = self._store.load_all()
        self._current_pending: Optional[PendingRequest] = None

        # push initial mappings to server module
        server_set_mappings(self._mappings)

        self._build_menu()
        self._build_ui()
        self._refresh_mappings_table()
        self._poll_queue()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    # ==================================================================
    # Menu
    # ==================================================================

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Export Mappings…", command=self._export_mappings)
        file_menu.add_command(label="Import Mappings…", command=self._import_mappings)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

    # ==================================================================
    # UI Layout
    # ==================================================================

    def _build_ui(self) -> None:
        # --- Server bar ----------------------------------------------
        server_frame = ttk.LabelFrame(self.root, text="Server", padding=5)
        server_frame.pack(fill="x", padx=8, pady=(8, 0))

        ttk.Label(server_frame, text="Host:").pack(side="left")
        self._var_host = tk.StringVar(value="127.0.0.1")
        ttk.Entry(server_frame, textvariable=self._var_host, width=14).pack(side="left", padx=(2, 10))

        ttk.Label(server_frame, text="Port:").pack(side="left")
        self._var_port = tk.IntVar(value=8080)
        ttk.Entry(server_frame, textvariable=self._var_port, width=7).pack(side="left", padx=(2, 10))

        self._btn_start_stop = ttk.Button(server_frame, text="Start", command=self._toggle_server)
        self._btn_start_stop.pack(side="left", padx=(0, 10))

        self._var_status = tk.StringVar(value="Stopped")
        self._status_lbl = ttk.Label(server_frame, textvariable=self._var_status, foreground="red")
        self._status_lbl.pack(side="left")

        # --- Mappings section ----------------------------------------
        map_frame = ttk.LabelFrame(self.root, text="Request → Response Mappings", padding=5)
        map_frame.pack(fill="both", expand=False, padx=8, pady=(8, 0))

        # toolbar
        toolbar = ttk.Frame(map_frame)
        toolbar.pack(fill="x", pady=(0, 4))
        ttk.Button(toolbar, text="➕ Add", command=self._add_mapping).pack(side="left", padx=2)
        ttk.Button(toolbar, text="✏️ Edit", command=self._edit_mapping).pack(side="left", padx=2)
        ttk.Button(toolbar, text="🗑 Delete", command=self._delete_mapping).pack(side="left", padx=2)
        ttk.Button(toolbar, text="🔁 Toggle", command=self._toggle_mapping).pack(side="left", padx=2)

        # treeview
        columns = ("name", "method", "url_path", "req_body", "resp_body", "status", "enabled")
        self._map_tree = ttk.Treeview(map_frame, columns=columns, show="headings", height=6)
        self._map_tree.heading("name", text="Name")
        self._map_tree.heading("method", text="Method")
        self._map_tree.heading("url_path", text="URL Path")
        self._map_tree.heading("req_body", text="Match Body")
        self._map_tree.heading("resp_body", text="Response Body")
        self._map_tree.heading("status", text="Status")
        self._map_tree.heading("enabled", text="On")

        self._map_tree.column("name", width=100, minwidth=60)
        self._map_tree.column("method", width=60, minwidth=50)
        self._map_tree.column("url_path", width=160, minwidth=80)
        self._map_tree.column("req_body", width=160, minwidth=80)
        self._map_tree.column("resp_body", width=200, minwidth=80)
        self._map_tree.column("status", width=50, minwidth=40)
        self._map_tree.column("enabled", width=35, minwidth=30)

        vsb = ttk.Scrollbar(map_frame, orient="vertical", command=self._map_tree.yview)
        self._map_tree.configure(yscrollcommand=vsb.set)
        self._map_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self._map_tree.bind("<Double-1>", lambda e: self._edit_mapping())

        # --- Request / Response area ---------------------------------
        rr_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        rr_pane.pack(fill="both", expand=True, padx=8, pady=8)

        # left: incoming request
        req_frame = ttk.LabelFrame(rr_pane, text="Incoming Request", padding=5)
        rr_pane.add(req_frame, weight=1)

        self._request_text = tk.Text(req_frame, state="disabled", wrap="word", font=("Consolas", 9))
        req_sb = ttk.Scrollbar(req_frame, orient="vertical", command=self._request_text.yview)
        self._request_text.configure(yscrollcommand=req_sb.set)
        self._request_text.pack(side="left", fill="both", expand=True)
        req_sb.pack(side="right", fill="y")

        # right: response editor
        resp_frame = ttk.LabelFrame(rr_pane, text="Response", padding=5)
        rr_pane.add(resp_frame, weight=1)

        resp_top = ttk.Frame(resp_frame)
        resp_top.pack(fill="x", pady=(0, 4))

        self._var_auto_reply = tk.BooleanVar(value=False)
        cb = ttk.Checkbutton(
            resp_top, text="Auto Reply (use matching rules)",
            variable=self._var_auto_reply, command=self._on_auto_reply_toggle,
        )
        cb.pack(side="left")

        ttk.Button(resp_top, text="Send Response", command=self._send_response).pack(side="right")

        self._response_text = tk.Text(resp_frame, wrap="word", font=("Consolas", 9))
        resp_sb = ttk.Scrollbar(resp_frame, orient="vertical", command=self._response_text.yview)
        self._response_text.configure(yscrollcommand=resp_sb.set)
        self._response_text.pack(side="left", fill="both", expand=True)
        resp_sb.pack(side="right", fill="y")

        # --- Log area ------------------------------------------------
        log_frame = ttk.LabelFrame(self.root, text="Request Log", padding=5)
        log_frame.pack(fill="x", padx=8, pady=(0, 8))

        self._log_text = tk.Text(log_frame, state="disabled", wrap="word", height=6, font=("Consolas", 8))
        log_sb = ttk.Scrollbar(log_frame, orient="vertical", command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=log_sb.set)
        self._log_text.pack(side="left", fill="both", expand=True)
        log_sb.pack(side="right", fill="y")

    # ==================================================================
    # Server control
    # ==================================================================

    def _toggle_server(self) -> None:
        if self._server.is_running:
            self._server.stop()
            self._current_pending = None
            self._request_text.configure(state="normal")
            self._request_text.delete("1.0", "end")
            self._request_text.configure(state="disabled")
            self._var_status.set("Stopped")
            self._status_lbl.configure(foreground="red")
            self._btn_start_stop.configure(text="Start")
        else:
            host = self._var_host.get().strip() or "127.0.0.1"
            port = self._var_port.get()
            try:
                self._server = MockServer(host, port)
                self._server.start()
                self._var_status.set(f"Running on {host}:{port}")
                self._status_lbl.configure(foreground="green")
                self._btn_start_stop.configure(text="Stop")
            except OSError as exc:
                messagebox.showerror("Server Error", str(exc))

    # ==================================================================
    # Mappings CRUD
    # ==================================================================

    def _refresh_mappings_table(self) -> None:
        for item in self._map_tree.get_children():
            self._map_tree.delete(item)
        for mp in self._mappings:
            req_preview = mp.request_body[:60] + "…" if len(mp.request_body) > 60 else mp.request_body
            resp_preview = mp.response_body[:60] + "…" if len(mp.response_body) > 60 else mp.response_body
            self._map_tree.insert("", "end", iid=mp.id, values=(
                mp.name,
                mp.method,
                mp.url_path,
                req_preview,
                resp_preview,
                mp.response_status,
                "✓" if mp.enabled else "✗",
            ))

    def _sync_mappings(self) -> None:
        server_set_mappings(self._mappings)
        self._store.save_all(self._mappings)
        self._refresh_mappings_table()

    def _get_selected_mapping(self) -> Optional[Mapping]:
        sel = self._map_tree.selection()
        if not sel:
            messagebox.showinfo("Info", "Select a mapping first.")
            return None
        mid = sel[0]
        for mp in self._mappings:
            if mp.id == mid:
                return mp
        return None

    def _add_mapping(self) -> None:
        dlg = MappingDialog(self.root)
        if dlg.result:
            self._mappings.append(dlg.result)
            self._sync_mappings()
            self._log(f"Added mapping: {dlg.result.name}")

    def _edit_mapping(self) -> None:
        mp = self._get_selected_mapping()
        if mp is None:
            return
        dlg = MappingDialog(self.root, mapping=mp)
        if dlg.result:
            idx = next(i for i, m in enumerate(self._mappings) if m.id == mp.id)
            self._mappings[idx] = dlg.result
            self._sync_mappings()
            self._log(f"Edited mapping: {dlg.result.name}")

    def _delete_mapping(self) -> None:
        mp = self._get_selected_mapping()
        if mp is None:
            return
        if messagebox.askyesno("Confirm", f"Delete mapping '{mp.name}'?"):
            self._mappings = [m for m in self._mappings if m.id != mp.id]
            self._sync_mappings()
            self._log(f"Deleted mapping: {mp.name}")

    def _toggle_mapping(self) -> None:
        mp = self._get_selected_mapping()
        if mp is None:
            return
        mp.enabled = not mp.enabled
        self._sync_mappings()
        self._log(f"Toggled mapping '{mp.name}' → {'ON' if mp.enabled else 'OFF'}")

    # ==================================================================
    # Auto-reply
    # ==================================================================

    def _on_auto_reply_toggle(self) -> None:
        server_set_auto_reply(self._var_auto_reply.get())
        self._log(f"Auto-reply: {'ON' if self._var_auto_reply.get() else 'OFF'}")

    # ==================================================================
    # Manual response
    # ==================================================================

    def _send_response(self) -> None:
        if self._current_pending is None:
            messagebox.showinfo("Info", "No pending request to respond to.")
            return
        body = self._response_text.get("1.0", "end-1c")
        self._current_pending.set_response(body)
        self._log(f"Sent manual response to {self._current_pending.request_info.method} "
                  f"{self._current_pending.request_info.path}")
        self._current_pending = None
        self._request_text.configure(state="normal")
        self._request_text.delete("1.0", "end")
        self._request_text.configure(state="disabled")

    # ==================================================================
    # Queue polling – bridge between server thread and GUI
    # ==================================================================

    def _poll_queue(self) -> None:
        if self._current_pending is None:
            try:
                self._current_pending = get_pending_queue().get_nowait()
                self._display_request(self._current_pending.request_info)
            except queue.Empty:
                pass
        self.root.after(150, self._poll_queue)

    def _display_request(self, info: RequestInfo) -> None:
        self._request_text.configure(state="normal")
        self._request_text.delete("1.0", "end")
        self._request_text.insert("end", f"Time   : {info.timestamp}\n")
        self._request_text.insert("end", f"Method : {info.method}\n")
        self._request_text.insert("end", f"Path   : {info.path}\n\n")
        self._request_text.insert("end", "Headers:\n")
        for k, v in info.headers.items():
            self._request_text.insert("end", f"  {k}: {v}\n")
        self._request_text.insert("end", "\nBody:\n")
        if info.body:
            try:
                pretty = json.dumps(json.loads(info.body), indent=2, ensure_ascii=False)
            except (json.JSONDecodeError, TypeError):
                pretty = info.body
            self._request_text.insert("end", pretty)
        else:
            self._request_text.insert("end", "(empty)")
        self._request_text.configure(state="disabled")
        self._log(f"{info.method} {info.path}")

    # ==================================================================
    # Logging
    # ==================================================================

    def _log(self, message: str) -> None:
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_text.configure(state="normal")
        self._log_text.insert("end", f"[{ts}] {message}\n")
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    # ==================================================================
    # Import / Export
    # ==================================================================

    def _export_mappings(self) -> None:
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON files", "*.json")],
            title="Export Mappings",
        )
        if path:
            export_store = ConfigStore(path)
            export_store.save_all(self._mappings)
            self._log(f"Exported {len(self._mappings)} mappings → {path}")

    def _import_mappings(self) -> None:
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json")],
            title="Import Mappings",
        )
        if path:
            try:
                import_store = ConfigStore(path)
                imported = import_store.load_all()
                self._mappings.extend(imported)
                self._sync_mappings()
                self._log(f"Imported {len(imported)} mappings from {path}")
            except Exception as exc:
                messagebox.showerror("Import Error", str(exc))

    # ==================================================================
    # Shutdown
    # ==================================================================

    def _on_close(self) -> None:
        if self._server.is_running:
            self._server.stop()
        self._store.save_all(self._mappings)
        self.root.destroy()
