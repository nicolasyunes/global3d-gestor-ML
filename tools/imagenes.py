"""Prepara fotos para MercadoLibre: quita fondo, fondo blanco, cuadrada 1200x1200.

Uso:
  python tools/imagenes.py preparar <url_o_archivo> [--sin-quitar-fondo] [--salida work/img]
  python tools/imagenes.py revisar <url_o_archivo>      # tamaño y si el fondo ya es claro

Las imágenes generadas quedan en work/img/ (no se suben a git).
"""
import hashlib
import io
import os
import sys

import requests
from PIL import Image, ImageStat

SIZE = 1200
MARGIN = 0.08  # 8% de aire alrededor del producto


def load(src):
    if src.startswith("http"):
        r = requests.get(src, timeout=60)
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content))
    return Image.open(src)


def borde_claro(img):
    g = img.convert("L")
    w, h = g.size
    tiras = [g.crop((0, 0, w, 10)), g.crop((0, h - 10, w, h)), g.crop((0, 0, 10, h)), g.crop((w - 10, 0, w, h))]
    return sum(ImageStat.Stat(t).mean[0] for t in tiras) / 4


def preparar(src, quitar=True, salida="work/img"):
    img = load(src)
    if quitar:
        from rembg import remove  # import tardío: es pesado
        img = remove(img)
    img = img.convert("RGBA")
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)
    lado = int(SIZE * (1 - 2 * MARGIN))
    img.thumbnail((lado, lado), Image.LANCZOS)
    lienzo = Image.new("RGB", (SIZE, SIZE), (255, 255, 255))
    lienzo.paste(img, ((SIZE - img.width) // 2, (SIZE - img.height) // 2), img)
    os.makedirs(salida, exist_ok=True)
    nombre = hashlib.md5(src.encode()).hexdigest()[:10] + ".jpg"
    ruta = os.path.join(salida, nombre)
    lienzo.save(ruta, "JPEG", quality=92)
    print(ruta)


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) < 2:
        sys.exit(__doc__)
    if a[0] == "preparar":
        sal = a[a.index("--salida") + 1] if "--salida" in a else "work/img"
        preparar(a[1], quitar="--sin-quitar-fondo" not in a, salida=sal)
    elif a[0] == "revisar":
        im = load(a[1])
        print({"ancho": im.width, "alto": im.height, "brillo_borde": round(borde_claro(im)),
               "fondo_blanco_probable": borde_claro(im) > 235, "minimo_ok": min(im.size) >= 500})
    else:
        sys.exit(__doc__)
