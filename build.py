#!/usr/bin/env python3
"""Gerador estático do site da Garopaba Loca Fácil.

Uso:
    python build.py            # build de produção em dist/
    python build.py --dev      # mostra dados pendentes e avaliações de exemplo
    SITE_URL=https://seudominio.com.br python build.py

Sem dependências: apenas a biblioteca padrão do Python 3.9+.
"""
import datetime
import html
import json
import os
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / "content"
STATIC = ROOT / "static"
DIST = ROOT / "dist"

DEV = "--dev" in sys.argv
# NOINDEX=1: cópia de teste (ex.: GitHub Pages) que não deve aparecer no Google.
NOINDEX = DEV or os.environ.get("NOINDEX") == "1"
ASSET_VERSION = datetime.datetime.now().strftime("%Y%m%d%H%M")


def load(name):
    with open(CONTENT / name, encoding="utf-8") as f:
        return json.load(f)


WARNINGS = []


def load_optional(name, key):
    try:
        return load(name).get(key) or []
    except FileNotFoundError:
        return []


# --------------------------------------------------------------------------- normalização
# O painel (/admin) grava strings vazias, "confirmar", textos com várias linhas etc.
# Aqui tudo vira o formato que o site espera, para nenhum campo em branco quebrar o build.

def blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def paragraphs(value):
    """Lista de parágrafos a partir de uma lista ou de um texto separado por linhas em branco."""
    if blank(value):
        return None
    if isinstance(value, list):
        items = [p.strip() for p in value if not blank(p)]
    else:
        items = [p.strip().replace("\n", " ") for p in str(value).split("\n\n") if p.strip()]
    return items or None


