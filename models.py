from beanie import Document, Link
from pydantic import BaseModel, Field
from typing import List, Optional


class CustomizationOption(BaseModel):
    value: str
    label: str
    price_impact: float = 0


class Customization(BaseModel):
    id: str
    name: str
    type: str
    options: List[CustomizationOption]
    required: bool = False


class Addon(BaseModel):
    id: str
    name: str
    price: float


class Category(Document):
    """
    A Category document.
    We add 'legacy_id' to store the original 'id' from the JSON.
    """
    name: str
    description: Optional[str] = None
    legacy_id: int = Field(..., unique=True)  #

    class Settings:
        name = "categories"


class MenuItem(Document):
    """
    A MenuItem document.
    It links to a Category and embeds customizations/addons.
    """
    name: str
    description: Optional[str] = None
    price: float
    imageSrc: str

    category: Link[Category]
    customizations: List[Customization] = []
    addons: List[Addon] = []

    legacy_id: int = Field(..., unique=True)

    class Settings:
        name = "menu_items"  # This is the collection name in MongoDB