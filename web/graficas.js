// Graficas en SVG, escritas a mano.
//
// Sin libreria a proposito: la politica de contenido de la pagina solo deja
// cargar scripts del propio dominio, y traerse doscientos kilobytes de libreria
// para dibujar una linea y unas barras no sale a cuenta.
//
// Reglas que se siguen en las dos formas:
//   - una sola serie por grafica, asi que no hace falta leyenda: el titulo dice
//     que se esta mirando;
//   - rejilla y ejes en gris tenue, que no compitan con el dato;
//   - capa de hover siempre, porque una grafica en una pagina web puede tenerla
//     y sin ella no se puede leer un valor concreto;
//   - los numeros no se escriben sobre cada punto, solo en los extremos.
"use strict";

const SVG = "http://www.w3.org/2000/svg";

function crear(nombre, atributos = {}) {
  const nodo = document.createElementNS(SVG, nombre);
  for (const [clave, valor] of Object.entries(atributos)) {
    nodo.setAttribute(clave, valor);
  }
  return nodo;
}

function globo(contenedor) {
  const caja = document.createElement("div");
  caja.className = "globo";
  caja.hidden = true;
  contenedor.appendChild(caja);
  return {
    mostrar(x, y, html) {
      caja.innerHTML = html;
      caja.hidden = false;
      const ancho = caja.offsetWidth;
      const limite = contenedor.clientWidth;
      caja.style.left = `${Math.min(Math.max(x - ancho / 2, 4), limite - ancho - 4)}px`;
      caja.style.top = `${y}px`;
    },
    ocultar() {
      caja.hidden = true;
    },
  };
}

// Escala del eje Y. Por defecto es de porcentaje, entre 0 y 100, como la usan
// las estadisticas. Con `opciones.formato` la escala es libre (minutos, por
// ejemplo): se redondea a un paso "bonito" y el cero siempre queda dentro,
// porque un eje de retraso que no empieza en cero exagera las diferencias.
function pasoBonito(bruto) {
  const potencia = 10 ** Math.floor(Math.log10(bruto || 1));
  const n = bruto / potencia;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * potencia;
}

function rangoY(valores, opciones, porcentajeConMargen) {
  if (!opciones.formato) {
    return { ...porcentajeConMargen, texto: (v) => `${Math.round(v)}%` };
  }
  const bajo = Math.min(0, ...valores);
  const alto = Math.max(...valores, bajo + 1);
  // Cuatro tramos de un paso bonito, y no el maximo redondeado partido en
  // cuatro: eso daba marcas de "3,75 min" y "11,25 min".
  let paso = pasoBonito((alto - bajo) / 4);
  let min = Math.floor(bajo / paso) * paso;
  while (min + 4 * paso < alto) {
    paso = pasoBonito(paso * 1.5);
    min = Math.floor(bajo / paso) * paso;
  }
  return { min, max: min + 4 * paso, texto: opciones.formato };
}

/**
 * Grafica de linea para una serie temporal.
 * datos: [{ etiqueta, valor, detalle }]
 */
function graficaLinea(contenedor, datos, opciones = {}) {
  contenedor.textContent = "";
  if (!datos.length) {
    contenedor.innerHTML = '<p class="vacio">sin datos en este periodo</p>';
    return;
  }

  const ancho = contenedor.clientWidth || 720;
  const alto = opciones.alto || 260;
  const margen = { arriba: 18, derecha: 16, abajo: 34, izquierda: 42 };
  const w = ancho - margen.izquierda - margen.derecha;
  const h = alto - margen.arriba - margen.abajo;

  const valores = datos.map((d) => d.valor);
  const { min, max, texto } = rangoY(valores, opciones, {
    max: Math.min(100, Math.ceil(Math.max(...valores) / 10) * 10 + 5),
    min: Math.max(0, Math.floor(Math.min(...valores) / 10) * 10 - 5),
  });
  const escalaX = (i) => (datos.length === 1 ? w / 2 : (i / (datos.length - 1)) * w);
  const escalaY = (v) => h - ((v - min) / (max - min || 1)) * h;

  const svg = crear("svg", {
    viewBox: `0 0 ${ancho} ${alto}`,
    width: "100%",
    height: alto,
    role: "img",
    "aria-label": opciones.titulo || "grafica",
  });
  const g = crear("g", { transform: `translate(${margen.izquierda},${margen.arriba})` });
  svg.appendChild(g);

  // Rejilla horizontal y su eje.
  for (let i = 0; i <= 4; i++) {
    const v = min + ((max - min) * i) / 4;
    const y = escalaY(v);
    g.appendChild(crear("line", { class: "rejilla", x1: 0, x2: w, y1: y, y2: y }));
    const t = crear("text", { class: "marca-eje", x: -8, y: y + 4, "text-anchor": "end" });
    t.textContent = texto(v);
    g.appendChild(t);
  }

  // Area bajo la linea, muy suave: da volumen sin tapar la rejilla.
  const puntos = datos.map((d, i) => `${escalaX(i)},${escalaY(d.valor)}`);
  g.appendChild(crear("path", {
    class: "area",
    d: `M0,${Math.min(h, escalaY(Math.max(min, 0)))} L${puntos.join(" L")} ` +
       `L${w},${Math.min(h, escalaY(Math.max(min, 0)))} Z`,
  }));
  g.appendChild(crear("path", { class: "linea-serie", d: `M${puntos.join(" L")}` }));

  // Etiquetas del eje X: solo las que caben, nunca todas encimadas.
  // La primera y la ultima se ponen siempre, alineadas hacia dentro para no
  // salirse de la caja. Alineadas asi ocupan hueco y medio, de modo que la
  // vecina de cada una se salta si le queda mas cerca: si no, se pisaban.
  const cada = Math.max(1, Math.ceil(datos.length / (w / (opciones.anchoEtiqueta || 64))));
  const ultima = datos.length - 1;
  datos.forEach((d, i) => {
    const extremo = i === 0 || i === ultima;
    if (!extremo && (i % cada || i < 1.5 * cada || ultima - i < 1.5 * cada)) return;
    const ancla = datos.length > 1 && i === 0 ? "start" : i === ultima && i > 0 ? "end" : "middle";
    const t = crear("text", {
      class: "marca-eje",
      x: escalaX(i),
      y: h + 22,
      "text-anchor": ancla,
    });
    t.textContent = d.etiqueta;
    g.appendChild(t);
  });

  datos.forEach((d, i) => {
    g.appendChild(crear("circle", {
      class: "punto-serie",
      cx: escalaX(i),
      cy: escalaY(d.valor),
      r: 3.5,
    }));
  });

  // Capa de hover: una guia vertical y un globo con el valor exacto.
  const guia = crear("line", { class: "guia", y1: 0, y2: h, x1: 0, x2: 0, opacity: 0 });
  const foco = crear("circle", { class: "foco", r: 6, opacity: 0 });
  g.appendChild(guia);
  g.appendChild(foco);

  const burbuja = globo(contenedor);
  const zona = crear("rect", { x: 0, y: 0, width: w, height: h, fill: "transparent" });
  g.appendChild(zona);

  svg.addEventListener("pointermove", (e) => {
    const caja = svg.getBoundingClientRect();
    const escala = ancho / caja.width;
    const x = (e.clientX - caja.left) * escala - margen.izquierda;
    const i = Math.max(0, Math.min(datos.length - 1, Math.round((x / w) * (datos.length - 1))));
    const d = datos[i];
    guia.setAttribute("x1", escalaX(i));
    guia.setAttribute("x2", escalaX(i));
    guia.setAttribute("opacity", 1);
    foco.setAttribute("cx", escalaX(i));
    foco.setAttribute("cy", escalaY(d.valor));
    foco.setAttribute("opacity", 1);
    burbuja.mostrar(
      (escalaX(i) + margen.izquierda) / escala,
      (escalaY(d.valor) + margen.arriba) / escala - 14,
      d.detalle
    );
  });

  svg.addEventListener("pointerleave", () => {
    guia.setAttribute("opacity", 0);
    foco.setAttribute("opacity", 0);
    burbuja.ocultar();
  });

  contenedor.appendChild(svg);
}

