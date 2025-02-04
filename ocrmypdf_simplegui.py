#!/usr/bin/env python3

"""
OCRmyPDF SimpleGUI

This application provides an easy-to-use graphical user interface (GUI) for performing
Optical Character Recognition (OCR) on PDF files using the OCRmyPDF library. Users can
select input and output PDF files, configure OCR options, and execute the OCR process.
The application supports saving/loading settings and drag-and-drop functionality for
input files.

Dependencies:
- Python Libraries:
  - PyQt5: Install using `pip install PyQt5`
  - OCRmyPDF: Install using `pip install ocrmypdf`
- External Tools:
  - Tesseract OCR: OCR engine (apt-get install tesseract-ocr).
  - Ghostscript: PDF processing tool (apt-get install ghostscript).
  - Unpaper: Post-processing tool (apt-get install unpaper)

Usage:
Run the script using Python 3:
    python ocrmypdf_gui.py

Features:
- Select input and output PDF files
- Configure OCR options (deskew, language, rotate pages, etc.)
- Save and load settings
- Drag-and-drop support for input files
- Mouse pointer displays processing
- Open output file automatically after OCR
"""

DATEVERSION = "20250124-V01"
AUTHOR = "https://github.com/active-idle/OCRmyPDF-SimpleGUI"

import sys
import json
import os
import subprocess
import webbrowser
from typing import Dict, Any
from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QLineEdit, QPushButton, QTextEdit, QVBoxLayout, QHBoxLayout,
                             QGroupBox, QFileDialog, QCheckBox, QComboBox, QGridLayout, QSplitter, QProgressBar, QDialog, QSpacerItem, QSizePolicy)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QDragEnterEvent, QDropEvent, QIcon, QPixmap, QCursor
import io
from contextlib import redirect_stderr

SETTINGS_FILE = "." + os.path.splitext(os.path.basename(__file__))[0] + ".json"
PDF_FILTER = "PDF files (*.pdf)"
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
ICON_PATH = os.path.join(SCRIPT_DIR, 'ocrmypdf_simplegui.png')