def slugify(text):
    import unicodedata
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def image_size(path):
    """Largura e altura lidas do cabeçalho do arquivo (WebP, PNG ou JPEG), sem bibliotecas."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        kind = data[12:16]
        if kind == b"VP8X":
            return 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
        if kind == b"VP8 ":
            return int.from_bytes(data[26:28], "little") & 0x3FFF, int.from_bytes(data[28:30], "little") & 0x3FFF
        if kind == b"VP8L":
            b = int.from_bytes(data[21:25], "little")
            return (b & 0x3FFF) + 1, ((b >> 14) & 0x3FFF) + 1
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data[:2] == b"\xff\xd8":
        i = 2
        while i < len(data) - 9:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
            i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    return None


def normalize_vehicle(v):
    v = dict(v)
    for key in ("versao", "resumo", "combustivel", "carroceria", "cor_ilustracao"):
        if blank(v.get(key)):
            v[key] = None
    v["cambio"] = v.get("cambio") if v.get("cambio") in ("manual", "automatico") else None
    ar = v.get("ar_condicionado")
    v["ar_condicionado"] = True if ar in (True, "sim") else False if ar in (False, "nao") else None
    for key in ("preco_diaria", "porta_malas_litros", "passageiros"):
        val = v.get(key)
        v[key] = None if blank(val) else int(float(val))
    v["passageiros"] = v["passageiros"] or 5
    v["destaques_empresa"] = [t for t in (v.get("destaques_empresa") or []) if not blank(t)]
    v["resumo"] = v["resumo"] or ""
    v["carroceria"] = v["carroceria"] or "hatch"
    v["destaque_home"] = bool(v.get("destaque_home"))
    if blank(v.get("slug")):
        v["slug"] = slugify(" ".join(x for x in [v.get("marca"), v.get("modelo"), v.get("versao")] if x))
    imgs = []
    for img in v.get("imagens") or []:
        if isinstance(img, str):
            img = {"src": img}
        if blank(img.get("src")):
            continue
        img = dict(img)
        img["src"] = img["src"].lstrip("/")
        if blank(img.get("alt")):
            img["alt"] = f"{v.get('marca', '')} {v.get('modelo', '')}".strip()
        if blank(img.get("foco")):
            img["foco"] = "50% 72%"
        if not img.get("w") or not img.get("h"):
            size = image_size(STATIC / img["src"])
            if size:
                img["w"], img["h"] = size
            else:
                WARNINGS.append(f"Foto não encontrada: {img['src']}")
                continue
        imgs.append(img)
    v["imagens"] = imgs
    return v


def normalize_company(c):
    c = dict(c)
    c["whatsapp"] = re.sub(r"\D", "", str(c.get("whatsapp", "")))
    c["telefone_e164"] = "+" + c["whatsapp"]
    for key in ("email", "horarios", "google_perfil_url", "google_avaliacoes_url", "site_url"):
        if blank(c.get(key)):
            c[key] = None
    c["sobre"] = paragraphs(c.get("sobre")) or []
    c["historia"] = paragraphs(c.get("historia"))
    c["diferenciais"] = [d for d in (c.get("diferenciais") or []) if not blank(d)]
    c["politicas"] = {k: (None if blank(val) else val) for k, val in (c.get("politicas") or {}).items()}
    c["area_atendida"] = c.get("area_atendida") or "Garopaba e região"
    return c


EMP = normalize_company(load("empresa.json"))
FLEET = [normalize_vehicle(v) for v in load("veiculos.json")["veiculos"]]
_vistos = set()
for _v in FLEET:  # dois carros com o mesmo nome ganham endereços diferentes
    _base, _n = _v["slug"], 2
    while _v["slug"] in _vistos:
        _v["slug"] = f"{_base}-{_n}"
        _n += 1
    _vistos.add(_v["slug"])
FAQ = [{**q, "resposta": None if blank(q.get("resposta")) else q["resposta"]} for q in load("faq.json")["perguntas"]]
REVIEWS_ALL = [{**r, "data": None if blank(r.get("data")) else r["data"]} for r in load("avaliacoes.json")["avaliacoes"]]
AVISOS = [a for a in load_optional("avisos.json", "avisos") if a.get("ativo") and not blank(a.get("texto"))]
PRAIAS = [p for p in load_optional("praias.json", "praias") if not blank(p.get("nome")) and not blank(p.get("texto"))]

SITE_URL = (os.environ.get("SITE_URL") or EMP.get("site_url") or "http://localhost:8000").rstrip("/")
GSC_TOKEN = os.environ.get("GOOGLE_SITE_VERIFICATION", "")
# Subpasta onde o site é servido (ex.: "/locafacil" no GitHub Pages de projeto). Vazio = raiz do domínio.
BASE_PATH = "/" + os.environ.get("BASE_PATH", "").strip("/") if os.environ.get("BASE_PATH", "").strip("/") else ""

e = html.escape


# --------------------------------------------------------------------------- helpers

def brl(value):
    return f"R$ {value:,.0f}".replace(",", ".")


def pending(dev_label, prod=""):
    """Dado ainda não fornecido: marcado no --dev, omitido ou neutro em produção."""
    if DEV:
        return f'<mark class="pending" title="Dado pendente: substituir antes de publicar">PENDENTE · {e(dev_label)}</mark>'
    return prod


def wa_url(message=None):
    url = f"https://wa.me/{EMP['whatsapp']}"
    return url + ("?text=" + quote(message) if message else "")


def full_address():
    a = EMP["endereco"]
    return f"{a['logradouro']} – {a['bairro']}, {a['cidade']} – {a['uf']}, {a['cep']}"


def maps_url():
    return "https://www.google.com/maps/search/?api=1&query=" + quote(
        f"{EMP['nome']}, {full_address()}"
    )


def vehicle_name(v):
    return " ".join(x for x in [v["marca"], v["modelo"], v["versao"]] if x)


def luggage_class(v):
    litros = v.get("porta_malas_litros")
    if not litros:
        return None
    if litros <= 240:
        return "pequena"
    if litros <= 320:
        return "media"
    return "grande"


MIN_REVIEWS_FOR_AVERAGE = 3  # abaixo disso, uma "média" diz pouco e não é exibida

LUGGAGE_LABEL = {"pequena": "Pequena", "media": "Média", "grande": "Grande"}


def published_reviews():
    return [r for r in REVIEWS_ALL if r.get("verificada") and r.get("autorizada") and not r.get("exemplo")]


def visible_reviews():
    pub = published_reviews()
    if DEV:
        return pub + [r for r in REVIEWS_ALL if r.get("exemplo")]
    return pub


# --------------------------------------------------------------------------- icons

ICON_PATHS = {
    "arrow": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "shield": '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z"/><path d="m9 12 2 2 4-4"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "pin": '<path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/>',
    "phone": '<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M18 14a6 6 0 0 1 3.5 6"/>',
    "gear": '<circle cx="6" cy="5" r="1.6"/><circle cx="12" cy="5" r="1.6"/><circle cx="18" cy="5" r="1.6"/><circle cx="6" cy="19" r="1.6"/><circle cx="12" cy="19" r="1.6"/><path d="M6 6.6v10.8M12 6.6v10.8M18 6.6V12H6"/>',
    "snow": '<path d="M12 2v20M3.3 7l17.4 10M20.7 7 3.3 17M9 4l3 2 3-2M9 20l3-2 3 2"/>',
    "bag": '<rect x="4" y="7" width="16" height="13" rx="2"/><path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M9 11v5M15 11v5"/>',
    "fuel": '<path d="M4 21V5a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v16M3 21h12M4 10h10M14 8h3l3 3v7a1.5 1.5 0 0 1-3 0v-3h-3"/>',
    "store": '<path d="M3 9l1.5-5h15L21 9M4 9v11h16V9M3 9h18M9 20v-6h6v6"/>',
    "key": '<circle cx="7.5" cy="15.5" r="3.5"/><path d="m10 13 9-9M15 8l3 3"/>',
    "file": '<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8l-5-5z"/><path d="M14 3v5h5M8 13h8M8 17h6"/>',
    "star": '<path d="M12 3l2.8 5.8 6.2.8-4.5 4.4 1.1 6.2L12 17.2l-5.6 3 1.1-6.2L3 9.6l6.2-.8z"/>',
    "menu": '<path d="M4 7h16M4 12h16M4 17h16"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    "instagram": '<rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><path d="M17.5 6.5h.01"/>',
    "compare": '<rect x="3" y="4" width="7" height="16" rx="1.5"/><rect x="14" y="4" width="7" height="16" rx="1.5"/>',
    "briefcase": '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M3 13h18"/>',
    "whatsapp": '<path d="M3.5 20.5l1.3-4.2A8.5 8.5 0 1 1 8 19.4z"/><path d="M9 8.6c0 3.4 2.6 6.4 6.4 6.4l.9-1.5-2-1-1 .9a5 5 0 0 1-2.8-2.8l.9-1-1-2z"/>',
    "chevron": '<path d="m6 9 6 6 6-6"/>',
    "map": '<path d="M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2zM9 4v14M15 6v14"/>',
    "wave": '<path d="M2 10c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2M2 16c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2"/>',
    "plane": '<path d="M10.5 13.5 3 11l1.5-1.5 7 1 4-4.5c1-1 2.6-1.4 3.2-.7.7.6.3 2.2-.7 3.2l-4.5 4 1 7L13 21l-2.5-7.5z"/>',
    "bus": '<rect x="4" y="3" width="16" height="15" rx="2"/><path d="M4 11h16M8 18v3M16 18v3M8 14.5h.01M16 14.5h.01"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>',
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16v4zM13.5 6.5l4 4"/>',
}


def icon(name, cls="icon"):
    return (
        f'<svg class="{cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'
        f"{ICON_PATHS[name]}</svg>"
    )


def logo_svg(variante="padrao", cls="logo"):
    """Logo oficial redesenhada em vetor: GAROPABA, carro de frente e selo “loca fácil · veículos”.
    variante "clara" para fundos verdes (nome em branco, selo um tom acima)."""
    nome = "#FFFFFF" if variante == "clara" else "var(--c-primary)"
    selo = "#145238" if variante == "clara" else "var(--c-primary)"
    return (
        f'<svg class="{cls}" viewBox="0 0 240 172" role="img" aria-label="Garopaba Loca Fácil Veículos">'
        f'<text x="120" y="22" text-anchor="middle" font-family="Montserrat, sans-serif" font-weight="800" font-size="22.5" letter-spacing="1.2" fill="{nome}">GAROPABA</text>'
        '<path d="M86 62 94 44q2-5 8-5h36q6 0 8 5l8 18 6 1q6 1 6 8v21H74V71q0-7 6-8z" fill="var(--c-sun)"/>'
        '<path d="M70 56h11l1 6H71zM170 56h-11l-1 6h11z" fill="var(--c-sun)"/>'
        f'<path d="M101 45h38l7 15H94z" fill="{selo}"/>'
        '<path d="M78 70l18 3-2 5-14-2zM162 70l-18 3 2 5 14-2z" fill="#fff"/>'
        f'<rect x="106" y="72" width="28" height="4" rx="2" fill="{selo}"/><rect x="110" y="80" width="20" height="3" rx="1.5" fill="{selo}"/>'
        f'<path d="M51 87h138l11 11v46l-80 25-80-25V98z" fill="{selo}"/>'
        '<text x="120" y="131" text-anchor="middle" font-family="&#39;Baloo 2&#39;, sans-serif" font-weight="700" font-size="33" fill="var(--c-sun)">loca fácil</text>'
        '<text x="120" y="152" text-anchor="middle" font-family="&#39;Baloo 2&#39;, sans-serif" font-weight="600" font-size="15" fill="#fff">veículos</text>'
        '<rect x="62" y="145.5" width="26" height="2.2" rx="1.1" fill="#fff"/><rect x="152" y="145.5" width="26" height="2.2" rx="1.1" fill="#fff"/>'
        "</svg>"
    )



# --------------------------------------------------------------------------- vehicle illustration

CAR_BODIES = {
    # Silhuetas laterais neutras (não representam fotos reais do veículo).
    "hatch": {
        "body": "M40 112V90c0-9 5-14 14-16l20-4 40-30c5-4 11-6 17-6h102c8 0 14 3 19 8l26 27 44 7c12 2 18 9 18 20v10c0 4-3 6-6 6h-30a32 32 0 0 0-64 0H134a32 32 0 0 0-64 0H46c-4 0-6-2-6-6z",
        "glass": "M84 71l30-25c3-2 6-3 10-3h65v28zM199 43h50c6 0 10 2 14 6l21 22h-85z",
        "wheels": (102, 298), "wy": 118, "r": 24, "light_f": "M356 88h14l2 7h-14z", "light_r": "M40 88h7v11h-7z",
    },
    "sedan": {
        "body": "M20 112V97c0-8 4-13 13-14l46-7 34-28c5-4 11-6 17-6h96c8 0 14 3 19 8l26 27 47 7c12 2 18 9 18 20v8c0 4-3 6-6 6h-30a32 32 0 0 0-64 0H136a32 32 0 0 0-64 0H26c-4 0-6-2-6-6z",
        "glass": "M88 75l32-25c3-2 6-3 10-3h52v28zM192 47h48c6 0 10 2 14 6l20 22h-82z",
        "wheels": (104, 300), "wy": 118, "r": 24, "light_f": "M358 89h14l2 7h-14z", "light_r": "M22 93h9v8h-9z",
    },
    "suv": {
        "body": "M30 108V90c0-8 5-13 14-15l38-5 30-30c5-4 10-6 16-6h106c8 0 14 3 18 8l26 29 42 7c11 2 17 9 17 19v12c0 4-3 6-6 6h-28a33 33 0 0 0-66 0H136a33 33 0 0 0-66 0H36c-4 0-6-2-6-6z",
        "glass": "M88 69l30-28c3-2 6-3 10-3h58v31zM196 38h48c6 0 10 2 13 6l22 25h-83z",
        "wheels": (103, 296), "wy": 114, "r": 26, "light_f": "M352 84h14l2 8h-14z", "light_r": "M32 86h8v10h-8z",
    },
}


def car_svg(v, cls="car-art"):
    body = CAR_BODIES.get(v.get("carroceria"), CAR_BODIES["hatch"])
    color = v.get("cor_ilustracao") or "#9aa4ad"
    light = color.lower() in ("#eeeeea", "#ffffff", "#f1f1ee")
    stroke = ' stroke="#c9c6bd" stroke-width="1.5"' if light else ""
    wy, r = body["wy"], body["r"]
    wheels = "".join(
        f'<circle cx="{x}" cy="{wy}" r="{r}" fill="#1b2227"/>'
        f'<circle cx="{x}" cy="{wy}" r="{r * 0.55:.1f}" fill="#cfd4d8"/>'
        f'<circle cx="{x}" cy="{wy}" r="{r * 0.18:.1f}" fill="#8b949b"/>'
        for x in body["wheels"]
    )
    return (
        f'<svg class="{cls}" viewBox="0 0 400 160" role="img" aria-label="Ilustração de um {e(vehicle_name(v))}">'
        f'<ellipse cx="200" cy="143" rx="178" ry="7" fill="rgba(15,30,43,.12)"/>'
        f'<path d="{body["body"]}" fill="{color}"{stroke}/>'
        f'<path d="{body["glass"]}" fill="#22313b" opacity=".88"/>'
        f'<path d="{body["light_f"]}" fill="#fff6d6"/><path d="{body["light_r"]}" fill="#c0392b"/>'
        f"{wheels}</svg>"
    )


def photo_tag(img, eager=False, alt=None, extra=""):
    """<img> de uma foto da frota, com dimensões reais (evita salto de layout) e ponto focal."""
    loading = 'fetchpriority="high"' if eager else 'loading="lazy"'
    alt_text = img.get("alt", "") if alt is None else alt
    return (
        f'<img src="/{e(quote(img["src"]))}" alt="{e(alt_text)}" width="{img.get("w", 800)}" height="{img.get("h", 600)}" '
        f'style="object-position:{e(img.get("foco", "50% 50%"))}" {loading} decoding="async"{extra}>'
    )


def vehicle_media(v, cls="car-art", eager=False):
    if v.get("imagens"):
        return photo_tag(v["imagens"][0], eager)
    return car_svg(v, cls)


# --------------------------------------------------------------------------- layout

NAV = [
    ("/veiculos/", "Veículos"),
    ("/#como-funciona", "Como funciona"),
    ("/sobre/", "Sobre"),
    ("/avaliacoes/", "Avaliações"),
    ("/perguntas-frequentes/", "Dúvidas"),
    ("/contato/", "Contato"),
]


def org_jsonld():
    a = EMP["endereco"]
    data = {
        "@context": "https://schema.org",
        "@type": "AutoRental",
        "@id": SITE_URL + "/#empresa",
        "name": EMP["nome"],
        "url": SITE_URL + "/",
        "telephone": EMP["telefone_e164"],
        "image": SITE_URL + "/img/og-loja.png",
        "logo": SITE_URL + "/favicon.svg",
        "address": {
            "@type": "PostalAddress",
            "streetAddress": a["logradouro"] + ", " + a["bairro"],
            "addressLocality": a["cidade"],
            "addressRegion": a["uf"],
            "postalCode": a["cep"],
            "addressCountry": "BR",
        },
        "areaServed": {"@type": "City", "name": "Garopaba"},
        "sameAs": [f"https://www.instagram.com/{EMP['instagram']}/"],
        "priceRange": f"A partir de {brl(EMP['diaria_a_partir'])} por dia",
        "hasMap": maps_url(),
    }
    if EMP.get("email"):
        data["email"] = EMP["email"]
    if EMP.get("google_perfil_url"):
        data["sameAs"].append(EMP["google_perfil_url"])
    # openingHours e aggregateRating só entram quando houver dados reais e verificáveis.
    return data


def breadcrumb_jsonld(items):
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": name, "item": SITE_URL + path}
            for i, (name, path) in enumerate(items)
        ],
    }


def avisos_band():
    hoje = datetime.date.today().isoformat()
    itens = []
    for a in AVISOS:
        fim, inicio = a.get("fim") or "", a.get("inicio") or ""
        if fim and fim < hoje:
            continue  # já expirou na data do build
        link = ""
        if not blank(a.get("link_url")):
            externo = a["link_url"].startswith("http")
            alvo = ' target="_blank" rel="noopener"' if externo else ""
            link = f'<a href="{e(a["link_url"])}"{alvo}>{e(a.get("link_texto") or "Saiba mais")}{icon("arrow")}</a>'
        itens.append(
            f'<div class="aviso" data-aviso data-inicio="{e(inicio)}" data-fim="{e(fim)}"{" hidden" if inicio and inicio > hoje else ""}>'
            f'<div class="container aviso__inner"><p>{e(a["texto"])}</p>{link}</div></div>'
        )
    return "".join(itens)


def header(active):
    cur = ' aria-current="page"'
    links = "".join(
        f'<li><a href="{href}"{cur if href == active else ""}>{label}</a></li>'
        for href, label in NAV
    )
    return f"""
<a class="skip-link" href="#conteudo">Pular para o conteúdo</a>
<header class="site-header" data-header>
  <div class="container site-header__inner">
    <a class="brand" href="/" aria-label="{e(EMP['nome'])} – página inicial">
      {logo_svg()}
    </a>
    <nav class="site-nav" id="site-nav" aria-label="Principal" data-nav>
      <ul>{links}</ul>
      <div class="site-nav__cta">
        <a class="btn btn--ghost btn--sm" href="{wa_url('Olá! Vim pelo site e gostaria de atendimento.')}" target="_blank" rel="noopener" data-track="whatsapp_click" data-track-label="menu">{icon('whatsapp')}WhatsApp</a>
        <a class="btn btn--primary btn--sm" href="/reserva/" data-track="cta_click" data-track-label="header_reserva">Solicitar reserva</a>
      </div>
    </nav>
    <button class="nav-toggle" type="button" aria-expanded="false" aria-controls="site-nav" data-nav-toggle>
      <span class="sr-only">Abrir menu</span>{icon('menu', 'icon nav-toggle__open')}{icon('x', 'icon nav-toggle__close')}
    </button>
  </div>
