/* Operacions locals: cap text no s'envia a cap servei. */
const EinesComposicio = (() => {
  function fusionar(base, opcions, edicions) {
    const propostes = new Map();
    const pendents = new Set();
    for (const opcio of opcions) {
      const canvis = edicions.get(opcio.option_id) || new Map();
      for (const token of opcio.tokens) {
        if (!canvis.has(token.start)) continue;
        const canvi = canvis.get(token.start);
        if (canvi === token.text) continue;
        const destins = base.tokens.filter(t => t.text === token.text);
        const repetit = opcio.tokens.filter(t => t.text === token.text).length !== 1;
        if (destins.length !== 1 || repetit) {
          pendents.add(`${token.text} → ${canvi}`);
          continue;
        }
        const desti = destins[0];
        if (!propostes.has(desti.start)) propostes.set(desti.start, { token: desti, valors: new Set() });
        propostes.get(desti.start).valors.add(canvi);
      }
    }
    const tots = [...propostes.values()];
    const aplicables = tots.filter(p => {
      const solapat = tots.some(q => p !== q && p.token.start < q.token.end && q.token.start < p.token.end);
      if (p.valors.size === 1 && !solapat) return true;
      for (const valor of p.valors) pendents.add(`${p.token.text} → ${valor}`);
      return false;
    }).sort((a, b) => b.token.start - a.token.start);
    let text = base.text;
    for (const p of aplicables) text = text.slice(0, p.token.start) + [...p.valors][0] + text.slice(p.token.end);
    return { text, pendents: [...pendents], aplicats: aplicables.length };
  }

  function puntuacio(text) {
    // Només espais davant de puntuació i comes duplicades; preserva decimals,
    // abreviatures, punts suspensius, salts de línia i el contingut verbal.
    return text.replace(/[^\S\r\n]+([,;:!?])/g, "$1")
      .replace(/,[ \t]*,+/g, ",")
      .replace(/[^\S\r\n]+\.(?=\s|$)/g, ".");
  }
  return { fusionar, puntuacio };
})();
if (typeof module !== "undefined") module.exports = EinesComposicio;
