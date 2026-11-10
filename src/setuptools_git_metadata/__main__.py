"""Write a standard runtime loader for a consuming package."""

import argparse
from pathlib import Path
import sys
from .template import standard_template


def main():
    """Print the loader or exclusively create a requested source file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["template"])
    parser.add_argument(
        "--output", type=Path, help="create a new file without overwriting an existing file"
    )
    args = parser.parse_args()
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
