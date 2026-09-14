// Mapa en vivo. La posicion la publica Renfe; aqui no se interpola nada.
"use strict";

const CATALUNYA = { nucleo: "51", centro: [41.55, 2.05], zoom: 9 };
const ESPANA = { nucleo: null, centro: [40.3, -3.7], zoom: 6 };
const CADA = 30_000;

let ambito = CATALUNYA;
let temporizador = null;
const marcas = new Map(); // trip_id -> marcador, para mover en vez de recrear

const mapa = L.map("mapa", { zoomControl: true, preferCanvas: true })
  .setView(CATALUNYA.centro, CATALUNYA.zoom);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 17,
  className: "hoja-mosaicos",
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
}).addTo(mapa);

const capaVias = L.layerGroup().addTo(mapa);
const capaTrenes = L.layerGroup().addTo(mapa);

// -- color segun el retraso ---------------------------------------------------

function tono(segundos) {
  if (segundos === null || segundos === undefined) return { color: "#8a8a8a", nombre: "sin dato" };
  if (segundos < -60) return { color: "#4a7fd4", nombre: "adelantado" };
  if (segundos <= 180) return { color: "#2e9e5b", nombre: "puntual" };
  if (segundos <= 300) return { color: "#d9a441", nombre: "leve" };
  if (segundos <= 900) return { color: "#e07a3c", nombre: "tarde" };
  return { color: "#c4342c", nombre: "grave" };
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
  return `
    <span class="ficha-linea" style="background:${color}">${escapar(t.linea)}</span>
    <div class="ficha-destino">${escapar(t.destino) || "destino sin publicar"}</div>
    <div class="ficha-retraso" style="color:${color}">${enMinutos(t.retraso_s)}</div>
    ${parada ? `<div class="ficha-dato">${parada}</div>` : ""}
    <div class="ficha-dato">visto ${new Date(t.visto).toLocaleTimeString("es-ES")}</div>
    <a class="ficha-enlace" href="/tren.html?id=${encodeURIComponent(t.trip_id)}">ver su historico →</a>
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
          radius: 6,
          weight: 1.5,
          color: "#00000055",
          fillColor: color,
          fillOpacity: .95,
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
    resumen.textContent = `${trenes.length} trenes en circulacion · ${tarde} con mas de 5 min`;
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
        color: "#7d8a99",
        weight: 1.6,
        opacity: .55,
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
pintarTrenes();
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
