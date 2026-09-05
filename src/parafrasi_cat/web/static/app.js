"use strict";

// Interfície local de parafrasi-cat. Tot el processament passa al servidor
// local d'aquesta mateixa màquina; aquest fitxer només mostra el resultat.

const estat = {
  acces: null,
  opcions: null,
  resultat: null,
  textUnitat: new Map(),
  feedback: [],
  textosEmpremta: [],
  componentPendent: "",
};

const CLAUS_RECURSOS = ["morphology", "syntax", "languagetool", "java", "offline"];

function llegeixFitxer(fitxer) {
  return new Promise((resol, rebutja) => {
    const lector = new FileReader();
    lector.onload = () => resol(String(lector.result));
    lector.onerror = () => rebutja(new Error(`No s'ha pogut llegir ${fitxer.name}`));
    lector.readAsText(fitxer, "utf-8");
  });
}

const $ = (id) => document.getElementById(id);

async function api(ruta, opcions) {
  const resposta = await fetch(ruta, opcions);
  if (resposta.status === 401) {
    // La sessió del mode de xarxa local ha caducat: cal tornar a entrar-hi.
    window.location.replace("/");
    throw new Error("La sessió ha caducat. Torneu a introduir el codi d'accés.");
  }
  const dades = await resposta.json().catch(() => ({ error: "Resposta il·legible" }));
  if (!resposta.ok) throw new Error(dades.error || `Error ${resposta.status}`);
  return dades;
}

function missatge(node, text, esError) {
  node.textContent = text;
  node.classList.toggle("error", Boolean(esError));
}

// --- opcions -----------------------------------------------------------------

function omplirSelect(select, elements, buit) {
  select.replaceChildren();
  if (buit) {
    const cap = document.createElement("option");
    cap.value = "";
    cap.textContent = buit;
    select.append(cap);
  }
  for (const element of elements) {
    const opcio = document.createElement("option");
    opcio.value = element.id;
    opcio.textContent = element.error
      ? `${element.label} (error: ${element.error})`
      : element.label;
    opcio.disabled = Boolean(element.error);
    if (element.description) opcio.title = element.description;
    select.append(opcio);
  }
}

function omplirModes(modes) {
  const contenidor = $("modes");
  contenidor.replaceChildren();
  modes.forEach((mode, index) => {
    const etiqueta = document.createElement("label");
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "mode";
    radio.value = mode.id;
    radio.checked = index === modes.length - 1;
    radio.addEventListener("change", mostrarDescripcioMode);
    etiqueta.append(radio, ` ${mode.label}`);
    contenidor.append(etiqueta);
  });
  mostrarDescripcioMode();
}

function modeTriat() {
  const marcat = document.querySelector('input[name="mode"]:checked');
  return marcat ? marcat.value : "profund";
}

// --- accés a la interfície ---------------------------------------------------
// El mode el fixa qui arrenca el servidor: canviar-lo demana tornar-lo a
// engegar, perquè el port on escolta es decideix en obrir-lo.

const MODES_ACCES = [
  { id: "local", label: "Només aquest ordinador" },
  { id: "lan", label: "Xarxa local" },
];

function accesTriat() {
  const marcat = document.querySelector('input[name="acces"]:checked');
  return marcat ? marcat.value : "local";
}

function mostrarAcces(acces) {
  estat.acces = acces;
  const contenidor = $("modes-acces");
  contenidor.replaceChildren();
  for (const mode of MODES_ACCES) {
    const etiqueta = document.createElement("label");
    etiqueta.className = "opcio";
    const entrada = document.createElement("input");
    entrada.type = "radio";
    entrada.name = "acces";
    entrada.value = mode.id;
    entrada.checked = mode.id === acces.mode;
    entrada.addEventListener("change", actualitzarAcces);
    etiqueta.append(entrada, ` ${mode.label}`);
    contenidor.append(etiqueta);
  }
  $("nota-acces").textContent = `${acces.label}. ${acces.privacy}`;
  actualitzarAcces();
}

