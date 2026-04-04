#!/usr/bin/env python3

"""
OCRmyPDF SimpleGUI.

Small PyQt5 frontend for running OCRmyPDF on local PDF files.
The app executes `python -m ocrmypdf` in a worker thread and streams
sanitized progress output into the GUI.

Settings are stored in a JSON file next to this script:
`.ocrmypdf_simplegui.json`.
"""

DATEVERSION = "20260403-V01"
AUTHOR = "https://github.com/active-idle/OCRmyPDF-SimpleGUI"

import sys
import json
import os
import subprocess
import webbrowser
import shutil
import re
import html
import shlex
import pty
import select
from typing import Any, Dict, Optional, Tuple
from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QLineEdit, QPushButton, QTextEdit, QVBoxLayout, QHBoxLayout,
                             QGroupBox, QFileDialog, QCheckBox, QComboBox, QGridLayout, QSplitter, QDialog, QSpacerItem, QSizePolicy, QToolButton, QToolTip)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QDragEnterEvent, QDropEvent, QIcon, QPixmap

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
SETTINGS_FILE = os.path.join(SCRIPT_DIR, "." + os.path.splitext(os.path.basename(__file__))[0] + ".json")
PDF_FILTER = "PDF files (*.pdf)"
ICON_PATH = os.path.join(SCRIPT_DIR, 'ocrmypdf_simplegui.png')
OCRMYPDF_DOCS_URL = "https://ocrmypdf.readthedocs.io/en/latest/"


def _prepend_host_bin_path():
    """Expose host binaries when running from a containerized/dev environment."""
    host_bin = "/run/host/bin"
    current_path = os.environ.get("PATH", "")
    if os.path.isdir(host_bin) and host_bin not in current_path.split(os.pathsep):
        os.environ["PATH"] = host_bin + os.pathsep + current_path


_prepend_host_bin_path()

