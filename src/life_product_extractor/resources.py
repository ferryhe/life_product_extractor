from __future__ import annotations

from importlib.resources import as_file, files
from pathlib import Path
from typing import Iterator
import contextlib


RESOURCE_ROOT = files("life_product_extractor").joinpath("resources")


def resource_text(relative_path: str) -> str:
    return RESOURCE_ROOT.joinpath(relative_path).read_text()


@contextlib.contextmanager
def resource_path(relative_path: str) -> Iterator[Path]:
    with as_file(RESOURCE_ROOT.joinpath(relative_path)) as path:
        yield path
