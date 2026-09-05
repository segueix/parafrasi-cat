"""Classificació explícita de la força i la funció epistemològica.

Cada expressió (marcador) pertany a una *classe* amb una *funció* («dubte»,
«possibilitat», «aparença», «indici», «demostració»...) i una *força* (0 =
impossibilitat de demostrar, 4 = certesa). Dues classes de la mateixa força
no són equivalents: «indica» no és «suggereix», «demostra» no és «confirma».

El :class:`EpistemicValidator` bloqueja qualsevol transformació que canviï
el perfil epistemològic (classes i recomptes) del fragment que reescriu, si
la regla que la proposa no ho autoritza explícitament. La forma no marcada
(«és», «constitueix»...) no es compta, però serveix per descriure una
hipòtesi convertida en afirmació.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.core.errors import ResourceError
from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.text import phrase_pattern
from parafrasi_cat.core.transformation import Transformation
from parafrasi_cat.resources import as_bool, as_mapping_list, as_str, as_str_list, load_mapping
from parafrasi_cat.validation.base import ValidationContext
from parafrasi_cat.validation.categories import EpistemicCategory
from parafrasi_cat.validation.result import (
    ValidationDimension,
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)
from parafrasi_cat.validation.transitions import (
    Transition,
    TransitionVerdict,
    check_categories,
)

EPISTEMOLOGY_FILE = "lexicon/epistemologia.yaml"
CHAINED_RULES_KEY = "chained_rules"

#: Força implícita d'un text sense cap marcador (afirmació neutra).
UNMARKED_STRENGTH = 3


@dataclass(frozen=True, slots=True)
class EpistemicClass:
    """Una classe d'expressions amb la mateixa funció i força epistemològica."""

    id: str
    label: str
    strength: int | None
    markers: tuple[str, ...]
    counted: bool = True
    category: EpistemicCategory = EpistemicCategory.UNKNOWN
    """Categoria (evidència, inferència, hipòtesi, limitació) de la classe."""
    explicit_markers: tuple[str, ...] = ()
    """Formes que fan explícita la categoria (el llenguatge assertiu les prefereix)."""

    def is_explicit(self, marker: str) -> bool:
        return marker.lower().strip() in {m.lower() for m in self.explicit_markers}

    @property
    def on_scale(self) -> bool:
        """Cert si la classe té força en l'escala de certesa (la necessitat deòntica no)."""
        return self.strength is not None


@dataclass(frozen=True, slots=True)
class EpistemicMatch:
    text: str
    span: Span
    class_id: str
    label: str
    strength: int | None
    category: EpistemicCategory = EpistemicCategory.UNKNOWN
    explicit: bool = False

    def describe(self) -> str:
        force = "" if self.strength is None else f", força {self.strength}"
        return f"«{self.text}» ({self.label}{force})"


@dataclass(frozen=True, slots=True)
class EpistemicProfile:
    """Marcadors trobats en un text i recomptes per classe i per categoria (només les comptades)."""

    matches: tuple[EpistemicMatch, ...]
    counts: Counter[str]
    categories: Counter[EpistemicCategory] = field(default_factory=Counter)

    @property
    def strengths(self) -> tuple[int, ...]:
        return tuple(m.strength for m in self.matches if m.strength is not None)

    @property
    def dominant(self) -> EpistemicCategory:
        """Categoria que governa el text: la més feble present (una limitació mana sobre tot)."""
        ranked = [c for c, n in self.categories.items() if n > 0 and c.rank is not None]
        if not ranked:
            return EpistemicCategory.UNKNOWN
        return min(ranked, key=lambda c: c.rank or 0)

    @property
    def explicit_markers(self) -> tuple[str, ...]:
        return tuple(m.text for m in self.matches if m.explicit)

    def describe(self) -> str:
        return ", ".join(m.describe() for m in self.matches) or "(cap marcador)"


