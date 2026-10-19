/* Painel da Loca Fácil: edita carros, avisos e dados da empresa e publica no site. */
(() => {
  'use strict';

  const API = String(window.PAINEL_API || '').replace(/\/+$/, '');
  const SITE = new URL('../', location.href).href;
  const ARQ = { carros: 'content/veiculos.json', avisos: 'content/avisos.json', empresa: 'content/empresa.json' };
  const SESSAO = 'locafacil-painel-sessao';
  const CATEGORIAS = ['Compacto', 'Hatch', 'Sedã', 'SUV', 'Picape', 'Utilitário'];
  const COMBUSTIVEIS = ['Flex', 'Gasolina', 'Etanol', 'Diesel', 'Híbrido', 'Elétrico'];
  const FOCOS = [['50% 72%', 'Carro um pouco abaixo do centro'], ['50% 82%', 'Carro na parte de baixo'], ['50% 50%', 'Carro no centro'], ['50% 30%', 'Carro na parte de cima']];
  const MAX_LADO = 1600;

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const clone = (o) => JSON.parse(JSON.stringify(o));
  const igual = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const slug = (t) => String(t || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'carro';
  const brl = (n) => `R$ ${Number(n).toLocaleString('pt-BR')}`;

  const estado = {
    base: null,
    orig: {},
    dados: {},
    fotosNovas: new Map(),   // caminho -> { base64, url }  (ainda não publicadas)
    fotosEnviadas: new Map(), // src -> url (publicadas, enquanto o site ainda atualiza)
    removidas: new Set(),     // caminhos de fotos publicadas que saíram do site
    aba: 'carros',
    editando: null,           // índice do carro ou 'novo'
    rascunho: null,
  };

  /* ------------------------------------------------------------ utilidades de tela */
  const toastEl = $('[data-toast]');
  let toastTimer;
  function toast(msg) {
    toastEl.textContent = msg;
    toastEl.classList.add('is-visivel');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove('is-visivel'), 3600);
  }
  const carregando = (on) => { $('[data-carregando]').hidden = !on; };

  function confirmar(texto, rotulo = 'Confirmar') {
    const dlg = $('[data-dialogo]');
    $('[data-dialogo-texto]', dlg).textContent = texto;
    $('[data-dialogo-ok]', dlg).textContent = rotulo;
    if (typeof dlg.showModal !== 'function') return Promise.resolve(window.confirm(texto));
    dlg.returnValue = '';
    dlg.showModal();
    return new Promise((ok) => dlg.addEventListener('close', () => ok(dlg.returnValue === 'sim'), { once: true }));
  }

  const sessao = {
    get() { try { const s = JSON.parse(localStorage.getItem(SESSAO)); return s && s.exp > Date.now() ? s : null; } catch (_) { return null; } },
    set(s) { try { localStorage.setItem(SESSAO, JSON.stringify(s)); } catch (_) { /* modo privado */ } },
    limpar() { try { localStorage.removeItem(SESSAO); } catch (_) { /* nada */ } },
  };

  async function api(rota, { method = 'GET', body } = {}) {
    const s = sessao.get();
    let res;
    try {
      res = await fetch(API + rota, {
        method,
        headers: { 'Content-Type': 'application/json', ...(s ? { Authorization: `Bearer ${s.token}` } : {}) },
        body: body ? JSON.stringify(body) : undefined,
      });
    } catch (_) {
      throw new Error('Sem conexão com o serviço do painel. Verifique a internet e tente de novo.');
    }
    const dados = await res.json().catch(() => ({}));
    if (res.status === 401 && rota !== '/login') {
      sair(dados.erro || 'Sua sessão expirou. Entre novamente.');
      throw new Error(dados.erro || 'Sessão expirada');
    }
    if (!res.ok) {
      const e = new Error(dados.erro || 'Algo deu errado. Tente de novo.');
      e.status = res.status;
      throw e;
    }
    return dados;
  }

  /* ------------------------------------------------------------ login */
  const formLogin = $('[data-login]');
  const erroLogin = $('[data-login-erro]');
  if (!API) {
    $('[data-sem-api]').hidden = false;
    $('button[type="submit"]', formLogin).disabled = true;
  }
  $('[data-ver-senha]').addEventListener('click', (ev) => {
    const campo = formLogin.elements.senha;
    const mostrar = campo.type === 'password';
    campo.type = mostrar ? 'text' : 'password';
    ev.currentTarget.textContent = mostrar ? 'Ocultar' : 'Mostrar';
  });
  formLogin.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const email = formLogin.elements.email.value.trim();
    const senha = formLogin.elements.senha.value;
    erroLogin.hidden = true;
    if (!email || !senha) { erroLogin.textContent = 'Preencha o e-mail e a senha.'; erroLogin.hidden = false; return; }
    const btn = $('button[type="submit"]', formLogin);
    btn.classList.add('is-carregando');
    try {
      const r = await api('/login', { method: 'POST', body: { email, senha } });
      sessao.set({ token: r.token, exp: r.exp, email: r.email });
      formLogin.elements.senha.value = '';
      await carregar();
    } catch (err) {
      erroLogin.textContent = err.message;
      erroLogin.hidden = false;
    } finally {
      btn.classList.remove('is-carregando');
    }
  });

  function mostrarTela(nome) {
    $$('[data-tela]').forEach((t) => { t.hidden = t.dataset.tela !== nome; });
  }

  function sair(motivo) {
    sessao.limpar();
    mostrarTela('login');
    if (motivo) { erroLogin.textContent = motivo; erroLogin.hidden = false; }
  }
  $('[data-sair]').addEventListener('click', async () => {
    if (temAlteracoes() && !(await confirmar('Você tem alterações não publicadas. Sair mesmo assim?', 'Sair'))) return;
    sair();
  });
  $('[data-ver-site]').href = SITE;

  /* ------------------------------------------------------------ carregar */
  async function carregar() {
    carregando(true);
    try {
      const r = await api('/conteudo');
      estado.base = r.base;
      estado.orig = clone(r.arquivos);
      estado.dados = clone(r.arquivos);
      estado.dados[ARQ.avisos] = estado.dados[ARQ.avisos] || { avisos: [] };
      estado.orig[ARQ.avisos] = estado.orig[ARQ.avisos] || { avisos: [] };
      estado.fotosNovas.clear();
      estado.removidas.clear();
      estado.editando = null;
      mostrarTela('painel');
      irPara(estado.aba);
    } catch (err) {
      if (err.status !== 401) toast(err.message);
    } finally {
      carregando(false);
    }
  }

  /* ------------------------------------------------------------ alterações pendentes */
  const carros = () => estado.dados[ARQ.carros].veiculos;
  const avisos = () => estado.dados[ARQ.avisos].avisos;
  const empresa = () => estado.dados[ARQ.empresa];

  function fotosReferenciadas() {
    const usadas = new Set();
    carros().forEach((v) => (v.imagens || []).forEach((i) => usadas.add(`static/${String(i.src).replace(/^\/+/, '')}`)));
    if (estado.rascunho) (estado.rascunho.imagens || []).forEach((i) => usadas.add(`static/${String(i.src).replace(/^\/+/, '')}`));
    return usadas;
  }

  function limparFotosSoltas() {
    const usadas = fotosReferenciadas();
    for (const [caminho, f] of estado.fotosNovas) {
      if (!usadas.has(caminho)) { URL.revokeObjectURL(f.url); estado.fotosNovas.delete(caminho); }
    }
  }

  function alteracoes() {
    const nomes = { [ARQ.carros]: 'Carros', [ARQ.avisos]: 'Avisos', [ARQ.empresa]: 'Empresa' };
    const arquivos = Object.values(ARQ).filter((k) => !igual(estado.dados[k], estado.orig[k]));
    return { arquivos, nomes: arquivos.map((k) => nomes[k]), fotos: estado.fotosNovas.size };
  }
  const temAlteracoes = () => { const a = alteracoes(); return a.arquivos.length > 0 || a.fotos > 0 || estado.removidas.size > 0; };

  function atualizarBarra() {
    const a = alteracoes();
    const barra = $('[data-barra-publicar]');
    barra.hidden = !temAlteracoes() || estado.editando !== null;
    const partes = [...a.nomes];
    if (a.fotos) partes.push(`${a.fotos} foto${a.fotos > 1 ? 's' : ''} nova${a.fotos > 1 ? 's' : ''}`);
    $('[data-resumo-alteracoes]').textContent = partes.join(' · ') || 'Fotos removidas';
  }

  window.addEventListener('beforeunload', (ev) => {
    if (temAlteracoes()) { ev.preventDefault(); ev.returnValue = ''; }
  });

  /* ------------------------------------------------------------ publicar */
  async function publicar(botao) {
    const a = alteracoes();
    if (!temAlteracoes()) { toast('Não há alterações para publicar.'); return false; }
    const usadas = fotosReferenciadas();
    const arquivos = [
      ...[...estado.fotosNovas].filter(([c]) => usadas.has(c)).map(([caminho, f]) => ({ caminho, base64: f.base64 })),
      ...a.arquivos.map((caminho) => ({ caminho, json: estado.dados[caminho] })),
    ];
    const remover = [...estado.removidas].filter((c) => !usadas.has(c));
    const mensagem = [...a.nomes, a.fotos ? `${a.fotos} foto(s)` : ''].filter(Boolean).join(', ').toLowerCase() || 'fotos';
    botao?.classList.add('is-carregando');
    try {
      const r = await api('/publicar', { method: 'POST', body: { base: estado.base, mensagem: `atualiza ${mensagem}`, arquivos, remover } });
      for (const [caminho, f] of estado.fotosNovas) estado.fotosEnviadas.set(caminho.replace(/^static\//, ''), f.url);
      estado.fotosNovas.clear();
      estado.removidas.clear();
      estado.base = r.commit;
      estado.orig = clone(estado.dados);
      atualizarBarra();
      acompanhar(r.commit);
      return true;
    } catch (err) {
      if (err.status === 409) {
        const recarregar = await confirmar(`${err.message}`, 'Recarregar');
        if (recarregar) await carregar();
      } else {
        toast(err.message);
      }
      return false;
    } finally {
      botao?.classList.remove('is-carregando');
    }
  }
  $('[data-publicar]').addEventListener('click', (ev) => publicar(ev.currentTarget));
  $('[data-descartar]').addEventListener('click', async () => {
    if (!(await confirmar('Descartar todas as alterações que ainda não foram publicadas?', 'Descartar'))) return;
    estado.dados = clone(estado.orig);
    estado.removidas.clear();
    limparFotosSoltas();
    irPara(estado.aba);
  });

  let timerStatus;
  function acompanhar(commit) {
    const box = $('[data-status]');
    const mostrar = (html, erro) => { box.hidden = false; box.innerHTML = `<div class="p-status__caixa${erro ? ' is-erro' : ''}">${html}</div>`; };
    mostrar('<span class="p-pulso"></span><span>Publicando no site… leva cerca de 1 minuto.</span>');
    const inicio = Date.now();
    clearTimeout(timerStatus);
    const checar = async () => {
      let s = { status: 'desconhecido' };
      try { s = await api('/status'); } catch (_) { /* tenta de novo */ }
      const meu = s.commit && commit.startsWith(s.commit.slice(0, 7)) && s.commit === commit;
      if (meu && s.status === 'completed') {
        if (s.conclusao === 'success') {
          mostrar(`<span>✓ Site atualizado.</span> <a href="${esc(SITE)}" target="_blank" rel="noopener">Ver no site</a>`);
        } else if (s.conclusao === 'cancelled') {
          mostrar('<span>✓ Publicado. O site atualiza junto com a próxima publicação, em instantes.</span>');
        } else {
          mostrar('<span>A publicação foi salva, mas o site não conseguiu atualizar. Avise quem fez o site.</span>', true);
        }
        return;
      }
      if (Date.now() - inicio > 4 * 60 * 1000 || (s.status === 'desconhecido' && Date.now() - inicio > 90 * 1000)) {
        mostrar(`<span>Publicado. O site deve atualizar em instantes.</span> <a href="${esc(SITE)}" target="_blank" rel="noopener">Ver no site</a>`);
        return;
      }
      timerStatus = setTimeout(checar, 6000);
    };
    timerStatus = setTimeout(checar, 8000);
  }

  /* ------------------------------------------------------------ navegação */
  $$('[data-aba]').forEach((b) => b.addEventListener('click', async () => {
    if (estado.editando !== null && !(await sairDoEditor())) return;
    irPara(b.dataset.aba);
  }));

  function irPara(aba) {
    estado.aba = aba;
    $$('[data-aba]').forEach((b) => (b.dataset.aba === aba ? b.setAttribute('aria-current', 'page') : b.removeAttribute('aria-current')));
    $$('[data-vista]').forEach((v) => { v.hidden = v.dataset.vista !== aba; });
    ({ carros: renderCarros, avisos: renderAvisos, empresa: renderEmpresa })[aba]();
    atualizarBarra();
    window.scrollTo(0, 0);
  }

  /* ------------------------------------------------------------ fotos */
  const urlFoto = (src) => {
    const limpo = String(src || '').replace(/^\/+/, '');
    const nova = estado.fotosNovas.get(`static/${limpo}`);
    if (nova) return nova.url;
    return estado.fotosEnviadas.get(limpo) || SITE + limpo.split('/').map(encodeURIComponent).join('/');
  };

  const blobParaBase64 = (blob) => new Promise((ok, falha) => {
    const r = new FileReader();
    r.onload = () => ok(String(r.result).split(',')[1]);
    r.onerror = falha;
    r.readAsDataURL(blob);
  });

  async function processarFoto(arquivo) {
    const bmp = await createImageBitmap(arquivo); // já aplica a orientação da câmera
    const escala = Math.min(1, MAX_LADO / Math.max(bmp.width, bmp.height));
    const w = Math.round(bmp.width * escala);
    const h = Math.round(bmp.height * escala);
    const canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    canvas.getContext('2d').drawImage(bmp, 0, 0, w, h);
    let blob = await new Promise((ok) => canvas.toBlob(ok, 'image/webp', 0.82));
    let ext = 'webp';
    if (!blob || blob.type !== 'image/webp') { // Safari antigo não gera WebP
      blob = await new Promise((ok) => canvas.toBlob(ok, 'image/jpeg', 0.85));
      ext = 'jpg';
    }
    return { base64: await blobParaBase64(blob), url: URL.createObjectURL(blob), w, h, ext };
  }

  /* ------------------------------------------------------------ lista de carros */
  const nomeCarro = (v) => [v.marca, v.modelo, v.versao].filter(Boolean).join(' ') || 'Carro sem nome';
  const temPreco = (v) => v.preco_diaria !== '' && v.preco_diaria !== null && v.preco_diaria !== undefined;

  function renderCarros() {
    const lista = carros();
    const naHome = lista.filter((v) => v.destaque_home).length;
    $('[data-vista="carros"]').innerHTML = `
      <div class="p-cabecalho">
        <div><h2>Carros</h2><p class="p-muted">${lista.length} carro${lista.length === 1 ? '' : 's'} no site · ${naHome} na página inicial</p></div>
        <button type="button" class="p-btn p-btn--primario" data-novo-carro>+ Adicionar carro</button>
      </div>
      <div class="p-carros">
        ${lista.length ? lista.map((v, i) => {
          const foto = (v.imagens || [])[0];
          return `
          <article class="p-carro">
            <div class="p-carro__foto">${foto ? `<img src="${esc(urlFoto(foto.src))}" alt="" loading="lazy">` : 'Sem foto'}</div>
            <div class="p-carro__info">
              <h3>${esc(nomeCarro(v))}</h3>
              <p><span class="p-carro__preco">${temPreco(v) ? `${brl(v.preco_diaria)}/dia` : 'Preço sob consulta'}</span> · ${esc(v.categoria || '')}</p>
              <div class="p-carro__tags">
                ${v.destaque_home ? '<span class="p-tag p-tag--sol">Na página inicial</span>' : ''}
                ${(v.imagens || []).length ? `<span class="p-tag">${v.imagens.length} foto${v.imagens.length > 1 ? 's' : ''}</span>` : '<span class="p-tag p-tag--sol">Falta foto</span>'}
              </div>
            </div>
            <div class="p-carro__acoes">
              <button type="button" class="p-btn p-btn--leve" data-editar="${i}">Editar</button>
              <div class="p-carro__ordem">
                <button type="button" class="p-btn p-btn--icone" data-subir="${i}" aria-label="Mover ${esc(nomeCarro(v))} para cima" ${i === 0 ? 'disabled' : ''}>↑</button>
                <button type="button" class="p-btn p-btn--icone" data-descer="${i}" aria-label="Mover ${esc(nomeCarro(v))} para baixo" ${i === lista.length - 1 ? 'disabled' : ''}>↓</button>
              </div>
            </div>
          </article>`;
        }).join('') : '<p class="p-vazio">Nenhum carro cadastrado ainda.</p>'}
      </div>
      <p class="p-muted" style="margin-top:1rem;font-size:.875rem">A ordem desta lista é a ordem do site. A página inicial mostra os 3 primeiros marcados como “Na página inicial”.</p>`;
  }

  $('[data-vista="carros"]').addEventListener('click', (ev) => {
    const b = ev.target.closest('button');
    if (!b) return;
    const lista = carros();
    if (b.matches('[data-novo-carro]')) abrirEditor('novo');
    else if (b.dataset.editar) abrirEditor(Number(b.dataset.editar));
    else if (b.dataset.subir || b.dataset.descer) {
      const i = Number(b.dataset.subir ?? b.dataset.descer);
      const j = b.dataset.subir ? i - 1 : i + 1;
      [lista[i], lista[j]] = [lista[j], lista[i]];
      renderCarros();
      atualizarBarra();
    }
  });

  /* ------------------------------------------------------------ editor de carro */
  function abrirEditor(indice) {
    estado.editando = indice;
    estado.rascunho = indice === 'novo'
      ? { marca: '', modelo: '', versao: '', categoria: 'Hatch', preco_diaria: '', destaque_home: false, imagens: [], passageiros: 5, cambio: 'manual', ar_condicionado: 'sim', porta_malas_litros: '', combustivel: 'Flex', destaques_empresa: [], resumo: '', slug: '', carroceria: 'hatch', cor_ilustracao: '' }
      : clone(carros()[indice]);
    estado.rascunhoOrig = clone(estado.rascunho);
    $$('[data-vista]').forEach((v) => { v.hidden = v.dataset.vista !== 'editor'; });
    renderEditor();
    atualizarBarra();
    window.scrollTo(0, 0);
  }

  const opcoes = (nome, lista, atual) => `<div class="p-opcoes" role="radiogroup">${lista.map(([valor, rotulo]) => `
    <label><input type="radio" name="${nome}" value="${esc(valor)}" ${String(atual) === valor ? 'checked' : ''}><span>${esc(rotulo)}</span></label>`).join('')}</div>`;

  function renderEditor() {
    const v = estado.rascunho;
    const novo = estado.editando === 'novo';
    $('[data-vista="editor"]').innerHTML = `
      <button type="button" class="p-voltar" data-cancelar>← Voltar para a lista</button>
      <div class="p-cabecalho"><div><h2>${novo ? 'Novo carro' : esc(nomeCarro(v))}</h2></div></div>
      <form data-form-carro novalidate>
        <section class="p-bloco">
          <h3>Fotos</h3>
          <p class="p-bloco__dica">A primeira é a capa. Use fotos com o carro inteiro, de dia. Elas são reduzidas automaticamente.</p>
          <div class="p-fotos">
            ${(v.imagens || []).map((img, i) => `
              <div class="p-foto">
                <div class="p-foto__img"><img src="${esc(urlFoto(img.src))}" alt="" style="object-position:${esc(img.foco || '50% 72%')}">
                  ${i === 0 ? '<span class="p-foto__capa">Capa</span>' : ''}
                  ${estado.fotosNovas.has(`static/${String(img.src).replace(/^\/+/, '')}`) ? '<span class="p-foto__nova">Nova</span>' : ''}
                </div>
                <div class="p-foto__corpo">
                  <select data-foco="${i}" aria-label="Posição do carro na foto ${i + 1}">${FOCOS.map(([val, rot]) => `<option value="${val}" ${img.foco === val ? 'selected' : ''}>${rot}</option>`).join('')}</select>
                  <div class="p-foto__botoes">
                    ${i > 0 ? `<button type="button" class="p-btn p-btn--leve" data-capa="${i}">Usar como capa</button>` : ''}
                    <button type="button" class="p-btn p-btn--leve" data-tirar-foto="${i}">Remover</button>
                  </div>
                </div>
              </div>`).join('')}
            <label class="p-add-foto" data-add-foto>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>
              <span>Adicionar fotos</span>
              <input type="file" accept="image/*" multiple hidden data-input-foto>
            </label>
          </div>
        </section>

        <section class="p-bloco">
          <h3>Dados principais</h3>
          <div class="p-grade p-grade--3">
            <label class="p-field" data-campo-wrap="marca"><span>Marca *</span><input name="marca" value="${esc(v.marca)}" placeholder="Ex.: Renault" autocomplete="off"></label>
            <label class="p-field" data-campo-wrap="modelo"><span>Modelo *</span><input name="modelo" value="${esc(v.modelo)}" placeholder="Ex.: Kwid" autocomplete="off"></label>
            <label class="p-field"><span>Versão</span><input name="versao" value="${esc(v.versao)}" placeholder="Ex.: 1.0" autocomplete="off"></label>
          </div>
          <div class="p-grade">
            <label class="p-field"><span>Preço da diária (R$)</span><input name="preco_diaria" type="number" inputmode="numeric" min="0" step="1" value="${esc(v.preco_diaria ?? '')}" placeholder="Vazio = sob consulta"><small>Só números, sem centavos.</small></label>
            <label class="p-field"><span>Categoria</span><select name="categoria">${CATEGORIAS.map((c) => `<option ${v.categoria === c ? 'selected' : ''}>${c}</option>`).join('')}</select></label>
          </div>
          <label class="p-switch"><input type="checkbox" name="destaque_home" ${v.destaque_home ? 'checked' : ''}><span class="p-switch__trilho"></span><span>Mostrar na página inicial</span></label>
        </section>

        <section class="p-bloco">
          <h3>Características</h3>
          <div class="p-field"><span>Câmbio</span>${opcoes('cambio', [['manual', 'Manual'], ['automatico', 'Automático'], ['confirmar', 'A confirmar']], v.cambio)}</div>
          <div class="p-field"><span>Ar-condicionado</span>${opcoes('ar_condicionado', [['sim', 'Sim'], ['nao', 'Não'], ['confirmar', 'A confirmar']], v.ar_condicionado)}</div>
          <div class="p-grade p-grade--3">
            <label class="p-field"><span>Passageiros</span><input name="passageiros" type="number" inputmode="numeric" min="1" max="9" value="${esc(v.passageiros ?? 5)}"></label>
            <label class="p-field"><span>Porta-malas (litros)</span><input name="porta_malas_litros" type="number" inputmode="numeric" min="0" value="${esc(v.porta_malas_litros ?? '')}" placeholder="Ex.: 290"></label>
            <label class="p-field"><span>Combustível</span><select name="combustivel">${COMBUSTIVEIS.map((c) => `<option ${v.combustivel === c ? 'selected' : ''}>${c}</option>`).join('')}</select></label>
          </div>
          <label class="p-field"><span>Destaques</span><input name="destaques_empresa" value="${esc((v.destaques_empresa || []).join(', '))}" placeholder="Ex.: Econômico, Som Bluetooth"><small>Separe por vírgula. Aparecem como etiquetas no site.</small></label>
          <label class="p-field"><span>Descrição curta</span><textarea name="resumo" placeholder="Para quem o carro é indicado, em uma ou duas frases.">${esc(v.resumo || '')}</textarea></label>
        </section>

        <div class="p-editor__rodape">
          ${novo ? '<span></span>' : '<button type="button" class="p-btn p-btn--leve" data-excluir style="color:var(--perigo)">Excluir carro</button>'}
          <div style="display:flex;gap:.5rem;flex-wrap:wrap">
            <button type="button" class="p-btn p-btn--leve" data-cancelar>Cancelar</button>
            <button type="submit" class="p-btn p-btn--primario" data-salvar-carro>Salvar e publicar</button>
          </div>
        </div>
      </form>`;
  }

  function lerFormulario() {
    const f = $('[data-form-carro]');
    if (!f) return;
    const v = estado.rascunho;
    const num = (val) => (val === '' ? '' : Math.max(0, Math.round(Number(val))));
    v.marca = f.elements.marca.value.trim();
    v.modelo = f.elements.modelo.value.trim();
    v.versao = f.elements.versao.value.trim();
    v.preco_diaria = num(f.elements.preco_diaria.value);
    v.categoria = f.elements.categoria.value;
    v.destaque_home = f.elements.destaque_home.checked;
    v.cambio = f.elements.cambio.value || 'confirmar';
    v.ar_condicionado = f.elements.ar_condicionado.value || 'confirmar';
    v.passageiros = num(f.elements.passageiros.value) || 5;
    v.porta_malas_litros = num(f.elements.porta_malas_litros.value);
    v.combustivel = f.elements.combustivel.value;
    v.destaques_empresa = f.elements.destaques_empresa.value.split(',').map((t) => t.trim()).filter(Boolean);
    v.resumo = f.elements.resumo.value.trim();
  }

  const editor = $('[data-vista="editor"]');
  editor.addEventListener('input', lerFormulario);
  editor.addEventListener('change', async (ev) => {
    if (ev.target.matches('[data-foco]')) {
      estado.rascunho.imagens[Number(ev.target.dataset.foco)].foco = ev.target.value;
      const img = ev.target.closest('.p-foto').querySelector('img');
      if (img) img.style.objectPosition = ev.target.value;
      return;
    }
    if (ev.target.matches('[data-input-foto]')) {
      lerFormulario();
      const arquivos = Array.from(ev.target.files || []);
      if (!arquivos.length) return;
      const caixa = ev.target.closest('[data-add-foto]');
      caixa.classList.add('p-processando');
      caixa.querySelector('span').textContent = 'Preparando fotos…';
      const base = slug(`${estado.rascunho.marca} ${estado.rascunho.modelo}`);
      let falhas = 0;
      for (const [n, arq] of arquivos.entries()) {
        try {
          const f = await processarFoto(arq);
          const nome = `${base}-${Date.now().toString(36)}${n}.${f.ext}`;
          const caminho = `static/img/frota/${nome}`;
          estado.fotosNovas.set(caminho, { base64: f.base64, url: f.url });
          estado.rascunho.imagens.push({ src: `img/frota/${nome}`, alt: '', foco: '50% 72%', w: f.w, h: f.h });
        } catch (_) {
          falhas += 1;
        }
      }
      if (falhas) toast(`${falhas} foto(s) não puderam ser lidas. Use fotos JPG ou PNG.`);
      renderEditor();
    }
  });

  editor.addEventListener('click', async (ev) => {
    const b = ev.target.closest('button');
    if (!b) return;
    const imgs = estado.rascunho?.imagens;
    if (b.dataset.capa) {
      lerFormulario();
      const [foto] = imgs.splice(Number(b.dataset.capa), 1);
      imgs.unshift(foto);
      renderEditor();
    } else if (b.dataset.tirarFoto) {
      lerFormulario();
      imgs.splice(Number(b.dataset.tirarFoto), 1);
      renderEditor();
    } else if (b.matches('[data-cancelar]')) {
      if (await sairDoEditor()) irPara('carros');
    } else if (b.matches('[data-excluir]')) {
      if (!(await confirmar(`Excluir o ${nomeCarro(estado.rascunho)} do site?`, 'Excluir'))) return;
      const removido = carros().splice(estado.editando, 1)[0];
      marcarFotosRemovidas(removido.imagens || []);
      fecharEditor();
      const ok = await publicar();
      if (ok) toast('Carro excluído.');
      irPara('carros');
    }
  });

  editor.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    lerFormulario();
    const v = estado.rascunho;
    const f = ev.target;
    $$('[data-campo-wrap]', f).forEach((w) => w.classList.remove('is-erro'));
    const faltando = ['marca', 'modelo'].filter((c) => !v[c]);
    if (faltando.length) {
      faltando.forEach((c) => $(`[data-campo-wrap="${c}"]`, f).classList.add('is-erro'));
      f.elements[faltando[0]].focus();
      toast('Preencha a marca e o modelo.');
      return;
    }
    const naHome = carros().filter((c, i) => c.destaque_home && i !== estado.editando).length;
    if (v.destaque_home && naHome >= 3) toast('Atenção: a página inicial mostra só os 3 primeiros carros marcados.');
    if (estado.editando === 'novo') {
      carros().push(v);
    } else {
      const antigas = (carros()[estado.editando].imagens || []).filter((a) => !v.imagens.some((n) => n.src === a.src));
      carros()[estado.editando] = v;
      marcarFotosRemovidas(antigas);
    }
    fecharEditor();
    const ok = await publicar(f.querySelector('[data-salvar-carro]'));
    irPara('carros');
    if (ok) toast('Carro salvo e enviado para o site.');
  });

  function marcarFotosRemovidas(lista) {
    for (const img of lista) {
      const caminho = `static/${String(img.src).replace(/^\/+/, '')}`;
      if (estado.fotosNovas.has(caminho)) continue; // nunca foi publicada
      estado.removidas.add(caminho);
    }
  }

  function fecharEditor() {
    estado.editando = null;
    estado.rascunho = null;
    estado.rascunhoOrig = null;
    limparFotosSoltas();
  }

  async function sairDoEditor() {
    lerFormulario();
    if (estado.rascunho && !igual(estado.rascunho, estado.rascunhoOrig)
      && !(await confirmar('Sair sem salvar as alterações deste carro?', 'Sair sem salvar'))) return false;
    fecharEditor();
    return true;
  }

  /* ------------------------------------------------------------ avisos */
  function renderAvisos() {
    const lista = avisos();
    $('[data-vista="avisos"]').innerHTML = `
      <div class="p-cabecalho">
        <div><h2>Avisos</h2><p class="p-muted">Faixa amarela no topo de todas as páginas do site.</p></div>
        <button type="button" class="p-btn p-btn--primario" data-novo-aviso>+ Novo aviso</button>
      </div>
      ${lista.length ? lista.map((a, i) => `
        <article class="p-aviso" data-aviso="${i}">
          <div class="p-aviso__topo">
            <label class="p-switch"><input type="checkbox" data-av="ativo" ${a.ativo ? 'checked' : ''}><span class="p-switch__trilho"></span><span>${a.ativo ? 'Ativo' : 'Desativado'}</span></label>
            <button type="button" class="p-btn p-btn--leve" data-tirar-aviso="${i}">Remover</button>
          </div>
          <label class="p-field"><span>Texto</span><input data-av="texto" value="${esc(a.texto)}" maxlength="140" placeholder="Ex.: Feriado de novembro: reserve com antecedência."></label>
          <div class="p-grade">
            <label class="p-field"><span>Texto do link (opcional)</span><input data-av="link_texto" value="${esc(a.link_texto)}" placeholder="Ex.: Ver carros"></label>
            <label class="p-field"><span>Endereço do link (opcional)</span><input data-av="link_url" value="${esc(a.link_url)}" placeholder="Ex.: /veiculos/"></label>
            <label class="p-field"><span>Mostrar a partir de</span><input type="date" data-av="inicio" value="${esc(a.inicio)}"></label>
            <label class="p-field"><span>Mostrar até</span><input type="date" data-av="fim" value="${esc(a.fim)}"></label>
          </div>
          <p class="p-previa" data-previa>${esc(a.texto || 'Prévia do aviso')}</p>
        </article>`).join('') : '<p class="p-vazio">Nenhum aviso. Use para feriados, promoções ou horários especiais.</p>'}`;
  }

  const vistaAvisos = $('[data-vista="avisos"]');
  vistaAvisos.addEventListener('input', (ev) => {
    const card = ev.target.closest('[data-aviso]');
    const campo = ev.target.dataset.av;
    if (!card || !campo) return;
    const a = avisos()[Number(card.dataset.aviso)];
    a[campo] = ev.target.type === 'checkbox' ? ev.target.checked : ev.target.value;
    if (campo === 'texto') $('[data-previa]', card).textContent = a.texto || 'Prévia do aviso';
    if (campo === 'ativo') ev.target.parentElement.lastElementChild.textContent = a.ativo ? 'Ativo' : 'Desativado';
    atualizarBarra();
  });
  vistaAvisos.addEventListener('click', async (ev) => {
    const b = ev.target.closest('button');
    if (!b) return;
    if (b.matches('[data-novo-aviso]')) {
      avisos().unshift({ ativo: true, texto: '', link_texto: '', link_url: '', inicio: '', fim: '' });
      renderAvisos();
      $('[data-aviso="0"] [data-av="texto"]').focus();
    } else if (b.dataset.tirarAviso) {
      if (!(await confirmar('Remover este aviso?', 'Remover'))) return;
      avisos().splice(Number(b.dataset.tirarAviso), 1);
      renderAvisos();
    }
    atualizarBarra();
  });

  /* ------------------------------------------------------------ empresa */
  const CAMPOS_EMPRESA = [
    ['diaria_a_partir', 'Diária a partir de (R$)', 'number', 'Aparece no selo verde do topo do site.'],
    ['whatsapp', 'WhatsApp (com 55 e DDD)', 'tel', 'Ex.: 5548998163119. Recebe todas as solicitações do site.'],
    ['telefone', 'Telefone exibido', 'tel', 'Ex.: (48) 99816-3119'],
    ['horarios', 'Horário de atendimento', 'text', 'Ex.: Seg. a sáb., 8h às 18h'],
    ['email', 'E-mail', 'email', ''],
    ['instagram', 'Instagram (sem @)', 'text', ''],
  ];
  const CAMPOS_ENDERECO = [['logradouro', 'Rua, número e sala'], ['bairro', 'Bairro'], ['cidade', 'Cidade'], ['uf', 'Estado (UF)'], ['cep', 'CEP']];

  function renderEmpresa() {
    const e = empresa();
    e.endereco = e.endereco || {};
    $('[data-vista="empresa"]').innerHTML = `
      <div class="p-cabecalho"><div><h2>Empresa</h2><p class="p-muted">Contato, horário e endereço exibidos no site.</p></div></div>
      <section class="p-bloco">
        <h3>Contato e valores</h3>
        <div class="p-grade">${CAMPOS_EMPRESA.map(([k, rot, tipo, dica]) => `
          <label class="p-field"><span>${rot}</span><input data-emp="${k}" type="${tipo}" ${tipo === 'number' ? 'inputmode="numeric" min="0"' : ''} value="${esc(e[k] ?? '')}">${dica ? `<small>${dica}</small>` : ''}</label>`).join('')}
        </div>
      </section>
      <section class="p-bloco">
        <h3>Endereço da loja</h3>
        <div class="p-grade">${CAMPOS_ENDERECO.map(([k, rot]) => `
          <label class="p-field ${k === 'logradouro' ? 'p-cheia' : ''}"><span>${rot}</span><input data-end="${k}" value="${esc(e.endereco[k] ?? '')}"></label>`).join('')}
        </div>
      </section>`;
  }

  $('[data-vista="empresa"]').addEventListener('input', (ev) => {
    const e = empresa();
    if (ev.target.dataset.emp) {
      const k = ev.target.dataset.emp;
      e[k] = k === 'diaria_a_partir' ? (ev.target.value === '' ? '' : Math.round(Number(ev.target.value))) : ev.target.value;
    } else if (ev.target.dataset.end) {
      e.endereco[ev.target.dataset.end] = ev.target.value;
    }
    atualizarBarra();
  });

  /* ------------------------------------------------------------ início */
  if (sessao.get() && API) carregar();
  else mostrarTela('login');
})();