class OCRWorker(QThread):
    finished = pyqtSignal(bool, str)
    progress = pyqtSignal(str)

    def __init__(self, input_file: str, output_file: str, options: Dict[str, Any]):
        super().__init__()
        self.input_file = input_file
        self.output_file = output_file
        self.options = options

    def run(self):
        """Run the OCR process in a separate thread."""
        try:
            self.ensure_external_dependencies()
            captured_text = self.run_cli_fallback()
            captured_output = html.escape(captured_text).replace(' ', '&nbsp;').replace('\n', '<br>')
            captured_output = f'<font color="blue" face="Courier New, monospace">{captured_output}</font>'
            if captured_output and captured_output != '<font color="blue" face="Courier New, monospace"></font>':
                self.finished.emit(True, captured_output + "<br><br>OCR process completed successfully!")
            else:
                self.finished.emit(True, "OCR process completed successfully!")
        except Exception as e:
            self.finished.emit(False, str(e))

    def ensure_external_dependencies(self):
        """Validate required external tools before invoking OCRmyPDF."""
        missing = []

        if not shutil.which("tesseract"):
            missing.append("tesseract")

        if sys.platform == "win32":
            gs_cmds = ("gswin64c", "gswin32c", "gs")
        else:
            gs_cmds = ("gs",)
        if not any(shutil.which(cmd) for cmd in gs_cmds):
            missing.append("ghostscript (gs)")

        optimize_level = int(self.options.get("optimize", 1))
        if optimize_level >= 2 and not shutil.which("pngquant"):
            missing.append("pngquant (required for optimize levels 2 and 3)")

        if missing:
            raise RuntimeError(
                "Missing external tools on PATH: "
                + ", ".join(missing)
                + ". Install them and restart the app from the same terminal."
            )

    def run_cli_fallback(self):
        """Run OCRmyPDF via CLI with equivalent options and stream progress output."""
        cmd = [sys.executable, "-m", "ocrmypdf"]

        if self.options.get("deskew"):
            cmd.append("--deskew")
        if self.options.get("language"):
            cmd.extend(["--language", str(self.options["language"])])
        if "optimize" in self.options:
            cmd.extend(["--optimize", str(self.options["optimize"])])
        if self.options.get("rotate_pages"):
            cmd.append("--rotate-pages")
        if self.options.get("force_ocr"):
            cmd.append("--force-ocr")
        if self.options.get("skip_text"):
            cmd.append("--skip-text")
        if self.options.get("remove_background"):
            cmd.append("--remove-background")
        if self.options.get("clean_final"):
            cmd.append("--clean-final")

        cmd.extend([self.input_file, self.output_file])
        self.progress.emit(f"$ {self._format_command_for_display(cmd)}")
        self.progress.emit("Starting OCRmyPDF...")

        lines = []
        in_traceback = False
        suppress_progress_after_error = False

        def emit_line(raw_line):
            nonlocal in_traceback, suppress_progress_after_error
            line = self._clean_terminal_line(raw_line)
            if not line:
                return

            # Suppress verbose traceback internals from the live progress stream.
            if line.startswith("Traceback (most recent call last):"):
                in_traceback = True
                return
            if in_traceback:
                if re.match(r"^[A-Za-z_]+Error:", line):
                    in_traceback = False
                else:
                    return

            if line and (not lines or lines[-1] != line):
                lines.append(line)
                # Keep progress area clean: once an error starts, show only final red message.
                if line.startswith("An exception occurred while executing the pipeline"):
                    suppress_progress_after_error = True
                    return
                if re.match(r"^[A-Za-z_]+Error:", line):
                    suppress_progress_after_error = True
                    return
                if not suppress_progress_after_error:
                    self.progress.emit(line)

        if os.name == "posix":
            master_fd = None
            slave_fd = None
            process = None
            buffer = []
            try:
                master_fd, slave_fd = pty.openpty()
                process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    close_fds=True,
                )
                os.close(slave_fd)
                slave_fd = None

                while True:
                    ready, _, _ = select.select([master_fd], [], [], 0.2)
                    if ready:
                        try:
                            chunk = os.read(master_fd, 4096).decode("utf-8", errors="replace")
                        except OSError:
                            break
                        if not chunk:
                            if process.poll() is not None:
                                break
                            continue

                        for char in chunk:
                            if char in ("\r", "\n"):
                                if buffer:
                                    emit_line("".join(buffer))
                                    buffer = []
                            else:
                                buffer.append(char)

                    if process.poll() is not None and not ready:
                        break

                if buffer:
                    emit_line("".join(buffer))
                returncode = process.wait()
            except Exception as e:
                if process is None:
                    returncode = self._run_cli_fallback_pipe(cmd, emit_line)
                else:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            process.kill()
                    raise RuntimeError(f"Failed while streaming OCRmyPDF output: {e}") from e
            finally:
                if slave_fd is not None:
                    try:
                        os.close(slave_fd)
                    except OSError:
                        pass
                if master_fd is not None:
                    try:
                        os.close(master_fd)
                    except OSError:
                        pass
        else:
            returncode = self._run_cli_fallback_pipe(cmd, emit_line)

        output_text = "\n".join(lines).strip()
        if returncode != 0:
            raise RuntimeError(self._summarize_cli_error(output_text, returncode))
        return output_text

    def _format_command_for_display(self, cmd) -> str:
        """Render command list as a shell-like string for the GUI log."""
        if os.name == "nt":
            return subprocess.list2cmdline(cmd)
        return shlex.join(cmd)

    def _clean_terminal_line(self, text: str) -> str:
        """Strip ANSI/OSC control sequences and unreadable control chars."""
        # OSC hyperlinks/title sequences (e.g. \x1b]8;;url\x1b\\label\x1b]8;;\x1b\\)
        text = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", text)
        # CSI ANSI sequences
        text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
        # Any remaining single ESC-prefixed codes
        text = re.sub(r"\x1b[@-_]", "", text)
        # Remove leftover control chars except tab/newline/carriage return
        text = re.sub(r"[\x00-\x08\x0B-\x1F\x7F]", "", text)
        return text.strip()

    def _summarize_cli_error(self, output_text: str, returncode: int) -> str:
        """Convert verbose CLI errors into concise, actionable GUI messages."""
        text = (output_text or "").strip()
        lower = text.lower()
        lower_compact = re.sub(r"\s+", " ", lower)

        if "remove-background is temporarily not implemented" in lower_compact:
            return (
                '"--remove-background" is temporarily not implemented '
                "(raised by OCRmyPDF preprocess_remove_background in _pipeline.py)"
            )

        if "page already has text" in lower:
            return (
                "Input PDF already contains text. Use 'Force OCR' to OCR all pages, "
                "or 'Skip text' to leave text pages unchanged."
            )

        if text:
            lines = [line for line in text.splitlines() if line.strip()]
            tail = lines[-12:] if len(lines) > 12 else lines
            return "\n".join(tail)

        return f"ocrmypdf exited with code {returncode}"

    def _run_cli_fallback_pipe(self, cmd, emit_line):
        """Fallback streaming mode for platforms where PTY is unavailable."""
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        buffer = []

        while True:
            char = process.stdout.read(1)
            if char == "" and process.poll() is not None:
                break
            if not char:
                continue
            if char in ("\r", "\n"):
                if buffer:
                    emit_line("".join(buffer))
                    buffer = []
                continue
            buffer.append(char)

        if buffer:
            emit_line("".join(buffer))
        return process.wait()

