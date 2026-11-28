"""Sinyal beslemesi (Qt'siz): CAN'den çözülen DBC sinyallerini ve gösterge değerlerini Scope pencerelerinin
ortak ``SignalHub``'ına taşır. (Eskiden Çalışma Alanı sayfası yapıyordu; sayfa kalktı, besleme burada kaldı.)

Yalnızca hub'da ETKİN olan (bir Scope'ta çizilen) DBC sinyalleri çözülür; yüzlerce sinyal CPU/bellek tüketmez.
A2L ölçümleri buradan beslenmez: Worksheets ölçüm turu (``ModasWorkspace.push_sample``) yapar.
"""
from __future__ import annotations

from app.signal_hub import SignalHub, kind_of

GROUP_TITLES = [("dbc", "DBC sinyalleri (CAN)"), ("gauge", "Göstergeler"),
                ("math", "Matematik sinyalleri"), ("csv", "İçe aktarılan kayıtlar")]


class SignalFeed:
    def __init__(self, hub: SignalHub, gauge_keys=None):
        self.hub = hub
        self._dbc = None
        self._dbc_map: dict = {}
        self._gauge_keys = list(gauge_keys or [])
        hub.on_active = self.rebuild_dbc_map

    # ---- dışarıdan besleme (MainWindow çağırır) -------------------------------------------
    def push(self, sid: str, value):
        self.hub.push(sid, value)

    def set_dbc(self, dbc):
        self._dbc = dbc
        self.rebuild_dbc_map()

    def rebuild_dbc_map(self):
        """Etkin ``dbc:`` kimliklerinden kare kimliği -> (mesaj, sinyal adları) tablosu."""
        m: dict = {}
        if self._dbc is not None and self._dbc.is_loaded:
            for sid in self.hub.active():
                if kind_of(sid) != "dbc":
                    continue
                msg_name, _, sig = sid.split(":", 1)[1].partition(".")
                msg = self._dbc.get_message(msg_name)
                if msg is None:
                    continue
                m.setdefault(msg.frame_id, (msg, set()))[1].add(sig)
        self._dbc_map = m

    def on_can_frame(self, arb_id: int, data: bytes):
        entry = self._dbc_map.get(arb_id)
        if entry is None:
            return
        msg, sigs = entry
        try:
            decoded = msg.decode(bytes(data), decode_choices=False)
        except Exception:
            return
        for s in sigs:
            if s in decoded:
                self.hub.push(f"dbc:{msg.name}.{s}", decoded[s])

    # ---- seçilebilir kaynaklar -----------------------------------------------------------
    def groups(self) -> list:
        """Scope sinyal seçicisi için ``[(grup başlığı, [sinyal kimliği, ...])]`` (boş gruplar atlanır)."""
        ids: dict[str, list] = {k: [] for k, _t in GROUP_TITLES}
        if self._dbc is not None and self._dbc.is_loaded:
            for mn in self._dbc.message_names():
                ids["dbc"] += [f"dbc:{mn}.{s.name}" for s in self._dbc.signals_of(mn)]
        ids["gauge"] = [f"gauge:{k}" for k in self._gauge_keys]
        ids["math"] = list(self.hub.derived)
        ids["csv"] = sorted(self.hub.static)
        return [(title, ids[k]) for k, title in GROUP_TITLES if ids[k]]

    def all_signal_ids(self, a2l_names=()) -> list:
        """Matematik sinyali kaynak listesi: A2L adları (verilirse) + tüm gruplar."""
        out = [f"a2l:{n}" for n in a2l_names]
        for _t, sids in self.groups():
            out += sids
        return out

    def snapshot(self):
        """PDF raporu için ``(veri, olaylar)``: Scope'larda çizilen sinyaller (etiket -> (zaman[unix], değer, birim)). Sonradan değişmez."""
        data = {}
        for sid in sorted(self.hub.active()):
            t, v = self.hub.get(sid)
            if t.size:
                data[sid.split(":", 1)[1]] = (t + self.hub.t0, v.copy(), "")
        return data, []
