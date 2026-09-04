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
from enum import StrEnum
from pathlib import Path

from parafrasi_cat.adapters.languagetool import find_installation, find_java
from parafrasi_cat.morphology.catalan import RESOURCE_RELATIVE, CatalanMorphology
from parafrasi_cat.syntax.spacy_parser import DEFAULT_MODEL, SpacySyntax


class LinguisticMode(StrEnum):
    """En quin mode treballa el motor segons els recursos que hi ha instal·lats."""

    FULL = "complet"
    """Morfologia de Softcatalà, parser sintàctic i LanguageTool local."""

    BASIC = "basic"
    """Només els components interns: menys cobertura i més prudència."""

    @property
    def label(self) -> str:
        if self is LinguisticMode.FULL:
            return "Mode lingüístic complet actiu"
        return "Mode bàsic: instal·la els recursos lingüístics per obtenir més cobertura."

    @property
    def detail(self) -> str:
        if self is LinguisticMode.FULL:
            return (
                "Morfologia de Softcatalà, analitzador sintàctic i validació gramatical "
                "local, tots en aquest ordinador."
            )
        return (
            "El motor funciona igualment, amb els components interns: transforma menys "
            "i, quan no en té prou seguretat, conserva el text original."
        )


#: Component instal·lable de cada recurs, per al botó de la interfície.
INSTALLERS: dict[str, str] = {
    "Morfologia catalana": "morphology",
    "Parser sintàctic català": "parser",
    "LanguageTool local": "languagetool",
}

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
    syntax: ComponentStatus
    languagetool: ComponentStatus
    java: ComponentStatus

    @property
    def components(self) -> tuple[ComponentStatus, ...]:
        return (self.morphology, self.syntax, self.languagetool, self.java)

    @property
    def offline_ready(self) -> bool:
        """Cert si tot el que cal per treballar sense connexió ja és a l'ordinador.

        El motor sempre funciona sense connexió; això indica que a més hi són
        tots els components opcionals.
        """
        return self.morphology.active and self.syntax.active and self.languagetool.active

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(c.component for c in self.components if not c.active)

    @property
    def mode(self) -> LinguisticMode:
        """Mode lingüístic complet si hi són els tres recursos; bàsic altrament."""
        return LinguisticMode.FULL if self.offline_ready else LinguisticMode.BASIC

    @property
    def installable(self) -> tuple[str, ...]:
        """Components que falten i que la interfície pot instal·lar."""
        return tuple(
            INSTALLERS[c.component]
            for c in self.components
            if not c.active and c.component in INSTALLERS
        )

    def to_dict(self) -> dict[str, object]:
        mode = self.mode
        return {
            "morphology": self.morphology.to_dict(),
            "syntax": self.syntax.to_dict(),
            "languagetool": self.languagetool.to_dict(),
            "java": self.java.to_dict(),
            "mode": {
                "id": mode.value,
                "label": mode.label,
                "detail": mode.detail,
                "full": mode is LinguisticMode.FULL,
                "missing": list(self.missing),
                "installable": list(self.installable),
            },
            "offline": {
                "component": "Mode fora de línia",
                "state": "disponible" if self.offline_ready else "parcial",
                "active": self.offline_ready,
                "message": (
                    "Tots els recursos són en aquest ordinador: no cal connexió per a res."
                    if self.offline_ready
                    else "El motor ja funciona sense connexió; queden recursos opcionals per posar."
                ),
                "detail": ", ".join(self.missing),
            },
        }

    def summary(self) -> str:
        lines = [self.mode.label, ""]
        lines.extend(
            f"{status.component}: [{status.state}] {status.message}" for status in self.components
        )
        return "\n".join(lines)


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


def syntax_status(model: str = DEFAULT_MODEL) -> ComponentStatus:
    """Estat de l'analitzador sintàctic català local."""
    parser = SpacySyntax(model)
    if not parser.available:
        return ComponentStatus(
            component="Parser sintàctic català",
            state=MORPHOLOGY_FALLBACK,
            active=False,
            message=(
                "S'utilitzen les heurístiques internes. El parser millora les "
                "transformacions estructurals; només analitza, no escriu mai res."
            ),
            detail=parser.failure,
        )
    return ComponentStatus(
        component="Parser sintàctic català",
        state=MORPHOLOGY_ACTIVE,
        active=True,
        message="Analitza dependències, subjecte, objecte, subordinades i coordinacions.",
        detail=f"{parser.describe()} · {parser.license()}",
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
        syntax=syntax_status(),
        languagetool=languagetool_status(root, java=java),
        java=java_status(java),
    )
