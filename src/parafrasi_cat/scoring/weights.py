"""Pesos configurables de la funció de puntuació."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from parafrasi_cat.core.errors import ConfigError
from parafrasi_cat.resources import as_float, as_int


@dataclass(frozen=True, slots=True)
class ScoringWeights:
    """Pesos de la puntuació global.

    - ``transformation_gain``: pes del guany per transformacions aplicades.
      Cada transformació aporta ``confiança × (1 − semantic_risk × pes_del_risc)``.
    - ``semantic_risk``: multiplicador del risc semàntic dins del guany.
    - ``style_distance``: penalització per distància respecte del perfil d'estil.
    - ``grammar``: penalització per defectes heurístics de gramaticalitat.
    - ``preferences``: pes de les preferències explícites (diccionaris del projecte,
      fitxer de preferències de l'autor i feedback manual).
    - ``author_affinity``: pes de l'adaptació autoral quan el text és un esborrany
      generat amb LLM: bonus o penalització segons si el candidat s'acosta a
      l'empremta de l'autor més que l'original.
    - ``author_affinity_own``: el mateix pes amb text propi i empremta: un
      desempat lleu entre candidats segurs, no una pressió per imitar.
    - ``rewrite_pressure``: pressió de reescriptura segura. Només es fa servir
      quan el mode d'origen és ``llm_draft``: entre candidats ja validats, evita
      tornar el mateix text. Des de la 1.3.17 la seva part estructural se suma a
      ``structure`` i la preferència per la reredacció es paga **una sola
      vegada**; aquí només hi queda la distància superficial respecte de
      l'original. No pot compensar errors factuals, epistemològics,
      terminològics o gramaticals.
    - ``connector_repetition``: penalització petita per **introduir** una
      repetició de connector que l'original no tenia. Serveix de microdesempat
      entre alternatives segures; no inventa cap connector ni força cap
      substitució, i conservar la repetició que l'autor ja havia escrit no costa
      res. Des de la 1.3.17 no depèn del mode d'origen: amb text propi el motor
      també tria entre connectors, i per tant també hi ha de decidir.
    - ``structure``: pes del grau de reredacció estructural (famílies de
      transformació ponderades: un canvi sintàctic segur pesa més que un
      connector, i un canvi entre frases més que un de dins de la frase). Val 0
      en mode conservador, on l'original guanya els empats, i el mode profund el
      puja perquè, entre candidats igualment segurs, tingui avantatge la
      reredacció estructural real. És l'**únic** lloc on es paga el grau
      estructural: quan hi ha pressió de reescriptura, la seva part estructural
      s'hi suma. Es multiplica per la gramaticalitat, per la qualitat sintàctica
      i pel ritme: mai no compensa un avís gramatical ni una fusió que trenca el
      ritme de l'autor.
    - ``family_gain_decay``: rendiments decreixents del guany dins d'una mateixa
      família: la segona transformació d'una família aporta aquesta fracció de
      la primera, la tercera el quadrat... Tres retocs verbals no valen tres
      vegades un retoc verbal, i mai no simulen una reordenació.
    - ``degradation``: penalització per degradació estructural local (relatives
      consecutives amb el mateix marcador, acumulació de «que», repetició de la
      mateixa estructura). Un candidat que degrada l'estructura perd, a més, el
      premi que tindria com a reredacció.
    - ``rhythm``: penalització d'una fusió que deixa una frase massa llarga o
      carregada per al ritme de l'autor (segons l'empremta o el perfil); també
      rebaixa el bonus estructural de la fusió. Mai no invalida.
    - ``coverage_balance``: bonus petit, només al nivell 5 del mode profund, per
      a l'arquitectura de paràgraf que reparteix millor la reredacció entre les
      frases que tenen alternatives segures (mai una quota: una frase sense
      alternativa segura no compta).
    - ``assertive``: pes del llenguatge assertiu quan l'opció és activa: bonus o
      penalització petits per una formulació epistemològica més directa, sense
      redundàncies i amb la categoria explícita; mai no rescata cap candidat.
    - ``max_transformations``: nombre de transformacions que normalitza el guany.

    Les dimensions de preservació (factual, epistemològica, terminològica) no
    tenen pes: qualsevol error hi invalida el candidat.
    """

    transformation_gain: float = 1.0
    semantic_risk: float = 1.0
    style_distance: float = 0.5
    grammar: float = 0.5
    preferences: float = 0.5
    author_affinity: float = 2.0
    author_affinity_own: float = 0.5
    rewrite_pressure: float = 0.0
    connector_repetition: float = 0.18
    structure: float = 0.0
    family_gain_decay: float = 0.5
    degradation: float = 0.5
    rhythm: float = 0.8
    coverage_balance: float = 0.0
    assertive: float = 0.15
    max_transformations: int = 3

    def __post_init__(self) -> None:
        if self.max_transformations < 1:
            raise ConfigError("max_transformations ha de ser almenys 1")
        if not 0.0 <= self.family_gain_decay <= 1.0:
            raise ConfigError("family_gain_decay ha d'estar entre 0 i 1")
        for name in (
            "transformation_gain",
            "semantic_risk",
            "style_distance",
            "grammar",
            "preferences",
            "author_affinity",
            "author_affinity_own",
            "rewrite_pressure",
            "connector_repetition",
            "structure",
            "degradation",
            "rhythm",
            "coverage_balance",
            "assertive",
        ):
            if getattr(self, name) < 0:
                raise ConfigError(f"El pes «{name}» no pot ser negatiu")

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> ScoringWeights:
        defaults = cls()
        return cls(
            transformation_gain=as_float(data, "transformation_gain", defaults.transformation_gain),
            semantic_risk=as_float(data, "semantic_risk", defaults.semantic_risk),
            style_distance=as_float(data, "style_distance", defaults.style_distance),
            grammar=as_float(data, "grammar", defaults.grammar),
            preferences=as_float(data, "preferences", defaults.preferences),
            author_affinity=as_float(data, "author_affinity", defaults.author_affinity),
            author_affinity_own=as_float(data, "author_affinity_own", defaults.author_affinity_own),
            rewrite_pressure=as_float(data, "rewrite_pressure", defaults.rewrite_pressure),
            connector_repetition=as_float(
                data, "connector_repetition", defaults.connector_repetition
            ),
            structure=as_float(data, "structure", defaults.structure),
            family_gain_decay=as_float(data, "family_gain_decay", defaults.family_gain_decay),
            degradation=as_float(data, "degradation", defaults.degradation),
            rhythm=as_float(data, "rhythm", defaults.rhythm),
            coverage_balance=as_float(data, "coverage_balance", defaults.coverage_balance),
            assertive=as_float(data, "assertive", defaults.assertive),
            max_transformations=as_int(data, "max_transformations", defaults.max_transformations),
        )

    def to_dict(self) -> dict[str, float | int]:
        return {
            "transformation_gain": self.transformation_gain,
            "semantic_risk": self.semantic_risk,
            "style_distance": self.style_distance,
            "grammar": self.grammar,
            "preferences": self.preferences,
            "author_affinity": self.author_affinity,
            "author_affinity_own": self.author_affinity_own,
            "rewrite_pressure": self.rewrite_pressure,
            "connector_repetition": self.connector_repetition,
            "structure": self.structure,
            "family_gain_decay": self.family_gain_decay,
            "degradation": self.degradation,
            "rhythm": self.rhythm,
            "coverage_balance": self.coverage_balance,
            "assertive": self.assertive,
            "max_transformations": self.max_transformations,
        }
