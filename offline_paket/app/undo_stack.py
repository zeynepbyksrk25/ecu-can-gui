"""Kalibrasyon yazımları için geri al / yinele yığını (Qt'siz).

Yalnızca BAŞARIYLA yazılıp ECU'dan doğrulanmış değişiklikler girer. Geri alma/yineleme ECU'ya yine güvenli yazım
yolundan (yedek + geri okuma doğrulaması) yazılır; bu modül yazma yapmaz, yalnızca ne yazılacağını söyler.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UndoEntry:
    kind: str            # "value" | "table"
    name: str
    old: object          # skaler ya da satır listesi (tablo)
    new: object


class UndoStack:
    def __init__(self, limit: int = 200):
        self.limit = limit
        self._undo: list[UndoEntry] = []
        self._redo: list[UndoEntry] = []

    def push(self, kind: str, name: str, old, new) -> None:
        """Yeni bir yazım kaydeder; yinele yığınını temizler. Eski değer bilinmiyorsa (None) kaydedilmez."""
        if old is None or old == new:
            return
        self._undo.append(UndoEntry(kind, name, old, new))
        del self._undo[:-self.limit]
        self._redo.clear()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def peek_undo(self) -> UndoEntry | None:
        return self._undo[-1] if self._undo else None

    def peek_redo(self) -> UndoEntry | None:
        return self._redo[-1] if self._redo else None

    def commit_undo(self) -> None:
        """Geri alma başarılı yazıldı: girdiyi yinele yığınına taşı."""
        if self._undo:
            self._redo.append(self._undo.pop())

    def commit_redo(self) -> None:
        if self._redo:
            self._undo.append(self._redo.pop())

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
