"""Export one private local source; never uploads or writes formal memory."""
import argparse
import json
from pathlib import Path

from fish_story.service import GameService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session_id')
    parser.add_argument('--home', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(GameService(args.home).export_evidence(args.session_id, args.output), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
