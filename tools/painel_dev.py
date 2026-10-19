#!/usr/bin/env python3
"""Servidor de SIMULAÇÃO do painel, só para desenvolvimento local.

Imita a API do Worker (painel-api/worker.js) gravando direto nos arquivos de content/
e em static/img/frota/, e refaz o build a cada publicação. Não use em produção.

    python tools/painel_dev.py            # http://127.0.0.1:8010/painel/
    Login de teste: teste@locafacil.local / teste123
"""
import base64
import json
import re
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
ARQUIVOS = ["content/veiculos.json", "content/avisos.json", "content/empresa.json"]
FOTO_RE = re.compile(r"^static/img/frota/[a-z0-9][a-z0-9-]{0,90}\.(webp|jpg|jpeg|png)$")
EMAIL, SENHA, TOKEN = "teste@locafacil.local", "teste123", "sessao-de-teste"
estado = {"versao": 1}


def build():
    subprocess.run([sys.executable, "build.py"], cwd=ROOT, check=True, capture_output=True)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(DIST), **k)

    def log_message(self, *a):
        pass

    def responder(self, status, dados):
        corpo = json.dumps(dados, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def autorizado(self):
        return self.headers.get("Authorization") == f"Bearer {TOKEN}"

    def do_GET(self):
        if self.path.startswith("/painel-api/"):
            arquivo = ROOT / self.path.lstrip("/").split("?")[0]
            corpo = arquivo.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
            self.end_headers()
            self.wfile.write(corpo)
            return
        if not self.path.startswith("/api/"):
            return super().do_GET()
        if not self.autorizado():
            return self.responder(401, {"erro": "Sua sessão expirou. Entre novamente."})
        rota = self.path.split("?")[0]
        if rota == "/api/conteudo":
            arquivos = {}
            for c in ARQUIVOS:
                p = ROOT / c
                arquivos[c] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"avisos": []}
            return self.responder(200, {"base": f"dev{estado['versao']}", "arquivos": arquivos})
        if rota == "/api/status":
            return self.responder(200, {"status": "completed", "conclusao": "success", "commit": f"dev{estado['versao']}"})
        return self.responder(404, {"erro": "Rota não encontrada."})

    def do_POST(self):
        tamanho = int(self.headers.get("Content-Length") or 0)
        corpo = json.loads(self.rfile.read(tamanho) or b"{}")
        rota = self.path.split("?")[0]
        if rota == "/api/login":
            if corpo.get("email", "").strip().lower() == EMAIL and corpo.get("senha") == SENHA:
                return self.responder(200, {"token": TOKEN, "exp": 4102444800000, "email": EMAIL})
            return self.responder(401, {"erro": "E-mail ou senha incorretos."})
        if not self.autorizado():
            return self.responder(401, {"erro": "Sua sessão expirou. Entre novamente."})
        if rota == "/api/publicar":
            if corpo.get("base") != f"dev{estado['versao']}":
                return self.responder(409, {"erro": "Estes dados foram alterados em outro lugar. Recarregue e refaça a alteração."})
            for a in corpo.get("arquivos", []):
                caminho = a.get("caminho", "")
                if caminho in ARQUIVOS and "json" in a:
                    (ROOT / caminho).write_text(json.dumps(a["json"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                elif FOTO_RE.match(caminho) and "base64" in a:
                    (ROOT / caminho).write_bytes(base64.b64decode(a["base64"]))
                else:
                    return self.responder(400, {"erro": "Arquivo não permitido."})
            for caminho in corpo.get("remover", []):
                if FOTO_RE.match(caminho) and (ROOT / caminho).exists():
                    (ROOT / caminho).unlink()
            estado["versao"] += 1
            try:
                build()
            except subprocess.CalledProcessError as err:
                print(err.stderr.decode(errors="replace")[-800:])
                return self.responder(500, {"erro": "O conteúdo foi salvo, mas o site não conseguiu ser gerado (veja o terminal)."})
            return self.responder(200, {"commit": f"dev{estado['versao']}"})
        return self.responder(404, {"erro": "Rota não encontrada."})


if __name__ == "__main__":
    porta = int(sys.argv[1]) if len(sys.argv) > 1 else 8010
    build()
    print(f"Painel de simulação em http://127.0.0.1:{porta}/painel/  (login: {EMAIL} / {SENHA})")
    ThreadingHTTPServer(("127.0.0.1", porta), Handler).serve_forever()
