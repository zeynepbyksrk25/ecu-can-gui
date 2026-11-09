"""DashGauge artık Performans ve Çalışma Alanı'nın da göstergesi: etiket desteği; eski GaugeWidget kalktı."""


def test_dash_gauge_label_and_range_unit(qapp):
    from app.ui.dash_widgets import DashGauge
    g = DashGauge(0.0, 100.0, "bar")
    assert g.label == "" and g.sizeHint().height() == 150
    g.set_label("Comp N")
    assert g.label == "Comp N" and g.sizeHint().height() > 150      # etiket için ek yükseklik
    g.set_range(10.0, 5.0, "rpm")                                      # ters aralık düzeltilir, birim güncellenir
    assert g._min == 10.0 and g._max > 10.0 and g._unit == "rpm"
    g.set_value(50.0)
    g.resize(200, 170)
    assert g.grab().width() == 200                                     # etiketli çizim hatasız


def test_old_gauge_classes_removed_and_users_migrated(qapp):
    import app.ui.dash_widgets as dw
    assert not hasattr(dw, "GaugeWidget") and not hasattr(dw, "DarkGauge")
    from app.ui.performance_tab import PerfGauge
    from app.ui.workspace_panels import GaugePanel
    from app.signal_hub import SignalHub
    pg = PerfGauge("comp_n", "Comp N", "RPM")
    assert isinstance(pg, dw.DashGauge) and pg.label == "Comp N" and pg.maximumHeight() == 168
    panel = GaugePanel(SignalHub())
    assert isinstance(panel.gauge, dw.DashGauge)
    panel.add_signal("gauge:RPM")
    panel.unit_edit.setText("rpm")
    assert panel.gauge.label and panel.gauge._unit == "rpm"
