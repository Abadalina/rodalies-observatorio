// Mapa en vivo. La posicion la publica Renfe; aqui no se interpola nada.
"use strict";

const CATALUNYA = { nucleo: "51", centro: [41.55, 2.05], zoom: 9 };
const ESPANA = { nucleo: null, centro: [40.3, -3.7], zoom: 6 };
const CADA = 30_000;

let ambito = CATALUNYA;
let temporizador = null;
const marcas = new Map(); // trip_id -> marcador, para mover en vez de recrear

// SVG en vez de lienzo: con unos cientos de trenes rinde igual y permite darles
// halo, sombra y una transicion suave al moverse, que en un lienzo no se puede.
const mapa = L.map("mapa", { zoomControl: true, preferCanvas: false, zoomSnap: .5 })
  .setView(CATALUNYA.centro, CATALUNYA.zoom);

// Base casi monocroma a proposito. Los mosaicos de serie de OpenStreetMap estan
// llenos de color y de detalle, y compiten con el dato: sobre un mapa asi, un
// punto rojo es un punto rojo mas. Sobre una base gris, es el unico.
//
// El apagado se hace con un filtro CSS sobre los mosaicos de OSM, y NO con un
// proveedor de base gris ya hecha. Se probo CARTO y pide clave: devuelve un PNG
// valido, con HTTP 200, cuya imagen es el aviso de que falta la clave. Un mapa
// entero de marcas de agua que ninguna comprobacion automatica ve.
const prefiereOscuro = window.matchMedia("(prefers-color-scheme: dark)");

const base = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 18,
  className: "hoja-mosaicos",
  attribution:
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · ' +
    'datos de Renfe (CC BY 4.0)',
}).addTo(mapa);

const capaVias = L.layerGroup().addTo(mapa);
const capaTrenes = L.layerGroup().addTo(mapa);

// -- color segun el retraso ---------------------------------------------------

// Escala de severidad, validada y no elegida a ojo. Antes eran CINCO bandas y
// dos de ellas, "3 a 5 min" y "5 a 15 min", quedaban a una distancia de color de
// 14,8 sobre 15: indistinguibles incluso con vision normal, no digamos con
// daltonismo. No habia ambar que lo arreglara, porque entre el verde y el rojo
// no caben cinco escalones. Se fusionan en una sola banda "tarde" y las cuatro
// que quedan pasan la validacion.
//
// El ambar se queda por debajo de 3:1 de contraste contra el fondo claro, cosa
// que se admite solo si el color no va solo: por eso la leyenda y el globo
// siempre traen el texto al lado.
const ESCALA = {
  claro:  { adelantado: "#2563eb", puntual: "#15803d", tarde: "#f59e0b", grave: "#b91c1c" },
  oscuro: { adelantado: "#4a90e8", puntual: "#30a865", tarde: "#d9a12b", grave: "#e8635c" },
};

function tono(segundos) {
  const c = prefiereOscuro.matches ? ESCALA.oscuro : ESCALA.claro;
  if (segundos === null || segundos === undefined) {
    return { color: "#9ca3af", nombre: "sin dato" };
  }
  if (segundos < -60) return { color: c.adelantado, nombre: "adelantado" };
  if (segundos <= 180) return { color: c.puntual, nombre: "puntual" };
  if (segundos <= 900) return { color: c.tarde, nombre: "tarde" };
  return { color: c.grave, nombre: "grave" };
}

function enMinutos(segundos) {
  if (segundos === null || segundos === undefined) return "sin dato de retraso";
  const s = Math.round(segundos);
  if (Math.abs(s) < 60) return s <= 0 ? "en hora" : `${s} s`;
  const m = Math.floor(Math.abs(s) / 60);
  const r = Math.abs(s) % 60;
  const texto = r ? `${m} min ${r} s` : `${m} min`;
  return s < 0 ? `${texto} adelantado` : `${texto} de retraso`;
}

const ESTADOS = {
  STOPPED_AT: "parado en",
  INCOMING_AT: "llegando a",
  IN_TRANSIT_TO: "en camino a",
};

function escapar(valor) {
  // El destino y el nombre de la parada vienen de la base. Van a innerHTML del
  // globo, asi que se escapan: un nombre con un `<` no debe poder inyectar nada.
  const d = document.createElement("div");
  d.textContent = valor === null || valor === undefined ? "" : String(valor);
  return d.innerHTML;
}

