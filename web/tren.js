// Ficha de un tren: cómo se ha portado estos días y su último recorrido.
"use strict";

const id = new URLSearchParams(location.search).get("id");
const decimal = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1 });

function minutos(segundos) {
  if (segundos === null || segundos === undefined || segundos === "") return "—";
  const s = Math.round(Number(segundos));
  const signo = s < 0 ? "−" : "";
  const abs = Math.abs(s);
  return `${signo}${Math.floor(abs / 60)}:${String(abs % 60).padStart(2, "0")}`;
}

function hora(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
}

function dia(fecha) {
  return new Date(`${fecha}T12:00:00`).toLocaleDateString("es-ES", {
    weekday: "short", day: "numeric", month: "short",
  });
}

// La misma escala de severidad que el mapa: el color de una barra significa lo
// mismo que el de un tren en el mapa.
const oscuro = window.matchMedia("(prefers-color-scheme: dark)");
function colorRetraso(segundos) {
  const c = oscuro.matches
    ? { puntual: "#30a865", tarde: "#d9a12b", grave: "#e8635c" }
    : { puntual: "#15803d", tarde: "#f59e0b", grave: "#b91c1c" };
  if (segundos <= 180) return c.puntual;
  if (segundos <= 900) return c.tarde;
  return c.grave;
}

function escapar(valor) {
  // Los nombres de estacion vienen de la base y van al globo de la grafica,
  // que es innerHTML.
  const d = document.createElement("div");
  d.textContent = valor === null || valor === undefined ? "" : String(valor);
  return d.innerHTML;
}

const enMinutos = (v) => `${decimal.format(v)} min`;

// Las graficas se dibujan al ancho de su caja; al girar el movil o cambiar el
// tamano de la ventana se rehacen con lo ya descargado.
const dibujos = [];
let redibujo = null;
window.addEventListener("resize", () => {
  clearTimeout(redibujo);
  redibujo = setTimeout(() => dibujos.forEach((dibujar) => dibujar()), 250);
});

function mostrarGrafica(idFigura, dibujar) {
  document.getElementById(idFigura).hidden = false;
  dibujos.push(dibujar);
  dibujar();
}

function celda(texto, clase) {
  const td = document.createElement("td");
  if (clase) td.className = clase;
  td.textContent = texto;
  return td;
}

// "Ultimos N dias" son dias del calendario, no las N filas mas recientes. Un
// tren que solo circula en laborables tiene siete filas repartidas en nueve
// dias, y llamar a eso "media de 7 dias" seria etiquetar mal el numero.
function ultimosDias(dias, cuantos) {
  const corte = new Date();
  corte.setDate(corte.getDate() - cuantos);
  const limite = corte.toISOString().slice(0, 10);
  return dias.filter((d) => d.service_date >= limite);
}

// La media se pondera por paradas: un dia con tres paradas observadas no puede
// pesar lo mismo que uno con cuarenta.
function mediaPonderada(dias) {
  let suma = 0;
  let peso = 0;
  for (const d of dias) {
    const n = Number(d.con_dato || 0);
    if (!n || d.retraso_medio_s === null) continue;
    suma += Number(d.retraso_medio_s) * n;
    peso += n;
  }
  return peso ? suma / peso : null;
}

