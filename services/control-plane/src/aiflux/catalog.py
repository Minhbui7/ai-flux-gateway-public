import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class ModelEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(min_length=1, max_length=100)
    provider: str = Field(min_length=1, max_length=60)
    capabilities: list[str]
    enabled: bool
    backend_model: str = ""
    region: str = ""


class Catalog(BaseModel):
    model_config = ConfigDict(extra="forbid")
    models: list[ModelEntry]

    @classmethod
    def load(cls, path: Path) -> "Catalog":
        data = cls.model_validate(json.loads(path.read_text(encoding="utf-8")))
        if len({model.id for model in data.models}) != len(data.models):
            raise ValueError("Catalog contains duplicate model aliases")
        return data
