const { test } = require('node:test');
const assert = require('node:assert/strict');
const {
  fusionar,
  puntuacio,
  continuacions,
  insereixAlCursor,
  creaEstatAssistit,
  registraAssistit,
  mouHistorialAssistit,
  referenciesAssistides,
} = require('../../src/parafrasi_cat/web/static/composicio.js');
const base = { option_id: 'a', text: 'La porta és oberta.', tokens: [
  { text: 'porta', start: 3, end: 8 }, { text: 'oberta', start: 12, end: 18 }
] };
const altra = { ...base, option_id: 'b' };
test('combina edicions de diverses alternatives', () => {
  const r = fusionar(base, [base, altra], new Map([
    ['a', new Map([[3, 'finestra']])], ['b', new Map([[12, 'tancada']])]
  ]));
  assert.equal(r.text, 'La finestra és tancada.');
  assert.equal(r.aplicats, 2);
});
test('conserva la base i mostra les alternatives contradictòries', () => {
  const r = fusionar(base, [base, altra], new Map([
    ['a', new Map([[3, 'finestra']])], ['b', new Map([[3, 'entrada']])]
  ]));
  assert.equal(r.text, base.text);
  assert.equal(r.pendents.length, 2);
});
test('no substitueix ocurrències ambigües', () => {
  const repetida = { ...base, tokens: [...base.tokens, { text: 'porta', start: 20, end: 25 }] };
  assert.equal(fusionar(repetida, [altra], new Map([['b', new Map([[3, 'entrada']])]])).aplicats, 0);
});
test('puntuació conserva dades, salts de línia i punts suspensius', () => {
  assert.equal(puntuacio('XVII: 3,14; 1.500...\nPerò, , sí .'), 'XVII: 3,14; 1.500...\nPerò, sí.');
  assert.equal(puntuacio('És cert?\nPotser...'), 'És cert?\nPotser...');
});

test('reescriptura assistida proposa només continuacions de candidats compatibles', () => {
  const opcions = [
    { option_id: 'o', text: 'La pintura va ser restaurada pel taller.' },
    { option_id: 'a', text: 'El taller va restaurar la pintura.' },
    { option_id: 'b', text: 'El taller restaurà la pintura.' },
  ];
  assert.deepEqual(
    continuacions('El taller', 9, opcions),
    [
      { text: 'va restaurar', option_id: 'a' },
      { text: 'restaurà la', option_id: 'b' },
    ],
  );
  assert.deepEqual(
    continuacions('El taller va restaurar', 22, opcions),
    [{ text: 'la pintura.', option_id: 'a' }],
  );
  assert.deepEqual(
    continuacions('El taller la pintura.', 9, opcions),
    [
      { text: 'va restaurar', option_id: 'a' },
      { text: 'restaurà', option_id: 'b' },
    ],
  );
  assert.deepEqual(continuacions('El tall', 7, opcions), []);
});

test('reescriptura assistida no barreja construccions sense correspondència fiable', () => {
  const opcions = [
    { option_id: 'a', text: 'El taller va restaurar la pintura.' },
    { option_id: 'b', text: 'La pintura va ser restaurada pel taller.' },
  ];
  assert.deepEqual(continuacions('El pintor', 9, opcions), []);
  assert.deepEqual(continuacions('taller', 6, opcions), []);
});

test('inserció al cursor conserva el text posterior i no duplica espais', () => {
  assert.deepEqual(
    insereixAlCursor('El taller la pintura.', 9, 'va restaurar'),
    { text: 'El taller va restaurar la pintura.', cursor: 22 },
  );
  assert.deepEqual(
    insereixAlCursor('El taller  la pintura.', 10, 'va restaurar'),
    { text: 'El taller va restaurar la pintura.', cursor: 22 },
  );
});

test('estat assistit conserva historial independent amb desfer i refer', () => {
  const una = creaEstatAssistit();
  const dues = creaEstatAssistit();
  registraAssistit(una, 'El taller', 9);
  registraAssistit(una, 'El taller va restaurar', 22);
  registraAssistit(dues, 'La pintura', 10);
  assert.deepEqual(mouHistorialAssistit(una, -1), { text: 'El taller', cursor: 9 });
  assert.equal(dues.text, 'La pintura');
  assert.deepEqual(mouHistorialAssistit(una, 1), { text: 'El taller va restaurar', cursor: 22 });
});

test('referències assistides separen original i mostren totes les reformulacions del sistema', () => {
  const frase = {
    source_text: 'La pintura va ser restaurada pel taller.',
    options: [
      { option_id: 'o', original: true, text: 'La pintura va ser restaurada pel taller.' },
      { option_id: 'a', original: false, summary: 'veu activa', text: 'El taller va restaurar la pintura.' },
      { option_id: 'b', original: false, summary: 'temps simple', text: 'El taller restaurà la pintura.' },
      { option_id: 'c', original: false, summary: 'ordre alternatiu', text: 'La pintura, el taller la va restaurar.' },
    ],
  };
  assert.deepEqual(referenciesAssistides(frase), {
    original: 'La pintura va ser restaurada pel taller.',
    reformulacions: [
      { option_id: 'a', label: 'Reformulació 1', summary: 'veu activa', text: 'El taller va restaurar la pintura.' },
      { option_id: 'b', label: 'Reformulació 2', summary: 'temps simple', text: 'El taller restaurà la pintura.' },
      { option_id: 'c', label: 'Reformulació 3', summary: 'ordre alternatiu', text: 'La pintura, el taller la va restaurar.' },
    ],
  });
});
