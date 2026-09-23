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
    await Lineas.cargar();
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
      celdaLinea.appendChild(Lineas.etiqueta(l.linea, l.nucleo_id));

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

// -- buscador ----------------------------------------------------------------
//
// Un numero busca trenes en la API; un texto busca estaciones en la lista que
// ya da /estaciones, filtrada aqui mismo sin acentos ni mayusculas: son unas
// doscientas y no merece la pena un endpoint para eso.

const MAX_RESULTADOS = 8;
let estaciones = null;
let busquedaEnCurso = 0;

function normalizar(texto) {
  return String(texto || "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase();
}

function diaCorto(iso) {
  return new Date(`${iso}T12:00:00`).toLocaleDateString("es-ES", { day: "numeric", month: "short" });
}

function resultado(href, principal, detalle, linea, nucleo) {
  const li = document.createElement("li");
  const a = document.createElement("a");
  a.href = href;
  if (linea) a.appendChild(Lineas.etiqueta(linea, nucleo));
  const texto = document.createElement("span");
  texto.className = "resultado-texto";
  texto.textContent = principal;
  const extra = document.createElement("span");
  extra.className = "resultado-detalle";
  extra.textContent = detalle;
  a.append(texto, extra);
  li.appendChild(a);
  return li;
}

async function buscar() {
  const lista = document.getElementById("resultados");
  const termino = document.getElementById("buscar").value.trim();
  const esta = ++busquedaEnCurso;
  if (!termino || (!/^\d+$/.test(termino) && termino.length < 2)) {
    lista.textContent = "";
    return;
  }

  let filas = [];
  try {
    if (/^\d{1,6}$/.test(termino)) {
      const trenes = await pedir(
        `/api/buscar/trenes?numero=${termino}&nucleo=${NUCLEO_CATALUNYA}&limite=${MAX_RESULTADOS}`
      );
      filas = trenes.map((t) =>
        resultado(
          `/tren.html?id=${encodeURIComponent(t.trip_id)}`,
          `tren ${t.numero}`,
          `visto el ${diaCorto(t.ultimo_dia)}`,
          t.linea,
          t.nucleo_id
        )
      );
    } else {
      if (!estaciones) {
        estaciones = await pedir(
          `/api/estaciones?desde=${fecha(-DIAS)}&hasta=${fecha(0)}` +
            `&nucleo=${NUCLEO_CATALUNYA}&limite=2000&minimo=1`
        );
      }
      const buscado = normalizar(termino);
      filas = estaciones
        .filter((e) => normalizar(e.estacion).includes(buscado))
        .slice(0, MAX_RESULTADOS)
        .map((e) =>
          resultado(
            `/estadisticas.html?estacion=${encodeURIComponent(e.estacion)}#estaciones`,
            e.estacion,
            e.pct_puntualidad === null
              ? "sin dato de puntualidad"
              : `${decimal.format(Number(e.pct_puntualidad))} % puntual`
          )
        );
    }
  } catch (error) {
    console.error(error);
  }

  // Si mientras llegaba esta respuesta se ha tecleado otra cosa, se descarta:
  // si no, una respuesta lenta podria pisar a una mas nueva.
  if (esta !== busquedaEnCurso) return;
  lista.textContent = "";
  if (!filas.length) {
    const li = document.createElement("li");
    li.className = "resultado-vacio";
    li.textContent = "no hay coincidencias";
    lista.appendChild(li);
    return;
  }
  lista.append(...filas);
}

// Los resultados de lo tecleado antes se quitan en cuanto se teclea otra cosa:
// si se quedaran mientras llega la respuesta nueva, un Intro en ese instante
// llevaria al primer resultado de la busqueda ANTERIOR.
let esperaBusqueda = null;
document.getElementById("buscar").addEventListener("input", () => {
  document.getElementById("resultados").textContent = "";
  clearTimeout(esperaBusqueda);
  esperaBusqueda = setTimeout(buscar, 200);
});

// Intro lleva al primer resultado de lo que hay escrito AHORA: si la busqueda
// aun no habia salido, se lanza y se espera.
document.getElementById("buscador").addEventListener("submit", async (e) => {
  e.preventDefault();
  clearTimeout(esperaBusqueda);
  await buscar();
  const primero = document.querySelector("#resultados a");
  if (primero) location.href = primero.href;
});

pintarEstado();
pintarCifras();
pintarLineas();
// El estado se refresca solo; las cifras no cambian en un minuto.
setInterval(pintarEstado, 60_000);
