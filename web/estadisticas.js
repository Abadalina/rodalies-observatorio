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
  return d.toISOString().slice(0, 10);
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

const DIAS_SEMANA = ["lun", "mar", "mie", "jue", "vie", "sab", "dom"];

async function cargar() {
  const dias = Number(document.getElementById("dias").value);
  const nucleo = document.getElementById("ambito").value;
  const desde = fecha(-dias);
  const hasta = fecha(0);
  const ambito = nucleo ? `&nucleo=${nucleo}` : "";
  const base = `desde=${desde}&hasta=${hasta}${ambito}`;

  document.getElementById("periodo").textContent =
    `${nucleo ? "Catalunya" : "Toda Espana"} · del ${desde} al ${hasta}`;

  // -- cifras -----------------------------------------------------------------
  try {
    const r = await pedir(`/api/resumen?${base}`);
    document.getElementById("c-puntualidad").textContent =
      r.pct_puntualidad === null ? "—" : `${decimal.format(r.pct_puntualidad)} %`;
    document.getElementById("c-retraso").textContent = minutos(r.retraso_medio_s);
    document.getElementById("c-trenes").textContent = numero.format(Number(r.trenes || 0));
    document.getElementById("c-paradas").textContent = numero.format(Number(r.paradas || 0));
  } catch (error) {
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
      { titulo: "Puntualidad por dia" }
    );
  } catch (error) {
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
      .filter(([, v]) => v.paradas >= 100)
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
      { titulo: "Puntualidad por dia de la semana", alto: 200 }
    );
  } catch (error) {
    console.error(error);
  }

  // -- lineas -----------------------------------------------------------------
  const cuerpoLineas = document.getElementById("cuerpo-lineas");
  try {
    const lineas = (await pedir(`/api/lineas?${base}`)).filter(
      (l) => Number(l.paradas) >= 500 && l.pct_puntualidad !== null
    );
    if (!lineas.length) {
      vacio(cuerpoLineas, 6, "sin lineas con datos suficientes en este periodo");
    } else {
      cuerpoLineas.textContent = "";
      for (const l of lineas) {
        const pct = Number(l.pct_puntualidad);
        const fila = document.createElement("tr");

        const celdaLinea = document.createElement("td");
        const etiqueta = document.createElement("span");
        etiqueta.className = "linea";
        etiqueta.textContent = l.linea;
        celdaLinea.appendChild(etiqueta);

        // Barra dentro de la tabla: la longitud dice lo mismo que el numero de
        // al lado, pero se compara de un vistazo sin leer quince cifras.
        const celdaBarra = document.createElement("td");
        const carril = document.createElement("div");
        carril.className = "carril";
        const relleno = document.createElement("div");
        relleno.className = "carril-relleno";
        relleno.style.width = `${pct}%`;
        relleno.style.background = colorPorPuntualidad(pct);
        carril.appendChild(relleno);
        celdaBarra.appendChild(carril);

        fila.append(
          celdaLinea,
          celdaBarra,
          celda(`${decimal.format(pct)} %`, "num"),
          celda(minutos(l.retraso_medio_s), "num"),
          celda(numero.format(Number(l.trenes || 0)), "num"),
          celda(numero.format(Number(l.paradas)), "num")
        );
        cuerpoLineas.appendChild(fila);
      }
    }
  } catch (error) {
    vacio(cuerpoLineas, 6, "no se han podido cargar las lineas");
    console.error(error);
  }

  // -- estaciones -------------------------------------------------------------
  const cuerpoEstaciones = document.getElementById("cuerpo-estaciones");
  try {
    const estaciones = await pedir(`/api/estaciones?${base}&limite=15&minimo=200`);
    if (!estaciones.length) {
      vacio(cuerpoEstaciones, 4, "sin estaciones con datos suficientes");
    } else {
      cuerpoEstaciones.textContent = "";
      for (const e of estaciones) {
        const fila = document.createElement("tr");
        fila.append(
          celda(e.estacion || e.stop_id),
          celda(minutos(e.retraso_medio_s), "num"),
          celda(minutos(e.retraso_max_s), "num"),
          celda(numero.format(Number(e.paradas)), "num")
        );
        cuerpoEstaciones.appendChild(fila);
      }
    }
  } catch (error) {
    vacio(cuerpoEstaciones, 4, "no se han podido cargar las estaciones");
    console.error(error);
  }
}

document.getElementById("dias").addEventListener("change", cargar);
document.getElementById("ambito").addEventListener("change", cargar);
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
