from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QDoubleSpinBox, QHeaderView, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

COLUMNS = [
    "Name", "Type", "Byteorder", "Mode", "Bitpos", "Length",
    "Factor", "Offset", "Minimum", "Maximum", "Unit", "Comment",
    "Values", "Attributes", "Değer",
]

from app.ui.noscroll import no_wheel
from app.dbc import signal_default, signal_limits


def _signal_mode(signal) -> str:
    if getattr(signal, "is_multiplexer", False):
        return "Multiplexor"
    if getattr(signal, "multiplexer_ids", None):
        return "Multiplexed"
    return "Signal"


def _signal_comment(signal) -> str:
    comment = getattr(signal, "comment", None)
    if isinstance(comment, dict):
        return next(iter(comment.values()), "") if comment else ""
    return comment or ""


def _signal_value_table(signal) -> str:
    choices = getattr(signal, "choices", None)
    if not choices:
        return ""
    return ", ".join(f"{key}={value}" for key, value in sorted(choices.items()))


def _signal_attributes(signal) -> str:
    try:
        attributes = signal.dbc.attributes
    except AttributeError:
        return ""
    if not attributes:
        return ""
    return ", ".join(f"{name}={attr.value}" for name, attr in attributes.items())


class SignalInputDialog(QDialog):
    """Seçilen DBC mesajının TÜM sinyallerini, standart bir DBC editörünün
    'Signals of Selected CAN Message' panelindeki gibi tek tabloda gösterir
    (Name, Type, Byteorder, Mode, Bitpos, Length, Factor, Offset, Minimum,
    Maximum, Unit, Comment, Values, Attributes) ve en sağdaki 'Değer'
    sütunundan her sinyal için mühendislik biriminde giriş alır."""

    def __init__(self, message, existing_values: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{message.name} - sinyaller")
        existing_values = existing_values or {}
        signals = message.signals

        self.table = QTableWidget(len(signals), len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)

        self._spin_boxes: dict[str, QDoubleSpinBox] = {}

        for row, signal in enumerate(signals):
            row_values = [
                signal.name,
                "Signed" if signal.is_signed else "Unsigned",
                "Intel" if signal.byte_order == "little_endian" else "Motorola",
                _signal_mode(signal),
                str(signal.start),
                str(signal.length),
                str(signal.scale),
                str(signal.offset),
                "" if signal.minimum is None else str(signal.minimum),
                "" if signal.maximum is None else str(signal.maximum),
                signal.unit or "",
                _signal_comment(signal),
                _signal_value_table(signal),
                _signal_attributes(signal),
            ]
            for col, text in enumerate(row_values):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, col, item)

            spin = no_wheel(QDoubleSpinBox())
            minimum, maximum = signal_limits(signal)
            spin.setRange(minimum, maximum)
            spin.setDecimals(4)
            step = signal.scale if signal.scale else 1.0
            spin.setSingleStep(step if step > 0 else 1.0)
            # Varsayılan: önceki giriş, yoksa DBC başlangıç değeri/0 (aralığa kırpılmış).
            spin.setValue(existing_values.get(signal.name, signal_default(signal)))
            self.table.setCellWidget(row, len(COLUMNS) - 1, spin)
            self._spin_boxes[signal.name] = spin

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addWidget(buttons)
        self.resize(min(1400, 90 * len(COLUMNS)), 180 + 34 * max(len(signals), 1))

    def values(self) -> dict:
        return {name: spin.value() for name, spin in self._spin_boxes.items()}
