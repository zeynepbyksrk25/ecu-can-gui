"""Test senaryoları (MIL ve gerçek ECU için ortak): adımlı yürütme, koşullu bekleme, işaretleme, rapor.

Karar ilkesi (docs/GOREV.md 11.9): GERÇEK limitler model gereksinimlerinden gelir. Bu modül hiçbir limit/eşik UYDURMAZ ve
varsayılan eşik taşımaz. Bir ``check`` adımı yalnızca senaryo dosyası ``requirement`` (gereksinim kimliği) ve ``value``
verirse PASS/FAIL karar üretir; verilmezse ``SKIPPED`` olur ("gereksinim tanımlı değil, otomatik karar verilmez").
``wait`` adımının zaman aşımı bir TEST kararı değil, senaryonun ilerleyememesidir (``TIMEOUT``).

Adım türleri (JSON)::

  {"do": "model", "cmd": "start|pause|resume|stop|reset"}            # model yaşam döngüsü
  {"do": "speed", "factor": 2.0}
  {"do": "set", "signal": "MESAJ.SINYAL", "value": 40}               # DBC sinyali yaz (mevcut yazma yolu)
  {"do": "wait", "signal": "ENG.rpm", "op": ">=", "value": 1000, "timeout": 30}
  {"do": "delay", "seconds": 2}
  {"do": "marker", "label": "Idle"}
  {"do": "check", "signal": "ENG.egt", "op": "<=", "value": 900, "requirement": "REQ-12"}
  {"do": "monitor", "signal": "ENG.egt", "op": "<=", "value": 900, "requirement": "REQ-12"}   # senaryo boyunca izle;
                                                                    # ihlalde işaretler ve FAIL (gereksinim varsa)
"""
from __future__ import annotations

import json
import math
import operator
import threading
import time
from dataclasses import dataclass, field

OPS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le, "==": operator.eq, "!=": operator.ne}
PASS, FAIL, TIMEOUT, SKIPPED, ABORTED, DONE, ERROR = "PASS", "FAIL", "TIMEOUT", "SKIPPED", "ABORTED", "DONE", "ERROR"
DO_TYPES = {"model", "speed", "set", "wait", "delay", "marker", "check", "monitor"}
MODEL_CMDS = {"start", "pause", "resume", "stop", "reset"}


class ScenarioError(ValueError):
    pass


@dataclass
class StepResult:
    index: int
    do: str
    text: str
    status: str = ""
    detail: str = ""
    t_start: float = 0.0
    t_end: float = 0.0
    observed: float | None = None


@dataclass
class Scenario:
    name: str
    steps: list
    description: str = ""


def parse_scenario(raw) -> Scenario:
    if not isinstance(raw, dict) or not isinstance(raw.get("steps"), list) or not raw["steps"]:
        raise ScenarioError("Senaryo 'steps' listesi içermiyor")
    for i, s in enumerate(raw["steps"], 1):
        if not isinstance(s, dict) or s.get("do") not in DO_TYPES:
            raise ScenarioError(f"Adım {i}: 'do' geçersiz (izinli: {', '.join(sorted(DO_TYPES))})")
        do = s["do"]
        if do == "model" and s.get("cmd") not in MODEL_CMDS:
            raise ScenarioError(f"Adım {i}: model komutu geçersiz")
        if do in ("set", "wait", "check", "monitor") and not isinstance(s.get("signal"), str):
            raise ScenarioError(f"Adım {i}: 'signal' zorunlu")
        if do in ("wait", "check", "monitor"):
            if s.get("op") not in OPS:
                raise ScenarioError(f"Adım {i}: 'op' geçersiz ({', '.join(OPS)})")
            if not _num(s.get("value")):
                raise ScenarioError(f"Adım {i}: 'value' sayı olmalı")
        if do == "set" and not _num(s.get("value")):
            raise ScenarioError(f"Adım {i}: 'value' sayı olmalı")
        if do == "wait" and not (_num(s.get("timeout")) and s["timeout"] > 0):
            raise ScenarioError(f"Adım {i}: wait için pozitif 'timeout' zorunlu")
        if do == "delay" and not (_num(s.get("seconds")) and s["seconds"] >= 0):
            raise ScenarioError(f"Adım {i}: 'seconds' >= 0 olmalı")
        if do == "speed" and not (_num(s.get("factor")) and s["factor"] >= 0):
            raise ScenarioError(f"Adım {i}: 'factor' >= 0 olmalı")
        if do == "marker" and not str(s.get("label", "")).strip():
            raise ScenarioError(f"Adım {i}: 'label' boş")
    return Scenario(str(raw.get("name") or "Senaryo"), raw["steps"], str(raw.get("description", "")))