</header>"""


def footer():
    year = datetime.date.today().year
    email = (
        f'<li><a href="mailto:{e(EMP["email"])}">{e(EMP["email"])}</a></li>'
        if EMP.get("email") else (f"<li>{pending('e-mail')}</li>" if DEV else "")
    )
    hours = (
        f"<li>{icon('clock')}<span>{e(EMP['horarios'])}</span></li>"
        if EMP.get("horarios")
        else f"<li>{icon('clock')}<span>{pending('horário de atendimento', 'Horários: consulte pelo WhatsApp')}</span></li>"
    )
    return f"""
<footer class="site-footer">
  <div class="container site-footer__grid">
    <div class="site-footer__brand">
      <a class="brand brand--light" href="/" aria-label="{e(EMP['nome'])} – página inicial">{logo_svg("clara")}</a>
      <p>Aluguel de carros em Garopaba/SC com veículos revisados, seguro total incluso e contrato transparente. Atendimento para pessoas e empresas, por diária ou mensal.</p>
    </div>
    <div>
      <h2 class="site-footer__title">Contato</h2>
      <ul class="site-footer__list">
        <li>{icon('whatsapp')}<a href="{wa_url('Olá! Vim pelo site e gostaria de atendimento.')}" target="_blank" rel="noopener" data-track="whatsapp_click" data-track-label="footer">{e(EMP['telefone'])}</a></li>
        <li>{icon('pin')}<a href="{maps_url()}" target="_blank" rel="noopener">{e(full_address())}</a></li>
        {hours}
        <li>{icon('instagram')}<a href="https://www.instagram.com/{e(EMP['instagram'])}/" target="_blank" rel="noopener">@{e(EMP['instagram'])}</a></li>
        {email}
      </ul>
    </div>
    <div>
      <h2 class="site-footer__title">Navegação</h2>
      <ul class="site-footer__list site-footer__list--plain">
        <li><a href="/veiculos/">Veículos</a></li>
        <li><a href="/reserva/">Solicitar reserva</a></li>
        <li><a href="/sobre/">Sobre a locadora</a></li>
        <li><a href="/avaliacoes/">Avaliações</a></li>
        <li><a href="/perguntas-frequentes/">Perguntas frequentes</a></li>
        <li><a href="/contato/">Contato e localização</a></li>
      </ul>
    </div>
  </div>
  <div class="container"><p class="site-footer__wordmark" aria-hidden="true">loca fácil</p></div>
  <div class="container site-footer__bottom">
    <p>© {year} {e(EMP['nome'])}. Solicitações enviadas pelo site não são reservas confirmadas: a confirmação é feita pela nossa equipe.</p>
    <p class="site-footer__links"><a href="/privacidade/">Política de privacidade</a> · <a href="/painel/" rel="nofollow">Área da locadora</a></p>
  </div>
</footer>
<a class="wa-float" href="{wa_url('Olá! Vim pelo site e gostaria de atendimento.')}" target="_blank" rel="noopener" data-track="whatsapp_click" data-track-label="flutuante" aria-label="Falar com a Loca Fácil pelo WhatsApp">{icon('whatsapp')}<span>WhatsApp</span></a>"""


def page(path, title, description, body, active=None, jsonld=None, page_class="", fleet_data=False, noindex=False):
    canonical = SITE_URL + path
    blocks = [org_jsonld()] + (jsonld or [])
    ld = "".join(
        f'<script type="application/ld+json">{json.dumps(b, ensure_ascii=False)}</script>' for b in blocks
    )
    fleet = ""
    if fleet_data:
        payload = [
            {
                "slug": v["slug"], "nome": vehicle_name(v), "categoria": v["categoria"],
                "passageiros": v["passageiros"], "cambio": v["cambio"], "ar": v["ar_condicionado"],
                "bagagem": luggage_class(v), "litros": v["porta_malas_litros"],
                "combustivel": v["combustivel"], "preco": v["preco_diaria"],
            }
            for v in FLEET
        ]
        fleet = f'<script type="application/json" id="fleet-data">{json.dumps(payload, ensure_ascii=False)}</script>'
    config = json.dumps({"base": BASE_PATH, "whatsapp": EMP["whatsapp"], "loja": f"Loja Loca Fácil ({EMP['endereco']['bairro']})"}, ensure_ascii=False)
    gsc = f'<meta name="google-site-verification" content="{e(GSC_TOKEN)}">' if GSC_TOKEN else ""
    robots = '<meta name="robots" content="noindex">' if (noindex or NOINDEX) else ""
    dev_bar = (
        '<div class="dev-bar" role="note">Modo desenvolvimento · itens <mark class="pending">PENDENTE</mark> e avaliações de EXEMPLO não aparecem no build de produção</div>'
        if DEV else ""
    )
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
<link rel="canonical" href="{canonical}">
{robots}{gsc}
<meta name="theme-color" content="#F7F3EC">
<meta name="color-scheme" content="light">
<meta property="og:type" content="website">
<meta property="og:locale" content="pt_BR">
<meta property="og:site_name" content="{e(EMP['nome'])}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(description)}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{SITE_URL}/img/og-loja.png">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Baloo+2:wght@600;700&family=Montserrat:wght@700;800&family=Manrope:wght@400;500;600;700&display=swap">
<link rel="stylesheet" href="/css/styles.css?v={ASSET_VERSION}">
<script>document.documentElement.classList.add('js')</script>
{ld}
</head>
<body class="{page_class}">
{dev_bar}
{header(active)}
{avisos_band()}
<main id="conteudo" tabindex="-1">
{body}
</main>
{footer()}
<div class="toast" role="status" aria-live="polite" data-toast></div>
<script type="application/json" id="site-config">{config}</script>
{fleet}
<script src="/js/app.js?v={ASSET_VERSION}" defer></script>
</body>
</html>"""


# --------------------------------------------------------------------------- shared sections

def spec_list(v, compact=False):
    items = [
        ("users", f"{v['passageiros']} passageiros"),
        ("gear", {"manual": "Câmbio manual", "automatico": "Câmbio automático"}.get(v["cambio"]) or pending("câmbio", "Câmbio a confirmar")),
        ("snow", "Ar-condicionado" if v["ar_condicionado"] else "Sem ar-condicionado" if v["ar_condicionado"] is False else pending("ar-condicionado", "Ar-condicionado: consulte")),
        ("bag", f"Porta-malas {LUGGAGE_LABEL[luggage_class(v)].lower()} · {v['porta_malas_litros']} L" if v.get("porta_malas_litros") else pending("porta-malas", "Porta-malas: consulte")),
    ]
    if not compact:
        items.append(("fuel", v["combustivel"] if v.get("combustivel") else pending("combustível", "Combustível: consulte")))
    lis = "".join(f"<li>{icon(i)}<span>{t}</span></li>" for i, t in items if t)
    return f'<ul class="specs{" specs--compact" if compact else ""}">{lis}</ul>'


def price_line(v):
    if v.get("preco_diaria"):
        return f'<p class="price"><span class="price__value">{brl(v["preco_diaria"])}</span><span class="price__unit">/dia</span></p>'
    return (
        f'<p class="price price--quote"><span class="price__label">Diárias da frota a partir de</span>'
        f'<span class="price__value">{brl(EMP["diaria_a_partir"])}</span>'
        f'<span class="price__unit">valor deste modelo sob consulta</span></p>'
    )


def mobile_price(v):
    if v.get("preco_diaria"):
        return f'<strong>{brl(v["preco_diaria"])}</strong><span>por dia</span>'
    return f'<span>Diárias da frota a partir de</span><strong>{brl(EMP["diaria_a_partir"])}</strong>'


def vehicle_card(v, compare=False, heading="h3"):
    name = vehicle_name(v)
    lug = luggage_class(v) or ""
    tags = "".join(f"<li>{e(t)}</li>" for t in v["destaques_empresa"])
    compare_ctrl = (
        f'<label class="compare-toggle"><input type="checkbox" data-compare value="{v["slug"]}"><span>{icon("compare")}Comparar</span></label>'
        if compare else ""
    )
    return f"""
<article class="vehicle-card reveal" data-vehicle
  data-categoria="{e(v['categoria'])}" data-passageiros="{v['passageiros']}" data-cambio="{v['cambio'] or ''}"
  data-ar="{'1' if v['ar_condicionado'] else ''}" data-bagagem="{lug}">
  <a class="vehicle-card__media{' vehicle-card__media--photo' if v.get('imagens') else ''}" href="/veiculos/{v['slug']}/" tabindex="-1" aria-hidden="true">{vehicle_media(v)}</a>
  <div class="vehicle-card__body">
    <{heading} class="vehicle-card__title"><a href="/veiculos/{v['slug']}/" data-track="vehicle_select" data-track-label="{v['slug']}">{e(name)}</a></{heading}>
    <p class="vehicle-card__meta">{e(v['categoria'])} · {v['passageiros']} lugares</p>
    <ul class="tags">{tags}</ul>
    {spec_list(v, compact=True)}
    {price_line(v)}
    <div class="vehicle-card__actions">
      <a class="btn btn--primary btn--block" href="/reserva/?veiculo={v['slug']}" data-track="cta_click" data-track-label="card_reserva_{v['slug']}">Solicitar este carro</a>
      <a class="btn btn--quiet btn--block" href="/veiculos/{v['slug']}/">Ver detalhes</a>
    </div>
    {compare_ctrl}
  </div>
</article>"""


def stars(n):
    return "".join(
        f'<span class="star{" star--on" if i < n else ""}">{icon("star")}</span>' for i in range(5)
    )


def review_card(r):
    date = ""
    if r.get("data"):
        d = datetime.date.fromisoformat(r["data"])
        meses = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
        date = f'<time datetime="{r["data"]}">{meses[d.month - 1]} de {d.year}</time>'
    source = ""
    if r.get("fonte"):
        source = (
            f'<a href="{e(r["url"])}" target="_blank" rel="noopener">Ver no {e(r["fonte"])}</a>'
            if r.get("url") else f'<span>Avaliação no {e(r["fonte"])}</span>'
        )
    badge = '<span class="review-card__example">EXEMPLO · não publicar</span>' if r.get("exemplo") else ""
    who = e(r["nome"]) + (f' <span class="muted">· {e(r["cidade"])}</span>' if r.get("cidade") else "")
    return f"""
<figure class="review-card reveal{' review-card--example' if r.get('exemplo') else ''}">
  {badge}
  <div class="stars" role="img" aria-label="Nota {r['nota']} de 5">{stars(r['nota'])}</div>
  <blockquote><p>{e(r['texto'])}</p></blockquote>
  <figcaption><strong>{who}</strong><span class="review-card__meta">{date}{source}</span></figcaption>
</figure>"""


