# -*- coding: utf-8 -*-
"""
EZHUB Ofertas — buscador automático v2
Varre o Promobit (categorias de hardware) e alimenta o ofertas.json.
v2: se o acesso direto for bloqueado, usa o proxy de leitura r.jina.ai.
"""

import html as htmllib
import json
import os
import re
import time

import requests

AMAZON_TAG = "ezhub-20"
MAX_NOVAS_POR_RODADA = 10
TIMEOUT = 40
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept": "text/html,application/xhtml+xml",
}

CATEGORIAS = [
    "https://www.promobit.com.br/promocoes/hardware-perifericos/s/",
    "https://www.promobit.com.br/promocoes/hd-ssd/s/",
    "https://www.promobit.com.br/promocoes/processador/s/",
    "https://www.promobit.com.br/promocoes/monitor/s/",
]

PALAVRAS_OK = [
    "ssd", "memória", "memoria", "ram", "ddr4", "ddr5", "placa de vídeo", "placa de video",
    "gpu", "rtx", "radeon", "geforce", "processador", "ryzen", "core i", "intel core",
    "placa mãe", "placa-mãe", "placa mae", "gabinete", "fonte", "cooler", "water cooler",
    "monitor", "teclado", "mouse", "headset", "mousepad", "nvme", "hd ", "pendrive",
    "cadeira gamer", "notebook", "pc gamer", "microfone", "webcam", "roteador", "kingston",
    "hyperx", "logitech", "redragon", "corsair", "asus", "gigabyte", "msi", "placa asus",
]

ARQ_OFERTAS = "ofertas.json"
ARQ_VISTAS = "vistas.json"


def fetch(url: str) -> str:
    """Tenta acesso direto; se bloqueado, usa o proxy r.jina.ai pedindo HTML."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200 and len(r.text) > 5000:
            print(f"    [direto ok] {url}")
            return r.text
        print(f"    [direto falhou: HTTP {r.status_code}, {len(r.text)}b] {url}")
    except Exception as e:
        print(f"    [direto erro: {type(e).__name__}] {url}")

    # Fallback: proxy de leitura (contorna bloqueio de datacenter)
    try:
        r = requests.get(
            f"https://r.jina.ai/{url}",
            headers={"X-Return-Format": "html", "User-Agent": HEADERS["User-Agent"]},
            timeout=60,
        )
        if r.status_code == 200 and len(r.text) > 3000:
            print(f"    [proxy ok, {len(r.text)}b]")
            return r.text
        print(f"    [proxy falhou: HTTP {r.status_code}, {len(r.text)}b]")
    except Exception as e:
        print(f"    [proxy erro: {type(e).__name__}]")
    return ""


def achar_ofertas_listagem(html: str) -> list[str]:
    urls = re.findall(r"https://www\.promobit\.com\.br/oferta/[a-zA-Z0-9\-]+-\d+", html)
    urls += [f"https://www.promobit.com.br{u}" for u in
             re.findall(r'href="(/oferta/[a-zA-Z0-9\-]+-\d+)"', html)]
    vistos, unicos = set(), []
    for u in urls:
        if u not in vistos:
            vistos.add(u)
            unicos.append(u)
    return unicos


def _buscar_url_loja(obj):
    if isinstance(obj, dict):
        for chave in ("offer_link", "offerLink", "link", "url", "store_url", "storeUrl"):
            v = obj.get(chave)
            if isinstance(v, str) and v.startswith("http") and "promobit" not in v \
                    and "promoby" not in v and not v.endswith((".png", ".jpg", ".svg", ".webp")):
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
    if not html:
        return None
    texto = htmllib.unescape(html).replace(" ", " ")

    # Título e preço: "Por R$ 439,00: Produto X" (og:title ou <title>)
    m = re.search(r"Por (R\$ ?[\d.]+,\d{2}):\s*([^\"<|]+)", texto)
    if not m:
        print(f"    (não achei título/preço)")
        return None
    preco, titulo = m.group(1).strip(), m.group(2).strip()

    # Preço antigo: par "R$X R$Y" colado (riscado + atual)
    preco_antigo = ""
    m = re.search(r"R\$ ?([\d.]+,\d{2})\s*R\$ ?([\d.]+,\d{2})", texto)
    if m and m.group(2) in preco:
        preco_antigo = f"R$ {m.group(1)}"

    # Loja
    loja_nome = ""
    m = re.search(r"Vendido por:?\s*([A-Za-zÀ-ú0-9!&. ]{2,30})", texto)
    if m:
        loja_nome = m.group(1).strip()

    # Cupom: código em caixa alta isolado perto de "cupom"
    cupom = ""
    if "cupom" in texto.lower():
        m = re.search(r"[>\n\s]([A-Z][A-Z0-9]{4,15})[<\n\s].{0,600}?[Ii]r à loja", texto, re.S)
        if m:
            cupom = m.group(1)

    # Link da loja via __NEXT_DATA__ (quando temos HTML bruto)
    link_loja = ""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if m:
        try:
            link_loja = _buscar_url_loja(json.loads(m.group(1))) or ""
        except Exception:
            pass

    loja, url_final = "outra", ""
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

    if not url_final:
        url_final = url_oferta  # sem link direto: manda pra página da oferta

    return {
        "titulo": titulo[:120],
        "destaque": f"Vendido por {loja_nome}" if loja_nome else "",
        "preco": preco,
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
        print(f"Categoria: {cat}")
        html = fetch(cat)
        achadas = achar_ofertas_listagem(html) if html else []
        print(f"  -> {len(achadas)} ofertas na página")
        candidatas += achadas
        time.sleep(3)

    # dedupe mantendo ordem
    unicas = list(dict.fromkeys(candidatas))
    novas = [u for u in unicas if u not in vistas]
    print(f"\nTotal: {len(unicas)} ofertas, {len(novas)} novas")

    adicionadas = 0
    for url in novas:
        if adicionadas >= MAX_NOVAS_POR_RODADA:
            break
        vistas.add(url)
        print(f"  Extraindo: {url}")
        try:
            oferta = extrair_oferta(url)
        except Exception as e:
            print(f"    (erro: {type(e).__name__}: {e})")
            continue
        if not oferta:
            continue
        if not relevante(oferta["titulo"]):
            print(f"    (fora do filtro) {oferta['titulo'][:60]}")
            continue
        ofertas.append(oferta)
        adicionadas += 1
        print(f"    + {oferta['titulo'][:60]} | {oferta['preco']} | loja={oferta['loja']}")
        time.sleep(3)

    with open(ARQ_OFERTAS, "w", encoding="utf-8") as f:
        json.dump(ofertas, f, ensure_ascii=False, indent=2)
    with open(ARQ_VISTAS, "w", encoding="utf-8") as f:
        json.dump(sorted(vistas), f, ensure_ascii=False, indent=2)

    print(f"\nAdicionadas ao ofertas.json: {adicionadas}")


if __name__ == "__main__":
    main()