class AboutDialog(QDialog):
    def __init__(self):
        """Initialize the About dialog."""
        super().__init__()
        self.setWindowTitle("About OCRmyPDF SimpleGUI")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint & ~Qt.WindowSystemMenuHint)
        self.setWindowIcon(QIcon(ICON_PATH))

        main_layout = QGridLayout()

        text_layout = QVBoxLayout()
        version_label = QLabel(f"Version: {DATEVERSION}")
        github_label = QLabel(f"Author: <a href='{AUTHOR}'>{AUTHOR}</a>")
        github_label.setOpenExternalLinks(True)
        text_layout.addWidget(version_label)
        text_layout.addWidget(github_label)

        icon_label = QLabel()
        pixmap = QPixmap(ICON_PATH)
        scaled_pixmap = pixmap.scaled(70, 70, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        icon_label.setPixmap(scaled_pixmap)

        spacer = QSpacerItem(20, 10, QSizePolicy.Minimum, QSizePolicy.Expanding)

        main_layout.addWidget(icon_label, 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
        main_layout.addItem(spacer, 0, 1)
        main_layout.addLayout(text_layout, 0, 2, Qt.AlignLeft | Qt.AlignVCenter)

        self.setLayout(main_layout)
        self.adjustSize()

class OCRmyPDFGUI(QWidget):
    """Main application window for OCRmyPDF SimpleGUI."""

    def __init__(self):
        """Initialize the application window and UI components."""
        super().__init__()
        self.initUI()
        self.load_settings()

    def initUI(self):
        """Build the main window and connect core actions."""
        self.setAcceptDrops(True)

        file_group_box = self.create_file_group_box()
        options_group_box = self.create_options_group_box()
        button_layout = self.create_button_layout()

        main_layout = QVBoxLayout()
        main_layout.addWidget(file_group_box)
        main_layout.addWidget(options_group_box)
        main_layout.addSpacing(10)
        main_layout.addLayout(button_layout)
        main_layout.addSpacing(10)
        main_layout.addWidget(self.create_splitter())

        self.setLayout(main_layout)
        self.setWindowTitle('OCRmyPDF SimpleGUI')
        self.setWindowIcon(QIcon(ICON_PATH))
        self.resize(600, 400)
        self.show()
        self.output_text.append("Please load an input file.")

        self.ocr_btn.setShortcut('Ctrl+O')
        self.help_btn.setShortcut('F1')

    def create_file_group_box(self):
        """Create the file selection group box."""
        file_group_box = QGroupBox("File Selection")

        self.input_label = QLabel('Input PDF File:', self)
        self.input_entry = QLineEdit(self)
        self.input_entry.setMinimumWidth(300)
        self.input_browse_btn = QPushButton('Browse', self)
        self.input_browse_btn.clicked.connect(self.select_input_file)

        self.output_label = QLabel('Output PDF File:', self)
        self.output_entry = QLineEdit(self)
        self.output_entry.setMinimumWidth(300)
        self.output_browse_btn = QPushButton('Browse', self)
        self.output_browse_btn.clicked.connect(self.select_output_file)

        file_layout = QGridLayout()
        file_layout.addWidget(self.input_label, 0, 0)
        file_layout.addWidget(self.input_entry, 0, 1)
        file_layout.addWidget(self.input_browse_btn, 0, 2)
        file_layout.addWidget(self.output_label, 1, 0)
        file_layout.addWidget(self.output_entry, 1, 1)
        file_layout.addWidget(self.output_browse_btn, 1, 2)
        file_group_box.setLayout(file_layout)

        return file_group_box

    def create_options_group_box(self):
        """Create the OCR options group box."""
        options_group_box = QGroupBox("Options")

        self.deskew_checkbox = QCheckBox("Deskew pages", self)
        self.open_output_checkbox = QCheckBox("Open output file", self)
        self.force_ocr_checkbox = QCheckBox("Force OCR", self)
        self.clean_final_checkbox = QCheckBox("Clean final", self)
        self.remove_background_checkbox = QCheckBox("Remove background", self)
        self.save_settings_checkbox = QCheckBox("Save settings", self)

        self.language_label = QLabel('Language:', self)
        self.language_combo = QComboBox(self)
        self.language_combo.addItems(["deu", "eng", "fra", "spa", "ita", "nld", "por", "rus", "chi_sim", "jpn"])
        self.language_combo.setCurrentText("eng")
        self.language_combo.setMinimumWidth(70)
        self.language_combo.setMaximumWidth(90)

        self.optimize_label = QLabel('Optimize:', self)
        self.optimize_combo = QComboBox(self)
        self.optimize_combo.addItems(["0", "1", "2", "3"])
        self.optimize_combo.setCurrentText("1")
        self.optimize_combo.setMinimumWidth(70)
        self.optimize_combo.setMaximumWidth(90)
        self.optimize_info_btn = QToolButton(self)
        self.optimize_info_btn.setText("i")
        self.optimize_info_btn.setFixedSize(16, 16)
        self.optimize_info_btn.setStyleSheet(
            "QToolButton {"
            "background-color: #1e88e5;"
            "color: white;"
            "border: none;"
            "border-radius: 8px;"
            "font-weight: bold;"
            "font-size: 10px;"
            "padding: 0px;"
            "}"
        )
        self.optimize_info_btn.setToolTip(
            "PDF optimization level:\n"
            "0 = off\n"
            "1 = lossless (default)\n"
            "2 = some lossy optimization\n"
            "3 = most aggressive optimization"
        )
        self.optimize_info_btn.setAutoRaise(True)
        self.optimize_info_btn.clicked.connect(self.show_optimize_info)

        self.rotate_pages_checkbox = QCheckBox("Rotate pages", self)
        self.skip_text_checkbox = QCheckBox("Skip text", self)
        self.force_ocr_checkbox.toggled.connect(self.on_force_ocr_toggled)
        self.skip_text_checkbox.toggled.connect(self.on_skip_text_toggled)

        options_layout = QGridLayout()
        options_layout.setHorizontalSpacing(10)
        options_layout.setVerticalSpacing(10)
        options_layout.setColumnStretch(0, 1)
        options_layout.setColumnStretch(1, 1)
        options_layout.setColumnStretch(2, 0)
        options_layout.addWidget(self.deskew_checkbox, 0, 0)
        options_layout.addWidget(self.open_output_checkbox, 0, 1)
        options_layout.addWidget(self.language_label, 0, 2)
        options_layout.addWidget(self.force_ocr_checkbox, 1, 0)
        options_layout.addWidget(self.clean_final_checkbox, 1, 1)
        options_layout.addWidget(self.language_combo, 1, 2)
        options_layout.addWidget(self.remove_background_checkbox, 2, 0)
        options_layout.addWidget(self.save_settings_checkbox, 2, 1)
        optimize_label_layout = QHBoxLayout()
        optimize_label_layout.setContentsMargins(0, 0, 0, 0)
        optimize_label_layout.setSpacing(5)
        optimize_label_layout.addWidget(self.optimize_label)
        optimize_label_layout.addWidget(self.optimize_info_btn)
        optimize_label_layout.addStretch()
        options_layout.addLayout(optimize_label_layout, 2, 2)
        options_layout.addWidget(self.rotate_pages_checkbox, 3, 0)
        options_layout.addWidget(self.skip_text_checkbox, 3, 1)
        options_layout.addWidget(self.optimize_combo, 3, 2)
        options_group_box.setLayout(options_layout)

        return options_group_box

    def create_button_layout(self):
        """Create the button layout."""
        self.ocr_btn = QPushButton('Perform OCR', self)
        self.ocr_btn.clicked.connect(self.perform_ocr)

        self.help_btn = QPushButton('Help', self)
        self.help_btn.clicked.connect(self.open_help)

        self.about_btn = QPushButton('About', self)
        self.about_btn.clicked.connect(self.open_about)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.ocr_btn)
        button_layout.addWidget(self.help_btn)
        button_layout.addWidget(self.about_btn)

        return button_layout

    def create_splitter(self):
        """Create the splitter for messages."""
        self.messages_label = QLabel('Messages:', self)
        self.output_text = QTextEdit(self)
        self.output_text.setReadOnly(True)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.messages_label)
        splitter.addWidget(self.output_text)

        return splitter

    def select_input_file(self):
        """Open a file dialog to select the input PDF file."""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Input PDF File", "", PDF_FILTER)
        if file_path:
            self.input_entry.setText(file_path)
            self.output_text.append(f"Selected input file: {file_path}")
            self.set_default_output_file(file_path)

    def select_output_file(self):
        """Open a file dialog to select the output PDF file."""
        file_path, _ = QFileDialog.getSaveFileName(self, "Select Output PDF File", "", PDF_FILTER)
        if file_path:
            self.output_entry.setText(file_path)
            self.output_text.append(f"Selected output file: {file_path}")

    def set_default_output_file(self, input_file):
        """Set the default output file name based on the input file."""
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        default_output_name = os.path.join(os.path.dirname(input_file), f"{base_name}_OCRed.pdf").replace("\\", "/")
        self.output_entry.setText(default_output_name)
        self.output_text.append(f"Default output file set to: {default_output_name}")

    def perform_ocr(self):
        """Validate paths and start OCR in a background worker thread."""
        validated_paths = self.validate_paths(self.input_entry.text(), self.output_entry.text())
        if not validated_paths:
            return
        input_file, output_file = validated_paths

        options = self.collect_options()

        self.ocr_worker = OCRWorker(input_file, output_file, options)
        self.ocr_worker.finished.connect(self.ocr_finished)
        self.ocr_worker.progress.connect(self.ocr_progress)
        self.ocr_btn.setEnabled(False)
        self.set_busy_cursor()
        self.ocr_worker.start()

    def ocr_finished(self, success: bool, message: str):
        """Handle the completion of the OCR process."""
        self.restore_cursor()
        self.ocr_btn.setEnabled(True)

        if success:
            self.output_text.append(message)
            if self.open_output_checkbox.isChecked():
                self.open_output_file(self.output_entry.text())
        else:
            self.display_error_message(f"Error during OCR process: {message}")

        if self.save_settings_checkbox.isChecked():
            self.save_settings()

    def ocr_progress(self, message: str):
        """Append live OCR progress output in monospace blue text."""
        safe_text = html.escape(message).replace(' ', '&nbsp;')
        if message.startswith("$ "):
            self.output_text.append(
                '<span style="color:#0b5394; background-color:#eaf3ff; '
                'font-family:\'Courier New\', monospace; font-weight:600;">'
                f"{safe_text}</span>"
            )
            return
        self.output_text.append(f'<font color="blue" face="Courier New, monospace">{safe_text}</font>')

    def collect_options(self):
        """Collect the OCR options from the UI."""
        return {
            'deskew': self.deskew_checkbox.isChecked(),
            'language': self.language_combo.currentText(),
            'optimize': int(self.optimize_combo.currentText()),
            'rotate_pages': self.rotate_pages_checkbox.isChecked(),
            'force_ocr': self.force_ocr_checkbox.isChecked(),
            'skip_text': self.skip_text_checkbox.isChecked(),
            'remove_background': self.remove_background_checkbox.isChecked(),
            'clean_final': self.clean_final_checkbox.isChecked()
        }

    def validate_paths(self, input_file: str, output_file: str) -> Optional[Tuple[str, str]]:
        """Validate and normalize input/output paths before running OCR."""
        input_file = input_file.strip()
        output_file = output_file.strip()

        if not input_file or not output_file:
            self.display_error_message("Please select both input and output files.")
            return None

        input_abs = os.path.abspath(input_file)
        output_abs = os.path.abspath(output_file)

        if not os.path.isfile(input_abs):
            self.display_error_message(f"Input file does not exist: {input_abs}")
            return None

        if not input_abs.lower().endswith(".pdf"):
            self.display_error_message("Input file must be a PDF (*.pdf).")
            return None

        if not output_abs.lower().endswith(".pdf"):
            self.display_error_message("Output file must end with .pdf.")
            return None

        if input_abs == output_abs:
            self.display_error_message("Input and output files must be different.")
            return None

        output_dir = os.path.dirname(output_abs) or "."
        if not os.path.isdir(output_dir):
            self.display_error_message(f"Output directory does not exist: {output_dir}")
            return None

        self.input_entry.setText(input_abs)
        self.output_entry.setText(output_abs)
        return input_abs, output_abs

    def on_force_ocr_toggled(self, checked: bool):
        """Prevent selecting Force OCR together with Skip text."""
        if checked and self.skip_text_checkbox.isChecked():
            self.skip_text_checkbox.setChecked(False)
            self.output_text.append("Disabled 'Skip text' because it conflicts with 'Force OCR'.")
        self.skip_text_checkbox.setEnabled(not checked)

    def on_skip_text_toggled(self, checked: bool):
        """Prevent selecting Skip text together with Force OCR."""
        if checked and self.force_ocr_checkbox.isChecked():
            self.force_ocr_checkbox.setChecked(False)
            self.output_text.append("Disabled 'Force OCR' because it conflicts with 'Skip text'.")
        self.force_ocr_checkbox.setEnabled(not checked)

    def display_error_message(self, message):
        """Display an error message in the output text area."""
        self.output_text.setTextColor(Qt.red)
        self.output_text.append(message)
        self.output_text.setTextColor(Qt.black)

    def open_output_file(self, file_path):
        """Open the output file using the default application."""
        if sys.platform == "win32":
            os.startfile(file_path)
        elif sys.platform == "darwin":
            subprocess.call(["open", file_path])
        else:
            subprocess.call(["xdg-open", file_path])

    def open_help(self):
        """Open the OCRmyPDF documentation in the web browser."""
        webbrowser.open(OCRMYPDF_DOCS_URL)
        self.output_text.append("Opened OCRmyPDF documentation in the web browser.")

    def open_about(self):
        """Open the About dialog."""
        about_dialog = AboutDialog()
        about_dialog.exec_()

    def show_optimize_info(self):
        """Show optimization explanation when the info button is clicked."""
        QToolTip.showText(
            self.optimize_info_btn.mapToGlobal(self.optimize_info_btn.rect().bottomLeft()),
            self.optimize_info_btn.toolTip(),
            self.optimize_info_btn
        )

    def dragEnterEvent(self, event: QDragEnterEvent):
        """Handle drag enter events."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        """Handle drop events."""
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if file_path.lower().endswith('.pdf'):
                self.input_entry.setText(file_path)
                self.output_text.append(f"Dragged and dropped input file: {file_path}")
                self.set_default_output_file(file_path)
                break

    def save_settings(self):
        """Save the current settings to a JSON file."""
        settings = {
            "input_file": self.input_entry.text(),
            "output_file": self.output_entry.text(),
            "deskew": self.deskew_checkbox.isChecked(),
            "rotate_pages": self.rotate_pages_checkbox.isChecked(),
            "force_ocr": self.force_ocr_checkbox.isChecked(),
            "skip_text": self.skip_text_checkbox.isChecked(),
            "remove_background": self.remove_background_checkbox.isChecked(),
            "clean_final": self.clean_final_checkbox.isChecked(),
            "language": self.language_combo.currentText(),
            "optimize": self.optimize_combo.currentText(),
            "open_output": self.open_output_checkbox.isChecked(),
            "save_settings": self.save_settings_checkbox.isChecked()
        }
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as file:
                json.dump(settings, file)
        except OSError as e:
            self.display_error_message(f"Could not save settings: {e}")
            return
        self.output_text.append("Settings saved.\n")

    def load_settings(self):
        """Load settings from the JSON file if it exists."""
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as file:
                    settings = json.load(file)
            except (OSError, json.JSONDecodeError) as e:
                self.display_error_message(f"Could not load settings: {e}")
                return

            self.input_entry.setText(settings.get("input_file", ""))
            self.output_entry.setText(settings.get("output_file", ""))
            self.deskew_checkbox.setChecked(settings.get("deskew", False))
            self.rotate_pages_checkbox.setChecked(settings.get("rotate_pages", False))
            self.force_ocr_checkbox.setChecked(settings.get("force_ocr", False))
            self.skip_text_checkbox.setChecked(settings.get("skip_text", False))
            self.remove_background_checkbox.setChecked(settings.get("remove_background", False))
            self.clean_final_checkbox.setChecked(settings.get("clean_final", False))
            self.language_combo.setCurrentText(settings.get("language", "eng"))
            self.optimize_combo.setCurrentText(str(settings.get("optimize", "1")))
            self.open_output_checkbox.setChecked(settings.get("open_output", False))
            self.save_settings_checkbox.setChecked(settings.get("save_settings", False))
            self.on_force_ocr_toggled(self.force_ocr_checkbox.isChecked())
            self.on_skip_text_toggled(self.skip_text_checkbox.isChecked())
            self.output_text.append("Settings loaded.")

    def closeEvent(self, event):
        """Handle the close event to optionally save settings."""
        if self.save_settings_checkbox.isChecked():
            self.save_settings()
        event.accept()

    def set_busy_cursor(self):
        """Set the busy cursor during the OCR process."""
        QApplication.setOverrideCursor(Qt.BusyCursor)

    def restore_cursor(self):
        """Restore the cursor to its default shape."""
        QApplication.restoreOverrideCursor()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    gui = OCRmyPDFGUI()
    sys.exit(app.exec_())
