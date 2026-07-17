# -*- coding: utf-8 -*-
"""
EZHUB Ofertas — robô de postagem v2
Novo formato: rodapé com teste grátis do Prime (comissão por cadastro)
e link de compartilhamento do canal.
"""

import json
import os
import re
import time

import requests

AMAZON_TAG = "ezhub-20"
CANAL_TELEGRAM = "@ezofertas"
LINK_CANAL_TG = "https://t.me/ezofertas"
LINK_PRIME = f"https://www.amazon.com.br/amazonprime?tag={AMAZON_TAG}"
LINK_CANAL_WA = ""  # preencher quando criar o Canal do WhatsApp
INTERVALO_SEGUNDOS = 8
MAX_POSTS_POR_RODADA = 10

ARQ_OFERTAS = "ofertas.json"
ARQ_WHATSAPP = "whatsapp_para_colar.md"

EMOJI_LOJA = {"amazon": "🛒", "ml": "🛒", "outra": "🛒"}


def montar_post(oferta: dict, formato: str) -> str:
    linhas = [f"🖥️ *{oferta['titulo']}*", ""]

    destaque = oferta.get("destaque", "")
    if destaque:
        for item in destaque.split(";"):
            item = item.strip()
            if item:
                linhas.append(f"🔹 {item}")
        linhas.append("")

    if oferta.get("preco_antigo"):
        linhas.append(f"❌ De: {oferta['preco_antigo']}")
    linhas.append(f"🔥 *{oferta['preco']}*")
    if oferta.get("cupom"):
        linhas.append(f"🎟️ Cupom: *{oferta['cupom']}*")

    linhas += ["", f"🛒 Compre aqui: {oferta['url']}", ""]

    # Rodapé fixo
    linhas.append(f"💙 Teste grátis Amazon Prime: {LINK_PRIME}")
    if formato == "whatsapp":
        linhas.append(f"✈️ Nosso canal no Telegram: {LINK_CANAL_TG}")
    else:
        linhas.append(f"📣 Compartilhe o canal: {LINK_CANAL_TG}")
        if LINK_CANAL_WA:
            linhas.append(f"💬 Prefere WhatsApp? {LINK_CANAL_WA}")

    return "\n".join(linhas)


def postar_telegram(texto: str) -> bool:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": CANAL_TELEGRAM,
            "text": texto,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False,
        },
        timeout=30,
    )
    if not (r.ok and r.json().get("ok")):
        print(f"::error::Falha no Telegram: {r.text[:300]}")
        return False
    return True


def main():
    with open(ARQ_OFERTAS, encoding="utf-8") as f:
        ofertas = json.load(f)

    pendentes = [o for o in ofertas if not o.get("postada")]
    print(f"{len(pendentes)} oferta(s) pendente(s)")

    publicadas = 0
    blocos_wa = []
    for oferta in pendentes[:MAX_POSTS_POR_RODADA]:
        post_tg = montar_post(oferta, "telegram")
        post_wa = montar_post(oferta, "whatsapp")

        if postar_telegram(post_tg):
            oferta["postada"] = True
            oferta["postada_em"] = time.strftime("%Y-%m-%d %H:%M")
            publicadas += 1
            blocos_wa.append(post_wa)
            print(f"✔ {oferta['titulo'][:60]}")
            time.sleep(INTERVALO_SEGUNDOS)

    if publicadas:
        with open(ARQ_OFERTAS, "w", encoding="utf-8") as f:
            json.dump(ofertas, f, ensure_ascii=False, indent=2)
        with open(ARQ_WHATSAPP, "a", encoding="utf-8") as f:
            for bloco in blocos_wa:
                f.write(f"\n---\n_{time.strftime('%d/%m %H:%M')}_\n\n```\n{bloco}\n```\n")

    print(f"Publicadas: {publicadas}")


if __name__ == "__main__":
    main()
