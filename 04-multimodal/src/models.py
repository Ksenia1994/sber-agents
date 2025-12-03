from pydantic import BaseModel, Field, ConfigDict, field_validator
from datetime import date, time
from enum import Enum
from typing import Optional

class TransactionType(str, Enum):
    INCOME = "income"      # доход
    EXPENSE = "expense"    # расход

class TransactionFrequency(str, Enum):
    DAILY = "daily"           # повседневные
    PERIODIC = "periodic"     # периодические
    ONE_TIME = "one_time"     # разовые

class Transaction(BaseModel):
    date: date                           # дата транзакции
    time: Optional[str] = None            # время (опционально, хранится как строка HH:MM:SS)
    type: TransactionType                # доход/расход
    amount: float = Field(gt=0)          # сумма (строго положительная)
    frequency: TransactionFrequency       # тип (повседневные, периодические, разовые)
    category: str                        # категория (продукты, рестораны, такси и т.д.)
    description: str = ""                # описание транзакции (подробная информация о товарах, услугах, источнике, контрагенте и т.п.)
    
    def get_time(self) -> Optional[time]:
        """Преобразует строковое время в объект time"""
        if self.time is None:
            return None
        if isinstance(self.time, time):
            return self.time
        if isinstance(self.time, str):
            parts = self.time.split(':')
            if len(parts) >= 2:
                try:
                    hours = int(parts[0])
                    minutes = int(parts[1])
                    seconds = int(parts[2]) if len(parts) > 2 else 0
                    return time(hours, minutes, seconds)
                except (ValueError, IndexError, TypeError):
                    return None
        return None

class TransactionResponse(BaseModel):
    transactions: list[Transaction]  # список транзакций (всегда должен быть, пустой [] если не найдено)
    answer: str                     # текстовый ответ пользователю (обязателен)