def reviews_block(limit=None, show_summary=True):
    reviews = visible_reviews()
    pub = published_reviews()
    if not reviews:
        google = EMP.get("google_avaliacoes_url")
        google_btn = (
            f'<a class="btn btn--ghost" href="{e(google)}" target="_blank" rel="noopener">Ver avaliações no Google</a>'
            if google else ""
        )
        return f"""
<div class="reviews-empty reveal">
  <div class="reviews-empty__icon">{icon('star')}</div>
  <h3>Avaliações verificadas em breve</h3>
  <p>Publicamos aqui apenas comentários reais de clientes, com autorização e link para a fonte original. Enquanto reunimos esses depoimentos, você pode conhecer o nosso trabalho no Instagram ou conversar direto com a equipe.</p>
  <div class="btn-row btn-row--center">
    <a class="btn btn--ghost" href="https://www.instagram.com/{e(EMP['instagram'])}/" target="_blank" rel="noopener">{icon('instagram')}Ver o Instagram</a>
    {google_btn}
  </div>
</div>"""
    summary = ""
    if show_summary and len(pub) >= MIN_REVIEWS_FOR_AVERAGE:
        avg = sum(r["nota"] for r in pub) / len(pub)
        src = EMP.get("google_avaliacoes_url")
        src_link = f' · <a href="{e(src)}" target="_blank" rel="noopener">ver todas na fonte</a>' if src else ""
        summary = (
            f'<p class="reviews-summary">{stars(round(avg))}<span><strong>{avg:.1f}</strong> de média em '
            f'{len(pub)} avaliação{"ões" if len(pub) > 1 else ""} publicada{"s" if len(pub) > 1 else ""} neste site{src_link}</span></p>'
        )
    items = reviews[:limit] if limit else reviews
    cards = "".join(review_card(r) for r in items)
    if len(items) < 3:
        google = EMP.get("google_avaliacoes_url")
        link = (
            f'<a class="btn btn--ghost btn--sm" href="{e(google)}" target="_blank" rel="noopener">Avaliar no Google</a>' if google
            else f'<a class="btn btn--ghost btn--sm" href="{wa_url("Olá! Aluguei com vocês e gostaria de deixar uma avaliação.")}" target="_blank" rel="noopener">Contar como foi</a>'
        )
        cards += (
            f'<div class="review-card review-card--invite reveal"><div class="reviews-empty__icon">{icon("star")}</div>'
            f'<p><strong>Já alugou com a gente?</strong><br>Sua avaliação ajuda outros viajantes a escolher com segurança.</p>{link}</div>'
        )
    return f'{summary}<div class="reviews-grid">{cards}</div>'


def faq_items(items, open_first=False):
    out = []
    for i, q in enumerate(items):
        if q["resposta"] is None and not DEV:
            continue
        answer = (
            e(q["resposta"].replace("{diaria}", f"{EMP['diaria_a_partir']:.0f}"))
            if q["resposta"] else pending("resposta com a regra real da empresa")
        )
        out.append(
            f'<details class="faq-item"{" open" if open_first and i == 0 else ""}>'
            f'<summary><span>{e(q["pergunta"])}</span>{icon("chevron", "icon faq-item__chev")}</summary>'
            f'<div class="faq-item__answer"><p>{answer}</p></div></details>'
        )
    return "".join(out)


def faq_fallback_note():
    return f"""
<div class="note">
  {icon('info')}
  <p>Documentos, caução, cancelamento e demais condições são explicados pela equipe antes de qualquer confirmação. <a href="{wa_url('Olá! Tenho uma dúvida sobre as condições de locação.')}" target="_blank" rel="noopener" data-track="whatsapp_click" data-track-label="faq_duvida">Pergunte pelo WhatsApp</a>.</p>
</div>"""


def cta_band(title="Garopaba no seu ritmo", text="Envie suas datas e receba disponibilidade e valores direto da equipe, sem compromisso."):
    return f"""
<section class="cta-band" aria-labelledby="cta-title">
  <div class="container cta-band__inner reveal">
    <div>
      <h2 id="cta-title">{e(title)}</h2>
      <p>{e(text)}</p>
    </div>
    <div class="btn-row">
      <a class="btn btn--sun btn--lg" href="/reserva/" data-track="cta_click" data-track-label="cta_band_reserva">Solicitar orçamento{icon('arrow')}</a>
      <a class="btn btn--on-dark btn--lg" href="{wa_url('Olá! Vim pelo site e gostaria de ajuda para escolher um carro.')}" target="_blank" rel="noopener" data-track="whatsapp_click" data-track-label="cta_band">{icon('whatsapp')}Falar no WhatsApp</a>
    </div>
  </div>
</section>"""


def page_hero(eyebrow, title, lead, crumbs=None):
    bc = ""
    if crumbs:
        parts = "".join(
            f'<li><a href="{href}">{e(label)}</a></li>' if href else f'<li aria-current="page">{e(label)}</li>'
            for label, href in crumbs
        )
        bc = f'<nav class="breadcrumb" aria-label="Você está em"><ol>{parts}</ol></nav>'
    return f"""
<section class="page-hero">
  <div class="container">
    {bc}
    <h1>{title}</h1>
    <p class="lead">{lead}</p>
  </div>
</section>"""


# --------------------------------------------------------------------------- pages

def vehicle_options(selected=None, include_help=True):
    opts = ['<option value="">Selecione um veículo</option>'] if not include_help else ['<option value="">Ainda não sei</option>']
    for v in FLEET:
        sel = " selected" if v["slug"] == selected else ""
        opts.append(f'<option value="{v["slug"]}"{sel}>{e(vehicle_name(v))} · {e(v["categoria"])}</option>')
    return "".join(opts)


# Mapa ilustrativo do litoral (sem escala). viewBox 400 x 560: terra à esquerda, mar à direita.
# As praias de content/praias.json são posicionadas em % sobre esta mesma área.
COAST_PATH = (
    "M0 0H246C250 30 254 60 254 70C258 100 268 120 268 140C268 170 250 190 236 200"
    "C222 210 214 224 220 236C232 246 270 238 300 250C312 258 300 272 294 280"
    "C286 300 280 320 282 330C286 345 276 352 270 360C262 380 270 395 262 410"
    "C254 430 262 450 262 470C262 480 246 486 244 495C250 510 270 520 268 560H0Z"
)


def region_map():
    pins = "".join(
        f'<button type="button" class="map-pin" style="left:{p["x"]}%;top:{p["y"]}%" data-beach-pin="{e(p["slug"])}" '
        f'aria-controls="praia-{e(p["slug"])}" aria-pressed="false"><span class="map-pin__dot"></span>'
        f'<span class="map-pin__label">{e(p.get("curto") or p["nome"])}</span></button>'
        for p in PRAIAS
    )
    return f"""<figure class="region-map">
      <div class="region-map__canvas">
      <svg viewBox="0 0 400 560" aria-hidden="true" focusable="false">
        <rect width="400" height="560" class="region-map__sea"/>
        <path d="{COAST_PATH}" class="region-map__land"/>
        <path d="M216 228C240 200 262 170 262 140C258 110 252 80 250 50M236 236C262 250 280 262 286 280C276 310 272 340 264 360C252 390 230 405 214 415M214 415C236 440 250 470 242 495" class="region-map__coast-road"/>
        <ellipse cx="192" cy="420" rx="42" ry="22" class="region-map__sea"/>
        <path d="M232 418C246 414 254 412 262 410" class="region-map__channel"/>
        <path d="M0 262C40 258 84 252 120 250C160 248 196 236 216 228" class="region-map__road"/>
        <text x="16" y="248" class="region-map__small">BR-101</text>
        <text x="40" y="150" class="region-map__town">Garopaba</text>
        <text x="40" y="470" class="region-map__town">Imbituba</text>
        <text x="380" y="300" class="region-map__ocean" transform="rotate(90 380 300)">Oceano Atlântico</text>
      </svg>
      <span class="map-store" style="left:30%;top:44.6%"><span class="map-store__mark"></span><span class="map-store__label">Nossa loja</span></span>
      {pins}
      </div>
      <figcaption>Mapa ilustrativo, fora de escala. A loja fica na {e(EMP['endereco']['logradouro'].split(',')[0])}, em {e(EMP['endereco']['bairro'])}.</figcaption>
    </figure>"""


def region_section():
    if not PRAIAS:
        return ""
    chips = "".join(
        f'<li><button type="button" class="beach-chip" data-beach-pin="{e(p["slug"])}" aria-controls="praia-{e(p["slug"])}" aria-pressed="false">{e(p["nome"])}</button></li>'
        for p in PRAIAS
    )
    panels = "".join(
        f"""<article class="beach" id="praia-{e(p['slug'])}" data-beach="{e(p['slug'])}">
          <h3>{e(p['nome'])}</h3>
          <p class="beach__place">{e(p.get('lugar') or '')}</p>
          <p>{e(p['texto'])}</p>
          <a class="btn btn--primary" href="{wa_url(f"Olá! Vim pelo site e quero alugar um carro para curtir a {p['nome']}. Pode me passar disponibilidade e valores?")}" target="_blank" rel="noopener" data-track="whatsapp_click" data-track-label="praia_{e(p['slug'])}">{icon('whatsapp')}Pedir um carro para este passeio</a>
        </article>"""
        for p in PRAIAS
    )
    return f"""
<section class="section region" id="praias" aria-labelledby="region-title">
  <div class="container region__grid" data-beach-picker>
    <div class="region__copy">
      <h2 id="region-title">Praias a minutos de carro</h2>
      <p class="region__lead">Garopaba é feita de praias em direções diferentes. Com um carro, você escolhe a do dia conforme o vento e o mar, sem horário de ônibus. Toque numa praia do mapa.</p>
      <ul class="beach-chips" aria-label="Praias">{chips}</ul>
      <div class="beaches" aria-live="polite">{panels}</div>
    </div>
    {region_map()}
  </div>
  <div class="container">
    <dl class="arrivals">
      <div><dt>Chegando de avião</dt><dd>O aeroporto de Florianópolis fica a cerca de 90 km. Combine com a equipe o horário de retirada para a sua chegada.</dd></div>
      <div><dt>Chegando de ônibus</dt><dd>Desembarque em Garopaba e retire o carro na loja para circular pela região.</dd></div>
      <div><dt>Mora ou trabalha aqui</dt><dd>Carro reserva para imprevistos, aluguel mensal e atendimento para empresas.</dd></div>
    </dl>
  </div>
</section>"""


