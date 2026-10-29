"""PyInstaller entry point; the desktop lifecycle lives in the application."""
from fish_story.desktop import main


if __name__ == '__main__':
    raise SystemExit(main())
