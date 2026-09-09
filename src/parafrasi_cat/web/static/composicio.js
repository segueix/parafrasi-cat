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

  function tokenitzaAmbRangs(text) {
    const tokens = [];
    const patro = /[\p{L}\p{N}]+(?:['’·-][\p{L}\p{N}]+)*|[^\s]/gu;
    for (const coincidencia of text.matchAll(patro)) {
      tokens.push({ text: coincidencia[0], start: coincidencia.index, end: coincidencia.index + coincidencia[0].length });
    }
    return tokens;
  }

  function plegat(text) {
    return text.normalize("NFC").toLocaleLowerCase("ca");
  }

  function esLexic(token) {
    return /[\p{L}\p{N}]/u.test(token);
  }

  function rangCompatible(text, cursor, candidat) {
    if (cursor < 0 || cursor > text.length) return null;
    const abans = text.slice(0, cursor);
    const despres = text.slice(cursor);
    const tokensCandidat = tokenitzaAmbRangs(candidat);
    const tokensAbans = tokenitzaAmbRangs(abans);
    const tokensDespres = tokenitzaAmbRangs(despres);
    if (!tokensAbans.length || tokensAbans.length > tokensCandidat.length) return null;

    let iniciBuit = 0;
    for (let i = 0; i < tokensAbans.length; i += 1) {
      const escrit = plegat(tokensAbans[i].text);
      const disponible = tokensCandidat[i];
      if (!disponible) return null;
      const candidatPlegat = plegat(disponible.text);
      // Primera versió deliberadament conservadora: només avancem quan el
      // token escrit coincideix sencer amb el mateix token del candidat.
      // Això evita completar mitges paraules amb espais o barrejar camins.
      if (escrit !== candidatPlegat) return null;
      iniciBuit = disponible.end;
    }

    let fiBuit = candidat.length;
    if (tokensDespres.length) {
      if (tokensDespres.length > tokensCandidat.length) return null;
      const offset = tokensCandidat.length - tokensDespres.length;
      for (let i = 0; i < tokensDespres.length; i += 1) {
        if (plegat(tokensDespres[i].text) !== plegat(tokensCandidat[offset + i].text)) return null;
      }
      fiBuit = tokensCandidat[offset].start;
    }
    if (iniciBuit >= fiBuit) return null;
    return { inici: iniciBuit, fi: fiBuit };
  }

  function fragmentCurt(candidat, inici, fi) {
    const tros = candidat.slice(inici, fi);
    const tokens = tokenitzaAmbRangs(tros);
    if (!tokens.length) return "";
    let lexics = 0;
    let final = 0;
    for (let i = 0; i < tokens.length; i += 1) {
      const token = tokens[i];
      final = token.end;
      if (esLexic(token.text)) lexics += 1;
      const puntuacioForta = /^[,;:.!?]$/u.test(token.text);
      if (puntuacioForta && lexics > 0) break;
      if (lexics >= 2) {
        const seguent = tokens[i + 1];
        if (seguent && /^[,;:.!?]$/u.test(seguent.text)) final = seguent.end;
        break;
      }
    }
    return tros.slice(tokens[0].start, final).trim();
  }

  function continuacions(text, cursor, opcions, maxim = 3) {
    if (!text.trim() || !Array.isArray(opcions) || maxim <= 0) return [];
    const resultat = [];
    const vistos = new Set();
    for (const opcio of opcions) {
      if (!opcio || typeof opcio.text !== "string") continue;
      const rang = rangCompatible(text, cursor, opcio.text);
      if (!rang) continue;
      const fragment = fragmentCurt(opcio.text, rang.inici, rang.fi);
      const clau = plegat(fragment);
      if (!fragment || vistos.has(clau)) continue;
      vistos.add(clau);
      resultat.push({ text: fragment, option_id: opcio.option_id || "" });
      if (resultat.length >= maxim) break;
    }
    return resultat;
  }

  function insereixAlCursor(text, cursor, fragment) {
    const posicio = Math.max(0, Math.min(Number(cursor) || 0, text.length));
    const net = String(fragment || "").trim();
    if (!net) return { text, cursor: posicio };
    const esquerra = text.slice(0, posicio);
    const dreta = text.slice(posicio);
    const calEspaiEsquerra = esquerra && !/\s$/u.test(esquerra) && !/^[,;:.!?)}\]]/u.test(net) && !/[('’\[-]$/u.test(esquerra);
    const calEspaiDreta = dreta && !/^\s/u.test(dreta) && !/^[,;:.!?)}\]]/u.test(dreta) && !/[('’\[-]$/u.test(net);
    const inserit = `${calEspaiEsquerra ? " " : ""}${net}${calEspaiDreta ? " " : ""}`;
    return {
      text: esquerra + inserit + dreta,
      cursor: posicio + inserit.length,
    };
  }

  function creaEstatAssistit() {
    return {
      text: "",
      cursor: 0,
      historial: [{ text: "", cursor: 0 }],
      posicioHistorial: 0,
      transferencia: null,
    };
  }

  function registraAssistit(estat, text, cursor) {
    estat.text = text;
    estat.cursor = cursor;
    const actual = estat.historial[estat.posicioHistorial];
    if (actual && actual.text === text) {
      actual.cursor = cursor;
      return estat;
    }
    estat.historial = estat.historial.slice(0, estat.posicioHistorial + 1);
    estat.historial.push({ text, cursor });
    estat.posicioHistorial = estat.historial.length - 1;
    return estat;
  }

  function mouHistorialAssistit(estat, direccio) {
    const nova = estat.posicioHistorial + direccio;
    if (nova < 0 || nova >= estat.historial.length) return null;
    estat.posicioHistorial = nova;
    const instant = estat.historial[nova];
    estat.text = instant.text;
    estat.cursor = instant.cursor;
    return { ...instant };
  }

  function referenciesAssistides(frase) {
    const original = typeof frase?.source_text === "string" ? frase.source_text : "";
    const reformulacions = (Array.isArray(frase?.options) ? frase.options : [])
      .filter(opcio => opcio && typeof opcio.text === "string" && !opcio.original)
      .map((opcio, index) => ({
        option_id: opcio.option_id || "",
        label: `Reformulació ${index + 1}`,
        summary: typeof opcio.summary === "string" ? opcio.summary : "",
        text: opcio.text,
      }));
    return { original, reformulacions };
  }

  return {
    fusionar,
    puntuacio,
    continuacions,
    insereixAlCursor,
    creaEstatAssistit,
    registraAssistit,
    mouHistorialAssistit,
    referenciesAssistides,
  };
})();

