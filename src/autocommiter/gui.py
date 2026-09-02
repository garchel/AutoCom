from __future__ import annotations

import importlib
import logging
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, cast

from .controller import MonitorController

LOGGER = logging.getLogger(__name__)


class AutoCommiterApp:
    def __init__(self, controller: MonitorController, start_minimized: bool = False) -> None:
        self.controller = controller
        self.root = self._build_root()
        self.root.title("AutoCommiter")
        self.root.geometry("960x600")

        self.max_detections_var = tk.StringVar()
        self.detected_today_var = tk.StringVar()
        self.commits_today_var = tk.StringVar()
        self.update_repository_var = tk.StringVar()
        self.recent_commits_text = tk.StringVar()
        self.watched_file_var = tk.StringVar()
        self.daily_notes_directory_var = tk.StringVar()
        self.repository_path_var = tk.StringVar()
        self.status_var = tk.StringVar()
        self.randomized_number_var = tk.StringVar(value="-")
        self.today_note_path_var = tk.StringVar()
        self.today_note_created_var = tk.StringVar()
        self.today_note_identified_var = tk.StringVar()
        self.today_note_monitored_var = tk.StringVar()
        self._poll_queue: queue.Queue[None] = queue.Queue()
        self._poll_thread: threading.Thread | None = None
        self._tray_icon: Any = None
        self._commits_box: tk.Text | None = None

        self.content_frame = ttk.Frame(self.root, padding=16)
        self.content_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        sidebar = ttk.Frame(self.root, padding=12)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        ttk.Label(sidebar, text="AutoCommiter", font=("Segoe UI", 16, "bold")).pack(
            anchor=tk.W, pady=(0, 20)
        )
        ttk.Button(sidebar, text="Dashboard", command=self.show_dashboard).pack(
            fill=tk.X, pady=4
        )
        ttk.Button(
            sidebar, text="Arquivo monitorado", command=self.show_file_page
        ).pack(fill=tk.X, pady=4)

        self.show_dashboard()
        self.refresh_snapshots()
        if start_minimized:
            self.root.withdraw()
            self._start_tray_icon()
        else:
            self.root.after(1200, self.check_for_updates)
        self._start_polling_thread()

    def _build_root(self) -> Any:
        try:
            module = importlib.import_module("tkinterdnd2")
            return module.TkinterDnD.Tk()
        except ModuleNotFoundError:
            return tk.Tk()

    def run(self) -> None:
        self.root.mainloop()

    def refresh_snapshots(self) -> None:
        dashboard = self.controller.dashboard_snapshot()
        file_snapshot = self.controller.file_snapshot()

        self.max_detections_var.set(str(dashboard.max_detections_per_day))
        self.detected_today_var.set(str(dashboard.detected_changes_today))
        self.commits_today_var.set(str(dashboard.committed_changes_today))
        self.update_repository_var.set(dashboard.update_repository)
        self.recent_commits_text.set("\n".join(dashboard.recent_commits))
        if self._commits_box is not None:
            self._commits_box.config(state=tk.NORMAL)
            self._commits_box.delete("1.0", tk.END)
            self._commits_box.insert("1.0", "\n".join(dashboard.recent_commits))
            self._commits_box.config(state=tk.DISABLED)
        self.watched_file_var.set(file_snapshot.watched_file)
        self.daily_notes_directory_var.set(file_snapshot.daily_notes_directory)
        self.repository_path_var.set(file_snapshot.repository_path)
        self.status_var.set(file_snapshot.monitoring_status)
        self.today_note_path_var.set(file_snapshot.today_note_path)
        self.today_note_created_var.set(
            "Sim" if file_snapshot.today_note_created else "Nao"
        )
        self.today_note_identified_var.set(
            "Sim" if file_snapshot.today_note_identified else "Nao"
        )
        self.today_note_monitored_var.set(
            "Sim" if file_snapshot.today_note_monitored else "Nao"
        )

    def show_dashboard(self) -> None:
        self._clear_content()
        ttk.Label(
            self.content_frame, text="Dashboard", font=("Segoe UI", 18, "bold")
        ).pack(anchor=tk.W, pady=(0, 16))
        form = ttk.Frame(self.content_frame)
        form.pack(fill=tk.X)

        self._metric_row(
            form,
            "Maximo de vezes que a aplicacao ira detectar mudancas hoje",
            self.max_detections_var,
            editable=True,
            save_command=self.save_daily_limit,
        )
        self._metric_row(
            form, "Quantas vezes ja detectou a mudanca hoje", self.detected_today_var
        )
        self._metric_row(
            form, "Quantas vezes fez um commit da mudanca hoje", self.commits_today_var
        )
        self._metric_row(
            form,
            "Repositorio de updates (GitHub Releases)",
            self.update_repository_var,
            editable=True,
            save_command=self.save_update_repository,
        )
        ttk.Button(
            self.content_frame,
            text="Verificar atualizacoes",
            command=self.check_for_updates,
        ).pack(anchor=tk.W, pady=(16, 0))

        ttk.Label(
            self.content_frame, text="Ultimos commits", font=("Segoe UI", 12, "bold")
        ).pack(anchor=tk.W, pady=(16, 4))
        commits_frame = ttk.LabelFrame(
            self.content_frame, text="Historico (git log -10)"
        )
        commits_frame.pack(fill=tk.X, padx=12, pady=(0, 8))
        commits_box = tk.Text(commits_frame, height=6, wrap=tk.WORD, state=tk.DISABLED)
        commits_box.pack(fill=tk.X, padx=8, pady=8)
        self._commits_box = commits_box

    def show_file_page(self) -> None:
        self._clear_content()
        ttk.Label(
            self.content_frame,
            text="Arquivo monitorado",
            font=("Segoe UI", 18, "bold"),
        ).pack(anchor=tk.W, pady=(0, 16))

        drop_frame = ttk.LabelFrame(self.content_frame, text="Arquivo")
        drop_frame.pack(fill=tk.X, pady=(0, 12))
        drop_zone = tk.Text(drop_frame, height=4, wrap=tk.WORD)
        drop_zone.pack(fill=tk.X, padx=12, pady=12)
        drop_zone.insert(
            "1.0",
            "Arraste e solte um arquivo aqui ou use o botao abaixo para selecionar.",
        )
        drop_zone.configure(state=tk.DISABLED)
        self._bind_drop(drop_zone)
        ttk.Button(
            drop_frame, text="Selecionar arquivo", command=self.select_watched_file
        ).pack(anchor=tk.W, padx=12, pady=(0, 12))

        notes_frame = ttk.LabelFrame(
            self.content_frame, text="Pasta de notas diarias"
        )
        notes_frame.pack(fill=tk.X, pady=(0, 12))
        ttk.Entry(notes_frame, textvariable=self.daily_notes_directory_var).pack(
            fill=tk.X, padx=12, pady=(12, 8)
        )
        ttk.Button(
            notes_frame,
            text="Selecionar pasta",
            command=self.select_daily_notes_directory,
        ).pack(anchor=tk.W, padx=12, pady=(0, 8))
        ttk.Button(
            notes_frame,
            text="Salvar pasta e auto-descobrir nota do dia",
            command=self.save_daily_notes_directory,
        ).pack(anchor=tk.W, padx=12, pady=(0, 12))

        repo_frame = ttk.LabelFrame(self.content_frame, text="Repositorio")
        repo_frame.pack(fill=tk.X, pady=(0, 12))
        ttk.Entry(repo_frame, textvariable=self.repository_path_var).pack(
            fill=tk.X, padx=12, pady=(12, 8)
        )
        ttk.Button(
            repo_frame,
            text="Procurar pasta...",
            command=self.select_repository_path,
        ).pack(anchor=tk.W, padx=12, pady=(0, 8))
        ttk.Button(
            repo_frame, text="Salvar repositorio", command=self.save_repository_path
        ).pack(anchor=tk.W, padx=12, pady=(0, 12))

        info_frame = ttk.Frame(self.content_frame)
        info_frame.pack(fill=tk.X)
        self._metric_row(info_frame, "Arquivo monitorado", self.watched_file_var)
        self._metric_row(
            info_frame, "Pasta de notas diarias", self.daily_notes_directory_var
        )
        self._metric_row(
            info_frame, "Status de monitoramento do arquivo", self.status_var
        )
        self._metric_row(info_frame, "Nota de hoje esperada", self.today_note_path_var)
        self._metric_row(
            info_frame, "Nota de hoje ja foi criada", self.today_note_created_var
        )
        self._metric_row(
            info_frame,
            "Nota de hoje ja foi identificada",
            self.today_note_identified_var,
        )
        self._metric_row(
            info_frame,
            "Nota de hoje ja esta sendo monitorada",
            self.today_note_monitored_var,
        )
        self._metric_row(info_frame, "Numero atual randomizado", self.randomized_number_var)

        ttk.Button(
            self.content_frame,
            text="Randomizar numero no arquivo",
            command=self.randomize_number,
        ).pack(anchor=tk.W, pady=(16, 0))
        ttk.Button(
            self.content_frame,
            text="Monitorar nota de hoje",
            command=self.monitor_today_note,
        ).pack(anchor=tk.W, pady=(8, 0))

    def _metric_row(
        self,
        parent: ttk.Frame,
        label: str,
        variable: tk.StringVar,
        editable: bool = False,
        save_command: Any | None = None,
    ) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=8)
        ttk.Label(row, text=label).pack(anchor=tk.W)
        entry = ttk.Entry(row, textvariable=variable)
        if not editable:
            entry.state(["readonly"])
        entry.pack(fill=tk.X, pady=(4, 0), side=tk.LEFT, expand=True)
        if editable and save_command is not None:
            ttk.Button(row, text="Salvar", command=save_command).pack(
                side=tk.LEFT, padx=(8, 0)
            )

    def save_daily_limit(self) -> None:
        try:
            value = int(self.max_detections_var.get())
            self.controller.save_limits(value)
        except ValueError as exc:
            messagebox.showerror("Valor invalido", str(exc))
            return
        self.refresh_snapshots()

    def save_update_repository(self) -> None:
        try:
            self.controller.save_update_repository(self.update_repository_var.get())
        except ValueError as exc:
            messagebox.showerror("Repositorio invalido", str(exc))
            return
        self.refresh_snapshots()

    def _choose_directory(self, title: str, initialdir: str | None = None) -> str | None:
        # Helper centralizado: garante titulo em PT-BR e usa dialogo moderno
        # No Windows 10/11 o askdirectory mapeia para IFileDialog com botao "Selecionar Pasta"
        # O titulo deixa claro que a confirmacao e "Selecionar Pasta" (ou "Abrir/OK" em SOs antigos)
        try:
            initial = initialdir or str(Path.home())
            # mustexist garante que so pastas existentes sao aceitas
            selected = filedialog.askdirectory(
                parent=self.root,
                title=title,
                initialdir=initial,
                mustexist=True,
            )
            return selected or None
        except Exception:
            # Fallback sem parent/mustexist para compatibilidade com versoes antigas do Tk
            try:
                return filedialog.askdirectory(title=title) or None
            except Exception:
                return None

    def _choose_file(self, title: str) -> str | None:
        try:
            selected = filedialog.askopenfilename(
                parent=self.root,
                title=title,
            )
            return selected or None
        except Exception:
            return filedialog.askopenfilename(title=title) or None

    def select_watched_file(self) -> None:
        selected = self._choose_file(title="Selecionar arquivo monitorado")
        if not selected:
            return
        self.controller.update_watched_file(selected)
        self.refresh_snapshots()

    def select_daily_notes_directory(self) -> None:
        # Titulo explicito faz IFileDialog mostrar "Selecionar Pasta" em PT-BR
        # Em SO antigo mostra "OK/Abrir" - titulo esclarece a ação
        current = self.daily_notes_directory_var.get().strip()
        initial = current or str(self.controller.config.daily_notes_directory or Path.home())
        selected = self._choose_directory(
            title="Selecionar pasta de notas diárias",
            initialdir=initial,
        )
        if not selected:
            return
        self.daily_notes_directory_var.set(selected)
        # Auto-salva apos dialogo para nao exigir clique extra em "Salvar"
        # Botao "Salvar..." permanece para edicao manual no Entry
        try:
            self.controller.update_daily_notes_directory(selected)
        except ValueError as exc:
            messagebox.showerror("Pasta invalida", str(exc))
            return
        self.refresh_snapshots()
        messagebox.showinfo(
            "Pasta selecionada",
            f"Pasta de notas diárias definida para:\n{selected}\n\nNota do dia auto-descoberta.",
        )

    def select_repository_path(self) -> None:
        current = self.repository_path_var.get().strip()
        initial = current or str(self.controller.config.repository_path or Path.home())
        selected = self._choose_directory(
            title="Selecionar pasta do repositório Git",
            initialdir=initial,
        )
        if not selected:
            return
        self.repository_path_var.set(selected)

    def save_daily_notes_directory(self) -> None:
        try:
            self.controller.update_daily_notes_directory(
                self.daily_notes_directory_var.get()
            )
        except ValueError as exc:
            messagebox.showerror("Pasta invalida", str(exc))
            return
        self.refresh_snapshots()

    def save_repository_path(self) -> None:
        try:
            self.controller.update_repository_path(self.repository_path_var.get())
        except ValueError as exc:
            messagebox.showerror("Repositorio invalido", str(exc))
            return
        self.refresh_snapshots()

    def randomize_number(self) -> None:
        try:
            generated_number = self.controller.randomize_watched_number()
        except Exception as exc:
            messagebox.showerror("Falha ao randomizar", str(exc))
            return
        self.randomized_number_var.set(str(generated_number))
        self.refresh_snapshots()

    def monitor_today_note(self) -> None:
        try:
            note_path = self.controller.monitor_today_note()
        except Exception as exc:
            messagebox.showerror("Falha ao monitorar nota de hoje", str(exc))
            return
        self.watched_file_var.set(str(note_path))
        self.refresh_snapshots()

    def check_for_updates(self) -> None:
        try:
            result = self.controller.check_for_update()
        except Exception as exc:
            messagebox.showerror("Falha ao verificar atualizacoes", str(exc))
            return
        if result is None:
            return

        if result.selected_asset is None:
            messagebox.showinfo(
                "Atualizacao disponivel",
                f"Versao {result.latest_version} encontrada, sem asset suportado para download.",
            )
            return

        should_download = messagebox.askyesno(
            "Atualizacao disponivel",
            (
                f"Nova versao encontrada: {result.latest_version}\n"
                f"Versao atual: {result.current_version}\n\n"
                f"Deseja baixar agora o asset {result.selected_asset.name}?"
            ),
        )
        if not should_download:
            return

        try:
            asset_path = self.controller.download_update(result)
        except Exception as exc:
            messagebox.showerror("Falha no download", str(exc))
            return

        should_restart = messagebox.askyesno(
            "Download concluido",
            (
                f"Arquivo baixado em:\n{asset_path}\n\n"
                "Deseja reiniciar agora para aplicar a atualizacao?"
            ),
        )
        if not should_restart:
            return

        self.controller.apply_update_on_restart(asset_path, os.getpid())
        self.root.destroy()

    def _clear_content(self) -> None:
        for widget in self.content_frame.winfo_children():
            widget.destroy()
        # commits box is destroyed with dashboard, reset reference
        self._commits_box = None

    def _start_polling_thread(self) -> None:
        try:
            self._poll_queue = queue.Queue()
            self._poll_thread = threading.Thread(
                target=self._poll_worker, daemon=True, name="autocommiter-poll"
            )
            self._poll_thread.start()
            self.root.after(100, self._poll_tick)
        except Exception as exc:
            LOGGER.exception("Falha ao iniciar thread de polling: %s", exc)

    def _poll_worker(self) -> None:
        while True:
            try:
                self._poll_queue.get()
            except Exception:
                pass
            try:
                self.controller.poll_once()
                # Schedule UI refresh on main thread (thread-safe via after)
                self.root.after(0, self.refresh_snapshots)
            except Exception as exc:
                LOGGER.exception("Poll worker failed: %s", exc)
                self.root.after(0, self.refresh_snapshots)
            try:
                self._poll_queue.task_done()
            except ValueError:
                pass

    def _poll_tick(self) -> None:
        try:
            self._poll_queue.put(None, timeout=0)
        except queue.Full:
            pass
        try:
            self.root.after(2000, self._poll_tick)
        except Exception:
            pass

    def _start_tray_icon(self) -> None:
        try:
            import pystray
            from pystray import Menu, MenuItem
        except ModuleNotFoundError:
            LOGGER.warning(
                "pystray não disponível; iniciando minimizado sem ícone no tray"
            )
            return
        try:
            icon = pystray.Icon(
                "autocommiter",
                menu=Menu(
                    MenuItem("Mostrar", self._show_window),
                    MenuItem("Sair", self._exit_app),
                ),
            )
            icon.title = "AutoCommiter"
            icon.run(set_up=self._tray_setup)
            self._tray_icon = icon
        except Exception as exc:
            LOGGER.exception("Falha ao iniciar ícone de tray: %s", exc)


    def _tray_setup(self, icon: Any) -> None:
        try:
            icon.icon = self._build_tray_image()
        except Exception:
            pass

    def _build_tray_image(self) -> Any:
        from PIL import Image, ImageDraw

        image = Image.new("RGB", (64, 64), "systembuttonface")
        draw = ImageDraw.Draw(image)
        draw.rectangle([8, 8, 56, 56], outline="black", width=2)
        draw.text((22, 22), "A", fill="black")
        return image

    def _show_window(self) -> None:
        if self._tray_icon is not None:
            self._tray_icon.stop()
            self._tray_icon = None
        self.root.deiconify()
        self.root.lift()

    def _exit_app(self) -> None:
        if self._tray_icon is not None:
            self._tray_icon.stop()
            self._tray_icon = None
        self.root.quit()

    def _bind_drop(self, widget: tk.Text) -> None:
        try:
            module = importlib.import_module("tkinterdnd2")
        except ModuleNotFoundError:
            return
        drop_widget = cast(Any, widget)
        drop_widget.drop_target_register(module.DND_FILES)
        drop_widget.dnd_bind("<<Drop>>", self._on_drop)

    def _on_drop(self, event: Any) -> None:
        raw_path = str(event.data).strip()
        cleaned = raw_path.strip("{}")
        if not cleaned:
            return
        if not Path(cleaned).exists():
            messagebox.showerror("Arquivo invalido", "O arquivo solto nao existe.")
            return
        self.controller.update_watched_file(cleaned)
        self.refresh_snapshots()
