"""Write a standard runtime loader for a consuming package."""

import argparse
from pathlib import Path
import sys
from .template import standard_template


def main():
    """Print the loader or exclusively create a requested source file."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    template = commands.add_parser("template", help="write the standard runtime loader")
    template.add_argument(
        "--output", type=Path, help="create a new file without overwriting an existing file"
    )
    args = parser.parse_args()
    if args.command == "template":
        write_template(args, parser)


def write_template(args, parser):
    """Write the selected template to stdout or a new file."""
    if args.output is None:
        sys.stdout.write(standard_template())
    else:
        try:
            with args.output.open("x", encoding="utf-8", newline="") as stream:
                stream.write(standard_template())
        except OSError as error:
            parser.error(str(error))


if __name__ == "__main__":
    main()
