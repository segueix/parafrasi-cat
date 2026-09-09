"""Activa ↔ passiva d'esdeveniments acabats, amb agent i pacient explícits.

Marc restringit al passat perifràstic de tercera persona. Ni subjectes
quantificats, ni pronoms, ni complements de règim, ni clítics, ni modalitat.
"""
from __future__ import annotations

from collections.abc import Iterable

from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.transformation import Transformation
from parafrasi_cat.morphology.features import MorphFeatures
from parafrasi_cat.rules.base import Rule, RuleContext
from parafrasi_cat.rules.definition import RuleDefinition

# Inventari finit i revisable d'accions que admeten la passiva amb agent.
PARTICIPLES = {"restaurar": "restaurat", "publicar": "publicat", "catalogar": "catalogat",
               "documentar": "documentat", "revisar": "revisat", "analitzar": "analitzat",
               "construir": "construït", "traduir": "traduït", "descriure": "descrit",
               "editar": "editat", "inventariar": "inventariat", "transcriure": "transcrit"}


FEMININES = {"restaurat": "restaurada", "publicat": "publicada", "catalogat": "catalogada",
              "documentat": "documentada", "revisat": "revisada", "analitzat": "analitzada",
              "construït": "construïda", "traduït": "traduïda", "descrit": "descrita",
              "editat": "editada", "inventariat": "inventariada", "transcrit": "transcrita"}


def lower_determiner(text: str, proper: bool = False) -> str:
    if not proper and text.startswith(("L'", "L’")):
        return "l" + text[1:]
    return text[0].lower() + text[1:] if text.split()[0] in ("El", "La", "Els", "Les") else text


def agent_phrase(text: str, proper: bool = False) -> str:
    text = lower_determiner(text, proper)
    if text.startswith("el "):
        return "pel " + text[3:]
    if text.startswith("els "):
        return "pels " + text[4:]
    return "per " + text


class VoiceRule(Rule):
    def __init__(self, definition: RuleDefinition) -> None:
        super().__init__(definition.rule_id, transformation_type=definition.transformation_type,
                         description=definition.description, category="veu", level=3)
        self.definition = definition

    def propose(self, ctx: RuleContext) -> Iterable[Transformation]:
        tree = ctx.parse()
        if not tree.confident:
            ctx.note("Canvi de veu bloquejat: falta una anàlisi sintàctica fiable.")
            return
        root = tree.root
        if root is None or root.lemma not in PARTICIPLES or root.pos != "VERB":
            if " ser " in ctx.text:
                detail = "sense arrel" if root is None else f"{root.text}: lema {root.lemma}, categoria {root.pos}"
                ctx.note(f"Passiva → activa bloquejada: arrel no admesa ({detail}).")
            return
        passive = root.verb_form == "Part"
        # Alguns parsers catalans retornen nsubj i obl/obj sense subtipus passiu.
        # Només acceptem aquesta lectura amb auxiliar passiu i agent conegut.
        explicit_passive = passive and any(
            t.head == root.index and t.lemma.lower() in {"ser", "ésser"}
            and t.dep in {"aux", "aux:pass"} for t in tree.tokens
        )
        subject_deps = {"nsubj:pass", "nsubj"} if explicit_passive else {"nsubj:pass"} if passive else {"nsubj"}
        subjects = [t for t in tree.tokens if t.head == root.index and t.dep in subject_deps]
        objects = [t for t in tree.tokens if t.head == root.index and t.dep == ("obl:agent" if passive else "obj")]
        if passive and not objects and explicit_passive:
            agents = {"taller", "equip", "investigador", "investigadora", "especialista",
                      "restaurador", "restauradora", "autor", "autora", "editor", "editora"}
            objects = [t for t in tree.tokens if t.head == root.index and t.dep in {"obl", "obj"}
                       and t.lemma.lower() in agents
                       and tree.text[slice(*tree.subtree_span(t))].startswith(("per ", "pel ", "pels "))]
        if len(subjects) != 1 or len(objects) != 1:
            if passive:
                labels = ", ".join(f"{t.text}: {t.dep}" for t in tree.tokens if t.head == root.index and t != root)
                ctx.note(f"Passiva → activa bloquejada: subjecte o agent no resolt ({labels}).")
            return
        subject, obj = subjects[0], objects[0]
        def nominal(head, agent=False):
            members = tree.subtree(head)
            allowed = {"det", "amod", "flat", "flat:name"}
            if any(t != head and t.dep not in allowed | ({"case"} if agent else set()) for t in members):
                return None
            if head.pos not in ("NOUN", "PROPN") or head.number not in ("sg", "pl"):
                return None
            if any(t.pos == "PRON" or (t.dep == "det" and t.text.lower() not in ("el", "la", "els", "les", "l'", "l’")) for t in members):
                return None
            start, end = tree.subtree_span(head)
            if not tree.block_check(start, end).ok:
                return None
            return ctx.text[start:end]
        left, right = nominal(subject), nominal(obj, passive)
        if left is None or right is None:
            if passive:
                ctx.note("Passiva → activa bloquejada: falta nombre o hi ha un sintagma nominal complex.")
            return
        aux = "va" if subject.number == "sg" else "van"
        # Exactitud del marc textual: rebutja negació, adverbis de focus,
        # subordinades, complements perduts i altres temps verbals.
        expected = f"{left} {aux} {'ser ' if passive else ''}{root.text} {right}."
        if ctx.text != expected:
            if passive:
                ctx.note("Passiva → activa bloquejada: la frase no encaixa en el marc de passat perifràstic amb agent explícit.")
            return
        if passive:
            if right.startswith("pel "):
                agent = "el " + right[4:]
            elif right.startswith("pels "):
                agent = "els " + right[5:]
            elif right.startswith("per "):
                agent = right[4:]
            else:
                return
            verb = "va" if obj.number == "sg" else "van"
            after = f"{agent[0].upper() + agent[1:]} {verb} {root.lemma} {lower_determiner(left, subject.pos == 'PROPN')}."
        else:
            if root.verb_form != "Inf" or obj.gender not in ("m", "f"):
                return
            forms = ctx.morphology.generate(root.lemma, MorphFeatures(
                pos="verb", mood="part", gender=obj.gender, number=obj.number))
            # Recurs morfològic preferit; reserva només per a aquest inventari.
            part = PARTICIPLES[root.lemma]
            if obj.gender == "f":
                part = FEMININES[part]
            if obj.number == "pl":
                part = part[:-1] + "es" if part.endswith("a") else part + "s"
            if forms:
                if part not in forms:
                    return  # cap forma triada arbitràriament entre lectures
            verb = "va" if obj.number == "sg" else "van"
            after = f"{right[0].upper() + right[1:]} {verb} ser {part} {agent_phrase(left, subject.pos == 'PROPN')}."
        span = Span(0, len(ctx.text))
        if ctx.protected_conflict(span, after) is not None:
            return
        d = self.definition
        yield Transformation(rule_id=self.rule_id, text_before=ctx.text, text_after=after,
            changed_span=span, transformation_type=d.transformation_type,
            confidence=d.confidence, semantic_risk=d.semantic_risk,
            explanation="Canvi d'agent/pacient com a subjecte; conserva el passat perifràstic.",
            metadata={"category": "veu", "level": "3", "family": "SYNTACTIC",
                      "architecture": "passiva_a_activa" if passive else "activa_a_passiva",
                      "parser_required": "true"})
