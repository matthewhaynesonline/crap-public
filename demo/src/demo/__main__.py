import subprocess
import sys
from pathlib import Path


def dev() -> None:
    app_path = Path(__file__).parent / "app.py"
    sys.exit(subprocess.call(["gradio", str(app_path)]))


def main() -> None:
    from demo.app import main as demo_main

    demo_main()


if __name__ == "__main__":
    main()
