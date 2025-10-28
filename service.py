from typing import Any, Dict, List
import json
import os


class Repository:

    database: Dict[str, Any] = {}

    @classmethod
    def initialize_database(cls, path: str = "database.json") -> None:
        if not os.path.exists(path):
            cls.database = {"categories": [], "menu_items": []}
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                cls.database = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Could not parse JSON in {path}: {exc}") from exc

    @classmethod
    def get_categories(cls) -> List[Dict[str, Any]]:
        return cls.database.get("categories", [])

    @classmethod
    def get_items_by_category(cls, category_id: int) -> List[Dict[str, Any]]:
        items = cls.database.get("menu_items", [])
        return [item for item in items if item.get("category_id") == category_id]
