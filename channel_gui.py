# AIGC START
"""海康录像机数字通道按表格就位 — 图形界面。账号密码登录，不用 SessionTag。"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from channel_core import (
    NvrClient,
    NvrOptions,
    apply_assignments,
    normalize_base_url,
    parse_table,
    sort_assignments,
)

SAMPLE = (
    "192.168.22.50\t2层仓库内监控靠近工装房\td18\n"
    "192.168.22.47\t2层仓库内工装房 旁边的小房\td21\n"
    "192.168.22.46\t2层仓库内监控靠近仓库入口2\td15\n"
    "192.168.22.132\t15层6号（走廊）\n"
    "192.168.22.36\t2层消防梯口\t待分配252\n"
)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("海康通道按表格就位")
        self.geometry("980x780")
        self.minsize(860, 680)

        self._stop = False
        self._running = False

        pad = {"padx": 12, "pady": 4}
        root = ttk.Frame(self)
        root.pack(fill=tk.BOTH, expand=True, **pad)

        tip = (
            "从 Excel 复制粘贴：监控 IP、位置名称、目标通道（d18，插空模式可省略）。\n"
            "就位模式：按 D 号升序强制落到目标通道，并核对断层。\n"
            "插空模式：不强制目标 D，有空位就加，由海康自动排号。"
        )
        ttk.Label(root, text=tip, justify=tk.LEFT).pack(anchor="w", pady=(0, 8))

        form = ttk.Frame(root)
        form.pack(fill=tk.X)
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        self.nvr_url = tk.StringVar(value="http://192.168.22.252")
        self.nvr_user = tk.StringVar(value="admin")
        self.nvr_pass = tk.StringVar(value="")
        self.cam_user = tk.StringVar(value="admin")
        self.cam_pass = tk.StringVar(value="")
        self.protocol = tk.StringVar(value="HIKVISION")
        self.cam_port = tk.StringVar(value="8000")
        self.timeout = tk.StringVar(value="25")
        self.settle = tk.StringVar(value="3")
        self.digital_start = tk.StringVar(value="1")
        self.dry_run = tk.BooleanVar(value=True)
        self.fill_gaps = tk.BooleanVar(value=False)

        self._pair(form, 0, 0, "录像机地址", self.nvr_url)
        self._pair(form, 0, 2, "协议", None, combo=True)
        self._pair(form, 1, 0, "录像机用户名", self.nvr_user)
        self._pair(form, 1, 2, "录像机密码", self.nvr_pass, show="*")
        self._pair(form, 2, 0, "摄像头用户名", self.cam_user)
        self._pair(form, 2, 2, "摄像头密码", self.cam_pass, show="*")

        extra = ttk.Frame(form)
        extra.grid(row=3, column=0, columnspan=4, sticky="ew", pady=2)
        ttk.Label(extra, text="摄像头端口", width=12).pack(side=tk.LEFT)
        ttk.Entry(extra, textvariable=self.cam_port, width=8).pack(side=tk.LEFT)
        ttk.Label(extra, text="超时(秒)", width=10).pack(side=tk.LEFT, padx=(16, 0))
        ttk.Entry(extra, textvariable=self.timeout, width=8).pack(side=tk.LEFT)
        ttk.Label(extra, text="删后等待(秒)", width=12).pack(side=tk.LEFT, padx=(16, 0))
        ttk.Entry(extra, textvariable=self.settle, width=6).pack(side=tk.LEFT)
        ttk.Label(extra, text="通道起点", width=10).pack(side=tk.LEFT, padx=(16, 0))
        ttk.Entry(extra, textvariable=self.digital_start, width=6).pack(side=tk.LEFT)
        mode_row = ttk.Frame(form)
        mode_row.grid(row=4, column=0, columnspan=4, sticky="ew", pady=4)
        ttk.Checkbutton(
            mode_row, text="只演练，不真正增删通道", variable=self.dry_run
        ).pack(side=tk.LEFT)
        ttk.Checkbutton(
            mode_row,
            text="插空模式（不强制目标 D，有空就加，海康自动排）",
            variable=self.fill_gaps,
        ).pack(side=tk.LEFT, padx=16)

        ttk.Label(
            root,
            text="通道名单（Excel 直接粘贴：IP、名称、d号；插空模式可无 d号）",
        ).pack(anchor="w", pady=(10, 2))
        self.names = tk.Text(root, height=12, font=("Consolas", 10))
        self.names.pack(fill=tk.BOTH, expand=False)
        self.names.insert("1.0", SAMPLE)

        btns = ttk.Frame(root)
        btns.pack(fill=tk.X, pady=8)
        ttk.Button(btns, text="检查名单", command=self.preview_names).pack(side=tk.LEFT)
        ttk.Button(btns, text="读取当前通道", command=self.refresh_live).pack(
            side=tk.LEFT, padx=8
        )
        ttk.Button(btns, text="清空名单", command=self.clear_names).pack(side=tk.LEFT)
        self.stop_btn = ttk.Button(
            btns, text="停止", command=self.request_stop, state=tk.DISABLED
        )
        self.stop_btn.pack(side=tk.LEFT, padx=8)
        self.start_btn = ttk.Button(btns, text="开始就位", command=self.start)
        self.start_btn.pack(side=tk.RIGHT)

        table_frm = ttk.Frame(root)
        table_frm.pack(fill=tk.BOTH, expand=True)
        cols = ("通道", "IP", "名称", "协议")
        self.tree = ttk.Treeview(table_frm, columns=cols, show="headings", height=8)
        for c, w in zip(cols, (70, 140, 280, 100)):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="w")
        sy = ttk.Scrollbar(table_frm, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sy.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sy.pack(side=tk.RIGHT, fill=tk.Y)

        ttk.Label(root, text="运行日志").pack(anchor="w", pady=(8, 2))
        self.log = tk.Text(
            root, height=10, font=("Consolas", 9), bg="#1e1e1e", fg="#dddddd"
        )
        self.log.pack(fill=tk.BOTH, expand=True)
        self.log.configure(state=tk.DISABLED)

        self.status = tk.StringVar(value="就绪 · 默认演练模式")
        ttk.Label(root, textvariable=self.status).pack(anchor="w", pady=(4, 0))

    def _pair(
        self,
        parent: ttk.Frame,
        row: int,
        col: int,
        label: str,
        var: tk.StringVar | None,
        show: str | None = None,
        combo: bool = False,
    ) -> None:
        ttk.Label(parent, text=label, width=12).grid(
            row=row, column=col, sticky="w", pady=2, padx=(0, 4)
        )
        if combo:
            box = ttk.Combobox(
                parent,
                textvariable=self.protocol,
                values=("HIKVISION", "ONVIF", "GB28181"),
                state="readonly",
                width=16,
            )
            box.grid(row=row, column=col + 1, sticky="ew", pady=2)
            return
        kw: dict = {"textvariable": var}
        if show is not None:
            kw["show"] = show
        ttk.Entry(parent, **kw).grid(row=row, column=col + 1, sticky="ew", pady=2)

    def append_log(self, msg: str) -> None:
        def _do() -> None:
            self.log.configure(state=tk.NORMAL)
            self.log.insert(tk.END, msg + "\n")
            self.log.see(tk.END)
            self.log.configure(state=tk.DISABLED)

        self.after(0, _do)

    def clear_names(self) -> None:
        self.names.delete("1.0", tk.END)

    def request_stop(self) -> None:
        self._stop = True
        self.append_log("正在停止…（当前这一路会做完）")

    def _parsed(self):
        return parse_table(
            self.names.get("1.0", tk.END),
            allow_no_channel=self.fill_gaps.get(),
        )

    def preview_names(self) -> None:
        fill = self.fill_gaps.get()
        result = self._parsed()
        if not result.items:
            extra = "\n".join(result.skipped[:8])
            tip = (
                "插空模式可只贴 IP + 名称。\n"
                if fill
                else "请从 Excel 粘贴三列：IP、名称、d18\n"
            )
            messagebox.showwarning(
                "检查名单",
                "没有解析到有效行。\n" + tip + "\n" + extra,
            )
            return
        if fill:
            show = result.items
            lines = [
                f"{a.ip}  {a.name}"
                + (f"  （表中 D{a.channel_id}，仅作参考）" if a.channel_id > 0 else "")
                for a in show[:25]
            ]
            title_extra = "插空模式 · 粘贴顺序 · 落到下一空位"
        else:
            show = sort_assignments(result.items)
            lines = [
                f"D{a.channel_id}  ←  {a.ip}  {a.name}" for a in show[:25]
            ]
            title_extra = "就位模式 · 已按 D 号升序"
        more = "" if len(show) <= 25 else f"\n… 还有 {len(show) - 25} 条"
        warn = ""
        if result.warnings:
            warn = "\n\n警告：\n" + "\n".join(result.warnings[:8])
        skip = ""
        if result.skipped:
            skip = f"\n\n已忽略 {len(result.skipped)} 行"
        messagebox.showinfo(
            "检查名单",
            f"将处理 {len(show)} 条（{title_extra}）：\n\n"
            + "\n".join(lines)
            + more
            + warn
            + skip,
        )

    def _nvr_options(self) -> NvrOptions:
        cam_user = self.cam_user.get().strip() or self.nvr_user.get().strip()
        cam_pass = self.cam_pass.get() or self.nvr_pass.get()
        return NvrOptions(
            base_url=normalize_base_url(self.nvr_url.get()),
            nvr_user=self.nvr_user.get().strip(),
            nvr_password=self.nvr_pass.get(),
            cam_user=cam_user,
            cam_password=cam_pass,
            protocol=self.protocol.get().strip() or "HIKVISION",
            cam_port=int(self.cam_port.get().strip() or "8000"),
            timeout=float(self.timeout.get().strip() or "25"),
            settle_seconds=float(self.settle.get().strip() or "3"),
            digital_start=int(self.digital_start.get().strip() or "1"),
        )

    def refresh_live(self) -> None:
        if self._running:
            messagebox.showinfo("提示", "正在执行，请稍候")
            return
        try:
            opt = self._nvr_options()
        except ValueError as exc:
            messagebox.showwarning("参数", str(exc))
            return
        if not opt.nvr_user or not opt.nvr_password:
            messagebox.showwarning("缺少信息", "请填写录像机用户名和密码")
            return

        def worker() -> None:
            try:
                client = NvrClient(opt)
                name = client.ping()
                channels = client.list_channels()

                def fill() -> None:
                    for i in self.tree.get_children():
                        self.tree.delete(i)
                    for cid in sorted(channels):
                        ch = channels[cid]
                        self.tree.insert(
                            "",
                            tk.END,
                            values=(f"D{cid}", ch.ip, ch.name, ch.protocol),
                        )
                    self.status.set(f"已读取 {len(channels)} 路 · 设备 {name}")
                    self.append_log(f"读取通道完成：{len(channels)} 路（{name}）")

                self.after(0, fill)
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: messagebox.showerror("读取失败", str(exc)))
                self.append_log(f"读取失败：{exc}")

        threading.Thread(target=worker, daemon=True).start()

    def start(self) -> None:
        if self._running:
            return
        result = self._parsed()
        try:
            opt = self._nvr_options()
        except ValueError as exc:
            messagebox.showwarning("参数", str(exc))
            return
        if not opt.nvr_user or not opt.nvr_password:
            messagebox.showwarning("缺少信息", "请填写录像机用户名和密码")
            return
        if not result.items:
            messagebox.showwarning("缺少名单", "没有解析到有效行。请先点「检查名单」。")
            return
        if result.warnings and not messagebox.askyesno(
            "名单有警告",
            "\n".join(result.warnings[:10]) + "\n\n仍要继续？",
        ):
            return
        dry = self.dry_run.get()
        fill = self.fill_gaps.get()
        mode_name = "插空" if fill else "就位"
        if not dry and not messagebox.askyesno(
            "真正写入",
            f"将在 {opt.base_url} 上以【{mode_name}】模式处理 {len(result.items)} 路，"
            f"不可轻易撤销。\n确定继续？",
        ):
            return

        self._stop = False
        self._running = True
        self.start_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        mode = "只演练" if dry else "真正写入"
        self.status.set(f"{mode}·{mode_name}中… {len(result.items)} 条")
        self.append_log("=" * 60)
        self.append_log(
            f"{opt.base_url}  ·  {mode}  ·  {mode_name}  ·  协议 {opt.protocol}"
        )
        for s in result.skipped[:12]:
            self.append_log(s)
        if len(result.skipped) > 12:
            self.append_log(f"… 另忽略 {len(result.skipped) - 12} 行")

        def worker() -> None:
            try:
                client = NvrClient(opt)
                device = client.ping()
                self.append_log(f"已登录：{device}")
                stats = apply_assignments(
                    client,
                    result.items,
                    dry_run=dry,
                    on_log=self.append_log,
                    should_stop=lambda: self._stop,
                    fill_gaps=fill,
                )

                def done_ok() -> None:
                    self.status.set(
                        f"完成 · 成功/演练 {stats.ok} · 跳过 {stats.skip} · 失败 {stats.fail}"
                    )

                self.after(0, done_ok)
            except Exception as exc:  # noqa: BLE001
                self.append_log(f"中止：{exc}")
                self.after(0, lambda: self.status.set(f"失败：{exc}"))
            finally:
                self.after(0, self._finished)

        threading.Thread(target=worker, daemon=True).start()

    def _finished(self) -> None:
        self._running = False
        self.start_btn.configure(state=tk.NORMAL)
        self.stop_btn.configure(state=tk.DISABLED)


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
# AIGC END