def build_home():
    featured = [v for v in FLEET if v.get("destaque_home")][:3]
    cards = "".join(vehicle_card(v) for v in featured)
    destaques = [q for q in FAQ if q.get("destaque")]
    a = EMP["endereco"]
    body = f"""
<section class="hero">
  <div class="container">
    <h1 class="hero__title">Aluguel de carros em Garopaba</h1>
    <div class="hero__grid">
      <div class="hero__copy">
        <p class="hero__lead">Diárias a partir de {brl(EMP['diaria_a_partir'])}, com seguro total incluso e carros revisados. Retire na nossa loja em {e(a['bairro'])} e aproveite o litoral por um dia ou por um mês.</p>
        <form class="quick-quote" action="/reserva/" method="get" data-quick-quote novalidate aria-labelledby="qq-title">
          <h2 id="qq-title" class="quick-quote__title">Consulte as suas datas</h2>
          <div class="field">
            <label for="qq-ret">Retirada</label>
            <input id="qq-ret" name="retirada" type="date" required data-min-today>
          </div>
          <div class="field">
            <label for="qq-dev">Devolução</label>
            <input id="qq-dev" name="devolucao" type="date" required data-min-today>
          </div>
          <div class="field field--wide">
            <label for="qq-car">Veículo</label>
            <select id="qq-car" name="veiculo">{vehicle_options()}</select>
          </div>
          <button class="btn btn--primary btn--lg field--wide" type="submit">Continuar{icon('arrow')}</button>
          <p class="field-error quick-quote__error" data-qq-error hidden></p>
        </form>
        <p class="hero__links">
          <a class="link-arrow" href="/veiculos/" data-track="cta_click" data-track-label="hero_veiculos">Ver os carros{icon('arrow')}</a>
          <a class="link-arrow" href="{wa_url('Olá! Vim pelo site e gostaria de atendimento.')}" target="_blank" rel="noopener" data-track="whatsapp_click" data-track-label="hero">{icon('whatsapp')}Falar no WhatsApp</a>
        </p>
      </div>
      <div class="hero__visual">
        <figure class="hero__photo">
          <img src="/img/frota/mobi-loja.webp" alt="Fiat Mobi da frota estacionado em frente à loja, com coqueiros ao fundo" width="437" height="538" fetchpriority="high">
        </figure>
        <p class="plate hero__plate"><span class="plate__small">Diárias a partir de</span><strong class="plate__big">{brl(EMP['diaria_a_partir'])}</strong><span class="plate__small">{pending('confirmar R$ 160 x R$ 180', 'por diária ou mensal')}</span></p>
      </div>
    </div>
  </div>
</section>

<section class="section" aria-labelledby="frota-title">
  <div class="container">
    <div class="section-head">
      <div>
        <h2 id="frota-title">Carros econômicos para o litoral</h2>
        <p class="section-head__lead">Do compacto para circular entre as praias ao sedã com porta-malas grande para a família inteira.</p>
      </div>
      <a class="link-arrow" href="/veiculos/">Ver todos os veículos{icon('arrow')}</a>
    </div>
    <div class="vehicle-grid">{cards}</div>
  </div>
</section>

<section class="section section--tint" aria-labelledby="dif-title">
  <div class="container split">
    <div class="split__head reveal">
      <h2 id="dif-title">Por que alugar aqui</h2>
      <p class="section-head__lead">Sem pacote surpresa no balcão e sem aplicativo no meio: você fala com gente da loja e sabe tudo antes de assinar.</p>
    </div>
    <dl class="facts">
      <div class="reveal"><dt>Seguro total incluso</dt><dd>O seguro já faz parte da locação. Nada de pacote extra para descobrir na hora da retirada.</dd></div>
      <div class="reveal"><dt>Revisados e vistoriados</dt><dd>Cada carro passa por revisão e vistoria antes de chegar às suas mãos.</dd></div>
      <div class="reveal"><dt>Contrato transparente</dt><dd>As condições são explicadas antes da assinatura. Sem surpresas na devolução.</dd></div>
      <div class="reveal"><dt>Cadastro rápido</dt><dd>Você resolve pelo WhatsApp, com a equipe da loja, sem burocracia.</dd></div>
      <div class="reveal"><dt>Diária ou mensal</dt><dd>Para o fim de semana, para a temporada ou para quem precisa de um carro por mais tempo.</dd></div>
      <div class="reveal"><dt>Pessoas e empresas</dt><dd>Turistas, moradores e empresas que precisam de mobilidade em Garopaba e região.</dd></div>
    </dl>
  </div>
</section>

<section class="section" id="como-funciona" aria-labelledby="how-title">
  <div class="container">
    <div class="section-head">
      <div>
        <h2 id="how-title">Do pedido à chave na mão</h2>
        <p class="section-head__lead">Sem pagamento pelo site e sem cadastro em aplicativo. Você só fecha quando tiver todas as informações.</p>
      </div>
    </div>
    <ol class="steps">
      <li class="step reveal"><h3>Escolha o carro e as datas</h3><p>Veja a frota ou peça orientação se ainda não souber qual modelo combina com a sua viagem.</p></li>
      <li class="step reveal"><h3>Envie a solicitação</h3><p>O site monta a mensagem com tudo preenchido e você envia pelo WhatsApp em um toque.</p></li>
      <li class="step reveal"><h3>Receba a confirmação</h3><p>A equipe confere a disponibilidade e responde com valor e condições. A reserva vale a partir daí.</p></li>
      <li class="step reveal"><h3>Retire e aproveite</h3><p>Retire o carro na loja em {e(a['bairro'])}, com contrato claro e seguro incluso.</p></li>
    </ol>
  </div>
</section>

<section class="section section--deep" aria-labelledby="rev-title">
  <div class="container">
    <div class="section-head">
      <h2 id="rev-title">Quem já alugou com a gente</h2>
      <a class="link-arrow link-arrow--light" href="/avaliacoes/">Todas as avaliações{icon('arrow')}</a>
    </div>
    {reviews_block(limit=3)}
  </div>
</section>

{region_section()}

<section class="section section--tint" aria-labelledby="faq-title">
  <div class="container faq-layout">
    <div class="section-head">
      <div>
        <h2 id="faq-title">Antes de solicitar</h2>
        <p class="section-head__lead">As respostas mais procuradas por quem está planejando a viagem.</p>
        <a class="link-arrow" href="/perguntas-frequentes/">Ver todas as perguntas{icon('arrow')}</a>
      </div>
    </div>
    <div class="faq-list">{faq_items(destaques, open_first=True)}</div>
  </div>
</section>
{cta_band()}"""
    return page(
        "/",
        "Aluguel de carros em Garopaba/SC | Garopaba Loca Fácil Veículos",
        f"Locadora de veículos em Garopaba/SC com seguro total incluso, carros revisados e diárias a partir de {brl(EMP['diaria_a_partir'])}. Aluguel por diária ou mensal. Solicite pelo WhatsApp.",
        body, active="/", page_class="page-home", fleet_data=True,
    )


def build_catalog():
    cats = sorted({v["categoria"] for v in FLEET})
    pax = sorted({v["passageiros"] for v in FLEET})
    chips = "".join(
        f'<label class="chip"><input type="radio" name="categoria" value="{e(c)}"><span>{e(c)}</span></label>' for c in cats
    )
    pax_opts = "".join(f'<option value="{p}">{p} ou mais</option>' for p in pax)
    cards = "".join(vehicle_card(v, compare=True, heading="h2") for v in FLEET)
    body = f"""
{page_hero('Frota', 'Carros para alugar', 'Frota da Loca Fácil em Garopaba, toda com seguro total incluso e revisados antes de cada locação. Filtre pelo que importa na sua viagem e solicite com as suas datas.', [('Início', '/'), ('Veículos', None)])}
<section class="section section--flush">
  <div class="container">
    <form class="filters" data-filters aria-label="Filtrar veículos" onsubmit="return false">
      <fieldset class="filters__group">
        <legend>Categoria</legend>
        <div class="chips">
          <label class="chip"><input type="radio" name="categoria" value="" checked><span>Todas</span></label>
          {chips}
        </div>
      </fieldset>
      <div class="filters__row">
        <div class="field field--inline">
          <label for="f-pax">Passageiros</label>
          <select id="f-pax" name="passageiros"><option value="">Qualquer</option>{pax_opts}</select>
        </div>
        <div class="field field--inline">
          <label for="f-cambio">Câmbio</label>
          <select id="f-cambio" name="cambio"><option value="">Qualquer</option><option value="manual">Manual</option><option value="automatico">Automático</option></select>
        </div>
        <div class="field field--inline">
          <label for="f-bag">Bagagem</label>
          <select id="f-bag" name="bagagem"><option value="">Qualquer</option><option value="pequena">Pequena ou mais</option><option value="media">Média ou mais</option><option value="grande">Grande</option></select>
        </div>
        <label class="switch"><input type="checkbox" name="ar" value="1"><span class="switch__track" aria-hidden="true"></span><span>Ar-condicionado confirmado</span></label>
      </div>
      <div class="filters__status">
        <p aria-live="polite" data-filter-count>{len(FLEET)} veículos</p>
        <button class="btn btn--quiet btn--sm" type="button" data-filter-reset hidden>Limpar filtros</button>
      </div>
    </form>
    <div class="vehicle-grid vehicle-grid--catalog" data-vehicle-grid>{cards}</div>
    <div class="empty-state" data-empty hidden>
      <h2>Nenhum veículo com essa combinação</h2>
      <p>Tente remover um filtro ou fale com a equipe: indicamos o carro mais adequado para a sua viagem.</p>
      <div class="btn-row btn-row--center">
        <button class="btn btn--ghost" type="button" data-filter-reset>Limpar filtros</button>
        <a class="btn btn--primary" href="/reserva/">Pedir orientação</a>
      </div>
    </div>
    <div class="note note--soft">
      {icon('info')}
      <p>Capacidade de porta-malas conforme a ficha técnica de fábrica de cada modelo. Itens marcados como “consulte” são confirmados pela equipe junto com a disponibilidade.</p>
    </div>
  </div>
</section>

<div class="compare-bar" data-compare-bar hidden>
  <div class="container compare-bar__inner">
    <p><strong data-compare-count>0</strong> de 3 selecionados para comparar</p>
    <div class="btn-row">
      <button class="btn btn--quiet btn--sm" type="button" data-compare-clear>Limpar</button>
      <button class="btn btn--primary btn--sm" type="button" data-compare-open>{icon('compare')}Comparar</button>
    </div>
  </div>
</div>
<dialog class="dialog" data-compare-dialog aria-labelledby="cmp-title">
  <div class="dialog__head">
    <h2 id="cmp-title">Comparar veículos</h2>
    <button class="icon-btn" type="button" data-dialog-close aria-label="Fechar comparação">{icon('x')}</button>
  </div>
  <div class="dialog__body" data-compare-table></div>
</dialog>
{cta_band('Não sabe qual escolher?', 'Conte quantas pessoas vão viajar e quanto de bagagem vocês levam. A equipe indica o carro certo.')}"""
    return page(
        "/veiculos/",
        "Carros para alugar em Garopaba | Frota Loca Fácil",
        "Veja a frota da Garopaba Loca Fácil: Kwid, Mobi, HB20, Argo e Logan com seguro incluso. Filtre por categoria, câmbio, bagagem e solicite pelo WhatsApp.",
        body, active="/veiculos/", page_class="page-catalog", fleet_data=True,
        jsonld=[breadcrumb_jsonld([("Início", "/"), ("Veículos", "/veiculos/")])],
    )