function actualitzarAcces() {
  const acces = estat.acces;
  if (!acces) return;
  const triat = accesTriat();
  const esLan = triat === "lan";
  $("descripcio-acces").textContent = esLan
    ? "Permet accedir a Parafrasi-cat des d'un altre dispositiu connectat a la mateixa xarxa local. El motor continua executant-se en aquest ordinador."
    : "La interfície només s'obre en aquest ordinador.";
  $("privacitat-acces").textContent = esLan
    ? "El text només circula dins de la xarxa local entre el navegador client i l'ordinador que executa Parafrasi-cat. No s'envia a cap servei d'Internet."
    : "El text no surt d'aquest ordinador.";
  const avis = $("avis-acces");
  avis.hidden = !esLan;
  avis.textContent = esLan
    ? "Utilitza aquesta funció només en una xarxa Wi-Fi privada i de confiança. La connexió dins de la xarxa local és HTTP i no va xifrada."
    : "";
  const canvi = $("canvi-acces");
  canvi.hidden = triat === acces.mode;
  canvi.textContent =
    triat === acces.mode
      ? ""
      : esLan
        ? "Per activar-ho, atureu el servidor i torneu-lo a engegar amb «parafrasi-cat web --lan». Us donarà un codi d'accés per al segon dispositiu."
        : "Per tornar-hi, atureu el servidor i torneu-lo a engegar amb «parafrasi-cat web».";
}

// --- origen del text ---------------------------------------------------------
// L'origen el diu l'usuari; el motor no intenta endevinar-lo mai.

function origenTriat() {
  const marcat = document.querySelector('input[name="origen"]:checked');
  return marcat ? marcat.value : "own";
}

function omplirOrigens(origens) {
  const contenidor = $("origens");
  contenidor.replaceChildren();
  for (const origen of origens) {
    const etiqueta = document.createElement("label");
    etiqueta.className = "opcio";
    const entrada = document.createElement("input");
    entrada.type = "radio";
    entrada.name = "origen";
    entrada.value = origen.id;
    entrada.checked = Boolean(origen.default);
    entrada.addEventListener("change", actualitzarOrigen);
    etiqueta.append(entrada, ` ${origen.label}`);
    contenidor.append(etiqueta);
  }
}

// --- estructura i ritme de l'empremta ------------------------------------------

function fila(dl, terme, valor) {
  const div = document.createElement("div");
  const dt = document.createElement("dt");
  dt.textContent = terme;
  const dd = document.createElement("dd");
  dd.textContent = valor;
  div.append(dt, dd);
  dl.append(div);
}

const percent = (x) => `${Math.round(Number(x) * 100)} %`;
const num = (x, d = 1) => (x === null || x === undefined ? "—" : Number(x).toFixed(d));

