/**
 * API do painel da Loca Fácil — Cloudflare Worker (um arquivo, sem dependências).
 *
 * Guarda a chave do GitHub em segredo e oferece ao painel (/painel) quatro rotas:
 *   POST /login      e-mail e senha  -> sessão assinada (7 dias)
 *   GET  /conteudo   veiculos, avisos e empresa (JSON) + o commit de base
 *   POST /publicar   grava JSONs e fotos em UM commit na branch principal
 *   GET  /status     situação da última publicação do site (GitHub Actions)
 *
 * Variáveis do Worker (Settings → Variables and Secrets):
 *   GITHUB_TOKEN    (segredo) token fine-grained só deste repositório: Contents read/write, Actions read
 *   GITHUB_REPO     ex.: Rafael-CFC/locadora-
 *   GITHUB_BRANCH   opcional, padrão "main"
 *   ALLOWED_ORIGIN  ex.: https://rafael-cfc.github.io (vários separados por vírgula)
 *   PAINEL_EMAIL    e-mail de acesso ao painel
 *   PAINEL_SENHA    (segredo) senha de acesso ao painel
 */

const ARQUIVOS = ['content/veiculos.json', 'content/avisos.json', 'content/empresa.json'];
const FOTO_RE = /^static\/img\/frota\/[a-z0-9][a-z0-9-]{0,90}\.(webp|jpg|jpeg|png)$/;
const MAX_FOTO_BASE64 = 8 * 1024 * 1024;
const SESSAO_DIAS = 7;
const enc = new TextEncoder();
const dec = new TextDecoder();

export default {
  async fetch(request, env) {
    const cors = corsHeaders(request.headers.get('Origin') || '', env);
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });
    try {
      const rota = `${request.method} ${new URL(request.url).pathname.replace(/\/+$/, '') || '/'}`;
      if (rota === 'POST /login') return json(await login(request, env), 200, cors);
      const usuario = await autenticar(request, env);
      if (!usuario) return json({ erro: 'Sua sessão expirou. Entre novamente.' }, 401, cors);
      if (rota === 'GET /conteudo') return json(await lerConteudo(env), 200, cors);
      if (rota === 'POST /publicar') return json(await publicar(request, env, usuario), 200, cors);
      if (rota === 'GET /status') return json(await statusPublicacao(env), 200, cors);
      return json({ erro: 'Rota não encontrada.' }, 404, cors);
    } catch (err) {
      if (!err.publico) console.error(err);
      return json({ erro: err.publico || 'Erro inesperado. Tente de novo em instantes.' }, err.status || 500, cors);
    }
  },
};

/* ------------------------------------------------------------------ utilidades */

function erro(status, publico) {
  const e = new Error(publico);
  e.status = status;
  e.publico = publico;
  return e;
}

