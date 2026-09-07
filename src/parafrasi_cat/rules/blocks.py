"""Moviment de blocs sintàctics tancats (motor «block_move»).

Les regles de patró treballen sobre seqüències de tokens i, per seguretat,
demanen clàusules simples. Aquest motor treballa directament sobre l'arbre de
dependències: quan l'analitzador és fiable, localitza blocs que formen un
**subarbre tancat** (totes les dependències internes hi queden dins i cap
dependència externa no s'hi talla) i els mou sencers entre l'inici, l'interior
i el final de l'oració:

- **subordinades adverbials** (condicionals, temporals, concessives, causals)
  que pengen del verb principal, encara que continguin una completiva o una
  relativa;
- **complements circumstancials** preposicionals del verb principal;
- **modificadors participials** del subjecte, interposats entre comes.

Cada moviment passa les comprovacions de bloc de
:meth:`parafrasi_cat.syntax.analysis.SentenceSyntax.block_check`: subarbre
complet, cap pronom feble segur, cap negació fora del seu domini, i, si el
bloc passa al davant del que el precedia, cap pronom o possessiu que
perdria el referent. Els fragments protegits es comproven com a tota
transformació, i el text del bloc no canvia (només el marcador quan la
posició ho exigeix: «perquè» al davant és «com que», «com que» al final és
«ja que»), de manera que la força epistemològica i la relació discursiva es
conserven. Sense analitzador fiable el motor no proposa res.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from parafrasi_cat.analyzer.clitics import Certainty
from parafrasi_cat.analyzer.lexicon import normalize_form
from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.transformation import Transformation
from parafrasi_cat.resources import as_int, as_mapping, as_str, as_str_list
from parafrasi_cat.rules.base import Rule, RuleContext
from parafrasi_cat.rules.definition import RuleDefinition
from parafrasi_cat.syntax.analysis import SUBJECT_DEPS, SentenceSyntax, SyntaxToken

#: Menes de bloc que el motor sap moure.
KINDS = ("adverbial", "adjunct", "participial")
#: Pes estructural de cada mena (la subordinada reorganitza més que un complement).
STRUCTURAL_WEIGHTS: Mapping[str, float] = {"adverbial": 0.9, "adjunct": 0.6, "participial": 0.7}
#: Relacions d'un complement circumstancial.
ADJUNCT_DEPS = frozenset({"obl", "obl:tmod", "obl:mod", "advmod", "nmod:tmod"})
#: Preposicions que obren un complement que es pot avantposar (mai l'agent «per»).
DEFAULT_PREPOSITIONS = (
    "en", "a", "durant", "des de", "dins", "sota", "davant", "després de", "abans de",
    "al llarg de", "arran de", "a partir de", "amb", "segons", "entre", "sobre", "cap a",
)  # fmt: skip
_TERMINAL = ".!?…"


@dataclass(frozen=True, slots=True)
class Block:
    """Un bloc movible: mena, interval (sense puntuació), posició i marcador inicial."""

    kind: str
    start: int
    end: int
    position: str
    head: SyntaxToken
    marker: str = ""
    clause_start: int = 0
    """Inici de la clàusula on ha d'anar el bloc si passa al davant (0 = la frase)."""


