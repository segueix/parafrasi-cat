"""Servei que connecta la interfície local amb la canonada existent.

Aquest mòdul no afegeix cap capacitat lingüística: només recull les opcions
disponibles (empremtes, perfils, diccionaris, preferències, modes), executa
la canonada i tradueix el resultat a estructures que la pàgina pot mostrar
(millor candidat, altres candidats, diferències, regles, puntuacions,
advertiments i fragments protegits). El feedback i el registre local passen
pels components de la fase 6 i de ``web.history``.
"""

from __future__ import annotations

import re
import subprocess
import sys
import threading
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from parafrasi_cat import __version__
from parafrasi_cat.adapters.status import resources_status
from parafrasi_cat.analyzer.analysis import RuleBasedAnalyzer
from parafrasi_cat.core.errors import ConfigError, ParafrasiError
from parafrasi_cat.dictionaries.dictionary import TermDictionary
from parafrasi_cat.pipeline.builder import build_pipeline
from parafrasi_cat.pipeline.config import FINGERPRINT_REQUIRED, PipelineConfig, SourceMode
from parafrasi_cat.pipeline.modes import (
    LEVEL_LABELS,
    MODES,
    RewriteMode,
    level_label,
    mode_settings,
)
from parafrasi_cat.pipeline.pipeline import Pipeline
from parafrasi_cat.pipeline.result import EvaluatedCandidate, ParaphraseResult, _UnitResult
from parafrasi_cat.preferences.author import AuthorPreferences
from parafrasi_cat.preferences.feedback import DEFAULT_FEEDBACK_FILE, VERDICTS, FeedbackStore
from parafrasi_cat.protected.spans import ProtectedSpan
from parafrasi_cat.resources import ProjectPaths, load_mapping
from parafrasi_cat.style.corpus import corpus_from_texts
from parafrasi_cat.style.fingerprint import StyleFingerprint
from parafrasi_cat.style.observations import DocumentObserver, StyleResources
from parafrasi_cat.style.preferences import StylePreferences
from parafrasi_cat.style.profiler import build_fingerprint
from parafrasi_cat.syntax.spacy_parser import SpacySyntax
from parafrasi_cat.web.history import DEFAULT_HISTORY_FILE, HistoryLog

DEFAULT_RULE_SET = "parafrasi"
#: Components opcionals que la interfície pot instal·lar, amb el seu script.
#: Els scripts són fora del paquet: són l'única part que accedeix a Internet.
INSTALLERS: dict[str, str] = {
    "morphology": "scripts/install_morphology.py",
    "languagetool": "scripts/install_languagetool.py",
    "parser": "scripts/install_parser.py",
}
DEFAULT_STYLE_PROFILE = "default"
MAX_TEXT_CHARS = 20000

#: Missatge quan algú intenta posar un esborrany generat amb LLM al corpus de l'autor.
LLM_DRAFT_NOT_CORPUS = (
    "Un esborrany generat amb LLM no pot formar part del corpus de l'autor: l'empremta "
    "només es construeix amb textos propis."
)

JsonDict = dict[str, Any]
"""Càrrega JSON que la interfície rep tal qual: les claus són dinàmiques."""

_TOKEN_RE = re.compile(r"\s+|\S+")


# --- diferències ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DiffPart:
    """Un tros del text amb la seva operació respecte de l'original."""

    op: str
    """``equal``, ``insert`` o ``delete``."""

    text: str

    def to_dict(self) -> dict[str, str]:
        return {"op": self.op, "text": self.text}


def word_diff(source: str, target: str) -> tuple[DiffPart, ...]:
    """Diferències per paraules entre dos textos, conservant els espais."""
    before = _TOKEN_RE.findall(source)
    after = _TOKEN_RE.findall(target)
    parts: list[DiffPart] = []

    def add(op: str, tokens: Sequence[str]) -> None:
        text = "".join(tokens)
        if not text:
            return
        if parts and parts[-1].op == op:
            parts[-1] = DiffPart(op, parts[-1].text + text)
        else:
            parts.append(DiffPart(op, text))

    for tag, i1, i2, j1, j2 in SequenceMatcher(a=before, b=after, autojunk=False).get_opcodes():
        if tag == "equal":
            add("equal", before[i1:i2])
        else:
            if tag in ("delete", "replace"):
                add("delete", before[i1:i2])
            if tag in ("insert", "replace"):
                add("insert", after[j1:j2])
    return tuple(parts)


