# Configurar o painel (uma vez só, cerca de 15 minutos)

O painel fica em `/painel/` no próprio site. Para ele conseguir publicar, falta ligar o **serviço do painel**: um pequeno programa gratuito na Cloudflare (o arquivo `painel-api/worker.js`) que guarda a chave do GitHub em segredo e grava as alterações no repositório.

```
Celular do cliente → /painel (e-mail e senha) → serviço na Cloudflare → GitHub → site atualizado em ~1 min
```

Nenhum dado de cliente passa por aí: só carros, avisos e dados da empresa.

---

## 1. Criar a chave do GitHub (token)

1. Entre no GitHub com a conta dona do repositório e abra **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.
2. Preencha:
   - **Token name:** `Painel Loca Fácil`
   - **Expiration:** 1 ano (anote no calendário para renovar).
   - **Repository access:** *Only select repositories* → `locadora-`
   - **Repository permissions:**
     - **Contents:** Read and write
     - **Actions:** Read-only (o painel mostra quando o site terminou de atualizar)
3. Clique em **Generate token** e copie o código (`github_pat_…`). Ele aparece uma vez só. **Não envie para ninguém.**

## 2. Criar o serviço na Cloudflare

1. Crie uma conta gratuita em **dash.cloudflare.com** (pode ser com o e-mail da locadora).
2. No menu, abra **Compute (Workers) → Workers & Pages → Create → Create Worker** (modelo *Hello World*).
3. Nome: `locafacil-painel` → **Deploy**.
4. Clique em **Edit code**, apague tudo, cole o conteúdo de `painel-api/worker.js` e clique em **Deploy**.

## 3. Colocar as configurações

No Worker, abra **Settings → Variables and Secrets → Add** e crie:

| Nome | Tipo | Valor |
| --- | --- | --- |
| `GITHUB_TOKEN` | **Secret** | o token do passo 1 |
| `GITHUB_REPO` | Text | `Rafael-CFC/locadora-` |
| `ALLOWED_ORIGIN` | Text | `https://rafael-cfc.github.io` (quando houver domínio próprio, acrescente: `https://rafael-cfc.github.io, https://www.seudominio.com.br`) |
| `PAINEL_EMAIL` | Text | o e-mail que o cliente vai usar para entrar |
| `PAINEL_SENHA` | **Secret** | uma senha forte (12+ caracteres) para o cliente |

Clique em **Deploy** para salvar.

## 4. Ligar o painel ao serviço

Copie o endereço do Worker (aparece no topo, algo como `https://locafacil-painel.SUACONTA.workers.dev`) e coloque em `static/painel/config.js`, na linha com `''`:

```js
  : 'https://locafacil-painel.SUACONTA.workers.dev';
```

Publique (commit e push). O endereço não é segredo.

## 5. Testar

Abra `https://rafael-cfc.github.io/locadora-/painel/`, entre com o e-mail e a senha do passo 3, mude um preço e toque em **Salvar e publicar**. Em cerca de 1 minuto o painel mostra **“✓ Site atualizado”**.

## Recomendado: limite de tentativas de login

Na Cloudflare, em **Security → WAF → Rate limiting rules**, crie uma regra para o endereço do Worker com o caminho `/login`: no máximo 10 pedidos por minuto por IP. O serviço já bloqueia depois de 8 senhas erradas em 15 minutos, e essa regra reforça a proteção.

---

## Manutenção

- **Trocar a senha do cliente:** altere `PAINEL_SENHA` no Worker e clique em Deploy.
- **Token vencido:** o painel mostra “perdeu o acesso ao GitHub”. Gere um token novo (passo 1) e troque `GITHUB_TOKEN`. Trocar o token também encerra todas as sessões abertas.
- **Teste local sem Cloudflare:** `python tools/painel_dev.py` e abra `http://127.0.0.1:8010/painel/` (login de teste `teste@locafacil.local` / `teste123`). Ele grava direto nos arquivos de `content/`; descarte com `git checkout -- content/` depois.