/**
 * Grafica de barras verticales.
 * datos: [{ etiqueta, valor, detalle, color }]
 */
function graficaBarras(contenedor, datos, opciones = {}) {
  contenedor.textContent = "";
  if (!datos.length) {
    contenedor.innerHTML = '<p class="vacio">sin datos en este periodo</p>';
    return;
  }

  const ancho = contenedor.clientWidth || 720;
  const alto = opciones.alto || 240;
  const margen = { arriba: 18, derecha: 12, abajo: 34, izquierda: 42 };
  const w = ancho - margen.izquierda - margen.derecha;
  const h = alto - margen.arriba - margen.abajo;
  const valores = datos.map((d) => Math.max(0, d.valor));
  const { max, texto } = rangoY(valores, opciones, {
    min: 0,
    max: Math.min(100, Math.ceil(Math.max(...valores) / 10) * 10 + 5),
  });

  const svg = crear("svg", {
    viewBox: `0 0 ${ancho} ${alto}`,
    width: "100%",
    height: alto,
    role: "img",
    "aria-label": opciones.titulo || "grafica",
  });
  const g = crear("g", { transform: `translate(${margen.izquierda},${margen.arriba})` });
  svg.appendChild(g);

  for (let i = 0; i <= 4; i++) {
    const v = (max * i) / 4;
    const y = h - (v / max) * h;
    g.appendChild(crear("line", { class: "rejilla", x1: 0, x2: w, y1: y, y2: y }));
    const t = crear("text", { class: "marca-eje", x: -8, y: y + 4, "text-anchor": "end" });
    t.textContent = texto(v);
    g.appendChild(t);
  }

  // Dos pixeles de aire entre barras: sin ellos dos barras contiguas del mismo
  // color se leen como una sola mancha.
  const paso = w / datos.length;
  const anchoBarra = Math.max(2, paso - 3);
  const burbuja = globo(contenedor);

  datos.forEach((d, i) => {
    const x = i * paso + (paso - anchoBarra) / 2;
    const altura = Math.max(1, (Math.max(0, d.valor) / max) * h);
    const barra = crear("rect", {
      class: "barra",
      x,
      y: h - altura,
      width: anchoBarra,
      height: altura,
      rx: Math.min(4, anchoBarra / 2),
    });
    // Como estilo y no como atributo `fill`: la regla .barra de la hoja gana a
    // un atributo de presentacion, y las barras salian todas del color de serie.
    if (d.color) barra.style.fill = d.color;
    barra.addEventListener("pointerenter", () => {
      burbuja.mostrar(x + anchoBarra / 2 + margen.izquierda, h - altura + margen.arriba - 12, d.detalle);
      barra.classList.add("barra--activa");
    });
    barra.addEventListener("pointerleave", () => {
      burbuja.ocultar();
      barra.classList.remove("barra--activa");
    });
    g.appendChild(barra);

    if (!(i % Math.max(1, Math.ceil(datos.length / (w / 34))))) {
      const t = crear("text", {
        class: "marca-eje",
        x: x + anchoBarra / 2,
        y: h + 22,
        "text-anchor": "middle",
      });
      t.textContent = d.etiqueta;
      g.appendChild(t);
    }
  });

  contenedor.appendChild(svg);
}