@dataclass(frozen=True, slots=True)
class EpistemicChange:
    """Diferència de perfil entre un text original i un de reescrit."""

    lost: tuple[EpistemicMatch, ...]
    gained: tuple[EpistemicMatch, ...]
    direction: str

    def describe(self) -> str:
        before = ", ".join(m.describe() for m in self.lost) or "(cap marcador)"
        after = ", ".join(m.describe() for m in self.gained) or "(cap marcador)"
        return f"{before} → {after}: {self.direction}"


class EpistemicLexicon:
    """Classes epistemològiques carregades de ``resources/ca/lexicon/epistemologia.yaml``."""

    def __init__(self, classes: Iterable[EpistemicClass]) -> None:
        self._classes = tuple(classes)
        self._by_id = {c.id: c for c in self._classes}
        if len(self._by_id) != len(self._classes):
            raise ResourceError("Identificadors de classe epistemològica repetits")
        patterns: list[tuple[str, EpistemicClass, re.Pattern[str]]] = []
        for cls in self._classes:
            for marker in cls.markers:
                patterns.append((marker, cls, phrase_pattern(marker)))
        # Les locucions més llargues primer: «és possible» abans que «és».
        self._patterns = tuple(sorted(patterns, key=lambda item: (-len(item[0]), item[0])))

    @property
    def classes(self) -> tuple[EpistemicClass, ...]:
        return self._classes

    def class_of(self, class_id: str) -> EpistemicClass:
        return self._by_id[class_id]

    def classify_marker(self, marker: str) -> EpistemicClass | None:
        """Classe d'una expressió concreta (o ``None`` si no és cap marcador)."""
        profile = self.profile(marker)
        if len(profile.matches) != 1 or profile.matches[0].text.lower() != marker.lower().strip():
            return None
        return self._by_id[profile.matches[0].class_id]

    def profile(self, text: str) -> EpistemicProfile:
        masked = text
        matches: list[EpistemicMatch] = []
        for _marker, cls, pattern in self._patterns:
            for match in pattern.finditer(masked):
                start, end = match.span()
                matches.append(
                    EpistemicMatch(
                        text[start:end],
                        Span(start, end),
                        cls.id,
                        cls.label,
                        cls.strength,
                        cls.category,
                        cls.is_explicit(_marker),
                    )
                )
                masked = masked[:start] + " " * (end - start) + masked[end:]
        matches.sort(key=lambda m: m.span.start)
        counts: Counter[str] = Counter(
            m.class_id for m in matches if self._by_id[m.class_id].counted
        )
        categories: Counter[EpistemicCategory] = Counter(
            m.category
            for m in matches
            if self._by_id[m.class_id].counted and m.category is not EpistemicCategory.UNKNOWN
        )
        return EpistemicProfile(tuple(matches), counts, categories)

    def categorize(self, text: str) -> EpistemicCategory:
        """Categoria que governa un text: la més feble dels seus marcadors comptats."""
        return self.profile(text).dominant

    def verdict(
        self, before: str, after: str, *, redundancy: bool = False
    ) -> TransitionVerdict | None:
        """Transició de categoria entre dos textos segons la matriu (``None`` si no n'hi ha).

        Dins d'una mateixa categoria, augmentar la força (una atribució «segons
        X» convertida en «està demostrat», un indici en demostració) també és
        una transició prohibida: cap regla no pot fer-la.
        """
        profile_before = self.profile(before)
        profile_after = self.profile(after)
        verdict = check_categories(
            profile_before.categories, profile_after.categories, redundancy=redundancy
        )
        if verdict is not None:
            return verdict
        strongest_before = max(profile_before.strengths, default=UNMARKED_STRENGTH)
        strongest_after = max(profile_after.strengths, default=UNMARKED_STRENGTH)
        if profile_before.counts != profile_after.counts and strongest_after > strongest_before:
            category = profile_after.dominant
            return TransitionVerdict(
                Transition.FORBIDDEN,
                profile_before.dominant,
                category,
                f"augmenta la força expressada dins de la categoria ({strongest_before} → "
                f"{strongest_after})",
            )
        return None

    def change(self, before: str, after: str) -> EpistemicChange | None:
        """Canvi de perfil entre ``before`` i ``after``; ``None`` si són equivalents."""
        profile_before = self.profile(before)
        profile_after = self.profile(after)
        if profile_before.counts == profile_after.counts:
            return None
        lost_counts = profile_before.counts - profile_after.counts
        gained_counts = profile_after.counts - profile_before.counts
        lost = _pick(profile_before.matches, lost_counts)
        gained = _pick(profile_after.matches, gained_counts)
        if not gained:
            # El marcador ha desaparegut: si el text nou té una afirmació no marcada,
            # la mostrem com a destí («sembla» → «és»).
            unmarked = [m for m in profile_after.matches if not self._by_id[m.class_id].counted]
            gained = tuple(unmarked[:1])
        return EpistemicChange(lost, gained, _direction(lost, gained))

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> EpistemicLexicon:
        classes: list[EpistemicClass] = []
        for item in as_mapping_list(data, "classes"):
            raw_strength = item.get("strength")
            strength: int | None
            if raw_strength is None:
                strength = None
            elif isinstance(raw_strength, int) and not isinstance(raw_strength, bool):
                strength = raw_strength
            else:
                raise ResourceError("La força d'una classe epistemològica ha de ser un enter")
            classes.append(
                EpistemicClass(
                    id=as_str(item, "id").strip(),
                    label=as_str(item, "label", "").strip(),
                    strength=strength,
                    markers=tuple(m.strip() for m in as_str_list(item, "markers") if m.strip()),
                    counted=as_bool(item, "counted", True),
                    category=EpistemicCategory.parse(item.get("category")),
                    explicit_markers=tuple(
                        m.strip() for m in as_str_list(item, "explicit_markers") if m.strip()
                    ),
                )
            )
        if not classes:
            raise ResourceError("El recurs epistemològic no defineix cap classe")
        return cls(classes)

    @classmethod
    def load(cls, path: str | Path) -> EpistemicLexicon:
        return cls.from_mapping(load_mapping(path))


