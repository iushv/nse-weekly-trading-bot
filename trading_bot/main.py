from __future__ import annotations

from importlib import import_module


def main() -> None:
    root_main = import_module("main")
    root_main.main()


if __name__ == "__main__":
    main()
