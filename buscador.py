# -*- coding: utf-8 -*-
"""
EZHUB Ofertas — buscador automático (roda no GitHub Actions)
Varre o Promobit (categorias de hardware), extrai as ofertas novas e
alimenta o ofertas.json. O postar.py publica em seguida.
"""

import html as htmllib
import json
import os
import re
import time

import requests

AMAZON_TAG = "ezhub-20"
MAX_NOVAS_POR_RODADA = 12
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

CATEGORIAS = [
    "https://www.promobit.com.br/promocoes/hardware-perifericos/s/",
    "https://www.promobit.com.br/promocoes/hd-ssd/s/",
    "https://www.promobit.com.br/promocoes/processador/s/",
    "https://www.promobit.com.br/promocoes/placa-mae/s/",
    "https://www.promobit.com.br/promocoes/monitor/s/",
    "https://www.promobit.com.br/promocoes/teclado-mouse/s/",
    "https://www.promobit.com.br/promocoes/pc-gamer/s/",
    "https://www.promobit.com.br/promocoes/cooler/s/",
]

# Palavras que interessam ao público maker (filtro de relevância)
PALAVRAS_OK = [
    "ssd", "memória", "memoria", "ram", "ddr4", "ddr5", "placa de vídeo", "placa de video",
    "gpu", "rtx", "radeon", "geforce", "processador", "ryzen", "core i", "intel core",
    "placa mãe", "placa-mãe", "placa mae", "gabinete", "fonte", "cooler", "water cooler",
    "monitor", "teclado", "mouse", "headset", "mousepad", "nvme", "hd ", "pendrive",
    "cadeira gamer", "notebook", "pc gamer", "microfone", "webcam", "roteador", "kingston",
    "hyperx", "logitech", "redragon", "corsair", "asus", "gigabyte", "msi",
]

ARQ_OFERTAS = "ofertas.json"
ARQ_VISTAS = "vistas.json"


def fetch(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def achar_ofertas_listagem(html: str) -> list[str]:
    """Extrai URLs de ofertas de uma página de listagem."""
    urls = re.findall(r"https://www\.promobit\.com\.br/oferta/[a-zA-Z0-9\-]+-\d+", html)
    urls += [f"https://www.promobit.com.br{u}" for u in
             re.findall(r'href="(/oferta/[a-zA-Z0-9\-]+-\d+)"', html)]
    vistos, unicos = set(), []
    for u in urls:
        if u not in vistos:
            vistos.add(u)
            unicos.append(u)
    return unicos


def _buscar_url_loja(obj) -> str | None:
    """Procura recursivamente um campo de URL externa no JSON do Next.js."""
    if isinstance(obj, dict):
        for chave in ("offer_link", "offerLink", "link", "url", "store_url", "storeUrl"):
            v = obj.get(chave)
            if isinstance(v, str) and v.startswith("http") and "promobit" not in v:
                return v
        for v in obj.values():
            r = _buscar_url_loja(v)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _buscar_url_loja(v)
            if r:
                return r
    return None


def extrair_oferta(url_oferta: str) -> dict | None:
    html = fetch(url_oferta)

    # Título e preço via og:title: "Por R$ 439,00: Produto X"
    m = re.search(r'property="og:title" content="([^"]+)"', html)
    og_title = htmllib.unescape(m.group(1)) if m else ""
    m = re.search(r"Por (R\$\s?[\d.,]+):\s*(.+)", og_title.replace(" ", " "))
    if not m:
        return None
    preco, titulo = m.group(1).strip(), m.group(2).strip()

    # Preço antigo: primeiro R$ riscado no corpo (aparece como par "R$X R$Y")
    preco_antigo = ""
    m = re.search(r"R\$\s?([\d.]+,\d{2})R\$\s?([\d.]+,\d{2})", html.replace(" ", " "))
    if m:
        preco_antigo = f"R$ {m.group(1)}"

    # Cupom: meta description costuma citar "com cupom"
    cupom = ""
    m = re.search(r'name="description" content="[^"]*cupom[^"]*"', html)
    if m:
        m2 = re.search(r"\b([A-Z0-9]{5,20})\b.*?cupom|cupom.*?\b([A-Z0-9]{5,20})\b", html)
        # cupom aparece como texto isolado na página (ex.: MB20OFF)
        m3 = re.findall(r">([A-Z]{2,}[A-Z0-9]{3,15})<", html)
        candidatos = [c for c in m3 if c not in ("CNPJ", "CASH")]
        if candidatos:
            cupom = candidatos[0]

    # Loja
    loja_nome = ""
    m = re.search(r"Vendido por:\s*([^<\n]+)", html)
    if m:
        loja_nome = m.group(1).strip()

    # Link da loja via __NEXT_DATA__
    link_loja = ""
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if m:
        try:
            link_loja = _buscar_url_loja(json.loads(m.group(1))) or ""
        except Exception:
            pass

    # Resolver redirecionamento e detectar Amazon
    loja, url_final = "outra", link_loja or url_oferta
    if link_loja:
        try:
            r = requests.get(link_loja, headers=HEADERS, timeout=30, allow_redirects=True)
            url_final = r.url
        except Exception:
            url_final = link_loja
    asin = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", url_final)
    if "amazon.com.br" in url_final and asin:
        loja = "amazon"
        url_final = f"https://www.amazon.com.br/dp/{asin.group(1)}"

    return {
        "titulo": titulo[:120],
        "destaque": f"Vendido por {loja_nome}" if loja_nome else "",
        "preco": f"{preco} " if preco.endswith("à vista") else preco,
        "preco_antigo": preco_antigo,
        "cupom": cupom,
        "url": url_final,
        "loja": loja,
        "fonte": url_oferta,
    }


def relevante(titulo: str) -> bool:
    t = titulo.lower()
    return any(p in t for p in PALAVRAS_OK)


def main():
    with open(ARQ_OFERTAS, encoding="utf-8") as f:
        ofertas = json.load(f)
    vistas = set()
    if os.path.exists(ARQ_VISTAS):
        with open(ARQ_VISTAS, encoding="utf-8") as f:
            vistas = set(json.load(f))

    candidatas = []
    for cat in CATEGORIAS:
        try:
            candidatas += achar_ofertas_listagem(fetch(cat))
        except Exception as e:
            print(f"::warning::Falha na listagem {cat}: {e}")
        time.sleep(2)

    novas = [u for u in candidatas if u not in vistas]
    print(f"{len(candidatas)} ofertas encontradas, {len(novas)} novas")

    adicionadas = 0
    for url in novas:
        if adicionadas >= MAX_NOVAS_POR_RODADA:
            break
        vistas.add(url)
        try:
            oferta = extrair_oferta(url)
        except Exception as e:
            print(f"::warning::Falha ao extrair {url}: {e}")
            continue
        if not oferta:
            print(f"  (sem dados) {url}")
            continue
        if not relevante(oferta["titulo"]):
            print(f"  (irrelevante) {oferta['titulo'][:60]}")
            continue
        ofertas.append(oferta)
        adicionadas += 1
        print(f"  + {oferta['titulo'][:60]} | {oferta['preco']} | {oferta['loja']}")
        time.sleep(2)

    with open(ARQ_OFERTAS, "w", encoding="utf-8") as f:
        json.dump(ofertas, f, ensure_ascii=False, indent=2)
    with open(ARQ_VISTAS, "w", encoding="utf-8") as f:
        json.dump(sorted(vistas), f, ensure_ascii=False, indent=2)

    print(f"Adicionadas ao ofertas.json: {adicionadas}")


if __name__ == "__main__":
    main()
