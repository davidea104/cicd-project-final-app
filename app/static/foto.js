// Reduce la foto de perfil a 256x256 (recorte centrado, JPEG) en el navegador y la sube.
(function () {
  "use strict";
  var form = document.getElementById("form-foto");
  var input = document.getElementById("f-foto");
  if (!form || !input || !window.DataTransfer) return;

  input.addEventListener("change", function () {
    var archivo = input.files && input.files[0];
    if (!archivo) return;
    var url = URL.createObjectURL(archivo);
    var img = new Image();
    img.onload = function () {
      var lado = Math.min(img.width, img.height);
      var canvas = document.createElement("canvas");
      canvas.width = canvas.height = 256;
      canvas.getContext("2d").drawImage(
        img, (img.width - lado) / 2, (img.height - lado) / 2, lado, lado, 0, 0, 256, 256
      );
      URL.revokeObjectURL(url);
      canvas.toBlob(function (blob) {
        var dt = new DataTransfer();
        dt.items.add(new File([blob], "perfil.jpg", { type: "image/jpeg" }));
        input.files = dt.files;
        form.submit();
      }, "image/jpeg", 0.85);
    };
    img.onerror = function () { URL.revokeObjectURL(url); form.submit(); };
    img.src = url;
  });
})();
