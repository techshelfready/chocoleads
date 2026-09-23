from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List
from ..models import Lead

class LeadSource(ABC):
    name: str = "base"

    @abstractmethod
    def search(self, zipcode: str, limit: int, category: str) -> List[Lead]:
        raise NotImplementedError
