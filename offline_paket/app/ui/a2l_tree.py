"""A2L nesne ağacı için ortak yardımcılar.

A2L sekmesi, Kalibrasyon > CCP ve Harita Editörü aynı "arama kutusu + nesne ağacı" kalıbını ayrı ayrı
kuruyor ve üç ayrı süzgeç fonksiyonu taşıyordu. Burada tek yerde toplanır; her sekme KENDİ gruplamasını
(Scalar/Curves/Maps, tuneable/readonly, Eğriler/Haritalar…) kurmaya devam eder.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

# Ağaç öğesinde gerçek nesnenin (MeasurementInfo/CharacteristicInfo ya da onu saran demet) taşındığı rol.
ROLE_OBJECT = Qt.UserRole


def new_tree(on_click) -> QTreeWidget:
    """Başlıksız ağaç; öğeye tıklanınca ``on_click(item, column)`` çağrılır."""
    tree = QTreeWidget()
    tree.setHeaderHidden(True)
    tree.itemClicked.connect(on_click)
    return tree


def payload_item(label: str, payload) -> QTreeWidgetItem:
    """Etiketli yaprak öğe; ``payload`` ROLE_OBJECT içinde taşınır."""
    item = QTreeWidgetItem([label])
    item.setData(0, ROLE_OBJECT, payload)
    return item


def measurements_root(title: str, measurements) -> QTreeWidgetItem:
    """Ölçümlerin altında listelendiği kök öğe; yaprakların payload'ı ("measurement", ölçüm)."""
    root = QTreeWidgetItem([title])
    for m in measurements:
        root.addChild(payload_item(m.name, ("measurement", m)))
    return root


def filter_tree(tree: QTreeWidget, text: str) -> None:
    """İsme göre süzer (büyük/küçük harf duyarsız, iç içe gruplarla). Boş metinde her şey görünür;
    eşleşen yaprağı olmayan grup gizlenir."""
    text = text.strip().lower()

    def visit(item: QTreeWidgetItem, top: bool) -> bool:
        if item.childCount() == 0:
            # Boş üst düzey grup yalnızca metin yokken görünür (etiketi eşleşse bile boş grup gizlenir)
            visible = not text if top else (not text or text in item.text(0).lower())
        else:
            any_visible = False
            for i in range(item.childCount()):
                any_visible = visit(item.child(i), False) or any_visible
            visible = any_visible or not text
        item.setHidden(not visible)
        return visible

    for i in range(tree.topLevelItemCount()):
        visit(tree.topLevelItem(i), True)