class BlockMoveRule(Rule):
    """Mou blocs sintàctics tancats quan l'analitzador és fiable."""

    def __init__(self, definition: RuleDefinition) -> None:
        super().__init__(
            definition.rule_id,
            transformation_type=definition.transformation_type,
            description=definition.description,
            category=definition.category or "ordre",
            level=definition.level,
        )
        self._definition = definition
        params = definition.params
        kind = as_str(params, "kind", "adverbial")
        if kind not in KINDS:
            raise ValueError(f"La regla «{definition.rule_id}» té una mena de bloc desconeguda")
        self._kind = kind
        self._markers = tuple(
            normalize_form(m) for m in as_str_list(params, "markers") if m.strip()
        )
        self._prepositions = tuple(
            normalize_form(p) for p in (as_str_list(params, "prepositions") or DEFAULT_PREPOSITIONS)
        )
        self._initial_markers = {
            normalize_form(str(k)): str(v) for k, v in as_mapping(params, "initial_markers").items()
        }
        self._final_markers = {
            normalize_form(str(k)): str(v) for k, v in as_mapping(params, "final_markers").items()
        }
        self._comma_final = frozenset(normalize_form(m) for m in as_str_list(params, "comma_final"))
        self._min_words = as_int(params, "min_words", 3 if kind == "adjunct" else 2)
        self._weight = STRUCTURAL_WEIGHTS[kind]

    @property
    def definition(self) -> RuleDefinition:
        return self._definition

    @property
    def kind(self) -> str:
        return self._kind

    # --- proposta ---------------------------------------------------------------------------

    def propose(self, ctx: RuleContext) -> Iterable[Transformation]:
        analysis = ctx.parse()
        if not analysis.confident or not analysis.tokens:
            return
        text = ctx.text
        body_end = max((t.end for t in analysis.tokens if t.pos != "PUNCT"), default=0)
        if body_end <= 0:
            return
        body = text[:body_end]
        clitics = tuple(p.span for p in ctx.sentence.pronouns if p.certainty is Certainty.SURE)
        seen: set[str] = set()
        for block in self._blocks(analysis, text, body_end):
            for target in self._targets(block):
                check = analysis.block_check(
                    block.start, block.end, to_front=(target == "initial"), clitic_spans=clitics
                )
                if not check.ok:
                    ctx.note(
                        f"no s'ha mogut el bloc «{_shorten(text[block.start : block.end])}»: "
                        + "; ".join(check.reasons)
                    )
                    continue
                rebuilt = self._rebuild(text, body_end, block, target, analysis, ctx)
                if rebuilt is None or rebuilt == body or rebuilt in seen:
                    continue
                span = Span(0, body_end)
                if ctx.protected_conflict(span, rebuilt) is not None:
                    continue
                seen.add(rebuilt)
                excerpt = _shorten(text[block.start : block.end])
                yield Transformation(
                    rule_id=self.rule_id,
                    text_before=body,
                    text_after=rebuilt,
                    changed_span=span,
                    transformation_type=self._definition.transformation_type,
                    confidence=self._definition.confidence,
                    semantic_risk=self._definition.semantic_risk,
                    explanation=(
                        f"{self._definition.description} — bloc «{excerpt}» "
                        f"de {block.position} a {target}"
                    ),
                    metadata={
                        "category": self._definition.category or "ordre",
                        "level": str(self._definition.level),
                        "family": "REORDER",
                        "block_kind": block.kind,
                        "movement": f"{block.position}→{target}",
                        "structural_weight": str(self._weight),
                    },
                )

    # --- detecció de blocs ------------------------------------------------------------------

    def _blocks(self, analysis: SentenceSyntax, text: str, body_end: int) -> list[Block]:
        root = analysis.root
        if root is None:
            return []
        verb = analysis.main_verb()
        heads = {root.index} | ({verb.index} if verb is not None else set())
        blocks: list[Block] = []
        for token in analysis.tokens:
            if token.pos == "PUNCT" or token.is_root:
                continue
            block: Block | None = None
            if self._kind == "adverbial" and token.dep == "advcl" and token.head in heads:
                block = self._adverbial(analysis, token, text, body_end)
            elif self._kind == "adjunct" and token.dep in ADJUNCT_DEPS and token.head in heads:
                block = self._adjunct(analysis, token, text, body_end)
            elif self._kind == "participial" and token.verb_form == "Part":
                block = self._participial(analysis, token, text, body_end)
            if block is not None:
                blocks.append(block)
        return blocks

    def _adverbial(
        self, analysis: SentenceSyntax, token: SyntaxToken, text: str, body_end: int
    ) -> Block | None:
        start, end = analysis.subtree_span(token)
        marker = _leading_marker(text[start:end], self._markers)
        if not marker:
            return None
        finite = analysis.finite_tokens_in(start, end)
        if not finite:
            return None
        if normalize_form(marker) == "perquè" and any(t.mood == "subj" for t in finite):
            return None  # final («perquè vinguin»), no causal
        position = _position(text, start, end, body_end)
        if position is None:
            return None
        return Block("adverbial", start, end, position, token, marker)

    def _adjunct(
        self, analysis: SentenceSyntax, token: SyntaxToken, text: str, body_end: int
    ) -> Block | None:
        if token.dep == "obl:agent":
            return None
        start, end = analysis.subtree_span(token)
        block_text = text[start:end]
        if not _leading_marker(block_text, self._prepositions):
            return None
        if len(block_text.split()) < self._min_words:
            return None
        if analysis.finite_tokens_in(start, end):
            return None  # un complement, no una clàusula
        root = analysis.root
        if root is not None and any(
            t.head == root.index and t.dep == "aux:pass" for t in analysis.tokens
        ):
            return None  # en una passiva, «per X» podria ser l'agent
        position = _position(text, start, end, body_end)
        if position != "interposed" and position != "final":
            return None
        return Block("adjunct", start, end, position, token)

    def _participial(
        self, analysis: SentenceSyntax, token: SyntaxToken, text: str, body_end: int
    ) -> Block | None:
        by_index = {t.index: t for t in analysis.tokens}
        if token.dep not in ("acl", "amod", "advcl"):
            return None
        # El participi modifica el subjecte, directament («els elements, considerats...»)
        # o a través d'un complement del nom («cap d'aquests elements, considerat...»).
        subject: SyntaxToken | None = None
        current = by_index.get(token.head)
        for _hop in range(3):
            if current is None:
                break
            if current.dep in SUBJECT_DEPS:
                subject = current
                break
            if current.dep not in ("nmod", "appos", "flat"):
                break
            current = by_index.get(current.head)
        if subject is None:
            return None
        start, end = analysis.subtree_span(token)
        if start != token.start:
            return None  # el participi ha d'obrir el bloc («considerat de manera aïllada»)
        if len(text[start:end].split()) < self._min_words:
            return None
        position = _position(text, start, end, body_end)
        if position != "interposed":
            return None
        verb = by_index.get(subject.head)
        clause_start = 0
        if verb is not None and not verb.is_root:
            clause_start, _ = analysis.subtree_span(verb)
            # El bloc va després del marcador que obre la clàusula («és que, considerat
            # de manera aïllada, cap d'aquests elements permet...»), no abans.
            for marker in sorted(analysis.subtree(verb), key=lambda t: t.start):
                if marker.start != clause_start or marker.dep != "mark":
                    break
                clause_start = marker.end
        return Block("participial", start, end, position, token, clause_start=clause_start)

    def _targets(self, block: Block) -> tuple[str, ...]:
        if block.kind == "adverbial":
            if block.position == "initial":
                return ("final",)
            return ("initial",)
        return ("initial",)

    # --- reconstrucció ------------------------------------------------------------------------

    def _rebuild(
        self,
        text: str,
        body_end: int,
        block: Block,
        target: str,
        analysis: SentenceSyntax,
        ctx: RuleContext,
    ) -> str | None:
        body = text[:body_end]
        block_text = text[block.start : block.end]
        before = body[: block.start]
        after = body[block.end :]
        marker = normalize_form(block.marker)
        if target == "final":
            main = after.lstrip(" ,;")
            if not main:
                return None
            moved = self._final_markers.get(marker, marker) + block_text[len(marker) :]
            separator = ", " if marker in self._comma_final else " "
            return (
                _capitalize(main, analysis, ctx, block.end + (len(after) - len(main)))
                + separator
                + _lower_first(moved, analysis, ctx, block.start)
            )
        # target == "initial"
        if block.position == "interposed":
            main = before.rstrip(" ,;") + " " + after.lstrip(" ,;")
            head_offset = 0
        else:
            main = before.rstrip(" ,;")
            head_offset = 0
        main = main.strip()
        if not main:
            return None
        moved = self._initial_markers.get(marker, marker) + block_text[len(marker) :]
        if block.clause_start > 0:
            # Bloc d'una clàusula subordinada: va al començament d'aquesta clàusula,
            # entre comes, després del marcador que l'obre.
            prefix = before[: block.clause_start].rstrip(" ,;")
            rest = (before[block.clause_start :].rstrip(" ,;") + " " + after.lstrip(" ,;")).strip()
            if not prefix or not rest:
                return None
            return f"{prefix}, {_lower_first(moved, analysis, ctx, block.start)}, {rest}"
        return (
            _capitalize(moved, analysis, ctx, block.start)
            + ", "
            + _lower_first(main, analysis, ctx, head_offset)
        )


