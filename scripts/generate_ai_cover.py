"""Manual entry point for the built-in AI cover service."""
import argparse
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from akifactory.ai_cover import generate

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--entry", required=True)
    args = parser.parse_args()
    asyncio.run(generate(args.entry))