# --- peticions ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RewriteRequest:
    """Petició de reescriptura tal com arriba de la interfície."""

    text: str
    mode: RewriteMode = RewriteMode.DEEP
    level: int | None = None
    style_profile: str = DEFAULT_STYLE_PROFILE
    dictionaries: tuple[str, ...] = ()
    preferences: str = ""
    rule_set: str = DEFAULT_RULE_SET
    languagetool: bool = False
    source_mode: SourceMode = SourceMode.OWN
    """Origen del text segons l'usuari. Per defecte, text propi: res no canvia."""

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ConfigError("Cal un text per reescriure")
        if len(self.text) > MAX_TEXT_CHARS:
            raise ConfigError(f"El text supera els {MAX_TEXT_CHARS} caràcters")
        object.__setattr__(self, "source_mode", SourceMode.parse(self.source_mode))

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> RewriteRequest:
        level = data.get("level")
        if isinstance(level, str):
            stripped = level.strip()
            if not stripped:
                level = None  # el selector encara no s'ha triat
            elif stripped.isdigit():
                level = int(stripped)
            else:
                raise ConfigError("«level» ha de ser un enter entre 1 i 5")
        if isinstance(level, bool) or not isinstance(level, int | None):
            raise ConfigError("«level» ha de ser un enter entre 1 i 5")
        return cls(
            text=str(data.get("text", "")),
            mode=RewriteMode.parse(str(data.get("mode", RewriteMode.DEEP.value))),
            level=level,
            style_profile=str(data.get("style_profile") or DEFAULT_STYLE_PROFILE),
            dictionaries=_as_names(data.get("dictionaries")),
            preferences=str(data.get("preferences") or ""),
            rule_set=str(data.get("rule_set") or DEFAULT_RULE_SET),
            languagetool=bool(data.get("languagetool", False)),
            source_mode=SourceMode.parse(str(data.get("source_mode") or SourceMode.OWN.value)),
        )

    def to_config(self, home: Path | None = None) -> PipelineConfig:
        """Configuració de la canonada amb l'envoltant del mode aplicat."""
        base = PipelineConfig(
            home=home,
            rule_set=self.rule_set,
            style_profile=self.style_profile,
            dictionaries=self.dictionaries,
            preferences=self.preferences or None,
            languagetool=self.languagetool,
            source_mode=self.source_mode,
        )
        return mode_settings(self.mode).apply(base, self.level)


@dataclass(frozen=True, slots=True)
class FeedbackRequest:
    """Marca d'un candidat com a preferit, acceptable o rebutjat."""

    verdict: str
    variants: tuple[str, ...] = ()
    text: str = ""
    source_text: str = ""
    preferences: str = ""
    source_mode: SourceMode = SourceMode.OWN
    """D'on venia el text valorat, per distingir-ho a l'historial local de feedback."""

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise ConfigError(
                f"Veredicte desconegut: «{self.verdict}» (vàlids: {', '.join(VERDICTS)})"
            )
        object.__setattr__(self, "source_mode", SourceMode.parse(self.source_mode))

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> FeedbackRequest:
        return cls(
            verdict=str(data.get("verdict", "")),
            variants=_as_names(data.get("variants")),
            text=str(data.get("text") or ""),
            source_text=str(data.get("source_text") or ""),
            preferences=str(data.get("preferences") or ""),
            source_mode=SourceMode.parse(str(data.get("source_mode") or SourceMode.OWN.value)),
        )


def _as_names(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value if str(item).strip())
    raise ConfigError("S'esperava una llista de noms")


# --- servei ------------------------------------------------------------------------------------