def _position(text: str, start: int, end: int, body_end: int) -> str | None:
    before = text[:start].strip()
    after = text[end:body_end].strip()
    if not before:
        return "initial" if after else None
    if not after:
        return "final"
    if before.endswith((",", ";", "—", "–")) and after.startswith((",", ";", "—", "–")):
        return "interposed"
    return None


def _leading_marker(block_text: str, markers: Iterable[str]) -> str:
    low = normalize_form(block_text)
    best = ""
    for marker in markers:
        if (low == marker or low.startswith(marker + " ")) and len(marker) > len(best):
            best = marker
    return block_text[: len(best)] if best else ""


def _capitalize(text: str, analysis: SentenceSyntax, ctx: RuleContext, offset: int) -> str:
    return text[:1].upper() + text[1:]


def _lower_first(text: str, analysis: SentenceSyntax, ctx: RuleContext, offset: int) -> str:
    """Minúscula inicial, llevat d'un nom propi, un fragment protegit o una sigla."""
    if not text:
        return text
    token = analysis.token_at(offset)
    if token is not None and token.pos == "PROPN":
        return text
    if ctx.is_protected(Span(offset, offset + 1)):
        return text
    first = text.split()[0]
    if len(first) > 1 and first.isupper():
        return text
    return text[:1].lower() + text[1:]


def _shorten(text: str, limit: int = 48) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


__all__ = ["KINDS", "STRUCTURAL_WEIGHTS", "Block", "BlockMoveRule"]
