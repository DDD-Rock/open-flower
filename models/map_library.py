"""Windows 地图库持久化。"""

import os
from pathlib import Path
from typing import Optional

from models.map_topology import MapTopology, MapTransferService


class MapLibraryStore:
    def __init__(self, path: Optional[str] = None):
        if path:
            self.path = Path(path)
        else:
            base = Path(os.environ.get("APPDATA") or Path.home())
            self.path = base / "YzY-Auto-Buff" / "maps.json"

    def load(self) -> list[MapTopology]:
        try:
            return MapTransferService.load(self.path)
        except (FileNotFoundError, OSError, ValueError):
            return []

    def save(self, maps: list[MapTopology]):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        MapTransferService.save(self.path, maps)

    def import_file(self, path: str):
        imported = MapTransferService.load(path)
        merged, added, replaced = MapTransferService.merge(imported, self.load())
        self.save(merged)
        return merged, added, replaced

    def export_file(self, path: str, maps: Optional[list[MapTopology]] = None):
        MapTransferService.save(path, maps if maps is not None else self.load())
