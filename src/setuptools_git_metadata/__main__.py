"""Write a standard runtime loader for a consuming package."""

import argparse
from pathlib import Path
import sys
from importlib import resources


def main() -> None:
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


def write_template(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Write the selected template to stdout or a new file."""
    content = resources.files(__package__).joinpath("_version.py").read_text(encoding="utf-8")
    if args.output is None:
        sys.stdout.write(content)
    else:
        try:
            with args.output.open("x", encoding="utf-8", newline="") as stream:
                stream.write(content)
        except OSError as error:
            parser.error(str(error))


if __name__ == "__main__":
    main()
