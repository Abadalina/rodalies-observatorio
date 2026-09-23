// Color oficial de cada linea, compartido por todas las paginas.
//
// El color lo publica Renfe en su horario, pero el del texto no sirve: pone
// blanco siempre, tambien sobre el lima de la R2N o el amarillo de la C5, donde
// no se lee. Aqui se elige blanco o casi negro segun cual contraste mas.
"use strict";

const Lineas = (() => {
  let peticion = null;
  const porNucleo = new Map(); // "51|R2N" -> "#D0DF00"
  const porNombre = new Map(); // "R2N" -> color, solo si el nombre es unico en toda Espana

  function cargar() {
    if (!peticion) {
      peticion = fetch("/api/colores")
        .then((r) => (r.ok ? r.json() : []))
        .then((filas) => {
          const vistos = new Map();
          for (const f of filas) {
            porNucleo.set(`${f.nucleo_id}|${f.linea}`, f.color);
            vistos.set(f.linea, vistos.has(f.linea) ? null : f.color);
          }
          // "C1" existe en seis nucleos con seis colores: sin nucleo no se
          // puede saber cual es, y es mejor el color neutro que uno equivocado.
          for (const [linea, color] of vistos) if (color) porNombre.set(linea, color);
        })
        .catch((error) => console.error(error));
    }
    return peticion;
  }

  function color(linea, nucleo) {
    if (nucleo && porNucleo.has(`${nucleo}|${linea}`)) return porNucleo.get(`${nucleo}|${linea}`);
    return porNombre.get(linea) || null;
  }

  // Luminancia relativa y contraste, como los define WCAG 2.
  function luminancia(hex) {
    const canal = (i) => {
      const c = parseInt(hex.slice(i, i + 2), 16) / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    };
    return 0.2126 * canal(1) + 0.7152 * canal(3) + 0.0722 * canal(5);
  }

  function textoSobre(hex) {
    const l = luminancia(hex);
    const contraBlanco = 1.05 / (l + 0.05);
    const contraOscuro = (l + 0.05) / (luminancia("#1b1a17") + 0.05);
    return contraBlanco >= contraOscuro ? "#ffffff" : "#1b1a17";
  }

  // Rellena una etiqueta de linea. Sin color conocido se queda con el estilo
  // por defecto de la hoja, que ya es legible en claro y en oscuro.
  function pintar(elemento, linea, nucleo) {
    elemento.textContent = linea;
    const c = color(linea, nucleo);
    if (c) {
      elemento.style.background = c;
      elemento.style.color = textoSobre(c);
    }
    return elemento;
  }

  function etiqueta(linea, nucleo) {
    const span = document.createElement("span");
    span.className = "linea";
    return pintar(span, linea, nucleo);
  }

  return { cargar, color, textoSobre, pintar, etiqueta };
})();