async function cargar() {
  if (!id) {
    document.getElementById("titulo").textContent = "Falta el identificador del tren";
    return;
  }

  let datos;
  try {
    const respuesta = await fetch(`/api/trenes/${encodeURIComponent(id)}/historial?dias=14`);
    if (respuesta.status === 404) {
      document.getElementById("titulo").textContent = "Ese tren no aparece en la serie";
      document.getElementById("subtitulo").textContent = id;
      return;
    }
    datos = await respuesta.json();
  } catch (error) {
    document.getElementById("titulo").textContent = "No se ha podido cargar el tren";
    console.error(error);
    return;
  }

  const tren = datos.tren || {};
  const dias = datos.dias || [];
  await Lineas.cargar();

  // El titulo lleva el numero comercial, que es lo que identifica al tren de un
  // dia para otro; el trip_id de hoy va debajo, como dato de trazabilidad.
  const titulo = document.getElementById("titulo");
  titulo.textContent = "";
  if (tren.linea) titulo.append(Lineas.etiqueta(tren.linea, tren.nucleo_id), " ");
  titulo.append(`tren ${tren.numero || tren.trip_id}`);
  document.title = `${tren.linea ? `${tren.linea} · ` : ""}tren ${tren.numero || tren.trip_id}` +
    " · Observatorio de Rodalies";
  // Renfe rellena el recorrido con espacios antes del guion que separa origen y
  // destino ("Molins de Rei      -Maçanet-Massanes"). Ese guion, y solo ese,
  // lleva espacio delante: los de dentro de un nombre de estacion no.
  const limpio = (v) =>
    v ? String(v).replace(/\s+-\s*/g, " – ").replace(/\s+/g, " ").trim() : "";
  document.getElementById("subtitulo").textContent =
    [limpio(tren.destino), limpio(tren.recorrido)].filter(Boolean).join(" · ") ||
    "recorrido sin publicar";
  const traza = document.getElementById("trazabilidad");
  if (traza) traza.textContent = `Identificador de hoy: ${tren.trip_id}`;

  // -- cifras -----------------------------------------------------------------
  const ventana7 = ultimosDias(dias, 7);
  const media7 = mediaPonderada(ventana7);
  const media14 = mediaPonderada(dias);
  document.getElementById("media-7").textContent = media7 === null ? "—" : minutos(media7);
  document.getElementById("media-14").textContent = media14 === null ? "—" : minutos(media14);

  // Si este tren solo ha circulado en la ultima semana, las dos ventanas
  // cubren los mismos dias y las dos cifras salen identicas. Es correcto, pero
  // dos numeros iguales sin explicacion parecen un error: se dice.
  const mismasVentanas = dias.length > 0 && ventana7.length === dias.length;
  const nota = document.getElementById("nota-14");
  if (nota) {
    nota.textContent = mismasVentanas ? "sin datos anteriores: mismo período" : "";
  }

  const conDato = dias.filter((d) => d.pct_puntualidad !== null);
  if (conDato.length) {
    const pesoTotal = conDato.reduce((t, d) => t + Number(d.con_dato || 0), 0);
    const puntuales = conDato.reduce(
      (t, d) => t + (Number(d.pct_puntualidad) / 100) * Number(d.con_dato || 0), 0);
    document.getElementById("punt-14").textContent =
      pesoTotal ? `${decimal.format((100 * puntuales) / pesoTotal)} %` : "—";
  }

  const peores = dias.map((d) => Number(d.retraso_max_s)).filter((n) => !Number.isNaN(n));
  if (peores.length) document.getElementById("peor").textContent = minutos(Math.max(...peores));

  // -- dia a dia --------------------------------------------------------------
  const cuerpoDias = document.getElementById("cuerpo-dias");
  cuerpoDias.textContent = "";
  if (!dias.length) {
    cuerpoDias.appendChild(celda("este tren no ha circulado estos días", "vacio")).colSpan = 6;
  } else {
    for (const d of dias) {
      const fila = document.createElement("tr");
      fila.append(
        celda(dia(d.service_date)),
        celda(minutos(d.retraso_medio_s), "num"),
        celda(minutos(d.retraso_mediano_s), "num"),
        celda(minutos(d.retraso_max_s), "num"),
        celda(d.pct_puntualidad === null ? "—" : `${decimal.format(d.pct_puntualidad)} %`, "num"),
        celda(d.paradas, "num"),
      );
      cuerpoDias.appendChild(fila);
    }
    const conMedia = dias
      .filter((d) => d.retraso_medio_s !== null)
      .sort((a, b) => (a.service_date < b.service_date ? -1 : 1));
    if (conMedia.length >= 2) {
      mostrarGrafica("figura-dias", () =>
        graficaBarras(
          document.getElementById("g-dias"),
          conMedia.map((d) => ({
            etiqueta: new Date(`${d.service_date}T12:00:00`).toLocaleDateString("es-ES", {
              day: "numeric", month: "short",
            }),
            valor: Number(d.retraso_medio_s) / 60,
            color: colorRetraso(Number(d.retraso_medio_s)),
            detalle: `<strong>${dia(d.service_date)}</strong><br>` +
              `retraso medio ${minutos(d.retraso_medio_s)}<br>` +
              `peor ${minutos(d.retraso_max_s)} · ` +
              `${d.pct_puntualidad === null ? "—" : `${decimal.format(d.pct_puntualidad)} %`} puntual`,
          })),
          { titulo: "Retraso medio de cada día", formato: enMinutos, alto: 210 }
        )
      );
    }
    document.getElementById("apunte-dias").textContent =
      `${dias.length} días con datos, ${ventana7.length} en la última semana. ` +
      `Renfe cambia el identificador del tren cada día, ` +
      `así que estos días se agrupan por su número comercial, que es lo que se mantiene. ` +
      `Las medias se ponderan por paradas observadas.`;
  }

  // -- ultimo recorrido -------------------------------------------------------
  const cuerpoParadas = document.getElementById("cuerpo-paradas");
  try {
    const paradas = await (await fetch(`/api/trenes/${encodeURIComponent(id)}`)).json();
    cuerpoParadas.textContent = "";
    if (!paradas.length) {
      cuerpoParadas.appendChild(celda("sin recorrido registrado", "vacio")).colSpan = 4;
      return;
    }
    // Un trip_id es un solo dia (Renfe le cambia el prefijo cada dia), asi que
    // estas paradas son un unico recorrido.
    const recorrido = paradas.filter((p) => p.delay_s !== null && p.delay_s !== undefined);
    if (recorrido.length >= 2) {
      const corto = (nombre) => (nombre.length > 14 ? `${nombre.slice(0, 13)}…` : nombre);
      mostrarGrafica("figura-paradas", () =>
        graficaLinea(
          document.getElementById("g-paradas"),
          recorrido.map((p) => ({
            etiqueta: corto(p.estacion || p.stop_id),
            valor: Number(p.delay_s) / 60,
            detalle: `<strong>${escapar(p.estacion || p.stop_id)}</strong><br>` +
              `prevista ${hora(p.scheduled_arrival)} · real ${hora(p.arrival_time)}<br>` +
              `retraso ${minutos(p.delay_s)}`,
          })),
          { titulo: "Retraso en cada parada", formato: enMinutos, anchoEtiqueta: 96, alto: 230 }
        )
      );
    }
    for (const p of paradas.slice(0, 60)) {
      const fila = document.createElement("tr");
      fila.append(
        celda(p.estacion || p.stop_id),
        celda(hora(p.scheduled_arrival), "num"),
        celda(hora(p.arrival_time), "num"),
        celda(minutos(p.delay_s), "num"),
      );
      cuerpoParadas.appendChild(fila);
    }
  } catch (error) {
    cuerpoParadas.textContent = "";
    cuerpoParadas.appendChild(celda("no se ha podido cargar el recorrido", "vacio")).colSpan = 4;
    console.error(error);
  }
}

cargar();