if (typeof window !== "undefined") {
  window.addEventListener("DOMContentLoaded", () => {
    if (typeof crearEditorFrase !== "function" || typeof pintarFrase !== "function") return;

    const estatsAssistits = new Map();
    const estil = document.createElement("style");
    estil.textContent = `
      .reescriptura-assistida { background: var(--plafo); border: 1px solid var(--vora); border-radius: 8px; margin: .9rem 0; padding: .9rem; }
      .reescriptura-assistida h5 { color: var(--accent); font-size: 1.05rem; margin: 0; }
      .reescriptura-assistida .introduccio-assistida { color: var(--suau); font-size: .88em; margin: .25rem 0 .75rem; }
      .espai-assistit { display: grid; gap: .9rem; grid-template-columns: minmax(19rem, .9fr) minmax(28rem, 1.1fr); align-items: start; }
      .referencies-assistides { background: var(--fons); border: 1px solid var(--vora); border-radius: 7px; max-height: min(62vh, 42rem); overflow: auto; padding: .65rem; }
      .cap-referencies { align-items: baseline; display: flex; gap: .5rem; justify-content: space-between; margin: 0 0 .5rem; }
      .cap-referencies h6, .taller-assistit h6 { color: var(--accent); font-size: .92rem; margin: 0; }
      .comptador-referencies { color: var(--suau); font-size: .78em; white-space: nowrap; }
      .referencia-assistida { background: var(--plafo); border: 1px solid var(--vora); border-radius: 6px; margin: 0 0 .55rem; padding: .55rem .65rem; }
      .referencia-assistida:last-child { margin-bottom: 0; }
      .referencia-original { border-left: 4px solid var(--accent); position: sticky; top: -.65rem; z-index: 2; box-shadow: 0 2px 7px rgba(0, 0, 0, .08); }
      .referencia-sistema { border-left: 4px solid var(--alternativa); }
      .referencia-etiqueta { align-items: baseline; display: flex; flex-wrap: wrap; gap: .35rem; margin-bottom: .28rem; }
      .referencia-etiqueta strong { color: var(--text); font-size: .82em; }
      .referencia-resum { color: var(--suau); font-size: .75em; }
      .referencia-text { color: var(--text); line-height: 1.5; margin: 0; }
      .sense-reformulacions { color: var(--suau); font-size: .84em; margin: .45rem 0 0; }
      .taller-assistit { align-self: start; background: var(--plafo); border: 1px solid var(--vora); border-radius: 7px; padding: .75rem; position: sticky; top: .75rem; }
      .taller-assistit .etiqueta-editor-assistit { display: block; font-weight: 600; margin: .5rem 0 .35rem; }
      .reescriptura-assistida textarea { box-sizing: border-box; min-height: 8.5rem; resize: vertical; width: 100%; }
      .reescriptura-assistida .barra-assistida, .reescriptura-assistida .suggeriments-assistits { display: flex; flex-wrap: wrap; gap: .4rem; margin-top: .45rem; }
      .reescriptura-assistida .suggeriment-assistit { background: var(--alternativa-fons); border: 1px solid var(--alternativa); color: var(--alternativa); }
      .reescriptura-assistida .suggeriment-assistit:hover, .reescriptura-assistida .suggeriment-assistit:focus-visible { background: var(--seleccio-fons); }
      .reescriptura-assistida .nota-assistida { color: var(--suau); font-size: .86em; margin: .55rem 0 0; }
      @media (max-width: 960px) {
        .espai-assistit { grid-template-columns: 1fr; }
        .referencies-assistides { max-height: 24rem; }
        .taller-assistit { position: static; }
      }
    `;
    document.head.append(estil);

    function estatDe(frase) {
      if (!estatsAssistits.has(frase.index)) estatsAssistits.set(frase.index, EinesComposicio.creaEstatAssistit());
      return estatsAssistits.get(frase.index);
    }

    function actualitzaSuggeriments(article, frase) {
      const caixa = article.querySelector(".reescriptura-assistida");
      if (!caixa) return;
      const editor = caixa.querySelector("textarea");
      const llista = caixa.querySelector(".suggeriments-assistits");
      const utilitza = caixa.querySelector(".utilitza-assistida");
      const desfer = caixa.querySelector(".desfer-assistit");
      const refer = caixa.querySelector(".refer-assistit");
      const estat = estatDe(frase);
      const feta = article.classList.contains("feta");
      editor.disabled = feta;
      caixa.querySelectorAll("button").forEach(b => { b.disabled = feta; });
      utilitza.disabled = feta || !editor.value.trim();
      desfer.disabled = feta || estat.posicioHistorial <= 0;
      refer.disabled = feta || estat.posicioHistorial >= estat.historial.length - 1;
      llista.replaceChildren();
      if (feta || editor.selectionStart !== editor.selectionEnd) return;
      const opcions = frase.options || [];
      const suggeriments = EinesComposicio.continuacions(editor.value, editor.selectionStart, opcions, 3);
      for (const suggeriment of suggeriments) {
        const boto = document.createElement("button");
        boto.type = "button";
        boto.className = "suggeriment-assistit";
        boto.textContent = suggeriment.text;
        boto.title = "Fragment d'una redacció ja disponible; no és una validació de la frase manual.";
        boto.addEventListener("click", () => {
          const insercio = EinesComposicio.insereixAlCursor(editor.value, editor.selectionStart, suggeriment.text);
          editor.value = insercio.text;
          editor.setSelectionRange(insercio.cursor, insercio.cursor);
          EinesComposicio.registraAssistit(estat, editor.value, insercio.cursor);
          editor.focus();
          actualitzaSuggeriments(article, frase);
        });
        boto.addEventListener("keydown", (esdeveniment) => {
          const botons = [...llista.querySelectorAll("button")];
          const i = botons.indexOf(boto);
          if (esdeveniment.key === "ArrowDown" && botons.length) {
            esdeveniment.preventDefault();
            botons[(i + 1) % botons.length].focus();
          } else if (esdeveniment.key === "ArrowUp" && botons.length) {
            esdeveniment.preventDefault();
            botons[(i - 1 + botons.length) % botons.length].focus();
          } else if (esdeveniment.key === "Escape") {
            esdeveniment.preventDefault();
            editor.focus();
          }
        });
        llista.append(boto);
      }
    }

    function aplicaInstant(editor, estat, instant, article, frase) {
      if (!instant) return;
      editor.value = instant.text;
      editor.setSelectionRange(instant.cursor, instant.cursor);
      editor.focus();
      actualitzaSuggeriments(article, frase);
    }

    function creaTargetaReferencia(label, text, resum, original) {
      const targeta = document.createElement("article");
      targeta.className = `referencia-assistida ${original ? "referencia-original" : "referencia-sistema"}`;
      const cap = document.createElement("div");
      cap.className = "referencia-etiqueta";
      const nom = document.createElement("strong");
      nom.textContent = label;
      cap.append(nom);
      if (resum) {
        const detall = document.createElement("span");
        detall.className = "referencia-resum";
        detall.textContent = resum;
        cap.append(detall);
      }
      const par = document.createElement("p");
      par.className = "referencia-text";
      par.textContent = text;
      targeta.append(cap, par);
      return targeta;
    }

    function crearAssistida(article, frase) {
      if (article.querySelector(".reescriptura-assistida")) return;
      const estat = estatDe(frase);
      const referencies = EinesComposicio.referenciesAssistides(frase);
      const caixa = document.createElement("section");
      caixa.className = "reescriptura-assistida";
      const titol = document.createElement("h5");
      titol.textContent = "Reescriptura assistida";
      const introduccio = document.createElement("p");
      introduccio.className = "introduccio-assistida";
      introduccio.textContent = "Consulta l'original i totes les reformulacions mentre redactes la teva versió, sense perdre de vista l'editor.";

      const espai = document.createElement("div");
      espai.className = "espai-assistit";
      const referencia = document.createElement("aside");
      referencia.className = "referencies-assistides";
      referencia.setAttribute("aria-label", "Textos de referència per a la reescriptura");
      const capReferencies = document.createElement("div");
      capReferencies.className = "cap-referencies";
      const titolReferencies = document.createElement("h6");
      titolReferencies.textContent = "Textos de referència";
      const comptador = document.createElement("span");
      comptador.className = "comptador-referencies";
      comptador.textContent = `${referencies.reformulacions.length} reformulació${referencies.reformulacions.length === 1 ? "" : "ns"}`;
      capReferencies.append(titolReferencies, comptador);
      referencia.append(capReferencies, creaTargetaReferencia("Original", referencies.original, "", true));
      for (const reformulacio of referencies.reformulacions) {
        referencia.append(creaTargetaReferencia(reformulacio.label, reformulacio.text, reformulacio.summary, false));
      }
      if (!referencies.reformulacions.length) {
        const buit = document.createElement("p");
        buit.className = "sense-reformulacions";
        buit.textContent = "El sistema no ha generat cap reformulació addicional per a aquesta frase.";
        referencia.append(buit);
      }

      const taller = document.createElement("div");
      taller.className = "taller-assistit";
      const titolTaller = document.createElement("h6");
      titolTaller.textContent = "La teva redacció";
      const etiqueta = document.createElement("label");
      etiqueta.className = "etiqueta-editor-assistit";
      etiqueta.htmlFor = `assistida-frase-${frase.index}`;
      etiqueta.textContent = "Reescriu-la manualment";
      const editor = document.createElement("textarea");
      editor.id = etiqueta.htmlFor;
      editor.rows = 5;
      editor.value = estat.text;
      editor.autocomplete = "off";
      editor.spellcheck = true;
      const suggeriments = document.createElement("div");
      suggeriments.className = "suggeriments-assistits";
      suggeriments.setAttribute("aria-label", "Continuacions disponibles");
      const barra = document.createElement("div");
      barra.className = "barra-assistida";
      const desfer = document.createElement("button");
      desfer.type = "button";
      desfer.className = "secundari desfer-assistit";
      desfer.textContent = "Desfés";
      const refer = document.createElement("button");
      refer.type = "button";
      refer.className = "secundari refer-assistit";
      refer.textContent = "Refés";
      const utilitza = document.createElement("button");
      utilitza.type = "button";
      utilitza.className = "utilitza-assistida";
      utilitza.textContent = "Utilitza aquesta redacció";
      const desferTransferencia = document.createElement("button");
      desferTransferencia.type = "button";
      desferTransferencia.className = "secundari desfer-transferencia";
      desferTransferencia.textContent = "Desfés la transferència";
      desferTransferencia.hidden = true;
      const nota = document.createElement("p");
      nota.className = "nota-assistida";
      nota.setAttribute("role", "status");
      nota.textContent = "Les continuacions provenen només de l'original i de redaccions ja disponibles. La redacció manual i les insercions no queden validades automàticament.";

      function registra() {
        EinesComposicio.registraAssistit(estat, editor.value, editor.selectionStart);
        actualitzaSuggeriments(article, frase);
      }
      editor.addEventListener("input", registra);
      for (const nom of ["click", "keyup", "select"]) editor.addEventListener(nom, () => {
        estat.cursor = editor.selectionStart;
        actualitzaSuggeriments(article, frase);
      });
      editor.addEventListener("keydown", (esdeveniment) => {
        const ctrl = esdeveniment.ctrlKey || esdeveniment.metaKey;
        if (ctrl && esdeveniment.key.toLowerCase() === "z") {
          esdeveniment.preventDefault();
          aplicaInstant(editor, estat, EinesComposicio.mouHistorialAssistit(estat, esdeveniment.shiftKey ? 1 : -1), article, frase);
        } else if (ctrl && esdeveniment.key.toLowerCase() === "y") {
          esdeveniment.preventDefault();
          aplicaInstant(editor, estat, EinesComposicio.mouHistorialAssistit(estat, 1), article, frase);
        } else if (esdeveniment.key === "ArrowDown" && suggeriments.firstElementChild) {
          esdeveniment.preventDefault();
          suggeriments.firstElementChild.focus();
        }
      });
      desfer.addEventListener("click", () => aplicaInstant(editor, estat, EinesComposicio.mouHistorialAssistit(estat, -1), article, frase));
      refer.addEventListener("click", () => aplicaInstant(editor, estat, EinesComposicio.mouHistorialAssistit(estat, 1), article, frase));
      utilitza.addEventListener("click", () => {
        if (!editor.value.trim()) return;
        const editable = article.querySelector(".editor-frase textarea");
        if (!editable) return;
        estat.transferencia = {
          anterior: editable.value,
          aplicada: editor.value,
          teniaManual: typeof composicio !== "undefined" && composicio.manuals.has(frase.index),
        };
        editable.value = editor.value;
        editable.dispatchEvent(new Event("input", { bubbles: true }));
        desferTransferencia.hidden = false;
        nota.textContent = "Redacció traslladada a «Redacció editable». Encara és una redacció manual pendent de revisió.";
      });
      desferTransferencia.addEventListener("click", () => {
        const editable = article.querySelector(".editor-frase textarea");
        if (!editable || !estat.transferencia) return;
        if (editable.value !== estat.transferencia.aplicada) {
          nota.textContent = "No s'ha desfet la transferència perquè «Redacció editable» ha canviat després.";
          return;
        }
        editable.value = estat.transferencia.anterior;
        editable.dispatchEvent(new Event("input", { bubbles: true }));
        if (!estat.transferencia.teniaManual && typeof composicio !== "undefined") {
          composicio.manuals.delete(frase.index);
          if (typeof refrescarParagraf === "function") refrescarParagraf();
        }
        estat.transferencia = null;
        desferTransferencia.hidden = true;
        nota.textContent = "Transferència desfeta. La reescriptura assistida es conserva.";
      });

      barra.append(desfer, refer, utilitza, desferTransferencia);
      taller.append(titolTaller, etiqueta, editor, suggeriments, barra, nota);
      espai.append(referencia, taller);
      caixa.append(titol, introduccio, espai);
      const editable = article.querySelector(".editor-frase");
      if (editable) editable.after(caixa);
      actualitzaSuggeriments(article, frase);
    }

    const crearEditorFraseOriginal = crearEditorFrase;
    crearEditorFrase = function(article, frase) {
      crearEditorFraseOriginal(article, frase);
      crearAssistida(article, frase);
    };

    const pintarFraseOriginal = pintarFrase;
    pintarFrase = function(frase) {
      pintarFraseOriginal(frase);
      const article = document.getElementById("frases")?.querySelector(`[data-frase="${frase.index}"]`);
      if (article) actualitzaSuggeriments(article, frase);
    };
  });
}

if (typeof module !== "undefined") module.exports = EinesComposicio;