async function mostrarEstructuraRitme() {
  const seccio = $("estructura-ritme");
  if (!estilEsEmpremta()) {
    seccio.hidden = true;
    return;
  }
  try {
    const resum = await api(`/api/fingerprint/summary?id=${encodeURIComponent($("estil").value)}`);
    seccio.hidden = false;
    const avis = $("empremta-avis");
    avis.hidden = !resum.regenerate_hint;
    avis.textContent = resum.regenerate_hint;

    const ritme = $("empremta-ritme");
    ritme.replaceChildren();
    if (resum.rhythm.available) {
      const r = resum.rhythm;
      fila(ritme, "Longitud típica", `${num(r.typical_length, 0)} tokens per frase (mitjana ${num(r.mean_length)})`);
      fila(ritme, "Variació de longitud", `coeficient ${num(r.variation, 2)} · canvi mitjà ${num(r.mean_change)} tokens`);
      fila(ritme, "Curta / mitjana / llarga", Object.entries(r.shares).map(([k, v]) => `${k} ${percent(v)}`).join(" · ") +
        ` (curta ≤ ${r.thresholds.short_max}, llarga ≥ ${r.thresholds.long_min})`);
      fila(ritme, "Alternança", r.tendency);
      fila(ritme, "Confiança de la mostra", `${r.confidence} (${r.sample_size_sentences} frases)`);
    } else {
      fila(ritme, "Ritme", "no disponible en aquesta empremta");
    }

    const transicions = $("empremta-transicions");
    transicions.replaceChildren();
    for (const t of resum.rhythm.available ? resum.rhythm.transitions : []) {
      transicions.append(liText(`${t.from} → ${t.to}: ${t.label} (${percent(t.share)})`));
    }

    const sintaxi = $("empremta-sintaxi");
    sintaxi.replaceChildren();
    if (resum.syntax.available) {
      const x = resum.syntax;
      fila(sintaxi, "Coordinació", `${num(x.coordination_per_sentence, 2)} per frase`);
      fila(sintaxi, "Subordinació", `${num(x.subordination_per_sentence, 2)} per frase · ${percent(x.sentences_with_subordination_share)} de frases amb subordinada`);
      fila(sintaxi, "Ordre predominant", x.subject_order);
      fila(sintaxi, "Complexitat", `${num(x.clauses_per_sentence, 1)} clàusules per frase · profunditat ${num(x.mean_parse_depth, 1)} · distància ${num(x.mean_dependency_distance, 1)}`);
      fila(sintaxi, "Confiança de la mostra", `${x.confidence} (${x.sample_size_sentences} frases)`);
    } else {
      fila(sintaxi, "Estructura sintàctica", resum.syntax.reason || "no disponible en aquesta empremta");
    }
    $("empremta-detalls").textContent = JSON.stringify(resum.details, null, 1);
  } catch (error) {
    seccio.hidden = false;
    missatge($("empremta-avis"), error.message, true);
    $("empremta-avis").hidden = false;
  }
}

function estilEsEmpremta() {
  const triat = estat.opcions.style_profiles.find((p) => p.id === $("estil").value);
  return Boolean(triat && triat.kind === "fingerprint");
}

function actualitzarOrigen() {
  const origen = estat.opcions.source_modes.find((o) => o.id === origenTriat());
  const descripcio = $("descripcio-origen");
  const avis = $("avis-empremta");
  if (!origen || !origen.requires_fingerprint) {
    descripcio.hidden = true;
    avis.hidden = true;
    return;
  }
  descripcio.hidden = false;
  descripcio.textContent = origen.description;
  const falta = !estilEsEmpremta();
  avis.hidden = !falta;
  avis.textContent = falta ? estat.opcions.fingerprint_required : "";
}

function mostrarDescripcioMode() {
  const mode = estat.opcions.modes.find((m) => m.id === modeTriat());
  if (!mode) return;
  $("descripcio-mode").textContent = mode.description;
  const nivell = Number($("nivell").value);
  $("avis-nivell").hidden = nivell <= mode.max_level;
  $("avis-nivell").textContent =
    `El mode «${mode.label}» limita les regles al nivell ${mode.max_level}.`;
}

function omplirDiccionaris(diccionaris) {
  const contenidor = $("diccionaris");
  contenidor.replaceChildren();
  if (!diccionaris.length) {
    const buit = document.createElement("p");
    buit.className = "ajuda";
    buit.textContent = "No hi ha cap diccionari a dictionaries/.";
    contenidor.append(buit);
    return;
  }
  for (const diccionari of diccionaris) {
    const etiqueta = document.createElement("label");
    const casella = document.createElement("input");
    casella.type = "checkbox";
    casella.value = diccionari.id;
    casella.className = "diccionari";
    casella.disabled = Boolean(diccionari.error);
    const detall = diccionari.error
      ? ` (error: ${diccionari.error})`
      : ` (${diccionari.n_entries} entrades, ${diccionari.n_protected} protegides)`;
    etiqueta.append(casella, ` ${diccionari.label}${detall}`);
    if (diccionari.description) etiqueta.title = diccionari.description;
    contenidor.append(etiqueta);
  }
}

