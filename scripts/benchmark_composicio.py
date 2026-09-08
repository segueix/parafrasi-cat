"""Mesura cobertura i defectes observables; no estima qualitat semàntica."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from parafrasi_cat.pipeline import PipelineConfig, apply_mode  # noqa: E402
from parafrasi_cat.pipeline.builder import build_pipeline  # noqa: E402
from parafrasi_cat.pipeline.modes import RewriteMode  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path,
                        default=ROOT / 'tests/fixtures/composicio_escacs.json')
    parser.add_argument('--languagetool', action='store_true')
    args = parser.parse_args()
    texts = json.loads(args.corpus.read_text(encoding='utf-8'))
    pipeline = build_pipeline(apply_mode(PipelineConfig(
        home=ROOT, rule_set='parafrasi', languagetool=args.languagetool), RewriteMode.DEEP, 5))
    rows = []
    for index, text in enumerate(texts, 1):
        result = pipeline.run(text).sentences[0]
        candidates = [e.candidate for e in result.candidates
                      if e.accepted and not e.candidate.is_identity]
        rows.append({
            'sentence': index, 'alternatives': len(candidates),
            'reordered': sum(any(f.value == 'REORDER' for f in c.families) for c in candidates),
            'duplicated_commas': sum(bool(re.search(r',\s*,', c.text)) for c in candidates),
        })
    n = len(rows)
    print(json.dumps({
        'parser_available': pipeline.syntax.available,
        'languagetool_requested': args.languagetool,
        'sentences': n,
        'with_alternatives_pct': round(100 * sum(r['alternatives'] > 0 for r in rows) / n, 2) if n else 0,
        'with_reordering_pct': round(100 * sum(r['reordered'] > 0 for r in rows) / n, 2) if n else 0,
        'duplicated_comma_candidates': sum(r['duplicated_commas'] for r in rows),
        'rows': rows,
        'limitation': 'Cobertura observada en aquest corpus; no és una puntuació de qualitat ni una previsió general.',
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
