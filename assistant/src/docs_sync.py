from pathlib import Path
import shutil
from typing import Union


def docs_folder_rel(graph_key: str) -> str:
    return f"kbs/{graph_key.replace('_', '-')}"


def copy_docs_tree(source_dir: Union[Path, str], destination_dir: Union[Path, str]) -> None:
    source = Path(source_dir)
    destination = Path(destination_dir)

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)

    shutil.copytree(source, destination)