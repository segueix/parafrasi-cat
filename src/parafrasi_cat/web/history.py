"""Registre local i opcional de les reescriptures (traçabilitat).

El registre és un fitxer JSONL: una línia per reescriptura, amb el text
original, la data, la configuració, els candidats, les puntuacions, el
candidat seleccionat, les regles aplicades, el feedback i l'edició manual
final. És local, llegible, exportable i es pot desactivar.

**Quan està desactivat no s'escriu res**: ni el text, ni la configuració, ni
cap metadada. No hi ha telemetria de cap mena; el fitxer no surt mai de
l'ordinador.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from parafrasi_cat.core.errors import ResourceError

DEFAULT_HISTORY_FILE = "history/parafrasi-cat.jsonl"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _mapping(value: object) -> dict[str, object]:
    """Diccionari de claus textuals, o buit si el valor desat no ho és."""
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {}


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    """Una reescriptura registrada."""

    entry_id: str
    timestamp: str
    source_text: str
    config: Mapping[str, object] = field(default_factory=dict)
    result: Mapping[str, object] = field(default_factory=dict)
    selected_text: str = ""
    final_text: str = ""
    feedback: tuple[Mapping[str, object], ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> HistoryEntry:
        feedback = data.get("feedback")
        entries = (
            tuple(_mapping(item) for item in feedback if isinstance(item, Mapping))
            if isinstance(feedback, list)
            else ()
        )
        return cls(
            entry_id=str(data.get("entry_id", "")),
            timestamp=str(data.get("timestamp", "")),
            source_text=str(data.get("source_text", "")),
            config=_mapping(data.get("config")),
            result=_mapping(data.get("result")),
            selected_text=str(data.get("selected_text", "")),
            final_text=str(data.get("final_text", "")),
            feedback=entries,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp,
            "source_text": self.source_text,
            "config": dict(self.config),
            "result": dict(self.result),
            "selected_text": self.selected_text,
            "final_text": self.final_text,
            "feedback": [dict(item) for item in self.feedback],
        }

    def summary(self) -> dict[str, object]:
        """Resum curt per llistar l'historial sense tornar tot el contingut."""
        config = self.config
        return {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp,
            "source_text": self.source_text[:120],
            "final_text": self.final_text[:120],
            "mode": config.get("mode", ""),
            "level": config.get("level"),
            "style_profile": config.get("style_profile", ""),
            "dictionaries": config.get("dictionaries", []),
            "preferences": config.get("preferences", ""),
            "n_feedback": len(self.feedback),
        }


class HistoryLog:
    """Registre JSONL local, desactivat mentre no s'activi explícitament."""

    def __init__(self, path: str | Path, *, enabled: bool = False) -> None:
        self._path = Path(path)
        self._enabled = enabled

    @property
    def path(self) -> Path:
        return self._path

    @property
    def enabled(self) -> bool:
        return self._enabled

    def enable(self, enabled: bool = True) -> bool:
        """Activa o desactiva el registre i retorna l'estat resultant."""
        self._enabled = enabled
        return self._enabled

    def append(self, entry: HistoryEntry | Mapping[str, object]) -> HistoryEntry | None:
        """Afegeix una entrada. Si el registre està desactivat, no escriu res i retorna ``None``."""
        if not self._enabled:
            return None
        if isinstance(entry, HistoryEntry):
            record = entry
        else:
            data = dict(entry)
            data.setdefault("entry_id", uuid.uuid4().hex[:12])
            data.setdefault("timestamp", _now())
            record = HistoryEntry.from_dict(data)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record.to_dict(), ensure_ascii=False)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return record

    def __iter__(self) -> Iterator[HistoryEntry]:
        return iter(self.entries())

    def __len__(self) -> int:
        return len(self.entries())

    def entries(self) -> tuple[HistoryEntry, ...]:
        """Entrades desades, de la més antiga a la més recent."""
        if not self._path.is_file():
            return ()
        result: list[HistoryEntry] = []
        for number, raw in enumerate(self._path.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except ValueError as exc:
                raise ResourceError(f"Línia {number} il·legible a «{self._path}»: {exc}") from exc
            if not isinstance(data, dict):
                raise ResourceError(f"Línia {number} de «{self._path}» no és un objecte JSON")
            result.append(HistoryEntry.from_dict(data))
        return tuple(result)

    def export(self, path: str | Path) -> Path:
        """Escriu tot l'historial com a JSON indentat i retorna la ruta."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = [entry.to_dict() for entry in self.entries()]
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return target

    def export_json(self) -> str:
        """Historial complet com a text JSON (per descarregar-lo des de la interfície)."""
        return json.dumps(
            [entry.to_dict() for entry in self.entries()], ensure_ascii=False, indent=2
        )

    def clear(self) -> None:
        """Esborra el fitxer del registre, si existeix."""
        self._path.unlink(missing_ok=True)

    def status(self) -> dict[str, object]:
        return {
            "enabled": self._enabled,
            "path": str(self._path),
            "exists": self._path.is_file(),
            "n_entries": len(self.entries()),
        }
