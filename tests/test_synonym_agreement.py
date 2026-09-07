"""Regressions de concordança nominal, sense recursos externs."""
import unittest
from dataclasses import replace
from types import SimpleNamespace

from parafrasi_cat.analyzer.analysis import RuleBasedAnalyzer
from parafrasi_cat.core.spans import Span
from parafrasi_cat.morphology.features import LexicalEntry, MorphFeatures
from parafrasi_cat.morphology.provider import DictionaryMorphology
from parafrasi_cat.synonyms.agreement import replacement
from parafrasi_cat.synonyms.suggester import SynonymSuggester
from parafrasi_cat.syntax.analysis import SentenceSyntax, SyntaxToken


def morphology():
    entries = []
    for lemma, pos, forms in [
        ('canvi', 'noun', [('canvi', 'm', 'sg'), ('canvis', 'm', 'pl')]),
        ('transformació', 'noun', [('transformació', 'f', 'sg'), ('transformacions', 'f', 'pl')]),
        ('acord', 'noun', [('acord', 'm', 'sg')]),
        ('un', 'det', [('un', 'm', 'sg'), ('una', 'f', 'sg'), ('uns', 'm', 'pl'), ('unes', 'f', 'pl')]),
        ('seu', 'det', [('seu', 'm', 'sg'), ('seva', 'f', 'sg')]),
        ('aquest', 'det', [('aquest', 'm', 'sg'), ('aquesta', 'f', 'sg')]),
        ('profund', 'adj', [('profund', 'm', 'sg'), ('profunda', 'f', 'sg'), ('profunds', 'm', 'pl'), ('profundes', 'f', 'pl')]),
        ('important', 'adj', [('important', 'm', 'sg'), ('important', 'f', 'sg')]),
    ]:
        entries.extend(LexicalEntry(form, lemma, MorphFeatures(pos=pos, gender=g, number=n))
                       for form, g, n in forms)
    return DictionaryMorphology(entries)


def parsed(words, noun_index, number='sg'):
    # Explicit dependency fixture: the final verb is outside the noun phrase.
    text = ' '.join(words) + ' funciona.'
    tokens = []
    offset = 0
    for i, word in enumerate(words):
        pos, dep = ('NOUN', 'nsubj') if i == noun_index else (
            ('ADJ', 'amod') if word in {'profund', 'profunds', 'important'} else ('DET', 'det'))
        tokens.append(SyntaxToken(i, word, word, pos, dep,
            len(words) if i == noun_index else noun_index, offset, offset + len(word), 'm', number))
        offset += len(word) + 1
    tokens.append(SyntaxToken(len(words), 'funciona', 'funcionar', 'VERB', 'ROOT',
        len(words), offset, offset + 8, number=number, mood='ind'))
    return SentenceSyntax(text, tuple(tokens)), tokens[noun_index]


class AgreementTests(unittest.TestCase):
    def test_determiners_possessives_adjectives_and_number(self):
        for words, index, number, expected in [
            (['un', 'canvi', 'profund'], 1, 'sg', 'una transformació profunda'),
            (['el', 'seu', 'canvi', 'important'], 2, 'sg', 'la seva transformació important'),
            (['aquest', 'canvi'], 1, 'sg', 'aquesta transformació'),
            (['uns', 'canvis', 'profunds'], 1, 'pl', 'unes transformacions profundes'),
            (['del', 'canvi'], 1, 'sg', 'de la transformació'),
            (['al', 'canvi'], 1, 'sg', 'a la transformació'),
            (['pel', 'canvi'], 1, 'sg', 'per la transformació'),
        ]:
            with self.subTest(words=words):
                syntax, noun = parsed(words, index, number)
                self.assertEqual(replacement(syntax, noun, 'transformació', morphology()), expected)

    def test_apostrophe_follows_adjacent_word(self):
        syntax, noun = parsed(['del', 'canvi'], 1)
        self.assertEqual(replacement(syntax, noun, 'acord', morphology()), 'de l’acord')
        syntax, noun = parsed(['de', 'el', 'canvi'], 2)
        syntax = replace(syntax, tokens=(replace(syntax.tokens[0], pos='ADP', dep='case'), *syntax.tokens[1:]))
        self.assertEqual(replacement(syntax, noun, 'canvi', morphology()), 'del canvi')
        self.assertEqual(replacement(syntax, noun, 'transformació', morphology()), 'de la transformació')
        syntax, noun = parsed(['el', 'important', 'canvi'], 2)
        # Initial i requires phonological information: don't guess.
        self.assertIsNone(replacement(syntax, noun, 'acord', morphology()))

    def test_unknown_and_external_agreement_are_rejected(self):
        syntax, noun = parsed(['un', 'canvi', 'profund'], 1)
        self.assertIsNone(replacement(syntax, noun, 'desconegut', morphology()))
        tokens = (*syntax.tokens[:-1], replace(syntax.tokens[-1], pos='ADJ'))
        self.assertIsNone(replacement(replace(syntax, tokens=tokens), noun, 'transformació', morphology()))
        tokens = tuple(replace(t, dep='conj') if t.index == noun.index else t for t in syntax.tokens)
        self.assertIsNone(replacement(replace(syntax, tokens=tokens), tokens[1], 'transformació', morphology()))

    def test_ui_gets_one_atomic_replacement_and_protects_entire_group(self):
        syntax, noun = parsed(['un', 'canvi', 'profund'], 1)
        from parafrasi_cat.synonyms.suggester import OptionGroup, SynonymOption
        suggester = SynonymSuggester(RuleBasedAnalyzer(), morphology=morphology())
        suggester._from_dictionary = lambda phrase: [OptionGroup('preferida', 'diccionari', (
            SynonymOption('transformació', 'transformació', 'diccionari'),))]
        suggester._syntax = SimpleNamespace(available=True, parse=lambda text: syntax)
        suggester._connectors = {"unused": ()}
        result = suggester.options(syntax.text)
        self.assertEqual(len(result), 1)
        entry = result[0].to_dict()
        self.assertEqual(entry['text'], 'un canvi profund')
        value = entry['groups'][0]['options'][0]['text']
        self.assertEqual(syntax.text[:entry['start']] + value + syntax.text[entry['end']:],
                         'una transformació profunda funciona.')
        protected = (SimpleNamespace(span=Span(0, 2)),)
        self.assertEqual(suggester.options(syntax.text, protected), ())
        self.assertEqual(suggester._dictionary_without_agreement('canvi'), [])


if __name__ == '__main__':
    unittest.main()
