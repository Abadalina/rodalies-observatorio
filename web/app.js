// Datos en vivo de la API. Sin dependencias externas a proposito: la politica de
// seguridad de la pagina solo permite cargar lo que sirve este mismo dominio.
"use strict";

const NUCLEO_CATALUNYA = "51";
const DIAS = 14;

const numero = new Intl.NumberFormat("es-ES");
const decimal = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1 });

async function pedir(ruta) {
  const respuesta = await fetch(ruta, { headers: { Accept: "application/json" } });
  if (!respuesta.ok) throw new Error(`${ruta}: HTTP ${respuesta.status}`);
  return respuesta.json();
}

function fecha(desplazamiento) {
  const d = new Date();
  d.setDate(d.getDate() + desplazamiento);
  const ano = d.getFullYear();
  const mes = String(d.getMonth() + 1).padStart(2, "0");
  const dia = String(d.getDate()).padStart(2, "0");
  return `${ano}-${mes}-${dia}`;
}

function minutosYSegundos(segundos) {
  if (segundos === null || segundos === undefined) return "—";
  const s = Math.round(Number(segundos));
  const signo = s < 0 ? "−" : "";
  const abs = Math.abs(s);
  return `${signo}${Math.floor(abs / 60)}:${String(abs % 60).padStart(2, "0")}`;
}

// -- estado de la captura ----------------------------------------------------

async function pintarEstado() {
  const punto = document.querySelector("#estado .punto");
  const texto = document.getElementById("estado-texto");
  try {
    const salud = await pedir("/api/salud");
    const principal = (salud.feeds || []).find((f) => f.feed === "trip_updates");
    const antiguedad = principal ? principal.antiguedad_s : null;
    const bien = salud.estado === "ok";
    punto.className = `punto ${bien ? "punto--bien" : "punto--mal"}`;
    texto.textContent = bien
      ? `capturando · última consulta hace ${antiguedad} s`
      : `la captura va con retraso (${salud.estado})`;
  } catch (error) {
    // Que falle el estado no debe dejar la pagina mintiendo con "comprobando".
    punto.className = "punto punto--mal";
    texto.textContent = "no se ha podido comprobar el estado";
    console.error(error);
  }
}

// -- cifras de cabecera ------------------------------------------------------

async function pintarCifras() {
  try {
    const dias = await pedir(
      `/api/kpi?desde=${fecha(-DIAS)}&hasta=${fecha(0)}&nucleo=${NUCLEO_CATALUNYA}`
    );
    if (!dias.length) return;

    const suma = (campo) => dias.reduce((t, d) => t + Number(d[campo] || 0), 0);
    const paradas = suma("paradas_observadas");
    const conRetraso = suma("paradas_con_retraso");
    // La puntualidad del conjunto se pondera por paradas, no se promedian los
    // porcentajes diarios: un domingo flojo pesaria lo mismo que un martes.
    const puntuales = dias.reduce(
      (t, d) => t + (Number(d.pct_puntualidad || 0) / 100) * Number(d.paradas_con_retraso || 0),
      0
    );

    document.getElementById("cifra-observaciones").textContent = numero.format(paradas);
    document.getElementById("cifra-dias").textContent = numero.format(dias.length);
    document.getElementById("cifra-trenes").textContent = numero.format(suma("trenes"));
    document.getElementById("cifra-puntualidad").textContent = conRetraso
      ? `${decimal.format((100 * puntuales) / conRetraso)} %`
      : "—";
  } catch (error) {
    console.error(error);
  }
}

// -- ranking de lineas -------------------------------------------------------

async function pintarLineas() {
  const cuerpo = document.getElementById("cuerpo-lineas");
  try {
    const lineas = await pedir(
      `/api/lineas?desde=${fecha(-DIAS)}&hasta=${fecha(0)}&nucleo=${NUCLEO_CATALUNYA}`
    );
    // Las lineas con cuatro paradas sueltas no son una linea: son ruido con
    // nombre. Mismo criterio que las comprobaciones de calidad.
    const utiles = lineas.filter((l) => Number(l.paradas) >= 500 && l.pct_puntualidad !== null);

    if (!utiles.length) {
      cuerpo.innerHTML = '<tr><td colspan="4" class="vacio">todavía no hay suficientes datos</td></tr>';
      return;
    }

    cuerpo.textContent = "";
    for (const l of utiles) {
      const fila = document.createElement("tr");
      // textContent en vez de innerHTML: el nombre de la linea viene de la base
      // de datos y no tiene por que acabar interpretandose como HTML.
      const celdaLinea = document.createElement("td");
      const etiqueta = document.createElement("span");
      etiqueta.className = "linea";
      etiqueta.textContent = l.linea;
      celdaLinea.appendChild(etiqueta);

      const celdas = [
        `${decimal.format(Number(l.pct_puntualidad))} %`,
        minutosYSegundos(l.retraso_medio_s),
        numero.format(Number(l.paradas)),
      ].map((valor) => {
        const td = document.createElement("td");
        td.className = "num";
        td.textContent = valor;
        return td;
      });

      fila.append(celdaLinea, ...celdas);
      cuerpo.appendChild(fila);
    }
  } catch (error) {
    cuerpo.innerHTML = '<tr><td colspan="4" class="vacio">no se han podido cargar las líneas</td></tr>';
    console.error(error);
  }
}

pintarEstado();
pintarCifras();
pintarLineas();
// El estado se refresca solo; las cifras no cambian en un minuto.
setInterval(pintarEstado, 60_000);