def build_vehicle(v):
    name = vehicle_name(v)
    others = [o for o in FLEET if o["slug"] != v["slug"]]
    # Recomendações: mesma categoria primeiro, depois porta-malas parecido.
    others.sort(key=lambda o: (o["categoria"] != v["categoria"], abs((o["porta_malas_litros"] or 0) - (v["porta_malas_litros"] or 0))))
    rec = "".join(vehicle_card(o) for o in others[:3])
    tags = "".join(f"<li>{e(t)}</li>" for t in v["destaques_empresa"])
    if v.get("imagens"):
        imgs = v["imagens"]
        first = imgs[0]
        main = photo_tag(first, eager=True, extra=" data-gallery-main")
        thumbs = ""
        if len(imgs) > 1:
            cur = ' aria-current="true"'
            thumbs = '<div class="gallery__thumbs">' + "".join(
                f'<button type="button" class="gallery__thumb" data-gallery-thumb="/{e(quote(img["src"]))}" data-alt="{e(img.get("alt", ""))}" '
                f'data-foco="{e(img.get("foco", "50% 50%"))}" aria-label="Ver foto {i + 1} de {len(imgs)}"{cur if i == 0 else ""}>'
                f'{photo_tag(img, alt="")}</button>'
                for i, img in enumerate(imgs)
            ) + "</div>"
        gallery = (
            f'<div class="gallery gallery--photo"><div class="gallery__main" style="--img:url(&quot;/{e(quote(first["src"]))}&quot;)">{main}</div>{thumbs}</div>'
        )
    else:
        gallery = (
            f'<div class="gallery gallery--art"><div class="gallery__main">{car_svg(v, "car-art car-art--lg")}</div>'
            f'<p class="gallery__note">{pending("fotos reais deste veículo", "Ilustração. Peça fotos do veículo pelo WhatsApp.")}</p></div>'
        )
    pol = EMP["politicas"]
    conditions = [
        ("shield", e("Seguro total incluso na locação")),
        ("check", e("Veículo revisado e vistoriado antes da entrega")),
        ("file", e("Contrato transparente, com as condições explicadas antes da assinatura")),
    ]
    for key, label in [("quilometragem", "quilometragem"), ("caucao", "caução"), ("combustivel", "política de combustível")]:
        if pol.get(key):
            conditions.append(("info", e(pol[key])))
        elif DEV:
            conditions.append(("info", pending(label)))
    cond_html = "".join(f"<li>{icon(i)}<span>{t}</span></li>" for i, t in conditions)
    spec_rows = [
        ("Marca", v["marca"]), ("Modelo", v["modelo"]),
        ("Versão", v["versao"] or None), ("Categoria", v["categoria"]),
        ("Passageiros", str(v["passageiros"])),
        ("Câmbio", {"manual": "Manual", "automatico": "Automático"}.get(v["cambio"])),
        ("Ar-condicionado", "Sim" if v["ar_condicionado"] else "Não" if v["ar_condicionado"] is False else None),
        ("Porta-malas", f"{v['porta_malas_litros']} litros (ficha de fábrica)" if v.get("porta_malas_litros") else None),
        ("Combustível", v.get("combustivel")),
    ]
    rows = "".join(
        f"<tr><th scope=\"row\">{k}</th><td>{e(val) if val else pending(k.lower(), 'Consulte')}</td></tr>" for k, val in spec_rows
    )
    body = f"""
<section class="vehicle-hero">
  <div class="container">
    <nav class="breadcrumb" aria-label="Você está em"><ol><li><a href="/">Início</a></li><li><a href="/veiculos/">Veículos</a></li><li aria-current="page">{e(name)}</li></ol></nav>
  </div>
  <div class="container vehicle-layout">
    <div class="vehicle-layout__main">
      {gallery}
      <div class="vehicle-intro">
        <h1>{e(name)}</h1>
        <p class="vehicle-intro__meta">{e(v['categoria'])} · {v['passageiros']} lugares</p>
        <ul class="tags">{tags}</ul>
        <p class="lead">{e(v['resumo'])}</p>
        {spec_list(v)}
      </div>
      <section class="panel" aria-labelledby="ficha">
        <h2 id="ficha">Ficha do veículo</h2>
        <table class="spec-table">{rows}</table>
      </section>
      <section class="panel" aria-labelledby="cond">
        <h2 id="cond">Condições da locação</h2>
        <ul class="check-list">{cond_html}</ul>
        <p class="muted small">Documentos, caução e demais condições são informados pela equipe junto com a cotação, antes de qualquer confirmação.</p>
      </section>
    </div>
    <aside class="vehicle-layout__aside">
      <form class="booking-card" action="/reserva/" method="get" data-period-form data-vehicle="{v['slug']}" data-vehicle-name="{e(name)}" novalidate aria-labelledby="bk-title">
        <input type="hidden" name="veiculo" value="{v['slug']}">
        <h2 id="bk-title" class="booking-card__title">Solicitar este veículo</h2>
        {price_line(v)}
        <div class="field-pair">
          <div class="field"><label for="p-ret">Retirada</label><input id="p-ret" name="retirada" type="date" data-min-today></div>
          <div class="field"><label for="p-ret-h">Horário</label><input id="p-ret-h" name="retirada_hora" type="time" step="1800" value="09:00"></div>
        </div>
        <div class="field-pair">
          <div class="field"><label for="p-dev">Devolução</label><input id="p-dev" name="devolucao" type="date" data-min-today></div>
          <div class="field"><label for="p-dev-h">Horário</label><input id="p-dev-h" name="devolucao_hora" type="time" step="1800" value="09:00"></div>
        </div>
        <div class="booking-card__summary" data-period-summary aria-live="polite">
          <p class="muted">Escolha as datas para ver o resumo do período.</p>
        </div>
        <button class="btn btn--primary btn--block btn--lg" type="submit" data-track="cta_click" data-track-label="vehicle_continuar">Continuar solicitação{icon('arrow')}</button>
        <a class="btn btn--ghost btn--block" href="{wa_url(f'Olá! Gostaria de saber a disponibilidade do {name}.')}" target="_blank" rel="noopener" data-period-wa data-track="whatsapp_click" data-track-label="vehicle_{v['slug']}">{icon('whatsapp')}Perguntar pelo WhatsApp</a>
        <p class="booking-card__foot">{icon('info')}Isto é uma solicitação. A reserva é confirmada pela equipe, com valor e condições.</p>
      </form>
    </aside>
  </div>
</section>
<section class="section section--tint" aria-labelledby="rec-title">
  <div class="container">
    <div class="section-head"><div><h2 id="rec-title">Outros veículos da frota</h2></div><a class="link-arrow" href="/veiculos/">Ver todos{icon('arrow')}</a></div>
    <div class="vehicle-grid">{rec}</div>
  </div>
</section>
<div class="mobile-cta" data-mobile-cta>
  <p class="mobile-cta__price">{mobile_price(v)}</p>
  <a class="btn btn--primary" href="/reserva/?veiculo={v['slug']}" data-track="cta_click" data-track-label="mobile_bar_{v['slug']}">Solicitar</a>
</div>"""
    lug = luggage_class(v)
    desc = (
        f"Alugue um {name} em Garopaba/SC: {v['passageiros']} passageiros"
        + (f", porta-malas {LUGGAGE_LABEL[lug].lower()}" if lug else "")
        + ", seguro total incluso. Solicite disponibilidade pelo WhatsApp."
    )
    return page(
        f"/veiculos/{v['slug']}/",
        f"Aluguel de {name} em Garopaba | Loca Fácil",
        desc, body, active="/veiculos/", page_class="page-vehicle", fleet_data=True,
        jsonld=[breadcrumb_jsonld([("Início", "/"), ("Veículos", "/veiculos/"), (name, f"/veiculos/{v['slug']}/")])],
    )


