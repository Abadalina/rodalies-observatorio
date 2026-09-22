// Pagina de estadisticas: pide los datos y llama a las graficas.
"use strict";

const numero = new Intl.NumberFormat("es-ES");
const decimal = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1 });

// La misma escala validada que usa el mapa. Cuatro bandas, no cinco: entre el
// verde y el rojo no caben cinco escalones distinguibles.
const oscuro = window.matchMedia("(prefers-color-scheme: dark)");
const ESCALA = {
  claro: { bien: "#15803d", medio: "#f59e0b", mal: "#b91c1c" },
  oscuro: { bien: "#30a865", medio: "#d9a12b", mal: "#e8635c" },
};

function colorPorPuntualidad(pct) {
  const c = oscuro.matches ? ESCALA.oscuro : ESCALA.claro;
  if (pct >= 60) return c.bien;
  if (pct >= 40) return c.medio;
  return c.mal;
}

function minutos(segundos) {
  if (segundos === null || segundos === undefined) return "—";
  const s = Math.round(Number(segundos));
  const signo = s < 0 ? "−" : "";
  const abs = Math.abs(s);
  return `${signo}${Math.floor(abs / 60)}:${String(abs % 60).padStart(2, "0")}`;
}

function fecha(desplazamiento) {
  const d = new Date();
  d.setDate(d.getDate() + desplazamiento);
  const ano = d.getFullYear();
  const mes = String(d.getMonth() + 1).padStart(2, "0");
  const dia = String(d.getDate()).padStart(2, "0");
  return `${ano}-${mes}-${dia}`;
}

function celda(texto, clase) {
  const td = document.createElement("td");
  if (clase) td.className = clase;
  td.textContent = texto;
  return td;
}

function vacio(cuerpo, columnas, texto) {
  cuerpo.textContent = "";
  const fila = document.createElement("tr");
  const td = celda(texto, "vacio");
  td.colSpan = columnas;
  fila.appendChild(td);
  cuerpo.appendChild(fila);
}

async function pedir(ruta) {
  const r = await fetch(ruta);
  if (!r.ok) throw new Error(`${ruta}: HTTP ${r.status}`);
  return r.json();
}

const DIAS_SEMANA = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"];
let estacionesCargadas = [];

function cambiarEstado(tipo, texto) {
  const punto = document.getElementById("punto-datos");
  punto.className = `punto${tipo ? ` punto--${tipo}` : ""}`;
  document.getElementById("texto-estado").textContent = texto;
}