function diccionarisTriats() {
  return Array.from(document.querySelectorAll("input.diccionari:checked")).map((c) => c.value);
}

function mostrarRecursos(recursos, instal·ladors) {
  const mode = recursos.mode;
  const avis = $("mode-linguistic");
  avis.className = mode.full ? "mode complet" : "mode basic";
  avis.replaceChildren();
  const titol = document.createElement("strong");
  titol.textContent = mode.label;
  const detall = document.createElement("span");
  detall.textContent = ` ${mode.detail}`;
  avis.append(titol, detall);

  const llista = $("recursos");
  llista.replaceChildren();
  for (const clau of CLAUS_RECURSOS) {
    const recurs = recursos[clau];
    if (!recurs) continue;
    const element = document.createElement("li");
    element.className = recurs.active ? "actiu" : "inactiu";
    const nom = document.createElement("span");
    nom.textContent = `${recurs.component}: `;
    const marca = document.createElement("span");
    marca.className = "estat-recurs";
    marca.textContent = recurs.active ? "✓" : "○";
    const text = document.createElement("span");
    text.className = "estat-recurs";
    text.textContent = ` ${recurs.state}`;
    element.append(nom, marca, text, ` — ${recurs.message}`);
    if (recurs.detail) element.title = recurs.detail;
    llista.append(element);
  }

  const actiu = recursos.languagetool.active;
  $("languagetool").disabled = !actiu;
  if (!actiu) $("languagetool").checked = false;
  $("ajuda-languagetool").textContent = actiu
    ? "Comprova gramàtica, concordança i puntuació de cada candidat. Només valida: mai no reescriu el text."
    : "No està instal·lada. El motor continua funcionant amb les seves comprovacions internes.";

  const botons = $("botons-instal-lacio");
  botons.replaceChildren();
  for (const clau of mode.installable) {
    if (!instal·ladors[clau]) continue;
    const boto = document.createElement("button");
    boto.type = "button";
    boto.className = "secundari";
    boto.textContent = `Instal·la ${instal·ladors[clau].component}`;
    boto.addEventListener("click", () => demanarInstalacio(clau));
    botons.append(boto);
  }
}

async function refrescarRecursos() {
  const recursos = await api("/api/resources");
  mostrarRecursos(recursos, estat.opcions.installers);
  return recursos;
}

function demanarInstalacio(component) {
  const info = estat.opcions.installers[component];
  estat.componentPendent = component;
  $("detall-instal-lacio").textContent =
    `Component: ${info.component}. Origen: ${info.origin}. Versió: ${info.version}. ` +
    `Mida aproximada: ${info.approximate_size_mb} MB. Llicència: ${info.license}. ` +
    `Requisit: ${info.requirement}. ${info.note} ` +
    "Els recursos s'instal·laran a l'ordinador que executa Parafrasi-cat.";
  $("confirma-instal-lacio").hidden = false;
}

async function confirmarInstalacio() {
  $("confirma").disabled = true;
  try {
    const resposta = await api("/api/resources/install", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ component: estat.componentPendent, confirm: true }),
    });
    missatge($("estat"), resposta.message + (resposta.command ? ` ${resposta.command}` : ""));
    $("confirma-instal-lacio").hidden = true;
    if (resposta.started) {
      const inici = Date.now();
      const repeticio = setInterval(async () => {
        const recursos = await refrescarRecursos();
        if (recursos.offline.active || Date.now() - inici > 900000) {
          clearInterval(repeticio);
          if (recursos.offline.active) missatge($("estat"), "Recursos instal·lats.");
        }
      }, 15000);
    }
  } catch (error) {
    missatge($("estat"), error.message, true);
  } finally {
    $("confirma").disabled = false;
  }
}

async function carregarFitxerText(esdeveniment) {
  const fitxer = esdeveniment.target.files[0];
  if (!fitxer) return;
  try {
    $("text").value = await llegeixFitxer(fitxer);
    missatge($("estat"), `Carregat ${fitxer.name}.`);
  } catch (error) {
    missatge($("estat"), error.message, true);
  }
}

