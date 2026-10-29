"""Console-only entry point, including MCP stdio without launcher messages."""
from fish_story.cli import main


if __name__ == '__main__':
    raise SystemExit(main())
