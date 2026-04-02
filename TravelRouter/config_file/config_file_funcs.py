import json
import os
from pathlib import Path
from threading import Lock
from typing import TypeVar

from pydantic import BaseModel

from TravelRouter.config_file.data_models import DataModels

DEFAULT_DATA_PATH = Path("./data/data.json")

ModelType = TypeVar("ModelType", bound=BaseModel)


def _model_dump(model: BaseModel) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _model_validate(model_type: type[ModelType], payload: dict) -> ModelType:
    if hasattr(model_type, "model_validate"):
        return model_type.model_validate(payload)
    return model_type.parse_obj(payload)


def _model_copy(model: ModelType) -> ModelType:
    if hasattr(model, "model_copy"):
        return model.model_copy(deep=True)
    return model.copy(deep=True)


class DataManager:
    _instance = None
    _instance_lock = Lock()

    def __new__(cls, data_path: Path | None = None):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, data_path: Path | None = None) -> None:
        if getattr(self, "_initialized", False):
            return

        configured_path = data_path or Path(os.getenv("TRAVELROUTER_DATA_FILE_PATH", DEFAULT_DATA_PATH))
        self.data_path = configured_path
        self._lock = Lock()
        self._data = self._load_data()
        self._write_data()
        self._initialized = True

    @classmethod
    def reset_instance(cls) -> None:
        with cls._instance_lock:
            cls._instance = None

    def get_data(self) -> DataModels:
        with self._lock:
            return _model_copy(self._data)

    def set_data(self, data: DataModels) -> None:
        with self._lock:
            self._data = _model_copy(data)
            self._write_data()

    def _load_data(self) -> DataModels:
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.data_path.exists():
            return DataModels()

        try:
            payload = json.loads(self.data_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Invalid data file at {self.data_path}") from exc

        return _model_validate(DataModels, payload)

    def _write_data(self) -> None:
        payload = json.dumps(_model_dump(self._data), indent=2) + "\n"
        temp_path = self.data_path.with_suffix(f"{self.data_path.suffix}.tmp")
        temp_path.write_text(payload, encoding="utf-8")
        temp_path.replace(self.data_path)