function json(dados, status, headers) {
  return new Response(JSON.stringify(dados), {
    status,
    headers: { ...headers, 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' },
  });
}

function corsHeaders(origin, env) {
  const permitidos = (env.ALLOWED_ORIGIN || '').split(',').map((s) => s.trim()).filter(Boolean);
  const headers = { Vary: 'Origin' };
  if (permitidos.includes(origin)) {
    headers['Access-Control-Allow-Origin'] = origin;
    headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS';
    headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization';
    headers['Access-Control-Max-Age'] = '86400';
  }
  return headers;
}

function b64url(bytes) {
  let s = '';
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function deB64url(texto) {
  let s = texto.replace(/-/g, '+').replace(/_/g, '/');
  while (s.length % 4) s += '=';
  return Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
}

function base64ParaTexto(b64) {
  return dec.decode(Uint8Array.from(atob(b64.replace(/\s/g, '')), (c) => c.charCodeAt(0)));
}

/* ------------------------------------------------------------------ sessão */

// A chave das sessões deriva do token do GitHub: trocar o token encerra todas as sessões.
async function chaveSessao(env) {
  if (!env.GITHUB_TOKEN) throw erro(500, 'Painel sem configuração: falta o GITHUB_TOKEN no Worker.');
  return crypto.subtle.importKey('raw', enc.encode(`painel-sessao:${env.GITHUB_TOKEN}`), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign', 'verify']);
}

async function assinar(payload, env) {
  const corpo = b64url(enc.encode(JSON.stringify(payload)));
  const assinatura = new Uint8Array(await crypto.subtle.sign('HMAC', await chaveSessao(env), enc.encode(corpo)));
  return `${corpo}.${b64url(assinatura)}`;
}

async function autenticar(request, env) {
  const cabecalho = request.headers.get('Authorization') || '';
  const token = cabecalho.startsWith('Bearer ') ? cabecalho.slice(7) : '';
  const [corpo, assinatura] = token.split('.');
  if (!corpo || !assinatura) return null;
  try {
    const valido = await crypto.subtle.verify('HMAC', await chaveSessao(env), deB64url(assinatura), enc.encode(corpo));
    if (!valido) return null;
    const dados = JSON.parse(dec.decode(deB64url(corpo)));
    return dados.exp > Date.now() ? dados : null;
  } catch (_) {
    return null;
  }
}

// Comparação em tempo constante (compara os hashes, nunca o texto direto).
async function iguais(a, b) {
  const [ha, hb] = await Promise.all([a, b].map(async (t) => new Uint8Array(await crypto.subtle.digest('SHA-256', enc.encode(String(t))))));
  let diferenca = 0;
  for (let i = 0; i < ha.length; i += 1) diferenca |= ha[i] ^ hb[i];
  return diferenca === 0;
}

const tentativas = new Map(); // por instância do Worker; complemente com uma regra de rate limit da Cloudflare

async function login(request, env) {
  const ip = request.headers.get('CF-Connecting-IP') || 'local';
  const agora = Date.now();
  const recentes = (tentativas.get(ip) || []).filter((t) => agora - t < 15 * 60 * 1000);
  if (recentes.length >= 8) throw erro(429, 'Muitas tentativas. Aguarde 15 minutos e tente de novo.');

  const { email = '', senha = '' } = await request.json().catch(() => ({}));
  const configurado = Boolean(env.PAINEL_EMAIL && env.PAINEL_SENHA);
  const emailOk = await iguais(String(email).trim().toLowerCase(), String(env.PAINEL_EMAIL || '').trim().toLowerCase());
  const senhaOk = await iguais(String(senha), String(env.PAINEL_SENHA || ''));
  if (!configurado || !emailOk || !senhaOk) {
    recentes.push(agora);
    tentativas.set(ip, recentes);
    await new Promise((r) => setTimeout(r, 600));
    throw erro(401, 'E-mail ou senha incorretos.');
  }
  tentativas.delete(ip);
  const exp = agora + SESSAO_DIAS * 24 * 60 * 60 * 1000;
  return { token: await assinar({ email: env.PAINEL_EMAIL, exp }, env), exp, email: env.PAINEL_EMAIL };
}

/* ------------------------------------------------------------------ GitHub */

async function gh(env, caminho, init = {}) {
  const res = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}${caminho}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'locafacil-painel',
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
    },
  });
  if (!res.ok) {
    const detalhe = await res.text().catch(() => '');
    console.error('GitHub', res.status, caminho, detalhe.slice(0, 300));
    if (res.status === 401 || res.status === 403) throw erro(502, 'O painel perdeu o acesso ao GitHub (token vencido ou sem permissão). Avise quem fez o site.');
    if (res.status === 409 || res.status === 422) throw erro(409, 'O site foi alterado ao mesmo tempo por outro lugar. Recarregue o painel e tente de novo.');
    throw erro(502, 'Não foi possível falar com o GitHub agora. Tente de novo em instantes.');
  }
  return res.status === 204 ? null : res.json();
}

const branch = (env) => env.GITHUB_BRANCH || 'main';

async function lerConteudo(env) {
  const ref = await gh(env, `/git/ref/heads/${branch(env)}`);
  const base = ref.object.sha;
  const arquivos = {};
  await Promise.all(ARQUIVOS.map(async (caminho) => {
    const f = await gh(env, `/contents/${caminho}?ref=${base}`);
    arquivos[caminho] = JSON.parse(base64ParaTexto(f.content));
  }));
  return { base, arquivos };
}