async function carregarTextosEmpremta(esdeveniment) {
  const fitxers = Array.from(esdeveniment.target.files);
  try {
    estat.textosEmpremta = await Promise.all(fitxers.map(llegeixFitxer));
    $("crea-empremta").disabled = estat.textosEmpremta.length === 0;
    $("estat-empremta").textContent = `${estat.textosEmpremta.length} textos preparats.`;
  } catch (error) {
    missatge($("estat-empremta"), error.message, true);
  }
}

async function crearEmpremta() {
  $("crea-empremta").disabled = true;
  missatge($("estat-empremta"), "Analitzant els textos…");
  try {
    const resposta = await api("/api/fingerprint", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: $("nom-empremta").value || "autor",
        texts: estat.textosEmpremta,
        source_mode: "own",
      }),
    });
    missatge($("estat-empremta"), `${resposta.message} ${resposta.n_words} paraules analitzades.`);
    estat.opcions = await api("/api/options");
    omplirSelect($("estil"), estat.opcions.style_profiles);
    $("estil").value = resposta.id;
    actualitzarOrigen();
    mostrarEstructuraRitme();
  } catch (error) {
    missatge($("estat-empremta"), error.message, true);
  } finally {
    $("crea-empremta").disabled = estat.textosEmpremta.length === 0;
  }
}

function mostrarEstatHistorial(historial) {
  $("historial-actiu").checked = historial.enabled;
  $("estat-historial").textContent = historial.enabled
    ? `Actiu: ${historial.path} (${historial.n_entries} entrades).`
    : "Desactivat: no es desa cap text ni cap configuració.";
}

async function carregarOpcions() {
  mostrarAcces(await api("/api/access"));
  estat.opcions = await api("/api/options");
  omplirSelect($("nivell"), estat.opcions.levels.map((n) => ({ id: n.level, label: n.label })));
  $("nivell").value = String(estat.opcions.modes.at(-1).max_level);
  $("nivell").addEventListener("change", mostrarDescripcioMode);
  omplirModes(estat.opcions.modes);
  omplirSelect($("estil"), estat.opcions.style_profiles);
  $("estil").value = "default";
  $("estil").addEventListener("change", actualitzarOrigen);
  $("estil").addEventListener("change", mostrarEstructuraRitme);
  omplirOrigens(estat.opcions.source_modes);
  actualitzarOrigen();
  mostrarEstructuraRitme();
  omplirDiccionaris(estat.opcions.dictionaries);
  omplirSelect($("preferencies"), estat.opcions.preferences, "cap");
  mostrarRecursos(estat.opcions.resources, estat.opcions.installers);
  mostrarEstatHistorial(estat.opcions.history);
}

// --- reescriptura ------------------------------------------------------------

async function generar(esdeveniment) {
  esdeveniment.preventDefault();
  const text = $("text").value.trim();
  if (!text) {
    missatge($("estat"), "Cal escriure o enganxar un text.", true);
    return;
  }
  $("genera").disabled = true;
  missatge($("estat"), "Generant candidats…");
  try {
    const resultat = await api("/api/rewrite", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        mode: modeTriat(),
        level: Number($("nivell").value),
        style_profile: $("estil").value,
        dictionaries: diccionarisTriats(),
        preferences: $("preferencies").value,
        languagetool: $("languagetool").checked,
        source_mode: origenTriat(),
        assertive_language: $("assertiu").checked,
      }),
    });
    estat.resultat = resultat;
    estat.feedback = [];
    mostrarResultat(resultat);
    missatge($("estat"), `${resultat.n_candidates} candidats avaluats.`);
  } catch (error) {
    missatge($("estat"), error.message, true);
  } finally {
    $("genera").disabled = false;
  }
}

