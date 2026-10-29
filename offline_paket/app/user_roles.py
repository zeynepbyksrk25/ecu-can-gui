"""Kullanıcı rolleri (SRS Faz 5). Bu bir kimlik doğrulama (authentication)
sistemi DEĞİLDİR — offline, tek kullanıcılı bir masaüstü aracında şifre
kontrolü anlamsızdır. Amaç, kimin hangi rolle çalıştığını denetim
günlüğünde görünür kılmak ve kalibrasyon yazma gibi riskli eylemleri
kazara "Operatör" rolüyle tetiklemeyi zorlaştırmaktır.
"""

from enum import Enum


class Role(Enum):
    OPERATOR = "Operatör"
    ENGINEER = "Mühendis"
    ADMIN = "Yönetici"


def can_write_calibration(role: Role) -> bool:
    """RAM'e kalibrasyon (Characteristic/Harita) yazma."""
    return role in (Role.ENGINEER, Role.ADMIN)


def can_write_flash(role: Role) -> bool:
    """Kalıcı (flaş) belleğe CCP PROGRAM/CLEAR_MEMORY ile yazma. RAM
    yazmadan daha riskli (gerçek donanım hasarı ihtimali, M220'nin
    gerçek flaş akışı doğrulanmadığı için) — bu yüzden Mühendis değil,
    yalnızca Yönetici rolüne açık."""
    return role == Role.ADMIN


def can_run_diagnostics(role: Role) -> bool:
    """DIAG_SERVICE gibi ham/riskli ECU komutlarını tetikleme."""
    return role in (Role.ENGINEER, Role.ADMIN)


def can_manage_profiles(role: Role) -> bool:
    return role in (Role.ENGINEER, Role.ADMIN)


def can_clear_audit_log(role: Role) -> bool:
    return role == Role.ADMIN


def can_override_actuator(role: Role) -> bool:
    """Ana Sayfa'daki 'Eyleyiciler' panelinden manuel override (CAN
    üzerinden gerçek donanımı/MATLAB override anahtarını süren bir sinyal
    göndermek) açma. RAM kalibrasyon yazmayla aynı seviyede riskli
    kabul edilir: Operatör rolüyle KAZARA tetiklenmesin diye Mühendis
    veya Yönetici rolü gerekir (bkz. app/ui/dashboard_tab.py)."""
    return role in (Role.ENGINEER, Role.ADMIN)
