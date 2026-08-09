## Goal
1. Save the translation (translated .epub) alongside the audiobook.
2. Make it obvious when the audiobook would be voiced from the ORIGINAL (untranslated) text.

## Steps
- [x] 1. Analyze code: app.py translation block, colab notebook, improved_translator.py, tkinter_ui.py.
- [x] 2. Confirm plan with user (items 1,2 approved).
- [x] 3. app.py: after translation, copy translated file into --output_dir (audiobooks_dir).
- [x] 4. app.py: print clear WARNING when conversion uses the ORIGINAL text (no translation).
- [x] 5. Notebooks/colab_ebook2audiobook.ipynb (cell 3): copy translated files to /content/out, offer download, save to Drive.
- [x] 6. Verify edits / logical flow.

## Verification results
- app.py: translation saved to tmp/translation, then copied into audiobooks_dir (sidecar) OK
- app.py: clear ВНИМАНИЕ warning when ORIGINAL text is used OK
- tkinter_ui.py: translation written directly into audiobooks_dir; PDF sidecar now uses .epub (matches _translate_pdf_file) OK
- Colab notebook: sidecar translations downloaded + saved to Drive OK
- Syntax validated (app.py, tkinter_ui.py, improved_translator.py); notebook JSON valid OK