function mostrarResultat(resultat) {
  $("sense-resultat").hidden = true;
  $("resum").hidden = false;
  $("resum-origen").textContent = resultat.author_adaptation
    ? `${resultat.source_mode.label} · ${resultat.author_adaptation}`
    : resultat.source_mode.label;
  $("resum-mode").textContent = resultat.mode.label;
  $("resum-nivell").textContent = resultat.level_capped
    ? `${resultat.level_label} (retallat des de ${resultat.requested_level})`
    : resultat.level_label;
  $("resum-assertiu").textContent = resultat.assertive_language
    ? resultat.assertive_language.label
    : "inactiu";
  $("resum-estil").textContent = resultat.style_profile || "cap";
  $("resum-diccionaris").textContent = resultat.dictionaries.join(", ") || "cap";
  $("resum-preferencies").textContent = resultat.preferences || "cap";
  $("resum-candidats").textContent =
    `${resultat.n_candidates} (${resultat.n_rejected_candidates} rebutjats)`;
  $("resum-languagetool").textContent = resultat.languagetool ? "activa" : "no activa";

  $("text-original").textContent = resultat.source_text;
  $("millor-candidat").textContent = resultat.output_text;

  const protegits = $("protegits");
  protegits.replaceChildren();
  if (!resultat.protected_spans.length) {
    const buit = document.createElement("li");
    buit.textContent = "cap";
    protegits.append(buit);
  }
  for (const fragment of resultat.protected_spans) {
    const element = document.createElement("li");
    element.textContent = `${fragment.text} · ${fragment.label}`;
    protegits.append(element);
  }

  estat.textUnitat = new Map(resultat.units.map((u) => [u.unit_id, u.output_text]));
  const unitats = $("unitats");
  unitats.replaceChildren();
  for (const unitat of resultat.units) unitats.append(dibuixaUnitat(unitat));

  $("final").value = resultat.output_text;
  missatge($("estat-final"), "");
}

function dibuixaUnitat(unitat) {
  const node = $("plantilla-unitat").content.cloneNode(true);
  node.querySelector(".titol-unitat").textContent = unitat.label;
  node.querySelector(".original-unitat").textContent = unitat.source_text;
  const llista = node.querySelector(".llista-candidats");
  for (const candidat of unitat.candidates) llista.append(dibuixaCandidat(unitat, candidat));
  return node;
}