class RewriteService:
    """Punt d'entrada únic de la interfície local.

    Manté una cau de canonades per configuració, perquè la interfície no hagi
    de tornar a carregar el lexicó i les regles a cada petició. La cau es
    buida quan es registra feedback, ja que els pesos canvien.

    El servidor és de diversos fils i, en mode de xarxa local, hi poden
    arribar dos navegadors alhora. Tot el que escriu (feedback, empremtes,
    registre, cau de canonades) passa per un pany, de manera que dues
    peticions simultànies no es trepitgen. La reescriptura, que només
    llegeix, no s'hi serialitza.
    """

    def __init__(
        self,
        paths: ProjectPaths | None = None,
        *,
        history: HistoryLog | None = None,
        rule_set: str = DEFAULT_RULE_SET,
    ) -> None:
        self._paths = paths or ProjectPaths.discover()
        self._rule_set = rule_set
        # Comparació amb None, no «or»: un registre buit té longitud 0 i seria fals.
        self._history = (
            HistoryLog(self._paths.root / DEFAULT_HISTORY_FILE) if history is None else history
        )
        self._pipelines: dict[PipelineConfig, Pipeline] = {}
        # Puja cada cop que es buida la memòria de canonades: una canonada
        # que s'estigui construint amb els pesos vells no s'hi desa.
        self._pipeline_generation = 0
        #: Reentrant: registrar feedback buida la cau de canonades dins del mateix pany.
        self._lock = threading.RLock()
        #: Instal·ladors en marxa, per component: dos navegadors no en poden
        #: engegar dos alhora del mateix component.
        self._installers: dict[str, subprocess.Popen[bytes]] = {}
        self._observer: DocumentObserver | None = None
        self._analyzer: RuleBasedAnalyzer | None = None
        self._syntax: SpacySyntax | None = None

    @property
    def paths(self) -> ProjectPaths:
        return self._paths

    @property
    def history(self) -> HistoryLog:
        return self._history

    # -- opcions ---------------------------------------------------------------------------

    def options(self) -> JsonDict:
        """Tot el que la interfície necessita per omplir els seus selectors."""
        return {
            "version": __version__,
            "root": str(self._paths.root),
            "rule_set": self._rule_set,
            "levels": [{"level": n, "label": level_label(n)} for n in sorted(LEVEL_LABELS)],
            "modes": [settings.to_dict() for settings in MODES.values()],
            "style_profiles": self.style_profiles(),
            "dictionaries": self.dictionaries(),
            "preferences": self.preferences(),
            "history": self._history.status(),
            "resources": self.resources(),
            "installers": self.installers(),
            "fingerprints_directory": str(self._paths.fingerprints),
            "source_modes": self.source_modes(),
            "fingerprint_required": FINGERPRINT_REQUIRED,
        }

    def source_modes(self) -> list[JsonDict]:
        """Orígens del text que l'usuari pot indicar. El motor no els endevina mai."""
        return [
            {
                "id": mode.value,
                "label": mode.label,
                "description": mode.description,
                "requires_fingerprint": mode.adapts_to_author,
                "default": mode is SourceMode.OWN,
            }
            for mode in SourceMode
        ]

    def resources(self) -> JsonDict:
        """Estat dels recursos lingüístics opcionals i del mode fora de línia."""
        return resources_status(self._paths.root).to_dict()

    def installers(self) -> JsonDict:
        """Informació de cada component instal·lable, per ensenyar-la abans de baixar res."""
        return {name: install_info(name) for name in INSTALLERS}

    def style_profiles(self) -> list[JsonDict]:
        """Perfils d'estil (``resources/style/*.yaml``) i empremtes (``style/*.json``)."""
        found: list[dict[str, object]] = []
        for file in sorted(self._paths.style.glob("*.yaml")):
            entry: dict[str, object] = {
                "id": file.stem,
                "label": f"{file.stem} (perfil)",
                "kind": "profile",
            }
            try:
                entry["description"] = str(load_mapping(file).get("description", ""))
            except ParafrasiError as exc:
                entry["error"] = str(exc)
            found.append(entry)
        for file in sorted(self._paths.fingerprints.glob("*.json")):
            if file.name == "fingerprint.schema.json":
                continue
            entry = {
                "id": f"style/{file.name}",
                "label": f"{file.stem} (empremta)",
                "kind": "fingerprint",
            }
            try:
                fingerprint = StyleFingerprint.load(file)
                entry["description"] = (
                    f"{fingerprint.n_documents} documents · {fingerprint.n_words} paraules"
                )
            except ParafrasiError as exc:
                entry["error"] = str(exc)
            found.append(entry)
        return found

    def dictionaries(self) -> list[JsonDict]:
        """Diccionaris terminològics disponibles a ``dictionaries/``."""
        found: list[dict[str, object]] = []
        for file in sorted(self._paths.dictionaries.glob("*.yml")):
            entry: dict[str, object] = {"id": file.stem, "label": file.stem}
            try:
                dictionary = TermDictionary.load(file)
                entry["description"] = dictionary.description
                entry["n_entries"] = len(dictionary.entries)
                entry["n_protected"] = len(dictionary.protected_terms)
            except ParafrasiError as exc:
                entry["error"] = str(exc)
            found.append(entry)
        return found

    def preferences(self) -> list[JsonDict]:
        """Fitxers de preferències de ``preferences/`` (el de feedback no hi surt)."""
        found: list[dict[str, object]] = []
        directory = self._paths.preferences
        if not directory.is_dir():
            return found
        for file in sorted(directory.glob("*.yml")):
            try:
                data = load_mapping(file)
            except ParafrasiError as exc:
                found.append({"id": file.stem, "label": file.stem, "error": str(exc)})
                continue
            if "variants" in data:
                continue  # és un fitxer de feedback, no de preferències
            entry: dict[str, object] = {"id": file.stem, "label": file.stem}
            try:
                author = AuthorPreferences.load(file)
                entry["label"] = author.name
                entry["description"] = author.description
            except ParafrasiError as exc:
                entry["error"] = str(exc)
            found.append(entry)
        return found

    # -- reescriptura ----------------------------------------------------------------------

    def pipeline_for(self, config: PipelineConfig) -> Pipeline:
        pipeline = self._pipelines.get(config)
        if pipeline is not None:
            return pipeline
        with self._lock:
            generacio = self._pipeline_generation
        # Construir la canonada triga i es fa fora del pany: si es fes a dins,
        # el primer «reescriu» d'un navegador aturaria l'altre uns segons.
        pipeline = build_pipeline(config)
        with self._lock:
            if generacio != self._pipeline_generation:
                # Mentre es construïa, algú ha desat una valoració o una
                # empremta: aquesta canonada ja duu els pesos vells i no s'ha
                # de desar, però serveix per a la petició que l'ha demanada.
                return pipeline
            # Dos navegadors poden construir la mateixa canonada alhora; es
            # queda la primera que hi arribi i totes dues reben la mateixa.
            return self._pipelines.setdefault(config, pipeline)

    def rewrite(self, request: RewriteRequest) -> JsonDict:
        """Executa la canonada i retorna tot el que la interfície ha de mostrar."""
        settings = mode_settings(request.mode)
        config = request.to_config(self._paths.root)
        pipeline = self.pipeline_for(config)
        result = pipeline.run(request.text)
        effective = settings.level_for(request.level)
        requested = settings.max_level if request.level is None else request.level
        adaptation = pipeline.adaptation
        return {
            "source_text": result.source_text,
            "source_mode": {
                "id": request.source_mode.value,
                "label": request.source_mode.label,
                "description": request.source_mode.description,
            },
            "author_adaptation": adaptation.describe() if adaptation is not None else "",
            "author_adaptation_components": (
                list(adaptation.active_components()) if adaptation is not None else []
            ),
            "output_text": result.output_text,
            "changed": result.changed,
            "rule_set": result.rule_set_name,
            "rule_ids": list(result.rule_ids),
            "style_profile": result.style_profile_name,
            "style_profile_id": request.style_profile,
            "dictionaries": list(result.dictionary_names),
            "preferences": result.preferences_name,
            "preferences_id": request.preferences,
            "mode": settings.to_dict(),
            "languagetool": self._languagetool_used(config),
            "level": effective,
            "requested_level": requested,
            "level_capped": effective < requested,
            "level_label": level_label(effective),
            "n_candidates": result.n_candidates,
            "n_rejected_candidates": result.n_rejected_candidates,
            "protected_spans": [_protected(span) for span in result.protected_spans],
            "units": self._units(result),
        }

    def _languagetool_used(self, config: PipelineConfig) -> bool:
        """Cert si la validació de LanguageTool ha intervingut realment."""
        if not config.languagetool:
            return False
        return any(v.validator_id == "languagetool" for v in self.pipeline_for(config).validators)

    def _units(self, result: ParaphraseResult) -> list[JsonDict]:
        units: list[dict[str, object]] = []
        for sentence in result.sentences:
            units.append(
                self._unit(sentence, "sentence", sentence.index, f"Frase {sentence.index + 1}")
            )
        for paragraph in result.paragraphs:
            if len(paragraph.candidates) <= 1 and not paragraph.rejected_proposals:
                continue  # cap regla entre frases hi ha proposat res
            units.append(
                self._unit(
                    paragraph,
                    "paragraph",
                    paragraph.index,
                    f"Paràgraf {paragraph.index + 1} (regles entre frases)",
                )
            )
        return units

    def _unit(self, unit: _UnitResult, kind: str, index: int, label: str) -> JsonDict:
        prefix = "s" if kind == "sentence" else "p"
        unit_id = f"{prefix}{index}"
        # Per a un paràgraf, l'origen dels candidats és el text ja passat per les regles de frase.
        source = unit.selected.candidate.source_text
        return {
            "unit_id": unit_id,
            "kind": kind,
            "index": index,
            "label": label,
            "source_text": source,
            "output_text": unit.selected.candidate.text,
            "changed": unit.selected.candidate.text != source,
            "candidates": [
                self._candidate(f"{unit_id}-{n}", evaluated, source)
                for n, evaluated in enumerate(unit.candidates)
            ],
            "rejected_proposals": [
                {
                    "rule_id": rejected.transformation.rule_id,
                    "text_before": rejected.transformation.text_before,
                    "text_after": rejected.transformation.text_after,
                    "reason": rejected.reason,
                }
                for rejected in unit.rejected_proposals
            ],
        }

    def _candidate(self, candidate_id: str, evaluated: EvaluatedCandidate, source: str) -> JsonDict:
        candidate = evaluated.candidate
        score = evaluated.score
        return {
            "candidate_id": candidate_id,
            "text": candidate.text,
            "selected": evaluated.selected,
            "accepted": evaluated.accepted,
            "is_identity": candidate.is_identity,
            "rejection_reason": evaluated.rejection_reason,
            "change_ratio": round(candidate.change_ratio(), 4),
            "signature": candidate.signature,
            "families": [f.value for f in candidate.families],
            "structural_degree": candidate.structural_degree(),
            "cross_sentence": any(t.family.cross_sentence for t in candidate.transformations),
            "score": None if score is None else score.to_dict(),
            "rules": [
                {
                    "rule_id": t.rule_id,
                    "text_before": t.text_before,
                    "text_after": t.text_after,
                    "explanation": t.explanation,
                    "semantic_risk": t.semantic_risk.value,
                    "confidence": t.confidence,
                    "category": t.metadata.get("category", ""),
                    "family": t.family.value,
                    "evidence": t.metadata.get("evidence", ""),
                }
                for t in candidate.transformations
            ],
            "warnings": [issue.to_dict() for issue in evaluated.validation.warnings],
            "errors": [issue.to_dict() for issue in evaluated.validation.errors],
            "diff": [part.to_dict() for part in word_diff(source, candidate.text)],
            "variants": list(self.introduced_variants(source, candidate.text)),
        }

    # -- variants conegudes (pont amb el feedback) ------------------------------------------

    def _document_observer(self) -> DocumentObserver:
        if self._observer is None:
            self._observer = DocumentObserver(StyleResources.load(self._paths))  # variants.yaml
        return self._observer

    def _syntax_provider(self) -> SpacySyntax:
        """Parser local per al perfil sintàctic de l'empremta (només analitza)."""
        with self._lock:
            # Crear-lo no carrega res (la càrrega és mandrosa): el pany només
            # evita que dos navegadors alhora en facin dos.
            if self._syntax is None:
                self._syntax = SpacySyntax()
            return self._syntax

    def _text_analyzer(self) -> RuleBasedAnalyzer:
        if self._analyzer is None:
            self._analyzer = RuleBasedAnalyzer()
        return self._analyzer

    def _variant_counts(self, text: str) -> Counter[str]:
        analysis = self._text_analyzer().analyze(text)
        observations = self._document_observer().observe(analysis)
        counts: Counter[str] = Counter()
        for group in observations.variants.values():
            for variant_id, examples in group.items():
                counts[variant_id] += len(examples)
        return counts

    def introduced_variants(self, source: str, text: str) -> tuple[str, ...]:
        """Variants equivalents conegudes que el candidat introdueix respecte de l'original.

        Són les claus amb què es registra el feedback («obra de», «fet per»),
        i surten dels grups de ``resources/ca/style/variants.yaml``.
        """
        if text == source:
            return ()
        before = self._variant_counts(source)
        after = self._variant_counts(text)
        return tuple(sorted(form for form, n in after.items() if n > before.get(form, 0)))

    # -- feedback ----------------------------------------------------------------------------

    def feedback_path(self, preferences: str = "") -> Path:
        """Fitxer de feedback: el que indiqui el fitxer de preferències, o el del projecte."""
        if preferences:
            try:
                author = AuthorPreferences.load(self._paths.resolve_preferences(preferences))
            except ParafrasiError:
                author = None
            if author is not None and author.feedback_file is not None:
                return author.feedback_file
        return self._paths.preferences / DEFAULT_FEEDBACK_FILE

    def record_feedback(self, request: FeedbackRequest) -> JsonDict:
        """Registra el veredicte de l'usuari sobre les variants d'un candidat."""
        variants = request.variants
        if not variants and request.text and request.source_text:
            variants = self.introduced_variants(request.source_text, request.text)
        path = self.feedback_path(request.preferences)
        if not variants:
            return {
                "verdict": request.verdict,
                "source_mode": request.source_mode.value,
                "path": str(path),
                "recorded": [],
                "message": (
                    "El candidat no introdueix cap variant equivalent coneguda: "
                    "no s'ha registrat res."
                ),
            }
        with self._lock:
            # Llegir, actualitzar i desar sense que dues peticions es perdin recomptes.
            store = FeedbackStore.load(path)
            recorded: list[JsonDict] = []
            for variant in variants:
                counts = store.record(variant, request.verdict)
                recorded.append(
                    {
                        "variant": variant,
                        **counts.to_dict(),
                        "weight": round(counts.weight(store.prior), 4),
                        "description": counts.describe(),
                    }
                )
            store.save(path)
            self._pipelines.clear()  # els pesos han canviat: cal reconstruir les canonades
            self._pipeline_generation += 1
        return {
            "verdict": request.verdict,
            "source_mode": request.source_mode.value,
            "path": str(path),
            "recorded": recorded,
            "message": f"Registrat a {path}",
        }

    def feedback_summary(self, preferences: str = "") -> JsonDict:
        path = self.feedback_path(preferences)
        store = FeedbackStore.load(path)
        return {
            "path": str(path),
            "prior": store.prior,
            "variants": [
                {
                    "variant": form,
                    **counts.to_dict(),
                    "weight": round(counts.weight(store.prior), 4),
                }
                for form, counts in ((f, store.counts_of(f)) for f in store.forms)
                if counts is not None
            ],
        }

    # -- resum d'una empremta: estructura i ritme ------------------------------------------------

    def fingerprint_summary(self, reference: str) -> JsonDict:
        """«Estructura i ritme» d'una empremta, en termes entenedors i amb els detalls a part.

        Amb una empremta antiga (esquema 1.0) les seccions noves surten com a no
        disponibles i es proposa tornar-la a crear; no s'inventa cap dada.
        """
        # «style/<nom>.json» (l'identificador del selector) o un nom dins de style/.
        fingerprint = StyleFingerprint.load(self._paths.resolve_fingerprint(reference))
        rhythm = fingerprint.features.get("rhythm_profile")
        syntax = fingerprint.features.get("syntactic_profile")
        hints: list[str] = []
        if not fingerprint.has_rhythm_profile:
            hints.append("ritme de frases")
        if not fingerprint.has_syntactic_profile:
            hints.append("estructura sintàctica")
        return {
            "id": reference,
            "name": fingerprint.name,
            "schema_version": fingerprint.schema_version,
            "n_documents": fingerprint.n_documents,
            "n_words": fingerprint.n_words,
            "parser": str(fingerprint.generator.get("parser", "")),
            "rhythm": _rhythm_summary(rhythm) if isinstance(rhythm, Mapping) else _unavailable(),
            "syntax": _syntax_summary(syntax) if isinstance(syntax, Mapping) else _unavailable(),
            "regenerate_hint": (
                "Aquesta empremta no té " + " ni ".join(hints) + ". Torna-la a crear amb els "
                "teus textos"
                + (" i el parser instal·lat" if "estructura sintàctica" in hints else "")
                + " per obtenir-los."
                if hints
                else ""
            ),
            "details": {
                "rhythm_profile": dict(rhythm) if isinstance(rhythm, Mapping) else None,
                "syntactic_profile": dict(syntax) if isinstance(syntax, Mapping) else None,
            },
        }

    # -- instal·lació de components opcionals ------------------------------------------------

    def install_component(self, component: str, confirmed: bool) -> JsonDict:
        """Instal·la un component opcional, però només amb confirmació explícita.

        Sense confirmació no es baixa res: només es retorna la informació del
        component perquè la interfície la pugui ensenyar. La descàrrega la fan
        els scripts de ``scripts/``, que són fora del paquet, i s'executen en
        aquest ordinador, no al dispositiu que ho ha demanat.

        Si el component ja s'està instal·lant —dos navegadors hi poden ser
        alhora en mode de xarxa local— no se n'engega un segon.
        """
        relative = INSTALLERS.get(component)
        if relative is None:
            raise ConfigError(
                f"Component desconegut: «{component}» (vàlids: {', '.join(INSTALLERS)})"
            )
        info = install_info(component)
        if not confirmed:
            return {**info, "started": False, "message": "Cal confirmar-ho abans de baixar res."}
        script = self._paths.root / relative
        if not script.is_file():
            return {
                **info,
                "started": False,
                "message": (
                    "No s'ha trobat l'instal·lador en aquesta còpia. Executeu aquesta ordre "
                    "en un terminal:"
                ),
                "command": f"python {relative} --yes",
            }
        with self._lock:
            running = self._installers.get(component)
            if running is not None and running.poll() is None:
                return {
                    **info,
                    "started": False,
                    "pid": running.pid,
                    "message": (
                        "Aquest component ja s'està instal·lant en aquest ordinador. "
                        "Espereu que acabi; l'estat s'actualitzarà sol."
                    ),
                }
            process = subprocess.Popen(  # noqa: S603 - ruta pròpia del projecte, sense shell
                [sys.executable, str(script), "--yes"],
                cwd=self._paths.root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._installers[component] = process
        return {
            **info,
            "started": True,
            "pid": process.pid,
            "message": (
                "S'està instal·lant a l'ordinador que executa Parafrasi-cat. "
                "Pot trigar uns minuts; l'estat s'actualitzarà sol."
            ),
        }

    # -- empremta de l'autor -----------------------------------------------------------------

    def create_fingerprint(
        self, name: str, texts: Sequence[str], *, source_mode: str | SourceMode = SourceMode.OWN
    ) -> JsonDict:
        """Construeix l'empremta d'un autor amb els textos que arriben de la interfície.

        Els textos són de l'usuari i no van a Internet: viatgen fins a
        l'ordinador que executa el motor —el mateix, o un altre de la xarxa
        local—, s'hi processen en memòria i només se'n desa l'empremta, que és
        un JSON de recomptes i estadístics. No s'entrena cap model.

        Només hi entren textos propis: un esborrany generat amb LLM no pot formar
        part del corpus de l'autor, perquè contaminaria l'empremta.
        """
        if SourceMode.parse(source_mode).adapts_to_author:
            raise ConfigError(LLM_DRAFT_NOT_CORPUS)
        clean = " ".join(name.split()) or "autor"
        if not re.fullmatch(r"[\w .\-]{1,60}", clean):
            raise ConfigError(
                "El nom de l'empremta només pot tenir lletres, xifres, espais i guions"
            )
        useful = [text for text in texts if text.strip()]
        if not useful:
            raise ConfigError("Cal almenys un text per construir l'empremta")
        corpus = corpus_from_texts(useful)
        resources = StyleResources.load(self._paths)
        fingerprint = build_fingerprint(
            corpus,
            resources,
            self._text_analyzer(),
            name=clean,
            description="Creada des de la interfície",
            syntax=self._syntax_provider(),
        )
        target = self._paths.fingerprints / f"{clean}.json"
        with self._lock:
            fingerprint.save(target)
            self._pipelines.clear()  # hi ha una empremta nova disponible
            self._pipeline_generation += 1
        return {
            "name": clean,
            "path": str(target),
            "id": f"style/{target.name}",
            "n_documents": fingerprint.n_documents,
            "n_words": fingerprint.n_words,
            "summary": StylePreferences(fingerprint).summary(),
            "message": f"Empremta «{clean}» creada amb {len(useful)} textos.",
        }

    # -- historial ---------------------------------------------------------------------------

    def set_history_enabled(self, enabled: bool) -> JsonDict:
        self._history.enable(enabled)
        return self._history.status()

    def save_history(self, data: Mapping[str, object]) -> JsonDict:
        """Desa una entrada del registre (si està activat) i retorna l'estat."""
        entry = self._history.append(data)
        status = self._history.status()
        status["saved"] = entry is not None
        status["entry_id"] = entry.entry_id if entry is not None else ""
        return status

    def history_entries(self) -> JsonDict:
        status = self._history.status()
        status["entries"] = [entry.summary() for entry in self._history.entries()]
        return status

    def history_export(self) -> str:
        return self._history.export_json()


#: Descripció de cada component instal·lable. Es mostra sencera abans de
#: baixar res, i la confirmació de l'usuari és obligatòria.
_INSTALL_INFO: dict[str, JsonDict] = {
    "morphology": {
        "component": "Morfologia catalana",
        "purpose": (
            "Flexió i concordança fiables: lema, categoria, gènere, nombre, persona, "
            "temps i mode de més d'un milió de formes catalanes."
        ),
        "origin": "https://github.com/Softcatala/catalan-dict-tools",
        "version": "darrera revisió del repositori (es desa el commit exacte)",
        "license": "GPL-2.0-or-later OR LGPL-2.1-or-later",
        "approximate_size_mb": 90,
        "requirement": "git",
        "offline_after_install": True,
        "note": (
            "Les dades són de Softcatalà (Jaume Ortolà i Joan Moratinos), són copyleft i no "
            "es distribueixen amb el programa: es baixen del repositori original i el recurs "
            "es genera en aquest ordinador."
        ),
    },
    "languagetool": {
        "component": "LanguageTool",
        "purpose": "Validació avançada de gramàtica, concordança i puntuació en català.",
        "origin": "https://languagetool.org/download/LanguageTool-stable.zip",
        "version": "estable (provada: 6.6)",
        "license": "LGPL-2.1-or-later",
        "approximate_size_mb": 250,
        "requirement": "Java",
        "offline_after_install": True,
        "note": (
            "La descàrrega es fa una sola vegada. Després, LanguageTool s'executa en aquest "
            "ordinador i no s'envia cap text enlloc."
        ),
    },
    "parser": {
        "component": "Parser sintàctic català",
        "purpose": (
            "Analitza dependències, subjecte, objecte, subordinades i coordinacions perquè "
            "les transformacions estructurals es puguin fer amb seguretat."
        ),
        "origin": "https://pypi.org/project/spacy/ i https://github.com/explosion/spacy-models",
        "version": "spaCy + ca_core_news_sm (UD Catalan AnCora)",
        "license": "spaCy: MIT · model: GPL-3.0",
        "approximate_size_mb": 120,
        "requirement": "Python 3.11 o superior",
        "offline_after_install": True,
        "note": (
            "El model només analitza: no genera text ni pren cap decisió. Un cop instal·lat, "
            "no cal connexió per a res."
        ),
    },
}


_BUCKET_LABELS = {"short": "Curta", "medium": "Mitjana", "long": "Llarga"}
_CONFIDENCE_LABELS = {"high": "alta", "medium": "mitjana", "low": "baixa"}


def _unavailable() -> JsonDict:
    return {"available": False}


def _frequency_label(share: float) -> str:
    if share >= 0.5:
        return "molt freqüent"
    if share >= 0.3:
        return "freqüent"
    if share >= 0.15:
        return "ocasional"
    return "poc freqüent"


def _rhythm_summary(profile: Mapping[str, object]) -> JsonDict:
    length = profile.get("length")
    buckets = profile.get("buckets")
    transitions = profile.get("transitions")
    alternation = profile.get("alternation")
    runs = profile.get("runs")
    if not isinstance(length, Mapping) or not length:
        return _unavailable()
    shares = buckets.get("shares") if isinstance(buckets, Mapping) else None
    thresholds = buckets.get("thresholds") if isinstance(buckets, Mapping) else None
    row_shares = transitions.get("shares") if isinstance(transitions, Mapping) else None
    lag = (
        alternation.get("lag1_sentence_length_correlation")
        if isinstance(alternation, Mapping)
        else None
    )
    change = (
        alternation.get("mean_absolute_sentence_length_change")
        if isinstance(alternation, Mapping)
        else None
    )
    if isinstance(lag, int | float) and not isinstance(lag, bool):
        tendency = (
            "alternança marcada"
            if lag < -0.2
            else "ritme força uniforme"
            if lag > 0.2
            else "alternança moderada"
        )
    else:
        tendency = "no hi ha prou frases per mesurar l'alternança"
    return {
        "available": True,
        "confidence": _CONFIDENCE_LABELS.get(str(profile.get("confidence")), "baixa"),
        "sample_size_sentences": profile.get("sample_size_sentences", 0),
        "typical_length": length.get("median"),
        "mean_length": length.get("mean"),
        "variation": length.get("cv"),
        "shares": {
            _BUCKET_LABELS[k]: float(v)
            for k, v in (shares.items() if isinstance(shares, Mapping) else [])
            if isinstance(v, int | float) and not isinstance(v, bool) and k in _BUCKET_LABELS
        },
        "thresholds": dict(thresholds) if isinstance(thresholds, Mapping) else {},
        "tendency": tendency,
        "lag1": lag,
        "mean_change": change,
        "transitions": [
            {
                "from": _BUCKET_LABELS[a],
                "to": _BUCKET_LABELS[b],
                "share": float(row_shares.get(f"{a}_to_{b}", 0.0)),
                "label": _frequency_label(float(row_shares.get(f"{a}_to_{b}", 0.0))),
            }
            for a in ("short", "medium", "long")
            for b in ("short", "medium", "long")
            if isinstance(row_shares, Mapping)
        ],
        "runs": dict(runs) if isinstance(runs, Mapping) else {},
    }


def _syntax_summary(profile: Mapping[str, object]) -> JsonDict:
    if profile.get("available") is not True:
        return {"available": False, "reason": str(profile.get("reason", ""))}
    coordination = profile.get("coordination")
    subordination = profile.get("subordination")
    order = profile.get("order")
    complexity = profile.get("complexity")
    distance = profile.get("dependency_distance")
    patterns = profile.get("patterns")

    def get(node: object, key: str) -> object:
        return node.get(key) if isinstance(node, Mapping) else None

    subject_before = get(order, "subject_before_verb_rate")
    if isinstance(subject_before, int | float):
        subject_order = (
            "subjecte abans del verb"
            if subject_before >= 0.6
            else "subjecte després del verb"
            if subject_before <= 0.4
            else "subjecte abans i després del verb per igual"
        )
    else:
        subject_order = "no hi ha prou subjectes per dir-ho"
    top = get(patterns, "top")
    return {
        "available": True,
        "confidence": _CONFIDENCE_LABELS.get(str(profile.get("confidence")), "baixa"),
        "sample_size_sentences": profile.get("sample_size_sentences", 0),
        "parser": str(profile.get("parser", "")),
        "coordination_per_sentence": get(coordination, "per_sentence"),
        "coordination_by_type": get(coordination, "by_type"),
        "subordination_per_sentence": get(subordination, "per_sentence"),
        "sentences_with_subordination_share": get(
            subordination, "sentences_with_subordination_share"
        ),
        "subordination_by_type": get(subordination, "by_type"),
        "subject_order": subject_order,
        "subject_before_verb_rate": subject_before,
        "preposed_complement_rate": get(order, "preposed_complement_rate"),
        "clauses_per_sentence": get(complexity, "clauses_per_sentence"),
        "simple_sentence_ratio": get(complexity, "simple_sentence_ratio"),
        "mean_parse_depth": get(complexity, "mean_parse_depth"),
        "mean_dependency_distance": get(distance, "mean_dependency_distance"),
        "top_patterns": list(top[:5]) if isinstance(top, list) else [],
    }


def install_info(component: str = "languagetool") -> JsonDict:
    """Descripció d'un component opcional, per ensenyar-la abans de baixar res."""
    return dict(_INSTALL_INFO[component])


def _protected(span: ProtectedSpan) -> JsonDict:
    return {
        "text": span.text,
        "kind": span.kind.value,
        "label": span.kind.label,
        "start": span.start,
        "end": span.end,
        "detector_id": span.detector_id,
        "note": span.note,
    }