def load_scenario(path: str) -> Scenario:
    try:
        with open(path, encoding="utf-8") as f:
            return parse_scenario(json.load(f))
    except OSError as exc:
        raise ScenarioError(f"Senaryo okunamadı: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ScenarioError(f"Senaryo JSON hatalı: {exc}") from exc


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def describe(s: dict) -> str:
    do = s["do"]
    if do == "model":
        return f"Model: {s['cmd']}"
    if do == "speed":
        return f"Hız: {s['factor']}x" if s["factor"] else "Hız: Fastest"
    if do == "set":
        return f"Yaz {s['signal']} = {s['value']}"
    if do in ("wait", "check", "monitor"):
        extra = f" (≤{s['timeout']} sn)" if do == "wait" else (f" [{s['requirement']}]" if s.get("requirement") else "")
        return f"{do} {s['signal']} {s['op']} {s['value']}{extra}"
    if do == "delay":
        return f"Bekle {s['seconds']} sn"
    return f"İşaret: {s['label']}"


class ScenarioRunner:
    """``ctx`` arayüzü: ``get_signal(name)->float|None``, ``set_signal(name, value)``, ``model_command(cmd, arg)``,
    ``marker(label)``, ``log(text)``. İş parçacığında çalışır; ``abort()`` güvenli durdurur."""

    def __init__(self, scenario: Scenario, ctx, clock=time.monotonic, sleep=time.sleep, poll_s: float = 0.05,
                 on_progress=None):
        self.scenario, self.ctx = scenario, ctx
        self._clock, self._sleep, self._poll = clock, sleep, poll_s
        self.on_progress = on_progress
        self.results: list[StepResult] = []
        self.status = "IDLE"            # IDLE | RUNNING | DONE | ABORTED
        self.verdict = ""               # PASS | FAIL | "TAMAMLANDI (otomatik karar yok)" | ABORTED
        self._abort = threading.Event()
        self._thread: threading.Thread | None = None
        self.violations: list = []

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._abort.clear()
        self.results, self.violations, self.verdict, self.status = [], [], "", "RUNNING"
        self._thread = threading.Thread(target=self.run, name="scenario", daemon=True)
        self._thread.start()

    def abort(self):
        self._abort.set()

    def join(self, timeout=None):
        if self._thread is not None:
            self._thread.join(timeout)

    # ---- yürütme ----------------------------------------------------------------------------
    def run(self):
        self.status = "RUNNING"
        monitors: list = []
        for i, s in enumerate(self.scenario.steps, 1):
            if self._abort.is_set():
                self._add(i, s, ABORTED, "kullanıcı durdurdu")
                continue
            r = StepResult(i, s["do"], describe(s), t_start=time.time())
            try:
                r.status, r.detail, r.observed = self._exec(s, monitors)
            except Exception as exc:  # noqa: BLE001 - adım hatası senaryoyu çökertmez; raporlanır
                r.status, r.detail = ERROR, f"{type(exc).__name__}: {exc}"
            r.t_end = time.time()
            self.results.append(r)
            if self.on_progress:
                self.on_progress(r)
            if r.status == ERROR:
                self._abort.set()                       # hata sonrası güvenli dur: kalan adımlar ABORTED
        self._finish()

    def _add(self, i, s, status, detail):
        r = StepResult(i, s["do"], describe(s), status, detail, time.time(), time.time())
        self.results.append(r)
        if self.on_progress:
            self.on_progress(r)

    def _check_monitors(self, monitors):
        for i, s in monitors:
            v = self.ctx.get_signal(s["signal"])
            if v is not None and not OPS[s["op"]](v, s["value"]):
                key = (i, round(v, 9))
                if key not in {(x[0], round(x[2], 9)) for x in self.violations}:
                    self.violations.append((i, s["signal"], v, s.get("requirement")))
                    self.ctx.marker(f"İHLAL {s['signal']} {s['op']} {s['value']} (gözlenen {v:g}) [{s.get('requirement')}]")

    def _sleep_checked(self, seconds, monitors):
        end = self._clock() + seconds
        while self._clock() < end and not self._abort.is_set():
            self._sleep(min(self._poll, max(0.0, end - self._clock())))
            self._check_monitors(monitors)

    def _exec(self, s, monitors):
        do = s["do"]
        if do == "model":
            self.ctx.model_command(s["cmd"], 0.0)
            return DONE, "", None
        if do == "speed":
            self.ctx.model_command("speed", float(s["factor"]))
            return DONE, "", None
        if do == "set":
            self.ctx.set_signal(s["signal"], float(s["value"]))
            return DONE, "", None
        if do == "marker":
            self.ctx.marker(str(s["label"]))
            return DONE, "", None
        if do == "delay":
            self._sleep_checked(float(s["seconds"]), monitors)
            return DONE, "", None
        if do == "monitor":
            if not s.get("requirement"):
                return SKIPPED, "gereksinim tanımlı değil; izleme yapılmaz (otomatik karar verilmez)", None
            monitors.append((len(self.results) + 1, s))
            return DONE, "izleniyor", None
        if do == "check":
            v = self.ctx.get_signal(s["signal"])
            if not s.get("requirement"):
                return SKIPPED, "gereksinim tanımlı değil; otomatik karar verilmez" + (
                    f" (gözlenen {v:g})" if v is not None else ""), v
            if v is None:
                return FAIL, "sinyal değeri alınamadı (veri yok)", None
            ok = OPS[s["op"]](v, s["value"])
            return (PASS if ok else FAIL), f"gözlenen {v:g}, beklenen {s['op']} {s['value']}", v
        # wait
        deadline = self._clock() + float(s["timeout"])
        last = None
        while not self._abort.is_set():
            last = self.ctx.get_signal(s["signal"])
            self._check_monitors(monitors)
            if last is not None and OPS[s["op"]](last, s["value"]):
                return DONE, f"koşul sağlandı (gözlenen {last:g})", last
            if self._clock() >= deadline:
                return TIMEOUT, "zaman aşımı: koşul sağlanmadı" + (f" (son değer {last:g})" if last is not None else
                                                                   " (veri yok)"), last
            self._sleep(self._poll)
        return ABORTED, "kullanıcı durdurdu", last

    def _finish(self):
        aborted = any(r.status == ABORTED for r in self.results) or self._abort.is_set()
        decided = [r for r in self.results if r.status in (PASS, FAIL)]
        failed = [r for r in self.results if r.status in (FAIL, TIMEOUT, ERROR)] or self.violations
        if aborted:
            self.verdict, self.status = ABORTED, ABORTED
        else:
            self.status = "DONE"
            if failed:
                self.verdict = FAIL
            elif decided or any(v for v in self.violations):
                self.verdict = PASS
            elif any(s.get("do") == "monitor" and s.get("requirement") for s in self.scenario.steps):
                self.verdict = PASS
            else:
                self.verdict = "TAMAMLANDI (otomatik karar yok)"

    # ---- rapor -------------------------------------------------------------------------------
    def report_text(self) -> str:
        lines = [f"Test raporu: {self.scenario.name}", f"Sonuç: {self.verdict or self.status}", ""]
        for r in self.results:
            lines.append(f"{r.index:>2}. [{r.status:<8}] {r.text}" + (f" — {r.detail}" if r.detail else ""))
        for _i, sig, v, req in self.violations:
            lines.append(f"İHLAL: {sig} gözlenen {v:g} [{req}]")
        lines.append("")
        lines.append("Not: PASS/FAIL yalnızca senaryodaki gereksinim kimlikli (requirement) adımlardan gelir; "
                     "hiçbir limit program tarafından uydurulmaz.")
        return "\n".join(lines)

    def report_dict(self) -> dict:
        return {"scenario": self.scenario.name, "verdict": self.verdict or self.status,
                "steps": [r.__dict__ for r in self.results],
                "violations": [{"signal": s, "observed": v, "requirement": q} for _i, s, v, q in self.violations]}
