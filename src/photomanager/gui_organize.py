"""Standalone GUI for the `organize` (date-folder sort) tool.

Tkinter ships with Python, so this needs no extra install and adds no
meaningful CPU/GPU/RAM cost beyond the scan itself (same work as the CLI).
Run with: python -m photomanager.gui_organize
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from .config import Config
from .organize import OrganizePlan, apply_plan, build_plan, summarize_plan


class OrganizeApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("사진 정리 도구 - 날짜 폴더로 이동")
        self.root.geometry("720x560")

        self.plan: OrganizePlan | None = None
        self._work_queue: queue.Queue = queue.Queue()

        self._build_widgets()

    def _build_widgets(self) -> None:
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill=tk.X)

        self.dir_var = tk.StringVar()
        ttk.Label(top, text="정리할 폴더:").pack(side=tk.LEFT)
        ttk.Entry(top, textvariable=self.dir_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        ttk.Button(top, text="찾아보기", command=self._choose_dir).pack(side=tk.LEFT)

        btns = ttk.Frame(self.root, padding=(10, 0))
        btns.pack(fill=tk.X)
        self.preview_btn = ttk.Button(btns, text="미리보기", command=self._run_preview)
        self.preview_btn.pack(side=tk.LEFT)
        self.apply_btn = ttk.Button(
            btns, text="실제로 정리하기 (이동)", command=self._run_apply, state=tk.DISABLED
        )
        self.apply_btn.pack(side=tk.LEFT, padx=6)

        self.status_var = tk.StringVar(value="폴더를 선택하고 미리보기를 눌러주세요.")
        ttk.Label(self.root, textvariable=self.status_var, padding=(10, 4)).pack(fill=tk.X)

        self.output = scrolledtext.ScrolledText(self.root, wrap=tk.WORD)
        self.output.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self.output.configure(state=tk.DISABLED)

    def _choose_dir(self) -> None:
        chosen = filedialog.askdirectory(title="정리할 폴더 선택")
        if chosen:
            self.dir_var.set(chosen)
            self.plan = None
            self.apply_btn.configure(state=tk.DISABLED)

    def _write_output(self, text: str) -> None:
        self.output.configure(state=tk.NORMAL)
        self.output.delete("1.0", tk.END)
        self.output.insert(tk.END, text)
        self.output.configure(state=tk.DISABLED)

    def _set_busy(self, busy: bool, status: str) -> None:
        self.status_var.set(status)
        state = tk.DISABLED if busy else tk.NORMAL
        self.preview_btn.configure(state=state)
        # apply_btn stays governed by whether a plan exists, handled by callers

    def _run_preview(self) -> None:
        directory = self.dir_var.get().strip()
        if not directory or not Path(directory).is_dir():
            messagebox.showerror("오류", "올바른 폴더를 선택하세요.")
            return

        self.apply_btn.configure(state=tk.DISABLED)
        self._set_busy(True, "스캔 중... (파일이 많으면 시간이 걸릴 수 있습니다)")
        self._write_output("")

        def worker() -> None:
            try:
                plan = build_plan(Path(directory), Config())
                self._work_queue.put(("preview_done", plan))
            except Exception as exc:  # surface any failure instead of freezing silently
                self._work_queue.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(100, self._poll_queue)

    def _run_apply(self) -> None:
        if self.plan is None or not self.plan.moves:
            return
        if not messagebox.askyesno(
            "확인",
            f"{len(self.plan.moves)}개 파일을 실제로 이동합니다.\n"
            "같은 이름의 다른 파일은 자동으로 (1)이 붙어 저장되며, 기존 파일을 덮어쓰지 않습니다.\n\n계속할까요?",
        ):
            return

        self._set_busy(True, "이동 중...")
        self.apply_btn.configure(state=tk.DISABLED)

        def worker() -> None:
            try:
                moved = apply_plan(self.plan)
                self._work_queue.put(("apply_done", moved))
            except Exception as exc:
                self._work_queue.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(100, self._poll_queue)

    def _poll_queue(self) -> None:
        try:
            kind, payload = self._work_queue.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_queue)
            return

        if kind == "preview_done":
            self.plan = payload
            self._write_output(summarize_plan(self.plan))
            self.apply_btn.configure(state=tk.NORMAL if self.plan.moves else tk.DISABLED)
            self._set_busy(False, f"미리보기 완료. 이동 대상 {len(self.plan.moves)}개.")
        elif kind == "apply_done":
            self._write_output(f"이동 완료: {payload}개\n\n다시 정리하려면 미리보기부터 다시 눌러주세요.")
            self.plan = None
            self.apply_btn.configure(state=tk.DISABLED)
            self._set_busy(False, "완료.")
        elif kind == "error":
            self._set_busy(False, "오류 발생")
            messagebox.showerror("오류", payload)


def main() -> None:
    root = tk.Tk()
    OrganizeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
