#!/usr/bin/env python3
"""Frozen (PyInstaller) launcher for the ebook2audiobook Windows folder build.

app.py is NOT used here on purpose: in NATIVE mode it pip-installs missing
requirements, which is impossible/undesirable inside a frozen bundle. All
runtime data (models/, tmp/, audiobooks/) lives next to the executable, so the
working directory is forced there first - lib/conf.py builds every path from
the current working directory.
"""
import os
import sys

if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))


def main():
    from tkinter_ui import main as tkinter_main
    tkinter_main()


if __name__ == '__main__':
    main()
