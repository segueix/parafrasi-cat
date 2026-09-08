from parafrasi_cat import PipelineConfig, build_pipeline
texts = [
 'El taller va restaurar la pintura.',
 'La pintura va ser restaurada pel taller.',
 'Van analitzar les dades del jaciment.',
 'Van fer l’anàlisi de les dades del jaciment.',
 'L’equip revisa la datació del sarcòfag.',
 'Van documentar les troballes.',
 'Tot i la pluja, la porta és oberta.',
 'La porta és oberta, malgrat el fred.',
 'Com es pot observar, la porta és oberta.',
 'Si plou, la porta és oberta.',
]
import json
out=[]
for text in texts:
 row={'original':text}
 for level in (2,3):
  p=build_pipeline(PipelineConfig(rule_set='parafrasi', level=level, syntax='none'))
  r=p.run(text)
  candidates=[e for e in r.sentences[0].candidates if e.accepted]
  ordered=sorted(candidates, key=lambda e:(e.candidate.structural_change_score, e.score.total if e.score else 0), reverse=True)
  row[str(level)]=[(e.candidate.text, e.candidate.structural_change_score) for e in ordered[:4]]
 out.append(row)
print(json.dumps(out, ensure_ascii=False, indent=2))
