#!/usr/bin/env python3
"""Importa corpus per revisar exemples i patrons, sense executar ni aprendre regles."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from parafrasi_cat.analyzer.numerals import looks_like_roman_numeral  # noqa: E402

LABELS = {0: 'non_equivalent', 1: 'equivalent', '0': 'non_equivalent', '1': 'equivalent',
          'parafrasis': 'equivalent', 'no_parafrasis': 'non_equivalent',
          'no parafrasis': 'non_equivalent'}
NUMBER_WORDS = set('zero un una dos dues tres quatre cinc sis set vuit nou deu onze dotze tretze catorze quinze setze disset divuit dinou vint trenta cent mil'.split())
NEGATIONS = {'no', 'mai', 'ningú', 'res', 'cap', 'tampoc', 'sense'}


def risks(first: str, second: str) -> list[str]:
    def features(text):
        words = list(re.finditer(r'\w+', text))
        return (
            Counter(re.findall(r'\d+(?:[.,]\d+)*', text)),
            Counter(m.group() for m in words if looks_like_roman_numeral(
                m.group(), text[:m.start()])),
            Counter(m.group().lower() for m in words if m.group().lower() in NUMBER_WORDS),
            Counter(m.group().lower() for m in words if m.group().lower() in NEGATIONS),
        )
    a, b = features(first), features(second)
    names = ('xifres_diferents', 'romans_diferents', 'quantificadors_a_revisar', 'negacio_a_revisar')
    return [name for name, x, y in zip(names, a, b, strict=True) if x != y]


def rows(path: Path):
    text = path.read_text(encoding='utf-8-sig')
    if text.lstrip().startswith('['):
        yield from json.loads(text)
    else:
        for line in text.splitlines():
            if line.strip():
                yield json.loads(line)


def import_pairs(source: Path, provenance: dict, reviews: dict | None = None):
    reviews = reviews or {}
    records = {}
    for raw in rows(source):
        first, second = raw.get('original', raw.get('sentence1')), raw.get('new', raw.get('sentence2'))
        if not isinstance(first, str) or not isinstance(second, str) or not first.strip() or not second.strip():
            raise ValueError('Parella sense els dos textos: no s’importa silenciosament.')
        key = hashlib.sha256((provenance['dataset'] + '\0' + first + '\0' + second).encode()).hexdigest()
        label = raw.get('label')
        normalized = label.strip().lower() if isinstance(label, str) else label
        # Unknown labels stay unknown; never interpret arbitrary truthy values.
        normalized = LABELS.get(normalized, 'unknown') if isinstance(normalized, (str, int)) else 'unknown'
        if key in records:
            previous = records[key]
            if label not in previous['source_labels_raw']:
                previous['source_labels_raw'].append(label)
            if normalized != previous['source_label']:
                previous['source_label'] = 'conflict'
                previous['risk_flags'] = sorted(set(previous['risk_flags'] + ['etiquetes_contradictories']))
                previous['rule_evidence_eligible'] = False
            continue
        flags = risks(first, second)
        review = reviews.get(key)
        if review is not None:
            if review.get('verdict') not in {'equivalent', 'non_equivalent', 'uncertain'}:
                raise ValueError('Veredicte de revisió desconegut')
            if not review.get('reviewer', '').strip() or not review.get('note', '').strip():
                raise ValueError('La revisió requereix responsable i justificació')
        records[key] = {
            'id': key, 'source_id': raw.get('id'), 'original': first, 'alternative': second,
            'source_label_raw': label, 'source_labels_raw': [label], 'source_label': normalized,
            'review_status': 'reviewed' if review else 'pending',
            'review': review, 'risk_flags': flags,
            'rule_evidence_eligible': bool(review and review['verdict'] == 'equivalent'
                                      and not flags and provenance['split'] == 'train'),
            'provenance': provenance,
        }

    yield from records.values()


def conllu_patterns(source: Path):
    """Exemples de dependències; no són parelles de paràfrasi ni regles executables."""
    counts, examples = Counter(), {}
    for block in re.split(r'\n\s*\n', source.read_text(encoding='utf-8').strip()):
        sentence_id, text, tokens = '', '', {}
        for line in block.splitlines():
            if line.startswith('# sent_id = '): sentence_id = line[12:]
            elif line.startswith('# text = '): text = line[9:]
            elif line and not line.startswith('#'):
                fields = line.split('\t')
                if len(fields) == 10 and fields[0].isdigit():
                    tokens[int(fields[0])] = fields
        for token in tokens.values():
            head = tokens.get(int(token[6]))
            if head is None:
                continue
            key = f'{head[3]} -> {token[7]} -> {token[3]}'
            counts[key] += 1
            examples.setdefault(key, {'sentence_id': sentence_id, 'text': text})
    return [{'pattern': k, 'count': n, 'example': examples[k], 'status': 'observed_not_validated_rule'}
            for k, n in counts.most_common()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True, choices=['parafraseja', 'paws-ca', 'ancora'])
    parser.add_argument('--split', choices=['train', 'validation', 'test'], default='train')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--source', type=Path)
    group.add_argument('--download', action='store_true')
    parser.add_argument('--reviews', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    catalog = json.loads((ROOT / 'resources/ca/paraphrases/sources.json').read_text())
    meta = catalog[args.dataset]
    output = args.output or ROOT / f'resources/ca/paraphrases/generated/{args.dataset}-{args.split}.jsonl'
    output.parent.mkdir(parents=True, exist_ok=True)
    source = args.source
    if args.download:
        url = meta['url_template'].format(revision=meta['revision'], file=meta['files'][args.split])
        source = output.with_suffix('.source')
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read(64 * 1024 * 1024 + 1)
        if len(data) > 64 * 1024 * 1024: raise ValueError('Corpus superior al límit de 64 MiB')
        source.write_bytes(data)
    if source.resolve() == output.resolve(): raise ValueError('Entrada i sortida han de ser diferents')
    provenance = {k: meta[k] for k in ('homepage', 'license', 'attribution')}
    provenance.update(dataset=args.dataset, split=args.split,
                      revision=meta['revision'] if args.download else 'local-unverified',
                      sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    if args.dataset == 'ancora':
        records = [dict(r, provenance=provenance) for r in conllu_patterns(source)]
    else:
        reviews = {}
        if args.reviews:
            for review in rows(args.reviews):
                if review['id'] in reviews: raise ValueError('Revisió duplicada')
                reviews[review['id']] = review
        records = list(import_pairs(source, provenance, reviews))
        unmatched = set(reviews) - {r['id'] for r in records}
        if unmatched: raise ValueError('Hi ha revisions que no corresponen a aquest corpus')
    temporary = output.with_suffix(output.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8') as handle:
        for record in records: handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n')
    temporary.replace(output)
    report = {'dataset': args.dataset, 'split': args.split, 'records': len(records),
              'source_labels': dict(Counter(r.get('source_label', 'syntax_only') for r in records)),
              'pending_review': sum(r.get('review_status') == 'pending' for r in records),
              'risk_flags': dict(Counter(f for r in records for f in r.get('risk_flags', []))),
              'rule_evidence_eligible': sum(r.get('rule_evidence_eligible', False) for r in records),
              'provenance': provenance}
    output.with_suffix('.summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
