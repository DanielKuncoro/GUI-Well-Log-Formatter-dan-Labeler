import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import pandas as pd
import numpy as np
import os
import re
import threading

#Bagian LAS PARSER
def parse_las_safe(las_path):
    curves = []
    data_rows = []
    read_curve = False
    read_data = False

    with open(las_path, "r", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if line.lower().startswith("~c"):
                read_curve = True
                read_data = False
                continue
            if read_curve and line.startswith("~"):
                read_curve = False
            if read_curve:
                if "." in line:
                    curve = line.split(".")[0].strip().upper()
                    curves.append(curve)
                continue
            if line.lower().startswith(("~a", "~ascii")):
                read_data = True
                continue
            if not read_data or not line or line.startswith("#"):
                continue
            parts = re.split(r"[,\s;]+", line)
            try:
                nums = [float(p) for p in parts]
            except ValueError:
                continue
            if len(nums) == len(curves):
                data_rows.append(nums)

    if not curves or not data_rows:
        return None, "Gagal parsing LAS"

    df = pd.DataFrame(data_rows, columns=curves)

    def find_curve(names):
        for c in df.columns:
            for n in names:
                if n in c:
                    return c
        return None

    depth_col = find_curve(["DEPTH", "DEPT"])
    gr_col    = find_curve(["GR"])
    dens_col  = find_curve(["DENS", "RHOB"])

    if not all([depth_col, gr_col, dens_col]):
        return None, "Kurva DEPTH / GR / DENSITY tidak lengkap"

    df = df[[depth_col, gr_col, dens_col]]
    df.columns = ["DEPTH", "GR", "DENSITY"]

    missing_vals = [-999, -9999, -99999, -1e30]
    df.replace(missing_vals, np.nan, inplace=True)
    df.dropna(subset=["DEPTH", "DENSITY"], inplace=True)
    df.sort_values("DEPTH", inplace=True)
    df.reset_index(drop=True, inplace=True)

    ddepth = df["DEPTH"].diff()
    qc = {
        "min": ddepth.min(),
        "median": ddepth.median(),
        "max": ddepth.max(),
        "gap": (ddepth > 0.02).sum()
    }
    return df, qc


#BAGIAN LABELER
def apply_lithology_by_thickness(csv_path, layers, output_dir):
    df = pd.read_csv(csv_path)
    if "DEPTH" not in df.columns:
        raise ValueError(f"Kolom DEPTH tidak ditemukan di {os.path.basename(csv_path)}")

    df = df.sort_values("DEPTH").reset_index(drop=True)
    df["LITHO"] = None

    current_top = 0.0
    for thickness, code in layers:
        current_bottom = current_top + thickness
        df.loc[
            (df["DEPTH"] > current_top) & (df["DEPTH"] <= current_bottom),
            "LITHO"
        ] = code
        current_top = current_bottom

    df.dropna(subset=["LITHO"], inplace=True)
    df["LITHO"] = df["LITHO"].astype(int)

    name = os.path.splitext(os.path.basename(csv_path))[0]
    out_path = os.path.join(output_dir, f"{name}_labeled.csv")
    df.to_csv(out_path, index=False)
    return len(df)


#MAIN APPLICATION
class WellLogApp:
    def __init__(self, root):
        self.root = root
        self.root.title("GUI Well Formatter & Labeler")
        self.root.geometry("750x700")
        self.root.resizable(True, True)
        self.root.configure(bg="#1a1f2e")

        # Style
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure("TNotebook", background="#1a1f2e", borderwidth=0)
        self.style.configure("TNotebook.Tab",
            background="#2a3040", foreground="#8090b0",
            padding=[18, 8], font=("Courier New", 10, "bold"))
        self.style.map("TNotebook.Tab",
            background=[("selected", "#1a6b8a")],
            foreground=[("selected", "#ffffff")])
        self.style.configure("TFrame", background="#1a1f2e")
        self.style.configure("Treeview",
            background="#232a3a", foreground="#c0cfe0",
            fieldbackground="#232a3a", rowheight=26,
            font=("Courier New", 9))
        self.style.configure("Treeview.Heading",
            background="#1a6b8a", foreground="#ffffff",
            font=("Courier New", 9, "bold"))
        self.style.map("Treeview", background=[("selected", "#1a6b8a")])

        self._build_header()

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        tab1 = ttk.Frame(notebook)
        tab2 = ttk.Frame(notebook)
        notebook.add(tab1, text="  ① LAS → CSV  ")
        notebook.add(tab2, text="  ② Label Litologi  ")

        self._build_las_tab(tab1)
        self._build_litho_tab(tab2)

        self.layers = []

    # ── Header ──────────────────────────────────────
    def _build_header(self):
        hdr = tk.Frame(self.root, bg="#0f1420", pady=12)
        hdr.pack(fill="x")
        tk.Label(hdr, text="⛏ Well Log Formatter & Labeler",
            font=("Courier New", 16, "bold"),
            bg="#0f1420", fg="#1ab8e0").pack()

    # ── Helper widgets ───────────────────────────────
    def _frame(self, parent, **kw):
        return tk.Frame(parent, bg="#1a1f2e", **kw)

    def _label(self, parent, text, bold=False, color="#8aaccc", size=9):
        font = ("Courier New", size, "bold" if bold else "normal")
        return tk.Label(parent, text=text, bg="#1a1f2e", fg=color,
                        font=font, anchor="w")

    def _entry(self, parent, width=48, textvariable=None):
        e = tk.Entry(parent, width=width, bg="#232a3a", fg="#c0d8f0",
                     insertbackground="#1ab8e0", relief="flat",
                     font=("Courier New", 9),
                     textvariable=textvariable)
        e.configure(highlightthickness=1,
                    highlightbackground="#2a4060",
                    highlightcolor="#1a6b8a")
        return e

    def _btn(self, parent, text, cmd, color="#1a6b8a", width=None):
        kw = dict(text=text, command=cmd,
                  bg=color, fg="white", activebackground="#1ab8e0",
                  relief="flat", font=("Courier New", 9, "bold"),
                  cursor="hand2", pady=5)
        if width:
            kw["width"] = width
        return tk.Button(parent, **kw)

    def _sep(self, parent):
        tk.Frame(parent, bg="#2a3a50", height=1).pack(fill="x", pady=8)

    def _log(self, widget, msg, tag="info"):
        widget.configure(state="normal")
        colors = {"info": "#8aaccc", "ok": "#2ecc71",
                  "warn": "#f39c12", "err": "#e74c3c"}
        widget.insert("end", msg + "\n", tag)
        widget.tag_config(tag, foreground=colors.get(tag, "#8aaccc"))
        widget.see("end")
        widget.configure(state="disabled")

    # =====================================================
    # TAB 1 — LAS → CSV
    # =====================================================
    def _build_las_tab(self, parent):
        pad = dict(padx=14, pady=4)

        # File list
        self._label(parent, "FILE LAS", bold=True,
                    color="#1ab8e0", size=10).pack(anchor="w", **pad)

        tree_frame = self._frame(parent)
        tree_frame.pack(fill="x", padx=14, pady=2)

        self.las_tree = ttk.Treeview(tree_frame, columns=("file", "status"),
                                      show="headings", height=7)
        self.las_tree.heading("file",   text="Nama File")
        self.las_tree.heading("status", text="Status")
        self.las_tree.column("file",   width=440)
        self.las_tree.column("status", width=200)

        sb = ttk.Scrollbar(tree_frame, orient="vertical",
                           command=self.las_tree.yview)
        self.las_tree.configure(yscrollcommand=sb.set)
        self.las_tree.pack(side="left", fill="x", expand=True)
        sb.pack(side="right", fill="y")

        btn_row = self._frame(parent)
        btn_row.pack(fill="x", padx=14, pady=4)
        self._btn(btn_row, "＋ Tambah File LAS",
                  self._add_las_files).pack(side="left", padx=4)
        self._btn(btn_row, "✕ Hapus Terpilih",
                  self._remove_las_selected,
                  color="#7a2030").pack(side="left", padx=4)
        self._btn(btn_row, "⬜ Hapus Semua",
                  self._clear_las_files,
                  color="#4a3000").pack(side="left", padx=4)

        self._sep(parent)

        # Output dir
        self._label(parent, "FOLDER OUTPUT", bold=True,
                    color="#1ab8e0", size=10).pack(anchor="w", **pad)
        out_row = self._frame(parent)
        out_row.pack(fill="x", padx=14, pady=2)
        self.las_out_var = tk.StringVar()
        self._entry(out_row, width=52,
                    textvariable=self.las_out_var).pack(side="left")
        self._btn(out_row, "📁 Browse",
                  self._pick_las_out).pack(side="left", padx=6)

        self._sep(parent)

        # Progress & log
        self.las_progress = ttk.Progressbar(parent, mode="determinate",
                                             length=700)
        self.las_progress.pack(padx=14, pady=4, fill="x")

        self.las_log = tk.Text(parent, height=7, bg="#0f1420",
                                fg="#8aaccc", relief="flat",
                                font=("Courier New", 8),
                                state="disabled")
        self.las_log.pack(padx=14, pady=4, fill="both", expand=True)

        self._btn(parent, "▶  PROSES BATCH LAS → CSV",
                  self._run_las_batch,
                  color="#0e7a30", width=60).pack(pady=8)

        self._las_files = []

    def _add_las_files(self):
        files = filedialog.askopenfilenames(
            title="Pilih File LAS",
            filetypes=[("LAS files", "*.las"), ("All", "*.*")])
        for f in files:
            if f not in self._las_files:
                self._las_files.append(f)
                self.las_tree.insert("", "end",
                    values=(os.path.basename(f), "—"))

    def _remove_las_selected(self):
        for sel in self.las_tree.selection():
            fname = self.las_tree.item(sel)["values"][0]
            self._las_files = [f for f in self._las_files
                               if os.path.basename(f) != fname]
            self.las_tree.delete(sel)

    def _clear_las_files(self):
        self._las_files.clear()
        for row in self.las_tree.get_children():
            self.las_tree.delete(row)

    def _pick_las_out(self):
        d = filedialog.askdirectory()
        if d:
            self.las_out_var.set(d)

    def _run_las_batch(self):
        if not self._las_files:
            messagebox.showerror("Error", "Belum ada file LAS dipilih.")
            return
        if not self.las_out_var.get():
            messagebox.showerror("Error", "Pilih folder output dulu.")
            return

        # Clear log
        self.las_log.configure(state="normal")
        self.las_log.delete("1.0", "end")
        self.las_log.configure(state="disabled")

        def worker():
            total = len(self._las_files)
            self.las_progress["maximum"] = total
            self.las_progress["value"] = 0
            ok = err = 0

            # Map iid → filename for updating status
            iid_map = {}
            for iid in self.las_tree.get_children():
                fname = self.las_tree.item(iid)["values"][0]
                iid_map[fname] = iid


            for i, fpath in enumerate(self._las_files):
                name = os.path.basename(fpath)
                self._log(self.las_log, f"[{i+1}/{total}] Memproses: {name}", "info")

                df, qc = parse_las_safe(fpath)
                if df is None:
                    self._log(self.las_log, f"  ✗ GAGAL — {qc}", "err")
                    self.las_tree.set(iid_map.get(name, ""), "status", "❌ Gagal")
                    err += 1
                else:
                    stem = os.path.splitext(name)[0]
                    out_csv = os.path.join(self.las_out_var.get(),
                                           f"{stem}_clean.csv")
                    df.to_csv(out_csv, index=False)
                    self._log(self.las_log,
                        f"  ✔ OK  |  rows={len(df)}  "
                        f"median Δdepth={qc['median']:.4f}m  "
                        f"gap={qc['gap']}", "ok")
                    self.las_tree.set(iid_map.get(name, ""), "status",
                                      f"✅ {len(df)} rows")
                    ok += 1

                self.las_progress["value"] = i + 1
                self.root.update_idletasks()

            self._log(self.las_log,
                f"\n══ SELESAI: {ok} berhasil, {err} gagal ══", "ok")
            messagebox.showinfo("Selesai",
                f"Batch LAS→CSV selesai!\n✅ Berhasil: {ok}\n❌ Gagal: {err}")

        threading.Thread(target=worker, daemon=True).start()


    # =====================================================
    # TAB 2 — LABEL LITOLOGI
    # =====================================================
    def _build_litho_tab(self, parent):
        # ── Scrollable container ──────────────────────
        canvas = tk.Canvas(parent, bg="#1a1f2e", highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical",
                                   command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg="#1a1f2e")
        inner_window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def on_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        inner.bind("<Configure>", on_configure)

        def on_canvas_resize(event):
            canvas.itemconfig(inner_window, width=event.width)
        canvas.bind("<Configure>", on_canvas_resize)

        def on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", on_mousewheel)

        parent = inner  # redirect all packing to inner frame

        pad = dict(padx=14, pady=4)

        # CSV file list
        self._label(parent, "FILE CSV WELL LOG", bold=True,
                    color="#1ab8e0", size=10).pack(anchor="w", **pad)

        tree_frame2 = self._frame(parent)
        tree_frame2.pack(fill="x", padx=14, pady=2)

        self.csv_tree = ttk.Treeview(tree_frame2, columns=("file", "status"),
                                      show="headings", height=5)
        self.csv_tree.heading("file",   text="Nama File CSV")
        self.csv_tree.heading("status", text="Status")
        self.csv_tree.column("file",   width=440)
        self.csv_tree.column("status", width=200)

        sb2 = ttk.Scrollbar(tree_frame2, orient="vertical",
                            command=self.csv_tree.yview)
        self.csv_tree.configure(yscrollcommand=sb2.set)
        self.csv_tree.pack(side="left", fill="x", expand=True)
        sb2.pack(side="right", fill="y")

        btn_row2 = self._frame(parent)
        btn_row2.pack(fill="x", padx=14, pady=4)
        self._btn(btn_row2, "＋ Tambah CSV",
                  self._add_csv_files).pack(side="left", padx=4)
        self._btn(btn_row2, "✕ Hapus Terpilih",
                  self._remove_csv_selected,
                  color="#7a2030").pack(side="left", padx=4)
        self._btn(btn_row2, "⬜ Hapus Semua",
                  self._clear_csv_files,
                  color="#4a3000").pack(side="left", padx=4)

        self._sep(parent)

        # Layer editor
        self._label(parent, "DEFINISI LAYER LITOLOGI", bold=True,
                    color="#1ab8e0", size=10).pack(anchor="w", **pad)

        input_row = self._frame(parent)
        input_row.pack(fill="x", padx=14, pady=2)

        self._label(input_row, "Ketebalan (m):").pack(side="left")
        self.entry_thick = self._entry(input_row, width=10)
        self.entry_thick.pack(side="left", padx=6)

        self._label(input_row, "Kode (0-3):").pack(side="left")
        self.entry_code = self._entry(input_row, width=10)
        self.entry_code.pack(side="left", padx=6)

        self._btn(input_row, "＋ Tambah Layer",
                  self._add_layer).pack(side="left", padx=8)
        self._btn(input_row, "✕ Hapus Layer",
                  self._remove_layer,
                  color="#7a2030").pack(side="left", padx=4)

        legend_row = self._frame(parent)
        legend_row.pack(fill="x", padx=14, pady=(0, 2))
        self._label(legend_row,
            "Kode:  0 = Claystone  |  1 = Sandstone  |  2 = Coaly Shale  |  3 = Coal",
            color="#4a8a6a", size=8).pack(side="left")

        # Layer listbox
        layer_frame = self._frame(parent)
        layer_frame.pack(fill="x", padx=14, pady=2)

        self.layer_tree = ttk.Treeview(layer_frame,
            columns=("no", "thick", "code", "range"),
            show="headings", height=5)
        self.layer_tree.heading("no",    text="#")
        self.layer_tree.heading("thick", text="Ketebalan (m)")
        self.layer_tree.heading("code",  text="Kode")
        self.layer_tree.heading("range", text="Depth Range")
        self.layer_tree.column("no",    width=40)
        self.layer_tree.column("thick", width=130)
        self.layer_tree.column("code",  width=80)
        self.layer_tree.column("range", width=380)
        self.layer_tree.pack(fill="x")

        self._sep(parent)

        # Output dir
        self._label(parent, "FOLDER OUTPUT", bold=True,
                    color="#1ab8e0", size=10).pack(anchor="w", **pad)
        out_row2 = self._frame(parent)
        out_row2.pack(fill="x", padx=14, pady=2)
        self.litho_out_var = tk.StringVar()
        self._entry(out_row2, width=52,
                    textvariable=self.litho_out_var).pack(side="left")
        self._btn(out_row2, "📁 Browse",
                  self._pick_litho_out).pack(side="left", padx=6)

        self._sep(parent)

        # Progress & log
        self.litho_progress = ttk.Progressbar(parent, mode="determinate",
                                               length=700)
        self.litho_progress.pack(padx=14, pady=2, fill="x")

        self.litho_log = tk.Text(parent, height=5, bg="#0f1420",
                                  fg="#8aaccc", relief="flat",
                                  font=("Courier New", 8),
                                  state="disabled")
        self.litho_log.pack(padx=14, pady=2, fill="both", expand=True)

        self._btn(parent, "▶  APPLY LABEL LITOLOGI (BATCH)",
                  self._run_litho_batch,
                  color="#0e7a30", width=60).pack(pady=8)

        self._csv_files = []

    # ── Layer management ─────────────────────────────
    def _add_layer(self):
        try:
            thickness = float(self.entry_thick.get())
            code = int(self.entry_code.get())
            if thickness <= 0 or code not in [0, 1, 2, 3]:
                raise ValueError
        except:
            messagebox.showerror("Error",
                "Ketebalan harus > 0\nKode litologi: 0=Claystone, 1=Sandstone, 2=Coaly Shale, 3=Coal")
            return

        self.layers.append((thickness, code))
        self._refresh_layer_tree()
        self.entry_thick.delete(0, tk.END)
        self.entry_code.delete(0, tk.END)

    def _remove_layer(self):
        sel = self.layer_tree.selection()
        if not sel:
            return
        # Get row number from "#" column
        indices = sorted(
            [int(self.layer_tree.item(s)["values"][0]) - 1 for s in sel],
            reverse=True)
        for idx in indices:
            del self.layers[idx]
        self._refresh_layer_tree()

    def _refresh_layer_tree(self):
        for row in self.layer_tree.get_children():
            self.layer_tree.delete(row)
        top = 0.0
        for i, (thick, code) in enumerate(self.layers):
            bottom = top + thick
            self.layer_tree.insert("", "end", values=(
                i + 1,
                f"{thick:.2f}",
                code,
                f"{top:.2f} m  →  {bottom:.2f} m"
            ))
            top = bottom

    # ── CSV file management ──────────────────────────
    def _add_csv_files(self):
        files = filedialog.askopenfilenames(
            title="Pilih File CSV",
            filetypes=[("CSV files", "*.csv"), ("All", "*.*")])
        for f in files:
            if f not in self._csv_files:
                self._csv_files.append(f)
                self.csv_tree.insert("", "end",
                    values=(os.path.basename(f), "—"))

    def _remove_csv_selected(self):
        for sel in self.csv_tree.selection():
            fname = self.csv_tree.item(sel)["values"][0]
            self._csv_files = [f for f in self._csv_files
                               if os.path.basename(f) != fname]
            self.csv_tree.delete(sel)

    def _clear_csv_files(self):
        self._csv_files.clear()
        for row in self.csv_tree.get_children():
            self.csv_tree.delete(row)

    def _pick_litho_out(self):
        d = filedialog.askdirectory()
        if d:
            self.litho_out_var.set(d)

    # ── Run batch litho ──────────────────────────────
    def _run_litho_batch(self):
        if not self._csv_files:
            messagebox.showerror("Error", "Belum ada CSV dipilih.")
            return
        if not self.litho_out_var.get():
            messagebox.showerror("Error", "Pilih folder output dulu.")
            return
        if not self.layers:
            messagebox.showerror("Error", "Layer litologi masih kosong.")
            return

        self.litho_log.configure(state="normal")
        self.litho_log.delete("1.0", "end")
        self.litho_log.configure(state="disabled")

        def worker():
            total = len(self._csv_files)
            self.litho_progress["maximum"] = total
            self.litho_progress["value"] = 0
            ok = err = 0

            iid_map = {}
            for iid in self.csv_tree.get_children():
                fname = self.csv_tree.item(iid)["values"][0]
                iid_map[fname] = iid

            for i, fpath in enumerate(self._csv_files):
                name = os.path.basename(fpath)
                self._log(self.litho_log,
                    f"[{i+1}/{total}] Label: {name}", "info")
                try:
                    rows = apply_lithology_by_thickness(
                        fpath, self.layers, self.litho_out_var.get())
                    self._log(self.litho_log,
                        f"  ✔ OK  |  {rows} baris berlabel", "ok")
                    self.csv_tree.set(iid_map.get(name, ""), "status",
                                      f"✅ {rows} rows")
                    ok += 1
                except Exception as e:
                    self._log(self.litho_log,
                        f"  ✗ GAGAL — {e}", "err")
                    self.csv_tree.set(iid_map.get(name, ""), "status",
                                      "❌ Gagal")
                    err += 1

                self.litho_progress["value"] = i + 1
                self.root.update_idletasks()

            self._log(self.litho_log,
                f"\n══ SELESAI: {ok} berhasil, {err} gagal ══", "ok")
            messagebox.showinfo("Selesai",
                f"Batch Label Litologi selesai!\n✅ Berhasil: {ok}\n❌ Gagal: {err}")

        threading.Thread(target=worker, daemon=True).start()


# =====================================================
# ENTRY POINT
# =====================================================
if __name__ == "__main__":
    root = tk.Tk()
    app = WellLogApp(root)
    root.mainloop()