function dibuixaCandidat(unitat, candidat) {
  const node = $("plantilla-candidat").content.cloneNode(true);
  const element = node.querySelector(".candidat");
  element.classList.toggle("seleccionat", candidat.selected);
  element.classList.toggle("rebutjat", !candidat.accepted);

  const marques = [];
  if (candidat.selected) marques.push("millor");
  if (candidat.is_identity) marques.push("original");
  if (!candidat.accepted) marques.push("rebutjat");
  if (candidat.score) marques.push(candidat.score.total.toFixed(3));
  node.querySelector(".marca").textContent = marques.join(" · ");
  node.querySelector(".text-candidat").textContent = candidat.text;

  if (candidat.rejection_reason) {
    const motiu = node.querySelector(".motiu-rebuig");
    motiu.hidden = false;
    motiu.textContent = `Rebutjat: ${candidat.rejection_reason}`;
  }

  const afinitatValor = candidat.score ? candidat.score.dimensions.afinitat_autor : null;
  if (afinitatValor !== null && afinitatValor !== undefined) {
    const afinitat = node.querySelector(".afinitat");
    afinitat.hidden = false;
    afinitat.textContent = `Afinitat amb l'estil: ${afinitatValor.toFixed(2)}`;
    const titol = node.querySelector(".titol-afinitat");
    const detall = node.querySelector(".detall-afinitat");
    titol.hidden = false;
    detall.hidden = false;
    detall.append(liText(`respecte de l'original: ${candidat.score.author_explanation}`));
    const info = candidat.score.author_affinity || {};
    for (const [nom, valor] of Object.entries(info.components || {})) {
      const nota = info.notes && info.notes[nom] ? ` — ${info.notes[nom]}` : "";
      detall.append(liText(`${nom}: ${Number(valor).toFixed(2)}${nota}`));
    }
  }

  const usa = node.querySelector(".usa");
  usa.disabled = !candidat.accepted;
  usa.addEventListener("click", () => usarCandidat(unitat.unit_id, candidat));

  const resposta = node.querySelector(".resposta-feedback");
  for (const boto of node.querySelectorAll(".vot")) {
    boto.addEventListener("click", () => votar(boto.dataset.verdicte, candidat, resposta));
  }

  node.querySelector(".diferencies").replaceChildren(...dibuixaDiferencies(candidat.diff));

  const regles = node.querySelector(".regles");
  if (!candidat.rules.length) regles.append(liText("cap: és el text original"));
  for (const regla of candidat.rules) {
    regles.append(
      liText(
        `${regla.rule_id} · risc ${regla.semantic_risk} · confiança ${regla.confidence}: ` +
          `«${regla.text_before}» a «${regla.text_after}»`
      )
    );
  }

  const puntuacions = node.querySelector(".puntuacions");
  if (candidat.score) {
    puntuacions.append(liText(`global ${candidat.score.total.toFixed(3)}`));
    for (const [nom, valor] of Object.entries(candidat.score.dimensions)) {
      if (valor !== null) puntuacions.append(liText(`${nom}: ${valor}`));
    }
    for (const [nom, valor] of Object.entries(candidat.score.components)) {
      puntuacions.append(liText(`component ${nom}: ${valor}`));
    }
    if (candidat.score.preference_explanation) {
      puntuacions.append(liText(`preferències: ${candidat.score.preference_explanation}`));
    }
  } else {
    puntuacions.append(liText("sense puntuació"));
  }

  const advertiments = node.querySelector(".advertiments");
  const avisos = [...candidat.errors, ...candidat.warnings];
  if (!avisos.length) advertiments.append(liText("cap"));
  for (const avis of avisos) {
    const li = liText(`[${avis.dimension}] ${avis.validator_id}: ${avis.message}`);
    li.className = "avis";
    advertiments.append(li);
  }
  return node;
}

function liText(text) {
  const li = document.createElement("li");
  li.textContent = text;
  return li;
}

function dibuixaDiferencies(diferencies) {
  return diferencies.map((part) => {
    if (part.op === "insert") {
      const ins = document.createElement("ins");
      ins.textContent = part.text;
      return ins;
    }
    if (part.op === "delete") {
      const del = document.createElement("del");
      del.textContent = part.text;
      return del;
    }
    return document.createTextNode(part.text);
  });
}

// --- accions sobre el resultat -----------------------------------------------

function usarCandidat(unitatId, candidat) {
  const actual = estat.textUnitat.get(unitatId);
  const final = $("final");
  if (actual && final.value.includes(actual)) {
    final.value = final.value.replace(actual, candidat.text);
    estat.textUnitat.set(unitatId, candidat.text);
    missatge($("estat-final"), "Text final actualitzat.");
    return;
  }
  estat.textUnitat.set(unitatId, candidat.text);
  missatge(
    $("estat-final"),
    "El text final ja no conté aquesta unitat tal com era: copieu-hi el candidat a mà.",
    true
  );
}

async function votar(verdicte, candidat, resposta) {
  try {
    const dades = await api("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        verdict: verdicte,
        variants: candidat.variants,
        preferences: estat.resultat ? estat.resultat.preferences_id : "",
        source_mode: estat.resultat ? estat.resultat.source_mode.id : "own",
      }),
    });
    estat.feedback.push({ candidate_id: candidat.candidate_id, verdict: verdicte, ...dades });
    resposta.hidden = false;
    resposta.textContent = dades.recorded.length
      ? dades.recorded.map((r) => `«${r.variant}»: ${r.description} (pes ${r.weight})`).join("; ")
      : dades.message;
  } catch (error) {
    resposta.hidden = false;
    resposta.textContent = error.message;
  }
}

async function copiar() {
  const text = $("final").value;
  try {
    await navigator.clipboard.writeText(text);
    missatge($("estat-final"), "Copiat al porta-retalls.");
  } catch {
    $("final").select();
    missatge($("estat-final"), "Premeu Ctrl+C per copiar el text seleccionat.", true);
  }
}

