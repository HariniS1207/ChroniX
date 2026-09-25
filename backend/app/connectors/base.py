from abc import ABC, abstractmethod

from app.models.incident import Evidence


class Connector(ABC):
    @abstractmethod
    def collect(self) -> list[Evidence]:
        """Collect source data and normalize it into ChroniX evidence."""
        raise NotImplementedError
