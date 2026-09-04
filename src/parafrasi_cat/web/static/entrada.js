"use strict";

// Pantalla d'entrada del mode de xarxa local. Envia el codi d'accés al
// servidor d'aquesta mateixa xarxa i, si és correcte, el servidor obre una
// sessió amb una galeta i ja es pot carregar la interfície de sempre.

const $ = (id) => document.getElementById(id);

async function estatAcces() {
  try {
    const acces = await (await fetch("/api/access")).json();
    $("privacitat-entrada").textContent = acces.privacy || "";
    $("avis-entrada").textContent = acces.warning || "";
    if (acces.authenticated) window.location.replace("/");
  } catch (error) {
    $("estat-entrada").textContent = `No s'ha pogut consultar el servidor: ${error.message}`;
    $("estat-entrada").classList.add("error");
  }
}

async function entrar(esdeveniment) {
  esdeveniment.preventDefault();
  const estat = $("estat-entrada");
  const codi = $("codi").value.trim();
  if (!codi) {
    estat.textContent = "Escriviu el codi d'accés.";
    estat.classList.add("error");
    return;
  }
  $("entra").disabled = true;
  estat.classList.remove("error");
  estat.textContent = "Comprovant el codi…";
  try {
    const resposta = await fetch("/api/access", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin: codi }),
    });
    const dades = await resposta.json().catch(() => ({ error: "Resposta il·legible" }));
    if (!resposta.ok) throw new Error(dades.error || `Error ${resposta.status}`);
    estat.textContent = "Codi correcte. Obrint la interfície…";
    window.location.replace("/");
  } catch (error) {
    estat.textContent = error.message;
    estat.classList.add("error");
    $("codi").value = "";
    $("codi").focus();
  } finally {
    $("entra").disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  $("formulari-entrada").addEventListener("submit", entrar);
  estatAcces();
});
