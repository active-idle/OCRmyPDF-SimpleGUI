# OCRmyPDF-SimpleGUI

Lightweight PyQt5 desktop frontend for `ocrmypdf`.

It lets you select input/output PDFs, choose common OCR options, and run OCR while
watching live command output in the GUI.

<img src="./gui.png" width="400" alt="OCRmyPDF-SimpleGUI screenshot">

## Features

- OCR a PDF through `python -m ocrmypdf`
- Live progress output in the Messages panel
- Full command preview before execution (highlighted)
- Common OCR options (deskew, rotate pages, force OCR, skip text, etc.)
- Optimization level selector (`0` to `3`)
- Dependency pre-check for required external tools
- Drag-and-drop PDF input
- Optional persistent settings

## Requirements

### Python packages

- `PyQt5`
- `ocrmypdf`

Install:

```bash
pip install PyQt5 ocrmypdf
```

### External tools

- `tesseract`
- `ghostscript` (`gs` on Linux/macOS, `gswin64c`/`gswin32c` on Windows)
- `pngquant` (required when Optimize is `2` or `3`)
- `unpaper` (commonly used by OCRmyPDF on Linux)

## Run

From inside this folder:

```bash
python ocrmypdf_simplegui.py
```

From the project root:

```bash
python OCRmyPDF-SimpleGUI/ocrmypdf_simplegui.py
```

## Behavior Notes

- `Force OCR` and `Skip text` are mutually exclusive in the UI.
- Input/output validation is done before OCR starts:
  - both paths must be set
  - input must exist and be a `.pdf`
  - output must end with `.pdf`
  - input and output must be different files
  - output directory must exist
- OCRmyPDF errors are condensed to short GUI messages when possible.

## Settings

If **Save settings** is enabled, settings are stored in:

`OCRmyPDF-SimpleGUI/.ocrmypdf_simplegui.json`

The file is created when settings are actually saved (for example after OCR or on app close).

## Known OCRmyPDF Limitation

Some OCRmyPDF versions may return:

`"--remove-background" is temporarily not implemented`

for certain page types. This is an upstream OCRmyPDF behavior.

## Donation

Thank you very much for a donation in recognition of my work:
[![PayPal Donate](https://img.shields.io/badge/paypal-donate-yellow.svg)](https://www.paypal.com/paypalme/MrDagoo/)
