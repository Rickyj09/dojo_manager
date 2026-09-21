document.addEventListener("DOMContentLoaded", function () {
  const tipo = document.getElementById("tipo_descuento");
  const grupoCantidad = document.getElementById(
    "grupo_cantidad_minima"
  );
  const cantidad = document.getElementById("cantidad_minima");

  const porcentaje = document.getElementById(
    "porcentaje_descuento"
  );
  const valorFijo = document.getElementById(
    "valor_fijo_descuento"
  );

  function actualizarCantidadMinima() {
    if (!tipo || !grupoCantidad || !cantidad) {
      return;
    }

    const esHermanos = tipo.value === "HERMANOS";

    grupoCantidad.classList.toggle("d-none", !esHermanos);
    cantidad.disabled = !esHermanos;
    cantidad.required = esHermanos;

    if (esHermanos) {
      cantidad.min = "2";
    }
  }

  function actualizarModoDescuento() {
    if (!porcentaje || !valorFijo) {
      return;
    }

    const tienePorcentaje = porcentaje.value.trim() !== "";
    const tieneValorFijo = valorFijo.value.trim() !== "";

    if (tienePorcentaje && !tieneValorFijo) {
      valorFijo.disabled = true;
      porcentaje.disabled = false;
    } else if (tieneValorFijo && !tienePorcentaje) {
      porcentaje.disabled = true;
      valorFijo.disabled = false;
    } else {
      porcentaje.disabled = false;
      valorFijo.disabled = false;
    }
  }

  if (tipo) {
    tipo.addEventListener(
      "change",
      actualizarCantidadMinima
    );
  }

  if (porcentaje) {
    porcentaje.addEventListener(
      "input",
      actualizarModoDescuento
    );
  }

  if (valorFijo) {
    valorFijo.addEventListener(
      "input",
      actualizarModoDescuento
    );
  }

  actualizarCantidadMinima();
  actualizarModoDescuento();
});