function ficha(t) {
  const estado = ESTADOS[t.estado] || "";
  const parada = t.parada ? `${estado} ${escapar(t.parada)}` : "";
  const color = tono(t.retraso_s).color;
  // La etiqueta lleva el color de la LINEA, no el del retraso: el retraso ya lo
  // dice la cifra grande de debajo. Sin color conocido, gris neutro, que no se
  // pueda leer como "puntual" o "grave".
  const fondo = Lineas.color(t.linea, t.nucleo_id) || "#6b6862";
  return `
    <span class="ficha-linea" style="background:${fondo};color:${Lineas.textoSobre(fondo)}">${escapar(t.linea)}</span>
    <div class="ficha-destino">${escapar(t.destino) || "destino sin publicar"}</div>
    <div class="ficha-retraso" style="color:${color}">${enMinutos(t.retraso_s)}</div>
    ${parada ? `<div class="ficha-dato">${parada}</div>` : ""}
    <div class="ficha-dato">visto ${new Date(t.visto).toLocaleTimeString("es-ES")}</div>
    <a class="ficha-enlace" href="/tren.html?id=${encodeURIComponent(t.trip_id)}">ver su histórico →</a>
  `;
}

// -- pintado ------------------------------------------------------------------

async function pintarTrenes() {
  const punto = document.getElementById("punto");
  const resumen = document.getElementById("resumen");
  try {
    const ruta = ambito.nucleo ? `/api/posiciones?nucleo=${ambito.nucleo}` : "/api/posiciones";
    const trenes = await (await fetch(ruta)).json();

    const vistos = new Set();
    for (const t of trenes) {
      vistos.add(t.trip_id);
      const { color } = tono(t.retraso_s);
      const donde = [t.lat, t.lon];
      let marca = marcas.get(t.trip_id);

      if (marca) {
        // Mover el marcador en vez de recrearlo: asi el globo abierto no se
        // cierra solo cada treinta segundos mientras lo estas leyendo.
        marca.setLatLng(donde);
        marca.setStyle({ fillColor: color });
      } else {
        marca = L.circleMarker(donde, {
          radius: 5.5,
          weight: 2,
          // Anillo del color del fondo, no negro: separa el punto de la base
          // del mapa sin ensuciarlo, y funciona igual en claro y en oscuro.
          color: prefiereOscuro.matches ? "#14130f" : "#ffffff",
          fillColor: color,
          fillOpacity: 1,
          className: "tren",
        }).addTo(capaTrenes);
        marcas.set(t.trip_id, marca);
      }
      marca.bindPopup(ficha(t));
      marca.bindTooltip(`${t.linea} · ${enMinutos(t.retraso_s)}`, { direction: "top" });
    }

    // Un tren que Renfe deja de publicar se quita. Dejarlo clavado donde se le
    // vio por ultima vez haria creer que sigue ahi, que es peor que no saberlo.
    for (const [id, marca] of marcas) {
      if (!vistos.has(id)) {
        capaTrenes.removeLayer(marca);
        marcas.delete(id);
      }
    }

    const tarde = trenes.filter((t) => t.retraso_s > 300).length;
    punto.className = "punto punto--bien";
    resumen.textContent = `${trenes.length} trenes en circulación · ${tarde} con más de 5 min`;
  } catch (error) {
    punto.className = "punto punto--mal";
    resumen.textContent = "no se han podido cargar los trenes";
    console.error(error);
  }
}

async function pintarVias() {
  capaVias.clearLayers();
  try {
    const ruta = ambito.nucleo ? `/api/trazados?nucleo=${ambito.nucleo}` : "/api/trazados";
    const trazados = await (await fetch(ruta)).json();
    for (const t of trazados) {
      L.polyline(t.puntos, {
        color: prefiereOscuro.matches ? "#4b5563" : "#94a3b8",
        weight: 2,
        opacity: .7,
        lineJoin: "round",
        lineCap: "round",
        interactive: false,
      }).addTo(capaVias);
    }
  } catch (error) {
    console.error(error);
  }
}

function cambiarAmbito(nuevo) {
  ambito = nuevo;
  capaTrenes.clearLayers();
  marcas.clear();
  mapa.setView(nuevo.centro, nuevo.zoom);
  pintarVias();
  pintarTrenes();
}

document.getElementById("todo-espana").addEventListener("change", (e) => {
  cambiarAmbito(e.target.checked ? ESPANA : CATALUNYA);
});

pintarVias();
Lineas.cargar().then(pintarTrenes);
temporizador = setInterval(pintarTrenes, CADA);

// Con la pestaña de fondo no se pide nada: ni gasta bateria ni carga el servidor.
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    clearInterval(temporizador);
  } else {
    pintarTrenes();
    temporizador = setInterval(pintarTrenes, CADA);
  }
});
