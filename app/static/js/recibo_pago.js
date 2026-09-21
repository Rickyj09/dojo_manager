document.addEventListener("DOMContentLoaded", function () {
  const botonImprimir = document.getElementById("btn-imprimir-recibo");

  if (botonImprimir) {
    botonImprimir.addEventListener("click", function () {
      window.print();
    });
  }
});