class OCRWorker(QThread):
    finished = pyqtSignal(bool, str)
    error_buffer = io.StringIO()

    def __init__(self, input_file: str, output_file: str, options: Dict[str, Any]):
        super().__init__()
        self.input_file = input_file
        self.output_file = output_file
        self.options = options

    def run(self):
        """Run the OCR process in a separate thread."""
        try:
            from ocrmypdf import ocr
            self.clear_error_buffer()
            with redirect_stderr(self.error_buffer):
                ocr(self.input_file, self.output_file, **self.options)
            captured_output = self.error_buffer.getvalue().replace(' ', '&nbsp;').replace('\n', '<br>')
            captured_output = f'<font color="blue" face="Courier New, monospace">{captured_output}</font>'
            self.finished.emit(True, captured_output + "OCR process completed successfully!")
        except Exception as e:
            captured_output = self.error_buffer.getvalue().rstrip('\n')
            self.finished.emit(False, str(e) + captured_output)

    def clear_error_buffer(self):
        """Clear the error buffer."""
        self.error_buffer.truncate(0)
        self.error_buffer.seek(0)

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

        # Add a vertical spacer item
        spacer = QSpacerItem(20, 10, QSizePolicy.Minimum, QSizePolicy.Expanding)

        main_layout.addWidget(icon_label, 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
        main_layout.addItem(spacer, 0, 1)  # Add spacer between icon and text
        main_layout.addLayout(text_layout, 0, 2, Qt.AlignLeft | Qt.AlignVCenter)

        self.setLayout(main_layout)
        self.adjustSize()

class OCRmyPDFGUI(QWidget):
    """Main application window for OCRmyPDF SimpleGUI."""

    def __init__(self):
        """Initialize the application window and UI components."""
        super().__init__()
        self.ocr_performed = False
        self.initUI()
        self.load_settings()

    def initUI(self):
        """Set up the user interface layout and components."""
        self.setAcceptDrops(True)

        file_group_box = self.create_file_group_box()
        options_group_box = self.create_options_group_box()
        button_layout = self.create_button_layout()

        main_layout = QVBoxLayout()
        main_layout.addWidget(file_group_box)
        main_layout.addWidget(options_group_box)
        main_layout.addSpacing(10)  # Increase space before buttons
        main_layout.addLayout(button_layout)
        main_layout.addSpacing(10)  # Increase space after buttons
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

        self.rotate_pages_checkbox = QCheckBox("Rotate pages", self)
        self.skip_text_checkbox = QCheckBox("Skip text", self)

        options_layout = QGridLayout()
        options_layout.addWidget(self.deskew_checkbox, 0, 0)
        options_layout.addWidget(self.open_output_checkbox, 0, 1)
        options_layout.addWidget(self.force_ocr_checkbox, 1, 0)
        options_layout.addWidget(self.clean_final_checkbox, 1, 1)
        options_layout.addWidget(self.remove_background_checkbox, 2, 0)
        options_layout.addWidget(self.save_settings_checkbox, 2, 1)
        options_layout.addWidget(self.rotate_pages_checkbox, 3, 0)
        options_layout.addWidget(self.language_label, 3, 1)
        options_layout.addWidget(self.language_combo, 4, 1)
        options_layout.addWidget(self.skip_text_checkbox, 4, 0)
        self.language_combo.setMinimumWidth(300)
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
        """Perform the OCR process using the selected options."""
        input_file = self.input_entry.text()
        output_file = self.output_entry.text()

        if not input_file or not output_file:
            self.display_error_message("Please select both input and output files.")
            return

        options = self.collect_options()

        self.ocr_worker = OCRWorker(input_file, output_file, options)
        self.ocr_worker.finished.connect(self.ocr_finished)
        self.ocr_btn.setEnabled(False)
        self.set_busy_cursor()  # Set busy cursor
        self.ocr_worker.start()

    def ocr_finished(self, success: bool, message: str):
        """Handle the completion of the OCR process."""
        self.restore_cursor()
        self.ocr_btn.setEnabled(True)

        if success:
            self.output_text.append(message)
            if self.open_output_checkbox.isChecked():
                self.open_output_file(self.output_entry.text())
            self.ocr_performed = True
        else:
            self.display_error_message(f"Error during OCR process: {message}")

        if self.save_settings_checkbox.isChecked():
            self.save_settings()

    def collect_options(self):
        """Collect the OCR options from the UI."""
        return {
            'deskew': self.deskew_checkbox.isChecked(),
            'language': self.language_combo.currentText(),
            'rotate_pages': self.rotate_pages_checkbox.isChecked(),
            'force_ocr': self.force_ocr_checkbox.isChecked(),
            'skip_text': self.skip_text_checkbox.isChecked(),
            'remove_background': self.remove_background_checkbox.isChecked(),
            'clean_final': self.clean_final_checkbox.isChecked()
        }

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
        webbrowser.open("https://ocrmypdf.readthedocs.io/en/latest/")
        self.output_text.append("Opened OCRmyPDF documentation in the web browser.")

    def open_about(self):
        """Open the About dialog."""
        about_dialog = AboutDialog()
        about_dialog.exec_()

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
            "open_output": self.open_output_checkbox.isChecked(),
            "save_settings": self.save_settings_checkbox.isChecked()
        }
        with open(SETTINGS_FILE, "w") as file:
            json.dump(settings, file)
        self.output_text.append("Settings saved.\n")

    def load_settings(self):
        """Load settings from the JSON file if it exists."""
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r") as file:
                settings = json.load(file)
                self.input_entry.setText(settings.get("input_file", ""))
                self.output_entry.setText(settings.get("output_file", ""))
                self.deskew_checkbox.setChecked(settings.get("deskew", False))
                self.rotate_pages_checkbox.setChecked(settings.get("rotate_pages", False))
                self.force_ocr_checkbox.setChecked(settings.get("force_ocr", False))
                self.skip_text_checkbox.setChecked(settings.get("skip_text", False))
                self.remove_background_checkbox.setChecked(settings.get("remove_background", False))
                self.clean_final_checkbox.setChecked(settings.get("clean_final", False))
                self.language_combo.setCurrentText(settings.get("language", "eng"))
                self.open_output_checkbox.setChecked(settings.get("open_output", False))
                self.save_settings_checkbox.setChecked(settings.get("save_settings", False))
                self.output_text.append("Settings loaded.")

    def closeEvent(self, event):
        """Handle the close event to optionally save settings."""
        if self.save_settings_checkbox.isChecked():
            self.save_settings()
        event.accept()

    def set_busy_cursor(self):
        """Set the busy cursor during the OCR process."""
        QApplication.setOverrideCursor(Qt.BusyCursor)

    def update_cursor(self):
        """This method is no longer needed and can be removed."""
        pass

    def restore_cursor(self):
        """Restore the cursor to its default shape."""
        QApplication.restoreOverrideCursor()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    gui = OCRmyPDFGUI()
    sys.exit(app.exec_())
