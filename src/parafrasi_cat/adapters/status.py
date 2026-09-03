"""Estat dels recursos lingüístics opcionals, per informar-ne la interfície.

Detecta, sense fallar mai i sense sortir de l'ordinador:

- el recurs morfològic català importat de Softcatalà;
- Java;
- una instal·lació local de LanguageTool.

Els missatges són per a una persona que no fa servir la consola: diuen si el
component està actiu i, si no hi és, què cal fer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from parafrasi_cat.adapters.languagetool import find_installation, find_java
from parafrasi_cat.morphology.catalan import RESOURCE_RELATIVE, CatalanMorphology

MORPHOLOGY_ACTIVE = "activa"
MORPHOLOGY_FALLBACK = "reserva"
LANGUAGETOOL_ACTIVE = "actiu"
LANGUAGETOOL_MISSING = "no instal·lat"


@dataclass(frozen=True, slots=True)
class ComponentStatus:
    """Estat d'un component opcional, amb un missatge llegible."""

    component: str
    state: str
    active: bool
    message: str
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "component": self.component,
            "state": self.state,
            "active": self.active,
            "message": self.message,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class LinguisticResources:
    """Estat conjunt dels recursos lingüístics opcionals."""

    morphology: ComponentStatus
    languagetool: ComponentStatus
    java: ComponentStatus

    def to_dict(self) -> dict[str, object]:
        return {
            "morphology": self.morphology.to_dict(),
            "languagetool": self.languagetool.to_dict(),
            "java": self.java.to_dict(),
        }

    def summary(self) -> str:
        return "\n".join(
            f"{status.component}: [{status.state}] {status.message}"
            for status in (self.morphology, self.languagetool, self.java)
        )


def morphology_status(language_dir: str | Path) -> ComponentStatus:
    """Estat del recurs morfològic català importat de Softcatalà."""
    resource = CatalanMorphology.discover(language_dir)
    if resource is None:
        return ComponentStatus(
            component="Morfologia catalana",
            state=MORPHOLOGY_FALLBACK,
            active=False,
            message=(
                "S'utilitza l'analitzador intern. Per millorar la flexió i la concordança, "
                "importeu el diccionari de Softcatalà."
            ),
            detail=str(Path(language_dir) / RESOURCE_RELATIVE),
        )
    metadata = resource.metadata
    return ComponentStatus(
        component="Morfologia catalana",
        state=MORPHOLOGY_ACTIVE,
        active=True,
        message=f"{len(resource)} formes del diccionari de Softcatalà.",
        detail=(
            f"{metadata.get('source_repository', '')} @ "
            f"{metadata.get('source_commit', '')[:12]} · {metadata.get('license', '')}"
        ),
    )


def java_status(java: str | None = None) -> ComponentStatus:
    """Estat de Java, que LanguageTool necessita."""
    interpreter = find_java(java)
    if interpreter is None:
        return ComponentStatus(
            component="Java",
            state="no instal·lat",
            active=False,
            message="Cal Java per fer servir la validació avançada de català.",
        )
    return ComponentStatus(
        component="Java",
        state="disponible",
        active=True,
        message="Java està instal·lat.",
        detail=str(interpreter),
    )


def languagetool_status(
    root: str | Path | None = None, *, java: str | None = None
) -> ComponentStatus:
    """Estat de la instal·lació local de LanguageTool."""
    installation = find_installation(root, java=java)
    if installation is None:
        return ComponentStatus(
            component="LanguageTool local",
            state=LANGUAGETOOL_MISSING,
            active=False,
            message=(
                "La validació avançada de català no està activa. El motor continua "
                "funcionant amb les seves comprovacions internes."
            ),
        )
    return ComponentStatus(
        component="LanguageTool local",
        state=LANGUAGETOOL_ACTIVE,
        active=True,
        message="La validació avançada de català està activa i s'executa en aquest ordinador.",
        detail=installation.describe(),
    )


def resources_status(
    root: str | Path, *, language: str = "ca", java: str | None = None
) -> LinguisticResources:
    """Estat de tots els recursos lingüístics opcionals."""
    language_dir = Path(root) / "resources" / language
    return LinguisticResources(
        morphology=morphology_status(language_dir),
        languagetool=languagetool_status(root, java=java),
        java=java_status(java),
    )
