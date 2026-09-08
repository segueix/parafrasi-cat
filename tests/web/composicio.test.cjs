const { test } = require('node:test');
const assert = require('node:assert/strict');
const { fusionar, puntuacio } = require('../../src/parafrasi_cat/web/static/composicio.js');
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