def _pick(matches: tuple[EpistemicMatch, ...], counts: Counter[str]) -> tuple[EpistemicMatch, ...]:
    remaining = Counter(counts)
    chosen: list[EpistemicMatch] = []
    for match in matches:
        if remaining[match.class_id] > 0:
            chosen.append(match)
            remaining[match.class_id] -= 1
    return tuple(chosen)


def _direction(lost: tuple[EpistemicMatch, ...], gained: tuple[EpistemicMatch, ...]) -> str:
    before = [m.strength for m in lost if m.strength is not None]
    after = [m.strength for m in gained if m.strength is not None]
    if not before and not after:
        return "canvia la modalitat (fora de l'escala de certesa)"
    strength_before = max(before) if before else UNMARKED_STRENGTH
    strength_after = max(after) if after else UNMARKED_STRENGTH
    if strength_after > strength_before:
        return "augmenta el grau de certesa"
    if strength_after < strength_before:
        return "redueix el grau de certesa"
    return "canvia la funció epistemològica sense canviar-ne la força"


def _who_could(verdict: TransitionVerdict) -> str:
    if verdict.transition is Transition.FORBIDDEN:
        return "cap regla no pot autoritzar aquesta transició"
    return "caldria una regla que ho declarés"


def rule_ids_of(transformation: Transformation) -> tuple[str, ...]:
    """Regla principal i regles encadenades d'una transformació."""
    chained = transformation.metadata.get(CHAINED_RULES_KEY, "")
    return (transformation.rule_id, *(r for r in chained.split(",") if r))


