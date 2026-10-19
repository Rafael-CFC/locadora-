/* Garopaba Loca Fácil — interações do site (sem dependências). */
(() => {
  'use strict';

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const readJSON = (id, fallback) => {
    try { return JSON.parse(document.getElementById(id).textContent); } catch (_) { return fallback; }
  };
  const config = readJSON('site-config', {});
  const fleet = readJSON('fleet-data', []);
  const bySlug = Object.fromEntries(fleet.map((v) => [v.slug, v]));
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Rascunho só na sessão: some ao fechar a aba (ver política de privacidade).
  const draft = {
    get(k) { try { return JSON.parse(sessionStorage.getItem(k)); } catch (_) { return null; } },
    set(k, v) { try { sessionStorage.setItem(k, JSON.stringify(v)); } catch (_) { /* modo privado */ } },
  };

  /* ------------------------------------------------------------ analytics */
  // Eventos vão para window.dataLayer (GTM/GA4 lêem daqui). Sem ferramenta configurada, nada é enviado.
  window.dataLayer = window.dataLayer || [];
  const track = (event, params = {}) => window.dataLayer.push({ event, ...params });
  document.addEventListener('click', (ev) => {
    const t = ev.target.closest('[data-track]');
    if (t) track(t.dataset.track, { label: t.dataset.trackLabel || '' });
  });

  /* ------------------------------------------------------------ toast */
  const toastEl = $('[data-toast]');
  let toastTimer;
  const toast = (msg) => {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.classList.add('is-visible');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove('is-visible'), 3200);
  };

  /* ------------------------------------------------------------ helpers de data */
  const todayISO = () => {
    const d = new Date();
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
    return d.toISOString().slice(0, 10);
  };
  const fmtDate = (iso) => {
    if (!iso) return '';
    const [y, m, d] = iso.split('-');
    return `${d}/${m}/${y}`;
  };
  const WEEKDAYS = ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sáb'];
  const fmtDateLong = (iso) => {
    if (!iso) return '';
    const [y, m, d] = iso.split('-').map(Number);
    return `${WEEKDAYS[new Date(y, m - 1, d).getDay()]}, ${fmtDate(iso)}`;
  };
  const toDate = (date, time) => (date ? new Date(`${date}T${time || '00:00'}`) : null);
  const daysBetween = (a, b) => Math.max(1, Math.ceil((b - a) / 86400000));
  const plural = (n, s, p) => `${n} ${n === 1 ? s : p}`;
  const waLink = (text) => `https://wa.me/${config.whatsapp}?text=${encodeURIComponent(text)}`;

  $$('[data-min-today]').forEach((input) => { input.min = todayISO(); });
  // Devolução nunca antes da retirada, em qualquer par de campos.
  const pairDates = (retInput, devInput) => {
    if (!retInput || !devInput) return;
    const sync = () => {
      devInput.min = retInput.value || todayISO();
      if (devInput.value && retInput.value && devInput.value < retInput.value) devInput.value = retInput.value;
    };
    retInput.addEventListener('change', sync);
    sync();
  };

  const setError = (form, name, msg) => {
    const el = $(`[data-error-for="${name}"]`, form);
    const field = form.elements[name];
    const input = field && field.length && !field.tagName ? field[0] : field;
    if (el) { el.textContent = msg || ''; el.hidden = !msg; }
    if (input && input.setAttribute && input.type !== 'radio') {
      if (msg) {
        input.setAttribute('aria-invalid', 'true');
        if (el) { el.id = el.id || `err-${name}`; input.setAttribute('aria-describedby', el.id); }
      } else {
        input.removeAttribute('aria-invalid');
      }
    }
  };

  /* ------------------------------------------------------------ avisos com período */
  // O build já remove avisos vencidos; aqui o período vale também entre uma publicação e outra.
  $$('[data-aviso]').forEach((el) => {
    const hoje = todayISO();
    const { inicio, fim } = el.dataset;
    el.hidden = Boolean((inicio && inicio > hoje) || (fim && fim < hoje));
  });

  /* ------------------------------------------------------------ header e navegação */
  const header = $('[data-header]');
  if (header) {
    const onScroll = () => header.classList.toggle('is-scrolled', window.scrollY > 8);
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }
  const navToggle = $('[data-nav-toggle]');
  const nav = $('[data-nav]');
  if (navToggle && nav) {
    const setOpen = (open) => {
      navToggle.setAttribute('aria-expanded', String(open));
      nav.classList.toggle('is-open', open);
      $('.sr-only', navToggle).textContent = open ? 'Fechar menu' : 'Abrir menu';
    };
    navToggle.addEventListener('click', () => setOpen(navToggle.getAttribute('aria-expanded') !== 'true'));
    nav.addEventListener('click', (ev) => { if (ev.target.closest('a')) setOpen(false); });
    document.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape' && nav.classList.contains('is-open')) { setOpen(false); navToggle.focus(); }
    });
    window.matchMedia('(min-width: 1041px)').addEventListener('change', () => setOpen(false));
  }

  /* ------------------------------------------------------------ revelar ao rolar */
  const revealEls = $$('.reveal');
  if ('IntersectionObserver' in window && !reduceMotion) {
    // Escalonamento curto entre irmãos (até 4 × 70 ms), nunca bloqueia o conteúdo.
    revealEls.forEach((el) => {
      const siblings = Array.from(el.parentElement.children).filter((c) => c.classList.contains('reveal'));
      const i = siblings.indexOf(el);
      if (i > 0) el.style.setProperty('--reveal-delay', `${Math.min(i, 4) * 70}ms`);
    });
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) { entry.target.classList.add('is-visible'); io.unobserve(entry.target); }
      });
    }, { rootMargin: '0px 0px -5% 0px', threshold: 0 });
    revealEls.forEach((el) => io.observe(el));
  } else {
    revealEls.forEach((el) => el.classList.add('is-visible'));
  }

  /* ------------------------------------------------------------ consulta rápida (home) */
  const qq = $('[data-quick-quote]');
  if (qq) {
    pairDates(qq.elements.retirada, qq.elements.devolucao);
    const err = $('[data-qq-error]', qq);
    qq.addEventListener('submit', (ev) => {
      ev.preventDefault();
      const r = qq.elements.retirada; const d = qq.elements.devolucao;
      [r, d].forEach((i) => i.removeAttribute('aria-invalid'));
      let msg = '';
      if (!r.value) { msg = 'Informe a data de retirada.'; r.setAttribute('aria-invalid', 'true'); }
      else if (!d.value) { msg = 'Informe a data de devolução.'; d.setAttribute('aria-invalid', 'true'); }
      else if (r.value < todayISO()) { msg = 'A retirada não pode ser em uma data passada.'; r.setAttribute('aria-invalid', 'true'); }
      else if (d.value < r.value) { msg = 'A devolução precisa ser depois da retirada.'; d.setAttribute('aria-invalid', 'true'); }
      err.textContent = msg; err.hidden = !msg;
      if (msg) { (r.getAttribute('aria-invalid') ? r : d).focus(); return; }
      track('form_start', { form: 'consulta_rapida' });
      const params = new URLSearchParams({ retirada: r.value, devolucao: d.value });
      if (qq.elements.veiculo.value) params.set('veiculo', qq.elements.veiculo.value);
      window.location.href = `${config.base || ''}/reserva/?${params}`;
    });
  }

  /* ------------------------------------------------------------ catálogo: filtros */
  const filters = $('[data-filters]');
  if (filters) {
    const cards = $$('[data-vehicle]');
    const count = $('[data-filter-count]');
    const empty = $('[data-empty]');
    const resets = $$('[data-filter-reset]');
    const grid = $('[data-vehicle-grid]');
    const bagRank = { pequena: 1, media: 2, grande: 3 };

    const read = () => ({
      categoria: filters.elements.categoria.value,
      passageiros: filters.elements.passageiros.value,
      cambio: filters.elements.cambio.value,
      bagagem: filters.elements.bagagem.value,
      ar: filters.elements.ar.checked ? '1' : '',
    });
    const apply = (fromUser) => {
      const f = read();
      let visible = 0;
      cards.forEach((c) => {
        const d = c.dataset;
        const ok = (!f.categoria || d.categoria === f.categoria)
          && (!f.passageiros || Number(d.passageiros) >= Number(f.passageiros))
          && (!f.cambio || d.cambio === f.cambio)
          && (!f.bagagem || (bagRank[d.bagagem] || 0) >= bagRank[f.bagagem])
          && (!f.ar || d.ar === '1');
        const wasHidden = c.hidden;
        c.hidden = !ok;
        if (ok) {
          visible += 1;
          c.classList.add('is-visible');
          if (wasHidden && fromUser && !reduceMotion) {
            c.classList.remove('is-entering'); void c.offsetWidth; c.classList.add('is-entering');
          }
        }
      });
      count.textContent = visible === 0 ? 'Nenhum veículo encontrado' : plural(visible, 'veículo', 'veículos');
      empty.hidden = visible > 0;
      grid.hidden = visible === 0;
      const active = Object.values(f).some(Boolean);
      resets[0].hidden = !active;
      const params = new URLSearchParams(Object.entries(f).filter(([, v]) => v));
      history.replaceState(null, '', params.toString() ? `?${params}` : location.pathname);
      if (fromUser) track('filter_change', f);
    };
    // Estado inicial a partir da URL (links compartilháveis).
    const url = new URLSearchParams(location.search);
    ['categoria', 'passageiros', 'cambio', 'bagagem'].forEach((k) => {
      if (!url.has(k)) return;
      const el = filters.elements[k];
      if (el instanceof RadioNodeList) {
        const match = Array.from(el).find((r) => r.value === url.get(k));
        if (match) match.checked = true;
      } else if (Array.from(el.options).some((o) => o.value === url.get(k))) {
        el.value = url.get(k);
      }
    });
    if (url.get('ar') === '1') filters.elements.ar.checked = true;
    filters.addEventListener('change', () => apply(true));
    resets.forEach((b) => b.addEventListener('click', () => {
      filters.reset();
      apply(true);
    }));
    apply(false);
  }

  /* ------------------------------------------------------------ catálogo: comparação */
  const compareBar = $('[data-compare-bar]');
  if (compareBar) {
    const boxes = $$('[data-compare]');
    const dialog = $('[data-compare-dialog]');
    const table = $('[data-compare-table]');
    const openBtn = $('[data-compare-open]');
    const MAX = 3;
    const selected = () => boxes.filter((b) => b.checked).map((b) => b.value);
    const update = () => {
      const sel = selected();
      $('[data-compare-count]').textContent = sel.length;
      compareBar.hidden = sel.length === 0;
      document.body.classList.toggle('has-compare', sel.length > 0);
      boxes.forEach((b) => { b.disabled = !b.checked && sel.length >= MAX; });
      openBtn.setAttribute('aria-disabled', String(sel.length < 2));
      openBtn.title = sel.length < 2 ? 'Selecione pelo menos 2 veículos' : '';
    };
    boxes.forEach((b) => b.addEventListener('change', () => {
      if (b.checked && selected().length === MAX) toast('Limite de 3 veículos para comparar');
      update();
    }));
    $('[data-compare-clear]').addEventListener('click', () => { boxes.forEach((b) => { b.checked = false; }); update(); });

    const cambioLabel = { manual: 'Manual', automatico: 'Automático' };
    const bagLabel = { pequena: 'Pequeno', media: 'Médio', grande: 'Grande' };
    openBtn.addEventListener('click', () => {
      const sel = selected().map((s) => bySlug[s]).filter(Boolean);
      if (sel.length < 2) { toast('Selecione pelo menos 2 veículos para comparar'); return; }
      const maxL = Math.max(...sel.map((v) => v.litros || 0));
      const art = (slug) => {
        const media = $(`[data-compare][value="${slug}"]`)?.closest('[data-vehicle]')?.querySelector('.vehicle-card__media');
        return media ? media.innerHTML : '';
      };
      const row = (label, fn) => `<tr><th scope="row">${label}</th>${sel.map((v) => `<td>${fn(v)}</td>`).join('')}</tr>`;
      table.innerHTML = `
        <table class="compare-table">
          <thead><tr><td></td>${sel.map((v) => `<th scope="col">${art(v.slug)}${v.nome}</th>`).join('')}</tr></thead>
          <tbody>
            ${row('Categoria', (v) => v.categoria)}
            ${row('Passageiros', (v) => v.passageiros)}
            ${row('Câmbio', (v) => cambioLabel[v.cambio] || 'Consulte')}
            ${row('Ar-condicionado', (v) => (v.ar ? 'Sim' : v.ar === false ? 'Não' : 'Consulte'))}
            ${row('Porta-malas', (v) => (v.litros ? `<span class="${v.litros === maxL ? 'is-best' : ''}">${bagLabel[v.bagagem]} · ${v.litros} L</span>` : 'Consulte'))}
            ${row('Combustível', (v) => v.combustivel || 'Consulte')}
            ${row('Diária', (v) => (v.preco ? `R$ ${v.preco}` : 'Sob consulta'))}
            ${row('', (v) => `<a class="btn btn--primary btn--sm" href="${config.base || ''}/reserva/?veiculo=${v.slug}">Solicitar</a>`)}
          </tbody>
        </table>
        <p class="muted small" style="margin-top:1rem">Porta-malas conforme ficha técnica de fábrica. Itens “consulte” são confirmados pela equipe.</p>`;
      if (typeof dialog.showModal === 'function') dialog.showModal(); else dialog.setAttribute('open', '');
      track('compare_open', { veiculos: sel.map((v) => v.slug).join(',') });
    });
    $('[data-dialog-close]', dialog).addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', (ev) => { if (ev.target === dialog) dialog.close(); });
    update();
  }

  /* ------------------------------------------------------------ página do veículo */
  const periodForm = $('[data-period-form]');
  if (periodForm) {
    const el = periodForm.elements;
    const summary = $('[data-period-summary]', periodForm);
    const waBtn = $('[data-period-wa]', periodForm);
    const name = periodForm.dataset.vehicleName;
    pairDates(el.retirada, el.devolucao);
    const saved = draft.get('reserva') || {};
    if (saved.retirada && saved.retirada >= todayISO()) el.retirada.value = saved.retirada;
    if (saved.devolucao && saved.devolucao >= (el.retirada.value || todayISO())) el.devolucao.value = saved.devolucao;

    const render = (showErrors) => {
      const r = toDate(el.retirada.value, el.retirada_hora.value);
      const d = toDate(el.devolucao.value, el.devolucao_hora.value);
      let html = '<p class="muted">Escolha as datas para ver o resumo do período.</p>';
      let valid = false;
      if (r && d && d > r) {
        valid = true;
        html = `<dl><dt>Retirada</dt><dd>${fmtDate(el.retirada.value)} · ${el.retirada_hora.value}</dd>`
          + `<dt>Devolução</dt><dd>${fmtDate(el.devolucao.value)} · ${el.devolucao_hora.value}</dd>`
          + `<dt>Período</dt><dd>${plural(daysBetween(r, d), 'dia', 'dias')}</dd></dl>`;
        waBtn.href = waLink([
          'Olá, Loca Fácil! 👋',
          `Quero saber a disponibilidade do *${name}*.`,
          '',
          `📅 *Retirada:* ${fmtDateLong(el.retirada.value)} às ${el.retirada_hora.value}`,
          `📅 *Devolução:* ${fmtDateLong(el.devolucao.value)} às ${el.devolucao_hora.value}`,
          `⏱️ *Período:* ${plural(daysBetween(r, d), 'dia', 'dias')}`,
        ].join('\n'));
      } else if (r && d) {
        html = '<p class="field-error">A devolução precisa ser depois da retirada.</p>';
      } else if (showErrors) {
        html = `<p class="field-error">Informe a data de ${r ? 'devolução' : 'retirada'} para continuar.</p>`;
      }
      summary.innerHTML = html;
      return valid;
    };
    periodForm.addEventListener('change', () => {
      render(false);
      draft.set('reserva', { ...(draft.get('reserva') || {}), retirada: el.retirada.value, devolucao: el.devolucao.value });
    });
    periodForm.addEventListener('submit', (ev) => {
      if (!render(true)) {
        ev.preventDefault();
        (el.retirada.value ? el.devolucao : el.retirada).focus();
      } else {
        track('vehicle_select', { veiculo: periodForm.dataset.vehicle });
      }
    });
    render(false);

    // Barra fixa no celular: some quando o cartão de reserva já está visível.
    const mobileCta = $('[data-mobile-cta]');
    if (mobileCta && 'IntersectionObserver' in window) {
      new IntersectionObserver(([entry]) => mobileCta.classList.toggle('is-hidden', entry.isIntersecting))
        .observe(periodForm);
    }
  }

  // Galeria (quando houver fotos reais)
  const galleryMain = $('[data-gallery-main]');
  if (galleryMain) {
    $$('[data-gallery-thumb]').forEach((thumb, i, all) => thumb.addEventListener('click', () => {
      if (thumb.getAttribute('aria-current') === 'true') return;
      all.forEach((t) => t.removeAttribute('aria-current'));
      thumb.setAttribute('aria-current', 'true');
      const swap = () => {
        galleryMain.src = thumb.dataset.galleryThumb;
        galleryMain.alt = thumb.dataset.alt || '';
        galleryMain.style.objectPosition = thumb.dataset.foco || '';
        galleryMain.parentElement.style.setProperty('--img', `url(${thumb.dataset.galleryThumb})`);
        galleryMain.classList.remove('is-swapping');
      };
      if (reduceMotion) { swap(); return; }
      galleryMain.classList.add('is-swapping');
      setTimeout(swap, 160);
    }));
  }

  /* ------------------------------------------------------------ fluxo de solicitação */
  const wizard = $('[data-wizard]');
  if (wizard) {
    const el = wizard.elements;
    const panels = $$('[data-step]', wizard);
    const tabs = $$('[data-step-tab]', wizard);
    const prevBtn = $('[data-prev]', wizard);
    const nextBtn = $('[data-next]', wizard);
    const sendBtn = $('[data-send-wa]', wizard);
    const progress = $('[data-progress]');
    const TOTAL = panels.length;
    let step = 1;
    let started = false;

    // Pré-preenchimento: URL (veículo/datas vindos de outras páginas) > rascunho da sessão.
    const url = new URLSearchParams(location.search);
    const saved = draft.get('reserva') || {};
    const initial = { ...saved };
    ['veiculo', 'retirada', 'devolucao', 'retirada_hora', 'devolucao_hora'].forEach((k) => { if (url.get(k)) initial[k] = url.get(k); });
    if (initial.retirada && initial.retirada < todayISO()) delete initial.retirada;
    if (initial.devolucao && initial.devolucao < todayISO()) delete initial.devolucao;
    if (initial.veiculo && !bySlug[initial.veiculo] && initial.veiculo !== 'orientacao') delete initial.veiculo;
    Object.entries(initial).forEach(([k, v]) => {
      const f = el[k];
      if (!f || v == null) return;
      if (f instanceof RadioNodeList) {
        const r = Array.from(f).find((x) => x.value === v);
        if (r) r.checked = true;
      } else if (f.type === 'checkbox') {
        f.checked = v === 'on' || v === true;
      } else {
        f.value = v;
      }
    });
    pairDates(el.retirada, el.devolucao);

    const data = () => {
      const fd = new FormData(wizard);
      const o = Object.fromEntries(fd.entries());
      o.mesmo_local = el.mesmo_local.checked ? 'on' : 'off';
      Object.keys(o).forEach((k) => { if (typeof o[k] === 'string') o[k] = o[k].trim(); });
      return o;
    };
    const vehicleLabel = (d) => {
      if (!d.veiculo) return '';
      const input = $(`input[name="veiculo"][value="${d.veiculo}"]`, wizard);
      return input ? input.dataset.label : '';
    };
    const pickupLabel = (d) => (d.local_retirada === 'outro' ? (d.local_retirada_txt ? `${d.local_retirada_txt} (a confirmar)` : '') : config.loja);
    const returnLabel = (d) => (d.mesmo_local === 'on' ? pickupLabel(d) : (d.local_devolucao_txt ? `${d.local_devolucao_txt} (a confirmar)` : ''));
    const period = (d) => {
      const r = toDate(d.retirada, d.retirada_hora);
      const v = toDate(d.devolucao, d.devolucao_hora);
      return r && v && v > r ? daysBetween(r, v) : 0;
    };

    const validate = (n) => {
      const d = data();
      const errs = {};
      if (n === 1 && !d.veiculo) errs.veiculo = 'Escolha um veículo ou a opção “Quero orientação”.';
      if (n === 2) {
        if (!d.retirada) errs.retirada = 'Informe a data de retirada.';
        else if (d.retirada < todayISO()) errs.retirada = 'A retirada não pode ser em uma data passada.';
        if (!d.devolucao) errs.devolucao = 'Informe a data de devolução.';
        else if (d.retirada && !period(d)) errs.devolucao = 'A devolução precisa ser depois da retirada.';
        if (d.local_retirada === 'outro' && d.local_retirada_txt.length < 3) errs.local_retirada_txt = 'Informe onde você quer retirar o carro.';
        if (d.mesmo_local === 'off' && (d.local_devolucao_txt || '').length < 3) errs.local_devolucao_txt = 'Informe onde você quer devolver o carro.';
      }
      if (n === 3 && (d.nome || '').length < 2) errs.nome = 'Informe seu nome para a equipe saber com quem está falando.';
      const fields = { 1: ['veiculo'], 2: ['retirada', 'devolucao', 'local_retirada_txt', 'local_devolucao_txt'], 3: ['nome'] }[n] || [];
      fields.forEach((f) => setError(wizard, f, errs[f]));
      return errs;
    };

    // Mensagem em blocos curtos: fácil de ler no WhatsApp e de responder pela equipe.
    const vehicleLine = (d) => (d.veiculo === 'orientacao' ? 'Ainda não escolhi, gostaria de uma indicação' : `*${vehicleLabel(d)}*`);
    const buildMessage = (d) => {
      const lines = [
        'Olá, Loca Fácil! 👋',
        'Gostaria de um *orçamento de aluguel de carro*.',
        '',
        '🚗 *Veículo*',
        vehicleLine(d),
        '',
        '📅 *Retirada*',
        `${fmtDateLong(d.retirada)} às ${d.retirada_hora}`,
        `📍 ${pickupLabel(d)}`,
        '',
        '📅 *Devolução*',
        `${fmtDateLong(d.devolucao)} às ${d.devolucao_hora}`,
        `📍 ${d.mesmo_local === 'on' ? 'No mesmo local da retirada' : returnLabel(d)}`,
        '',
        `⏱️ *Período:* ${plural(period(d), 'dia', 'dias')}`,
        `👤 *Nome:* ${d.nome}`,
        `🧾 *Locação para:* ${d.cliente}`,
      ];
      if (d.observacoes) lines.push('', '📝 *Observações*', d.observacoes);
      lines.push('', '_Enviado pelo site. Aguardo a confirmação de disponibilidade e valores._');
      return lines.join('\n');
    };

    const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    const renderSummary = () => {
      const d = data();
      const rows = [
        ['Veículo', vehicleLabel(d), 1],
        ['Retirada', `${fmtDate(d.retirada)} às ${d.retirada_hora}<br><span class="muted">${esc(pickupLabel(d))}</span>`, 2],
        ['Devolução', `${fmtDate(d.devolucao)} às ${d.devolucao_hora}<br><span class="muted">${esc(returnLabel(d))}</span>`, 2],
        ['Período', plural(period(d), 'dia', 'dias'), 2],
        ['Nome', esc(d.nome), 3],
        ['Locação para', esc(d.cliente), 3],
      ];
      if (d.observacoes) rows.push(['Observações', esc(d.observacoes), 3]);
      $('[data-summary]', wizard).innerHTML = rows.map(([k, v, s]) => `<dt>${k}</dt><dd><span>${v}</span><button type="button" class="edit" data-goto="${s}">Editar</button></dd>`).join('');
      sendBtn.href = waLink(buildMessage(d));
    };

    const renderProgress = () => {
      const d = data();
      const days = period(d);
      const items = [
        ['Veículo', vehicleLabel(d)],
        ['Retirada', d.retirada ? `${fmtDate(d.retirada)} · ${d.retirada_hora}` : ''],
        ['Devolução', d.devolucao && days ? `${fmtDate(d.devolucao)} · ${d.devolucao_hora}` : ''],
        ['Local', pickupLabel(d) && returnLabel(d) ? (d.local_retirada === 'loja' && d.mesmo_local === 'on' ? 'Retirada e devolução na loja' : 'Local a confirmar com a equipe') : ''],
        ['Nome', d.nome],
      ];
      const check = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>';
      progress.innerHTML = items.map(([k, v]) => `<li class="${v ? 'is-ok' : 'is-missing'}"><span class="dot">${check}</span><span>${k}<small>${v ? esc(v) : 'Falta informar'}</small></span></li>`).join('');
      const pill = $('[data-period-pill]', wizard);
      pill.hidden = !days;
      if (days) pill.textContent = `Período de ${plural(days, 'dia', 'dias')} · o valor final é confirmado pela equipe`;
    };

    const syncConditional = () => {
      $$('[data-show-when]', wizard).forEach((box) => {
        const [name, val] = box.dataset.showWhen.split('=');
        const f = el[name];
        const current = f.type === 'checkbox' ? (f.checked ? 'on' : 'off') : f.value;
        box.hidden = current !== val;
      });
    };

    const goTo = (n, opts = {}) => {
      const back = n < step;
      step = Math.min(Math.max(n, 1), TOTAL);
      panels.forEach((p) => {
        const isCurrent = Number(p.dataset.step) === step;
        p.hidden = !isCurrent;
        p.classList.toggle('is-back', back);
      });
      tabs.forEach((t) => {
        const s = Number(t.dataset.stepTab);
        t.classList.toggle('is-done', s < step);
        if (s === step) t.setAttribute('aria-current', 'step'); else t.removeAttribute('aria-current');
      });
      prevBtn.hidden = step === 1;
      nextBtn.hidden = step === TOTAL;
      if (step === TOTAL) renderSummary();
      if (!opts.silent) {
        const top = wizard.getBoundingClientRect().top;
        if (top < 0 || top > window.innerHeight * 0.4) wizard.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
        const legend = $('.wizard__legend', panels[step - 1]);
        if (legend) { legend.tabIndex = -1; legend.focus({ preventScroll: true }); }
        track('reserva_etapa', { etapa: step });
      }
    };

    const save = () => {
      const d = data();
      delete d.nome; delete d.observacoes; // dados pessoais não ficam salvos
      draft.set('reserva', d);
    };

    wizard.addEventListener('input', () => {
      if (!started) { started = true; track('form_start', { form: 'reserva' }); }
      syncConditional();
      renderProgress();
      save();
    });
    wizard.addEventListener('change', (ev) => {
      syncConditional(); renderProgress(); save();
      if (ev.target.name && ev.target.getAttribute('aria-invalid')) validate(step);
      if (ev.target.name === 'veiculo') setError(wizard, 'veiculo', '');
    });
    nextBtn.addEventListener('click', () => {
      const errs = validate(step);
      const first = Object.keys(errs)[0];
      if (first) {
        const f = el[first];
        const target = f instanceof RadioNodeList ? f[0] : f;
        target?.focus();
        return;
      }
      goTo(step + 1);
    });
    prevBtn.addEventListener('click', () => goTo(step - 1));
    wizard.addEventListener('click', (ev) => {
      const g = ev.target.closest('[data-goto]');
      if (g) goTo(Number(g.dataset.goto));
    });
    // Enter avança a etapa em vez de enviar o formulário.
    wizard.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' && ev.target.tagName === 'INPUT' && ev.target.type !== 'checkbox' && ev.target.type !== 'radio') {
        ev.preventDefault();
        if (step < TOTAL) nextBtn.click();
      }
    });
    wizard.addEventListener('submit', (ev) => ev.preventDefault());

    sendBtn.addEventListener('click', () => {
      for (let s = 1; s < TOTAL; s += 1) {
        if (Object.keys(validate(s)).length) { goTo(s); return; }
      }
      renderSummary();
      track('reserva_enviada', { veiculo: data().veiculo, dias: period(data()) });
      toast('Abrimos o WhatsApp com a sua solicitação. É só enviar.');
    });
    $('[data-copy-msg]', wizard).addEventListener('click', async (ev) => {
      const btn = ev.currentTarget;
      try {
        await navigator.clipboard.writeText(buildMessage(data()));
        toast('Mensagem copiada');
      } catch (_) {
        toast('Não foi possível copiar automaticamente');
      }
      btn.blur();
    });

    syncConditional();
    renderProgress();
    // Se o veículo já veio escolhido, começa pelas datas.
    goTo(initial.veiculo ? 2 : 1, { silent: true });
  }

  /* ------------------------------------------------------------ contato */
  const contactForm = $('[data-contact-form]');
  if (contactForm) {
    contactForm.addEventListener('submit', (ev) => {
      ev.preventDefault();
      const el = contactForm.elements;
      const nome = el.nome.value.trim();
      const msg = el.mensagem.value.trim();
      setError(contactForm, 'nome', nome.length < 2 ? 'Informe seu nome.' : '');
      setError(contactForm, 'mensagem', msg.length < 5 ? 'Escreva sua mensagem.' : '');
      if (nome.length < 2) { el.nome.focus(); return; }
      if (msg.length < 5) { el.mensagem.focus(); return; }
      const text = ['Olá, Loca Fácil! 👋', `Meu nome é *${nome}*.`, '', `📌 *Assunto:* ${el.assunto.value}`, '', msg].join('\n');
      track('whatsapp_click', { label: 'formulario_contato' });
      const win = window.open(waLink(text), '_blank', 'noopener');
      if (!win) window.location.href = waLink(text);
      toast('Abrimos o WhatsApp com a sua mensagem.');
    });
  }

  /* ------------------------------------------------------------ mapa sob demanda */
  $$('[data-map]').forEach((box) => {
    $('[data-map-load]', box)?.addEventListener('click', () => {
      const iframe = document.createElement('iframe');
      iframe.src = box.dataset.src;
      iframe.title = 'Mapa com a localização da loja';
      iframe.loading = 'lazy';
      iframe.referrerPolicy = 'no-referrer-when-downgrade';
      box.replaceChildren(iframe);
    });
  });
})();