function validarJson(caminho, dados) {
  const ok = {
    'content/veiculos.json': Array.isArray(dados?.veiculos),
    'content/avisos.json': Array.isArray(dados?.avisos),
    'content/empresa.json': dados && typeof dados === 'object' && typeof dados.whatsapp === 'string',
  }[caminho];
  if (!ok) throw erro(400, `Conteúdo inválido em ${caminho}.`);
}

async function publicar(request, env, usuario) {
  const corpo = await request.json().catch(() => null);
  if (!corpo || typeof corpo.base !== 'string') throw erro(400, 'Pedido inválido.');
  const arquivos = Array.isArray(corpo.arquivos) ? corpo.arquivos : [];
  const remover = Array.isArray(corpo.remover) ? corpo.remover : [];
  if (!arquivos.length && !remover.length) throw erro(400, 'Nada para publicar.');

  const entradas = [];
  const jsonsAlterados = [];
  for (const a of arquivos) {
    if (ARQUIVOS.includes(a.caminho) && a.json !== undefined) {
      validarJson(a.caminho, a.json);
      jsonsAlterados.push(a.caminho);
      entradas.push({ caminho: a.caminho, conteudo: `${JSON.stringify(a.json, null, 2)}\n`, encoding: 'utf-8' });
    } else if (FOTO_RE.test(a.caminho || '') && typeof a.base64 === 'string') {
      if (a.base64.length > MAX_FOTO_BASE64) throw erro(413, 'Foto grande demais. Use uma foto menor.');
      entradas.push({ caminho: a.caminho, conteudo: a.base64, encoding: 'base64' });
    } else {
      throw erro(400, 'Arquivo não permitido.');
    }
  }
  for (const caminho of remover) if (!FOTO_RE.test(caminho)) throw erro(400, 'Remoção não permitida.');

  const ref = await gh(env, `/git/ref/heads/${branch(env)}`);
  const head = ref.object.sha;
  // Se alguém publicou depois que o painel carregou, só seguimos se os mesmos arquivos não mudaram.
  if (head !== corpo.base) {
    const cmp = await gh(env, `/compare/${corpo.base}...${head}`);
    const mudados = new Set((cmp.files || []).map((f) => f.filename));
    if (jsonsAlterados.some((c) => mudados.has(c))) {
      throw erro(409, 'Estes dados foram alterados em outro lugar depois que você abriu o painel. Recarregue e refaça a alteração.');
    }
  }

  const commitAtual = await gh(env, `/git/commits/${head}`);
  const arvore = [];
  for (const ent of entradas) {
    const blob = await gh(env, '/git/blobs', { method: 'POST', body: JSON.stringify({ content: ent.conteudo, encoding: ent.encoding }) });
    arvore.push({ path: ent.caminho, mode: '100644', type: 'blob', sha: blob.sha });
  }
  for (const caminho of remover) arvore.push({ path: caminho, mode: '100644', type: 'blob', sha: null });

  const tree = await gh(env, '/git/trees', { method: 'POST', body: JSON.stringify({ base_tree: commitAtual.tree.sha, tree: arvore }) });
  const mensagem = `Painel: ${String(corpo.mensagem || 'atualiza o site').slice(0, 100)}\n\nAlterado por ${usuario.email} pelo painel do site.`;
  const commit = await gh(env, '/git/commits', { method: 'POST', body: JSON.stringify({ message: mensagem, tree: tree.sha, parents: [head] }) });
  await gh(env, `/git/refs/heads/${branch(env)}`, { method: 'PATCH', body: JSON.stringify({ sha: commit.sha, force: false }) });
  return { commit: commit.sha };
}

async function statusPublicacao(env) {
  try {
    const r = await gh(env, `/actions/runs?branch=${branch(env)}&per_page=5`);
    const run = (r.workflow_runs || []).find((w) => w.event === 'push' || w.event === 'workflow_dispatch') || (r.workflow_runs || [])[0];
    if (!run) return { status: 'desconhecido' };
    return { status: run.status, conclusao: run.conclusion, commit: run.head_sha, atualizado: run.updated_at };
  } catch (_) {
    return { status: 'desconhecido' };
  }
}
