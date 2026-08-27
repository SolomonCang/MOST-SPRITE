"""Normalize grpc_tools imports for the checked-in Python package."""

from pathlib import Path


def main() -> None:
    target = Path("backend/src/most_sprite/schemas/generated/device_agent_pb2_grpc.py")
    source = target.read_text(encoding="utf-8")
    source = source.replace(
        "import device_agent_pb2 as device__agent__pb2",
        "from . import device_agent_pb2 as device__agent__pb2",
    )
    target.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