def build_reserva():
    a = EMP["endereco"]
    cards = "".join(
        f"""<label class="choice-card">
  <input type="radio" name="veiculo" value="{v['slug']}" data-label="{e(vehicle_name(v))}">
  <span class="choice-card__art{' choice-card__art--photo' if v.get('imagens') else ''}">{car_svg(v, 'car-art car-art--sm') if not v.get('imagens') else photo_tag(v['imagens'][0], alt='')}</span>
  <span class="choice-card__text"><strong>{e(vehicle_name(v))}</strong><span>{e(v['categoria'])} · {v['passageiros']} lugares{' · porta-malas ' + LUGGAGE_LABEL[luggage_class(v)].lower() if luggage_class(v) else ''}</span></span>
  <span class="choice-card__check">{icon('check')}</span>
</label>"""
        for v in FLEET
    )
    loja = f"Loja – {a['bairro']}, Garopaba"
    body = f"""
{page_hero('Solicitação de reserva', 'Solicite seu carro', 'Em poucos passos: preencha o essencial e envie pelo WhatsApp com tudo já organizado. A equipe confirma disponibilidade, valor e condições antes de qualquer reserva.', [('Início', '/'), ('Solicitar reserva', None)])}
<section class="section section--flush">
  <div class="container booking">
    <form class="wizard" data-wizard novalidate aria-label="Solicitação de reserva">
      <ol class="wizard__steps" aria-label="Etapas">
        <li data-step-tab="1" aria-current="step"><span>1</span>Veículo</li>
        <li data-step-tab="2"><span>2</span>Período e local</li>
        <li data-step-tab="3"><span>3</span>Seus dados</li>
        <li data-step-tab="4"><span>4</span>Revisar e enviar</li>
      </ol>

      <fieldset class="wizard__panel" data-step="1">
        <legend class="wizard__legend">Qual veículo você procura?</legend>
        <p class="wizard__hint">Não tem certeza? Escolha “Quero orientação” e a equipe indica o carro ideal.</p>
        <div class="choice-grid">
          {cards}
          <label class="choice-card choice-card--help">
            <input type="radio" name="veiculo" value="orientacao" data-label="Quero orientação para escolher">
            <span class="choice-card__art choice-card__art--icon">{icon('users')}</span>
            <span class="choice-card__text"><strong>Quero orientação</strong><span>Conte quantas pessoas vão e quanto de bagagem levam</span></span>
            <span class="choice-card__check">{icon('check')}</span>
          </label>
        </div>
        <p class="field-error" data-error-for="veiculo" hidden></p>
      </fieldset>

      <fieldset class="wizard__panel" data-step="2" hidden>
        <legend class="wizard__legend">Quando e onde?</legend>
        <div class="form-grid">
          <div class="field"><label for="r-ret">Data de retirada</label><input id="r-ret" name="retirada" type="date" required data-min-today><p class="field-error" data-error-for="retirada" hidden></p></div>
          <div class="field"><label for="r-ret-h">Horário de retirada</label><input id="r-ret-h" name="retirada_hora" type="time" step="1800" value="09:00" required></div>
          <div class="field"><label for="r-dev">Data de devolução</label><input id="r-dev" name="devolucao" type="date" required data-min-today><p class="field-error" data-error-for="devolucao" hidden></p></div>
          <div class="field"><label for="r-dev-h">Horário de devolução</label><input id="r-dev-h" name="devolucao_hora" type="time" step="1800" value="09:00" required></div>
        </div>
        <p class="period-pill" data-period-pill hidden></p>
        <div class="form-grid">
          <div class="field">
            <label for="r-local">Local de retirada</label>
            <select id="r-local" name="local_retirada">
              <option value="loja">{e(loja)}</option>
              <option value="outro">Outro local (sujeito a confirmação)</option>
            </select>
          </div>
          <div class="field" data-show-when="local_retirada=outro" hidden>
            <label for="r-local-txt">Endereço ou ponto de retirada</label>
            <input id="r-local-txt" name="local_retirada_txt" type="text" autocomplete="street-address" placeholder="Ex.: pousada, endereço ou rodoviária">
            <p class="field-error" data-error-for="local_retirada_txt" hidden></p>
          </div>
          <label class="check field--full"><input type="checkbox" name="mesmo_local" checked><span>Devolver no mesmo local da retirada</span></label>
          <div class="field" data-show-when="mesmo_local=off" hidden>
            <label for="r-local-dev">Local de devolução</label>
            <input id="r-local-dev" name="local_devolucao_txt" type="text" placeholder="Endereço ou ponto de devolução">
            <p class="field-error" data-error-for="local_devolucao_txt" hidden></p>
          </div>
        </div>
        <p class="hint">{icon('info')}Retirada ou devolução fora da loja depende de confirmação da equipe e pode ter condições específicas.</p>
      </fieldset>

      <fieldset class="wizard__panel" data-step="3" hidden>
        <legend class="wizard__legend">Como podemos te chamar?</legend>
        <p class="wizard__hint">Pedimos só o necessário. O seu número de WhatsApp chega automaticamente quando você enviar a mensagem.</p>
        <div class="form-grid">
          <div class="field field--full"><label for="r-nome">Nome</label><input id="r-nome" name="nome" type="text" autocomplete="name" required maxlength="80" enterkeyhint="next"><p class="field-error" data-error-for="nome" hidden></p></div>
          <fieldset class="field field--full segmented">
            <legend>A locação é para</legend>
            <label><input type="radio" name="cliente" value="Pessoa física" checked><span>{icon('users')}Pessoa física</span></label>
            <label><input type="radio" name="cliente" value="Empresa"><span>{icon('briefcase')}Empresa</span></label>
          </fieldset>
          <div class="field field--full"><label for="r-obs">Observações <span class="optional">(opcional)</span></label><textarea id="r-obs" name="observacoes" rows="3" maxlength="500" placeholder="Ex.: chegamos de avião às 15h, somos 4 pessoas com 3 malas"></textarea></div>
        </div>
      </fieldset>

      <section class="wizard__panel" data-step="4" hidden aria-labelledby="sum-title">
        <h2 class="wizard__legend" id="sum-title">Confira antes de enviar</h2>
        <dl class="summary" data-summary></dl>
        <div class="callout">
          {icon('info')}
          <div>
            <strong>O que acontece depois</strong>
            <p>Ao tocar em enviar, o WhatsApp abre com esta mensagem pronta para a Loca Fácil. A equipe responde com disponibilidade, valor e condições. <strong>A reserva só está confirmada depois dessa resposta.</strong></p>
          </div>
        </div>
        <div class="btn-row">
          <a class="btn btn--primary btn--lg" href="#" target="_blank" rel="noopener" data-send-wa>{icon('whatsapp')}Enviar solicitação pelo WhatsApp</a>
          <button class="btn btn--ghost" type="button" data-copy-msg>{icon('copy')}Copiar mensagem</button>
        </div>
        <p class="hint">Não usa WhatsApp? Ligue para <a href="tel:{EMP['telefone_e164']}">{e(EMP['telefone'])}</a> com estas informações em mãos.</p>
      </section>

      <div class="wizard__nav">
        <button class="btn btn--quiet" type="button" data-prev hidden>Voltar</button>
        <button class="btn btn--primary" type="button" data-next>Continuar{icon('arrow')}</button>
      </div>
    </form>

    <aside class="booking__aside">
      <div class="side-summary" data-side-summary>
        <h2>Sua solicitação</h2>
        <ul class="progress-list" data-progress></ul>
      </div>
      <div class="side-help">
        <h3>Ficou com dúvida?</h3>
        <p>Fale com a equipe antes de enviar. Respondemos pelo mesmo WhatsApp.</p>
        <a class="link-arrow" href="{wa_url('Olá! Estou preenchendo a solicitação no site e tenho uma dúvida.')}" target="_blank" rel="noopener" data-track="whatsapp_click" data-track-label="reserva_ajuda">{icon('whatsapp')}Tirar dúvida</a>
      </div>
    </aside>
  </div>
</section>"""
    return page(
        "/reserva/",
        "Solicitar reserva de carro em Garopaba | Loca Fácil",
        "Solicite o aluguel do seu carro em Garopaba: escolha o veículo, as datas e o local de retirada e envie pelo WhatsApp. Confirmação feita pela equipe.",
        body, active="/reserva/", page_class="page-booking", fleet_data=True,
    )


def build_sobre():
    paras = "".join(f"<p>{e(p)}</p>" for p in EMP["sobre"])
    hist = (
        "".join(f"<p>{e(p)}</p>" for p in EMP["historia"]) if EMP.get("historia")
        else (f"<p>{pending('história da empresa: fundação, quem está à frente, como começou')}</p>" if DEV else "")
    )
    difs = "".join(f"<li>{icon('check')}<span>{e(d)}</span></li>" for d in EMP["diferenciais"])
    body = f"""
{page_hero('Sobre a locadora', 'Sobre a Loca Fácil', 'Mobilidade com segurança, preço justo e atendimento de verdade. Somos uma locadora de Garopaba, com loja física e atendimento próximo para quem visita, mora ou trabalha na região.', [('Início', '/'), ('Sobre', None)])}
<section class="section section--flush">
  <div class="container about">
    <div class="about__text prose reveal">
      {paras}
      {hist}
    </div>
    <figure class="about__photo reveal">
      <img src="/img/frota/mobi-loja.webp" alt="Fiat Mobi da frota estacionado em frente à loja" width="437" height="538" loading="lazy">
      <figcaption>{icon('pin')}{e(EMP['endereco']['logradouro'])} · {e(EMP['endereco']['bairro'])}</figcaption>
    </figure>
  </div>
</section>
<section class="section section--tint" aria-labelledby="dif2">
  <div class="container">
    <div class="section-head"><div><h2 id="dif2">O que você encontra aqui</h2></div></div>
    <ul class="check-grid">{difs}</ul>
  </div>
</section>
{cta_band()}"""
    return page(
        "/sobre/", "Sobre a Garopaba Loca Fácil | Locadora de veículos em Garopaba",
        "Conheça a Garopaba Loca Fácil: locadora com loja física em Garopaba/SC, veículos revisados, seguro total incluso e atendimento para pessoas e empresas.",
        body, active="/sobre/",
        jsonld=[breadcrumb_jsonld([("Início", "/"), ("Sobre", "/sobre/")])],
    )


def build_avaliacoes():
    body = f"""
{page_hero('Avaliações', 'O que dizem nossos clientes', 'Somente avaliações reais, publicadas com autorização e com indicação da fonte original.', [('Início', '/'), ('Avaliações', None)])}
<section class="section section--flush">
  <div class="container">
    {reviews_block()}
    <div class="note note--soft">
      {icon('info')}
      <p>Já alugou com a Loca Fácil? Conte como foi pelo <a href="{wa_url('Olá! Gostaria de deixar uma avaliação sobre a minha locação.')}" target="_blank" rel="noopener">WhatsApp</a>{' ou no <a href="' + e(EMP['google_avaliacoes_url']) + '" target="_blank" rel="noopener">Google</a>' if EMP.get('google_avaliacoes_url') else ''}. Seu comentário ajuda outros viajantes a escolher com segurança.</p>
    </div>
  </div>
</section>
{cta_band()}"""
    return page(
        "/avaliacoes/", "Avaliações de clientes | Garopaba Loca Fácil",
        "Avaliações reais de clientes da Garopaba Loca Fácil, locadora de veículos em Garopaba/SC, com indicação da fonte original.",
        body, active="/avaliacoes/",
        jsonld=[breadcrumb_jsonld([("Início", "/"), ("Avaliações", "/avaliacoes/")])],
    )


def build_faq():
    groups = []
    for cat in ["Reserva", "Valores", "Retirada e devolução", "Documentos e requisitos"]:
        qs = [q for q in FAQ if q["categoria"] == cat]
        items = faq_items(qs)
        if items:
            groups.append(f'<section class="faq-group reveal" aria-labelledby="g-{cat[:4]}"><h2 id="g-{cat[:4]}">{e(cat)}</h2><div class="faq-list">{items}</div></section>')
    body = f"""
{page_hero('Perguntas frequentes', 'Perguntas frequentes', 'Tudo o que você precisa saber antes de alugar. Respostas diretas sobre reserva, valores, retirada e devolução. Se a sua dúvida não estiver aqui, a equipe responde pelo WhatsApp.', [('Início', '/'), ('Perguntas frequentes', None)])}
<section class="section section--flush">
  <div class="container narrow">
    {''.join(groups)}
    {faq_fallback_note()}
  </div>
</section>
{cta_band()}"""
    return page(
        "/perguntas-frequentes/", "Perguntas frequentes sobre aluguel de carro em Garopaba | Loca Fácil",
        "Como reservar, quanto custa a diária, seguro, retirada e devolução: tire suas dúvidas sobre o aluguel de carros na Garopaba Loca Fácil.",
        body, active="/perguntas-frequentes/",
        jsonld=[breadcrumb_jsonld([("Início", "/"), ("Perguntas frequentes", "/perguntas-frequentes/")])],
    )