class EpistemicValidator:
    """Bloqueja els canvis de força o funció epistemològica no autoritzats.

    Cada transformació ha de conservar el perfil epistemològic del fragment
    que reescriu. Si el canvia:

    - la matriu de transicions (:mod:`parafrasi_cat.validation.transitions`)
      decideix si el canvi de categoria és impossible (mai cap regla no pot
      convertir una hipòtesi o una inferència en evidència, ni fer desaparèixer
      una limitació o un marcador);
    - un canvi de classe dins del que la matriu permet només passa si totes les
      regles implicades (la principal i les encadenades) figuren a
      ``authorized_rules``;
    - una reducció de redundància (un marcador repetit de la mateixa
      categoria, o una aparença damunt d'una possibilitat) només passa si
      totes les regles figuren a ``redundancy_rules`` i la categoria més feble
      es conserva.

    A més, el candidat sencer ha de conservar el perfil de la frase original
    llevat que alguna transformació autoritzada l'hagi canviat.
    """

    validator_id = "epistemic"
    dimension = ValidationDimension.EPISTEMIC

    def __init__(
        self,
        lexicon: EpistemicLexicon,
        authorized_rules: Iterable[str] = (),
        redundancy_rules: Iterable[str] = (),
    ) -> None:
        self._lexicon = lexicon
        self._authorized = frozenset(authorized_rules)
        self._redundancy = frozenset(redundancy_rules)

    @property
    def lexicon(self) -> EpistemicLexicon:
        return self._lexicon

    @property
    def authorized_rules(self) -> frozenset[str]:
        return self._authorized

    @property
    def redundancy_rules(self) -> frozenset[str]:
        return self._redundancy

    def validate(self, candidate: Candidate, ctx: ValidationContext) -> ValidationResult:
        issues: list[ValidationIssue] = []
        authorized_change = False
        for transformation in candidate.transformations:
            change = self._lexicon.change(transformation.text_before, transformation.text_after)
            if change is None:
                continue
            rules = rule_ids_of(transformation)
            authorized = all(rule in self._authorized for rule in rules)
            redundancy = all(rule in self._redundancy for rule in rules)
            verdict = self._lexicon.verdict(
                transformation.text_before, transformation.text_after, redundancy=redundancy
            )
            if verdict is not None and not verdict.allowed(authorized=authorized):
                issues.append(
                    ValidationIssue(
                        self.validator_id,
                        ValidationSeverity.ERROR,
                        f"La regla «{transformation.rule_id}» {change.describe()} sense cap regla "
                        f"que ho autoritzi: {verdict.describe()} ({_who_could(verdict)})",
                        self.dimension,
                    )
                )
                continue
            if verdict is None and redundancy and not authorized:
                authorized_change = True
                issues.append(
                    ValidationIssue(
                        self.validator_id,
                        ValidationSeverity.WARNING,
                        f"Redundància epistemològica reduïda per la regla "
                        f"«{transformation.rule_id}»: {change.describe()}",
                        self.dimension,
                    )
                )
                continue
            if authorized:
                authorized_change = True
                issues.append(
                    ValidationIssue(
                        self.validator_id,
                        ValidationSeverity.WARNING,
                        f"Canvi epistemològic autoritzat per la regla «{transformation.rule_id}»: "
                        f"{change.describe()}",
                        self.dimension,
                    )
                )
                continue
            issues.append(
                ValidationIssue(
                    self.validator_id,
                    ValidationSeverity.ERROR,
                    f"La regla «{transformation.rule_id}» {change.describe()} "
                    "sense cap regla que ho autoritzi",
                    self.dimension,
                )
            )
        if not any(i.severity is ValidationSeverity.ERROR for i in issues):
            whole = self._lexicon.change(ctx.source_text, candidate.text)
            if whole is not None:
                verdict = self._lexicon.verdict(
                    ctx.source_text, candidate.text, redundancy=authorized_change
                )
                if verdict is not None and not verdict.allowed(authorized=authorized_change):
                    issues.append(
                        ValidationIssue(
                            self.validator_id,
                            ValidationSeverity.ERROR,
                            "El candidat canvia el perfil epistemològic de la frase: "
                            f"{whole.describe()}; {verdict.describe()} ({_who_could(verdict)})",
                            self.dimension,
                        )
                    )
                elif not authorized_change:
                    issues.append(
                        ValidationIssue(
                            self.validator_id,
                            ValidationSeverity.ERROR,
                            "El candidat canvia el perfil epistemològic de la frase: "
                            f"{whole.describe()}",
                            self.dimension,
                        )
                    )
        return ValidationResult(tuple(issues))
