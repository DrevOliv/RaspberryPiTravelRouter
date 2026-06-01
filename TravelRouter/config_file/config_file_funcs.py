import json
import os
from pathlib import Path
from threading import Lock

from TravelRouter.config_file.data_models import DataModels

# Anchor to the repo root (<repo>/data/data.json) so the path does not depend
# on the process working directory.
DEFAULT_DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "data.json"


class DataManager:
    # Singleton: constructor arguments (data_path) are only honoured on the
    # first instantiation. Call reset_instance() before re-constructing with a
    # different path, e.g. in tests.
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
            return self._data.model_copy(deep=True)

    def set_data(self, data: DataModels) -> None:
        with self._lock:
            self._data = data.model_copy(deep=True)
            self._write_data()

    def _load_data(self) -> DataModels:
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.data_path.exists():
            return DataModels()

        try:
            payload = json.loads(self.data_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Invalid data file at {self.data_path}") from exc

        return DataModels.model_validate(payload)

    def _write_data(self) -> None:
        payload = json.dumps(self._data.model_dump(), indent=2) + "\n"
        temp_path = self.data_path.with_suffix(f"{self.data_path.suffix}.tmp")
        temp_path.write_text(payload, encoding="utf-8")
        temp_path.replace(self.data_path)
