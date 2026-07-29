#!/usr/bin/env python3
"""
ebook2audiobook - Tkinter GUI Version
Convert eBooks to audiobooks with chapters and metadata
"""

import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    try:
        # Import and run the tkinter GUI
        from tkinter_ui import main as tkinter_main
        tkinter_main()
    except ImportError as e:
        print(f"Error importing tkinter UI: {e}")
        print("Make sure all dependencies are installed.")
        sys.exit(1)
    except Exception as e:
        print(f"Error running tkinter UI: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()