function normalizar(texto) {
  return String(texto || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function renderEstaciones() {
  const cuerpo = document.getElementById("cuerpo-estaciones");
  const termino = normalizar(document.getElementById("buscar-estacion").value.trim());
  const visibles = termino
    ? estacionesCargadas.filter((e) => normalizar(`${e.estacion} ${e.stop_id}`).includes(termino))
    : estacionesCargadas;

  document.getElementById("total-estaciones").textContent = termino
    ? `${numero.format(visibles.length)} de ${numero.format(estacionesCargadas.length)} estaciones`
    : `${numero.format(estacionesCargadas.length)} estaciones con datos`;

  if (!visibles.length) {
    vacio(cuerpo, 5, termino ? "ninguna estación coincide con la búsqueda" : "sin estaciones con datos");
    return;
  }

  cuerpo.textContent = "";
  for (const e of visibles) {
    const fila = document.createElement("tr");
    const puntualidad = e.pct_puntualidad === null
      ? "—"
      : `${decimal.format(Number(e.pct_puntualidad))} %`;
    fila.append(
      celda(e.estacion || e.stop_id),
      celda(puntualidad, "num"),
      celda(minutos(e.retraso_medio_s), "num"),
      celda(minutos(e.retraso_max_s), "num"),
      celda(numero.format(Number(e.paradas)), "num")
    );
    cuerpo.appendChild(fila);
  }
}

async function cargar() {
  cambiarEstado("", "Actualizando estadísticas…");
  let fallos = 0;
  const dias = Number(document.getElementById("dias").value);
  const selectorAmbito = document.getElementById("ambito");
  const nucleo = selectorAmbito.value;
  const nombreAmbito = selectorAmbito.options[selectorAmbito.selectedIndex].text;
  const desde = fecha(-dias);
  const hasta = fecha(0);
  const ambito = nucleo ? `&nucleo=${nucleo}` : "";
  const base = `desde=${desde}&hasta=${hasta}${ambito}`;

  document.getElementById("periodo").textContent =
    `${nombreAmbito} · del ${desde} al ${hasta}`;

  // -- cifras -----------------------------------------------------------------
  try {
    const r = await pedir(`/api/resumen?${base}`);
    document.getElementById("c-puntualidad").textContent =
      r.pct_puntualidad === null ? "—" : `${decimal.format(r.pct_puntualidad)} %`;
    document.getElementById("c-retraso").textContent = minutos(r.retraso_medio_s);
    document.getElementById("c-graves").textContent =
      r.pct_muy_tarde === null ? "—" : `${decimal.format(r.pct_muy_tarde)} %`;
    document.getElementById("c-suprimidas").textContent = numero.format(Number(r.suprimidas || 0));
    document.getElementById("c-trenes").textContent = numero.format(Number(r.trenes || 0));
    document.getElementById("c-paradas").textContent = numero.format(Number(r.paradas || 0));
    document.getElementById("c-lineas").textContent = numero.format(Number(r.lineas || 0));
    document.getElementById("c-dias").textContent = numero.format(Number(r.dias || 0));
  } catch (error) {
    fallos += 1;
    console.error(error);
  }

  // -- puntualidad dia a dia --------------------------------------------------
  try {
    const kpi = await pedir(`/api/kpi?${base}`);
    graficaLinea(
      document.getElementById("g-dias"),
      kpi
        .filter((d) => d.pct_puntualidad !== null)
        .map((d) => ({
          etiqueta: new Date(`${d.service_date}T12:00:00`).toLocaleDateString("es-ES", {
            day: "numeric",
            month: "short",
          }),
          valor: Number(d.pct_puntualidad),
          detalle:
            `<strong>${new Date(`${d.service_date}T12:00:00`).toLocaleDateString("es-ES", {
              weekday: "long",
              day: "numeric",
              month: "long",
            })}</strong><br>` +
            `${decimal.format(d.pct_puntualidad)} % puntuales<br>` +
            `retraso medio ${minutos(d.retraso_medio_s)}<br>` +
            `${numero.format(Number(d.trenes))} trenes`,
        })),
      { titulo: "Puntualidad por día" }
    );
  } catch (error) {
    fallos += 1;
    console.error(error);
  }

  // -- por hora ---------------------------------------------------------------
  try {
    const franjas = await pedir(`/api/franjas?${base}`);
    const porHora = new Map();
    for (const f of franjas) {
      const h = Number(f.hora);
      const acumulado = porHora.get(h) || { paradas: 0, suma: 0 };
      const paradas = Number(f.paradas || 0);
      acumulado.paradas += paradas;
      acumulado.suma += Number(f.pct_puntualidad || 0) * paradas;
      porHora.set(h, acumulado);
    }
    const datos = [...porHora.entries()]
      .sort((a, b) => a[0] - b[0])
      .filter(([, v]) => v.paradas > 0)
      .map(([h, v]) => {
        const pct = v.suma / v.paradas;
        return {
          etiqueta: `${h}h`,
          valor: pct,
          color: colorPorPuntualidad(pct),
          detalle: `<strong>${String(h).padStart(2, "0")}:00</strong><br>` +
            `${decimal.format(pct)} % puntuales<br>${numero.format(v.paradas)} paradas`,
        };
      });
    graficaBarras(document.getElementById("g-horas"), datos, { titulo: "Puntualidad por hora" });
  } catch (error) {
    fallos += 1;
    console.error(error);
  }

  // -- por dia de la semana ---------------------------------------------------
  try {
    const semana = await pedir(`/api/semana?${base}`);
    graficaBarras(
      document.getElementById("g-semana"),
      semana
        .filter((d) => d.pct_puntualidad !== null)
        .map((d) => {
          const pct = Number(d.pct_puntualidad);
          return {
            etiqueta: DIAS_SEMANA[Number(d.dia_semana) - 1] || d.dia_semana,
            valor: pct,
            color: colorPorPuntualidad(pct),
            detalle: `<strong>${DIAS_SEMANA[Number(d.dia_semana) - 1]}</strong><br>` +
              `${decimal.format(pct)} % puntuales<br>` +
              `retraso medio ${minutos(d.retraso_medio_s)}`,
          };
        }),
      { titulo: "Puntualidad por día de la semana", alto: 200 }
    );
  } catch (error) {
    fallos += 1;
    console.error(error);
  }

  // -- lineas -----------------------------------------------------------------
  const cuerpoLineas = document.getElementById("cuerpo-lineas");
  try {
    const lineas = await pedir(`/api/lineas?${base}`);
    document.getElementById("total-lineas").textContent =
      `${numero.format(lineas.length)} líneas`;
    if (!lineas.length) {
      vacio(cuerpoLineas, 8, "sin líneas con datos en este período");
    } else {
      cuerpoLineas.textContent = "";
      for (const l of lineas) {
        const pct = l.pct_puntualidad === null ? null : Number(l.pct_puntualidad);
        const paradas = Number(l.paradas || 0);
        const fila = document.createElement("tr");
        if (paradas < 500) fila.classList.add("muestra-baja");

        const celdaLinea = document.createElement("td");
        const etiqueta = document.createElement("span");
        etiqueta.className = "linea";
        etiqueta.textContent = l.linea;
        celdaLinea.appendChild(etiqueta);
        if (paradas < 500) {
          const aviso = document.createElement("span");
          aviso.className = "aviso-muestra";
          aviso.textContent = "muestra pequeña";
          celdaLinea.appendChild(aviso);
        }

        // Barra dentro de la tabla: la longitud dice lo mismo que el numero de
        // al lado, pero se compara de un vistazo sin leer quince cifras.
        const celdaBarra = document.createElement("td");
        const carril = document.createElement("div");
        carril.className = "carril";
        const relleno = document.createElement("div");
        relleno.className = "carril-relleno";
        relleno.style.width = `${pct ?? 0}%`;
        if (pct !== null) relleno.style.background = colorPorPuntualidad(pct);
        carril.appendChild(relleno);
        celdaBarra.appendChild(carril);

        fila.append(
          celdaLinea,
          celdaBarra,
          celda(pct === null ? "—" : `${decimal.format(pct)} %`, "num"),
          celda(minutos(l.retraso_medio_s), "num"),
          celda(
            l.pct_muy_tarde === null ? "—" : `${decimal.format(Number(l.pct_muy_tarde))} %`,
            "num"
          ),
          celda(numero.format(Number(l.suprimidas || 0)), "num"),
          celda(numero.format(Number(l.trenes || 0)), "num"),
          celda(numero.format(paradas), "num")
        );
        cuerpoLineas.appendChild(fila);
      }
    }
  } catch (error) {
    fallos += 1;
    vacio(cuerpoLineas, 8, "no se han podido cargar las líneas");
    console.error(error);
  }

  // -- estaciones -------------------------------------------------------------
  const cuerpoEstaciones = document.getElementById("cuerpo-estaciones");
  try {
    estacionesCargadas = await pedir(`/api/estaciones?${base}&limite=2000&minimo=1`);
    renderEstaciones();
  } catch (error) {
    fallos += 1;
    estacionesCargadas = [];
    vacio(cuerpoEstaciones, 5, "no se han podido cargar las estaciones");
    console.error(error);
  }

  const hora = new Date().toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
  cambiarEstado(
    fallos ? "mal" : "bien",
    fallos ? `Carga parcial: ${fallos} bloques no han respondido` : `Datos actualizados a las ${hora}`
  );
}

document.getElementById("dias").addEventListener("change", cargar);
document.getElementById("ambito").addEventListener("change", cargar);
document.getElementById("buscar-estacion").addEventListener("input", renderEstaciones);
oscuro.addEventListener("change", cargar);
// Las graficas se dibujan al ancho del contenedor, asi que al cambiar de tamaño
// hay que rehacerlas; se espera a que el usuario suelte para no redibujar cien
// veces mientras arrastra.
let redibujo = null;
window.addEventListener("resize", () => {
  clearTimeout(redibujo);
  redibujo = setTimeout(cargar, 250);
});

cargar();