def build_contato():
    a = EMP["endereco"]
    map_q = quote(f"{a['logradouro']}, {a['bairro']}, {a['cidade']} - {a['uf']}, {a['cep']}")
    hours = e(EMP["horarios"]) if EMP.get("horarios") else pending("horário de atendimento", "Consulte pelo WhatsApp")
    email_card = (
        f'<li class="contact-card">{icon("file")}<div><h2>E-mail</h2><a href="mailto:{e(EMP["email"])}">{e(EMP["email"])}</a></div></li>'
        if EMP.get("email") else ""
    )
    body = f"""
{page_hero('Contato', 'Fale com a Loca Fácil', 'Atendimento pelo WhatsApp e na nossa loja em Garopaba. Conte o que precisa e respondemos com as opções disponíveis.', [('Início', '/'), ('Contato', None)])}
<section class="section section--flush">
  <div class="container contact">
    <div class="contact__info">
      <ul class="contact-cards">
        <li class="contact-card contact-card--primary">{icon('whatsapp')}<div><h2>WhatsApp</h2><a href="{wa_url('Olá! Vim pelo site e gostaria de atendimento.')}" target="_blank" rel="noopener" data-track="whatsapp_click" data-track-label="contato">{e(EMP['telefone'])}</a><p>Canal principal para orçamentos e reservas.</p></div></li>
        <li class="contact-card">{icon('phone')}<div><h2>Telefone</h2><a href="tel:{EMP['telefone_e164']}">{e(EMP['telefone'])}</a></div></li>
        <li class="contact-card">{icon('pin')}<div><h2>Endereço</h2><p>{e(a['logradouro'])}<br>{e(a['bairro'])}, {e(a['cidade'])} – {e(a['uf'])}<br>CEP {e(a['cep'])}</p><a href="{maps_url()}" target="_blank" rel="noopener">Abrir no Google Maps</a></div></li>
        <li class="contact-card">{icon('clock')}<div><h2>Horário</h2><p>{hours}</p></div></li>
        <li class="contact-card">{icon('instagram')}<div><h2>Instagram</h2><a href="https://www.instagram.com/{e(EMP['instagram'])}/" target="_blank" rel="noopener">@{e(EMP['instagram'])}</a></div></li>
        {email_card}
        <li class="contact-card">{icon('map')}<div><h2>Área atendida</h2><p>{e(EMP['area_atendida'])}</p></div></li>
      </ul>
    </div>
    <div class="contact__side">
      <form class="contact-form" data-contact-form novalidate aria-labelledby="cf-title">
        <h2 id="cf-title">Envie sua mensagem</h2>
        <p class="muted">A mensagem abre no WhatsApp, pronta para enviar. Nada fica armazenado neste site.</p>
        <div class="field"><label for="c-nome">Nome</label><input id="c-nome" name="nome" type="text" autocomplete="name" required maxlength="80"><p class="field-error" data-error-for="nome" hidden></p></div>
        <div class="field"><label for="c-assunto">Assunto</label>
          <select id="c-assunto" name="assunto">
            <option>Orçamento de locação</option>
            <option>Aluguel mensal</option>
            <option>Locação para empresa</option>
            <option>Dúvida sobre uma reserva</option>
            <option>Outro assunto</option>
          </select>
        </div>
        <div class="field"><label for="c-msg">Mensagem</label><textarea id="c-msg" name="mensagem" rows="4" required maxlength="800"></textarea><p class="field-error" data-error-for="mensagem" hidden></p></div>
        <button class="btn btn--primary btn--block btn--lg" type="submit">{icon('whatsapp')}Enviar pelo WhatsApp</button>
      </form>
      <div class="map" data-map data-src="https://www.google.com/maps?q={map_q}&output=embed">
        <div class="map__placeholder">
          {icon('map')}
          <p>O mapa é carregado do Google Maps somente se você pedir.</p>
          <button class="btn btn--ghost btn--sm" type="button" data-map-load>Mostrar mapa</button>
        </div>
      </div>
    </div>
  </div>
</section>"""
    return page(
        "/contato/", "Contato e localização | Garopaba Loca Fácil",
        f"Fale com a Garopaba Loca Fácil pelo WhatsApp {EMP['telefone']} ou visite a loja na {a['logradouro']}, {a['bairro']}, Garopaba/SC.",
        body, active="/contato/",
        jsonld=[breadcrumb_jsonld([("Início", "/"), ("Contato", "/contato/")])],
    )


def build_privacidade():
    body = f"""
{page_hero('Privacidade', 'Política de privacidade', 'Como tratamos as informações que você compartilha com a Garopaba Loca Fácil por este site.', [('Início', '/'), ('Privacidade', None)])}
<section class="section section--flush">
  <div class="container narrow prose">
    <h2>O que este site coleta</h2>
    <p>Os formulários de solicitação e de contato <strong>não enviam dados para nenhum servidor</strong>. As informações preenchidas ficam no seu navegador e servem apenas para montar uma mensagem que você mesmo envia pelo WhatsApp. Enquanto você preenche, um rascunho fica salvo temporariamente no seu navegador (armazenamento da sessão) e é apagado quando você fecha a aba.</p>
    <h2>Mensagens pelo WhatsApp</h2>
    <p>Ao enviar uma mensagem, os dados passam a ser tratados pela {e(EMP['nome'])} exclusivamente para responder à sua solicitação, elaborar orçamentos e formalizar a locação, conforme a Lei Geral de Proteção de Dados (Lei nº 13.709/2018). O uso do WhatsApp segue também a política de privacidade do próprio aplicativo.</p>
    <h2>Mapa</h2>
    <p>O mapa da página de contato é fornecido pelo Google Maps e só é carregado quando você clica em “Mostrar mapa”.</p>
    <h2>Estatísticas de uso</h2>
    <p>Se ferramentas de estatística forem ativadas, elas só serão carregadas com o seu consentimento e servem para entender, de forma agregada, quais páginas e botões são mais usados.</p>
    <h2>Seus direitos</h2>
    <p>Você pode pedir a confirmação, correção ou exclusão dos seus dados a qualquer momento pelo WhatsApp {e(EMP['telefone'])}{(' ou pelo e-mail ' + e(EMP['email'])) if EMP.get('email') else ''}.</p>
    {('<p>' + pending('revisar este texto com o responsável jurídico da empresa') + '</p>') if DEV else ''}
  </div>
</section>"""
    return page(
        "/privacidade/", "Política de privacidade | Garopaba Loca Fácil",
        "Como a Garopaba Loca Fácil trata as informações compartilhadas pelo site e pelo WhatsApp.",
        body, noindex=False,
    )


def build_404():
    body = f"""
<section class="page-hero page-hero--center">
  <div class="container narrow">

    <h1>Esta página saiu para passear</h1>
    <p class="lead">O endereço pode ter mudado. Que tal ver a frota ou falar com a equipe?</p>
    <div class="btn-row btn-row--center">
      <a class="btn btn--primary" href="/veiculos/">Ver veículos</a>
      <a class="btn btn--ghost" href="/">Ir para o início</a>
    </div>
  </div>
</section>"""
    return page("/404.html", "Página não encontrada | Garopaba Loca Fácil", "Página não encontrada.", body, noindex=True)


# --------------------------------------------------------------------------- output

def with_base(html_text):
    """Prefixa links internos (/...) com BASE_PATH; links externos e // ficam como estão."""
    if not BASE_PATH:
        return html_text
    html_text = re.sub(r'((?:href|src|action|data-gallery-thumb)=")/(?!/)', lambda m: m.group(1) + BASE_PATH + "/", html_text)
    html_text = re.sub(r"url\(&quot;/(?!/)", f"url(&quot;{BASE_PATH}/", html_text)
    return re.sub(r"url\(/(?!/)", f"url({BASE_PATH}/", html_text)


def write(rel, content):
    if rel.endswith(".html"):
        content = with_base(content)
    out = DIST / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")


def main():
    if DIST.exists():
        shutil.rmtree(DIST)
    shutil.copytree(STATIC, DIST)

    pages = {
        "index.html": build_home(),
        "veiculos/index.html": build_catalog(),
        "reserva/index.html": build_reserva(),
        "sobre/index.html": build_sobre(),
        "avaliacoes/index.html": build_avaliacoes(),
        "perguntas-frequentes/index.html": build_faq(),
        "contato/index.html": build_contato(),
        "privacidade/index.html": build_privacidade(),
        "404.html": build_404(),
    }
    for v in FLEET:
        pages[f"veiculos/{v['slug']}/index.html"] = build_vehicle(v)
    for rel, content in pages.items():
        write(rel, content)

    today = datetime.date.today().isoformat()
    urls = [p for p in pages if p != "404.html"]
    sitemap = "".join(
        f"<url><loc>{SITE_URL}/{p.replace('index.html', '')}</loc><lastmod>{today}</lastmod></url>" for p in urls
    )
    write("sitemap.xml", f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{sitemap}</urlset>\n')
    write("robots.txt", ("User-agent: *\nDisallow: /\n" if NOINDEX else "User-agent: *\nAllow: /\n") + f"\nSitemap: {SITE_URL}/sitemap.xml\n")

    # Relatório de pendências
    if SITE_URL.startswith("http://localhost"):
        WARNINGS.append("SITE_URL não definido: canonical, Open Graph e sitemap apontam para localhost.")
    if not published_reviews():
        WARNINGS.append("Nenhuma avaliação verificada e autorizada em content/avaliacoes.json.")
    if published_reviews() and not EMP.get("google_avaliacoes_url") and not any(r.get("url") for r in published_reviews()):
        WARNINGS.append("Avaliações sem link para a fonte: preencha google_avaliacoes_url em empresa.json.")
    if not EMP.get("horarios"):
        WARNINGS.append("Horário de atendimento não informado.")
    if not EMP.get("email"):
        WARNINGS.append("E-mail não informado.")
    missing_faq = [q["pergunta"] for q in FAQ if q["resposta"] is None]
    if missing_faq:
        WARNINGS.append(f"{len(missing_faq)} perguntas frequentes sem resposta (ocultas em produção).")
    no_photo = [vehicle_name(v) for v in FLEET if not v.get("imagens")]
    if no_photo:
        WARNINGS.append("Veículos sem fotos reais (usando ilustração): " + ", ".join(no_photo))

    mode = "DESENVOLVIMENTO" if DEV else "PRODUÇÃO"
    print(f"Build {mode} concluído: {len(pages)} páginas em {DIST}")
    for w in WARNINGS:
        print("  ! " + w)


if __name__ == "__main__":
    main()