function baixar(bloc, nom) {
  const enllac = document.createElement("a");
  enllac.href = URL.createObjectURL(bloc);
  enllac.download = nom;
  enllac.click();
  URL.revokeObjectURL(enllac.href);
}

function exportar() {
  baixar(new Blob([$("final").value], { type: "text/plain;charset=utf-8" }), "parafrasi-cat.txt");
  missatge($("estat-final"), "Fitxer exportat.");
}

async function canviarHistorial() {
  try {
    const estatHistorial = await api("/api/history/enabled", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: $("historial-actiu").checked }),
    });
    mostrarEstatHistorial(estatHistorial);
  } catch (error) {
    missatge($("estat"), error.message, true);
  }
}

async function desarAlRegistre() {
  if (!estat.resultat) return;
  const resultat = estat.resultat;
  try {
    const desat = await api("/api/history", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_text: resultat.source_text,
        config: {
          mode: resultat.mode.id,
          level: resultat.level,
          rule_set: resultat.rule_set,
          style_profile: resultat.style_profile_id,
          dictionaries: resultat.dictionaries,
          preferences: resultat.preferences_id,
          source_mode: resultat.source_mode.id,
          assertive_language: Boolean(
            resultat.assertive_language && resultat.assertive_language.active
          ),
        },
        result: {
          output_text: resultat.output_text,
          protected_spans: resultat.protected_spans,
          units: resultat.units.map((unitat) => ({
            unit_id: unitat.unit_id,
            source_text: unitat.source_text,
            candidates: unitat.candidates.map((candidat) => ({
              candidate_id: candidat.candidate_id,
              text: candidat.text,
              accepted: candidat.accepted,
              selected: candidat.selected,
              score: candidat.score ? candidat.score.total : null,
              rules: candidat.rules.map((regla) => regla.rule_id),
            })),
          })),
        },
        selected_text: resultat.output_text,
        final_text: $("final").value,
        feedback: estat.feedback,
      }),
    });
    mostrarEstatHistorial(desat);
    missatge(
      $("estat-final"),
      desat.saved ? `Desat al registre (${desat.entry_id}).` : "El registre està desactivat.",
      !desat.saved
    );
  } catch (error) {
    missatge($("estat-final"), error.message, true);
  }
}

async function exportarHistorial() {
  // Es baixa amb fetch per poder detectar la sessió caducada del mode de
  // xarxa local; la descàrrega es desa al dispositiu que mira la interfície.
  try {
    const resposta = await fetch("/api/history/export");
    if (resposta.status === 401) {
      window.location.replace("/");
      return;
    }
    if (!resposta.ok) throw new Error(`Error ${resposta.status}`);
    baixar(await resposta.blob(), "historial.json");
  } catch (error) {
    missatge($("estat"), error.message, true);
  }
}

// --- arrencada ---------------------------------------------------------------

async function iniciar() {
  try {
    await carregarOpcions();
    missatge($("estat"), "");
  } catch (error) {
    missatge($("estat"), `No s'han pogut carregar les opcions: ${error.message}`, true);
  }
  $("formulari").addEventListener("submit", generar);
  $("copia").addEventListener("click", copiar);
  $("exporta").addEventListener("click", exportar);
  $("desa").addEventListener("click", desarAlRegistre);
  $("historial-actiu").addEventListener("change", canviarHistorial);
  $("confirma").addEventListener("click", confirmarInstalacio);
  $("cancel-la").addEventListener("click", () => {
    $("confirma-instal-lacio").hidden = true;
  });
  $("fitxer-text").addEventListener("change", carregarFitxerText);
  $("fitxers-empremta").addEventListener("change", carregarTextosEmpremta);
  $("crea-empremta").addEventListener("click", crearEmpremta);
  $("exporta-historial").addEventListener("click", exportarHistorial);
}

document.addEventListener("DOMContentLoaded", iniciar);
