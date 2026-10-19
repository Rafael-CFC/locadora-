# Site — Garopaba Loca Fácil Veículos

Site estático, rápido e sem dependências para a locadora Garopaba Loca Fácil (Garopaba/SC).
Gerado por um script Python (biblioteca padrão apenas) a partir de arquivos de conteúdo em JSON.

## Como executar

Requisito: Python 3.9 ou superior.

```bash
python build.py --dev                       # mostra itens PENDENTES e avaliações de EXEMPLO
python build.py                             # build de produção (o que vai ao ar)
python -m http.server 8000 --directory dist # abrir http://localhost:8000
```

Ao final do build, o terminal lista o que ainda falta preencher.

## Como publicar

Qualquer hospedagem de site estático serve (Netlify, Cloudflare Pages, Vercel, GitHub Pages, hospedagem compartilhada).

- Comando de build: `python build.py`
- Pasta publicada: `dist`
- Variáveis de ambiente:
  - `SITE_URL` (obrigatória): domínio final, ex.: `https://www.garopabalocafacil.com.br`. Usada em canonical, Open Graph, sitemap e dados estruturados.
  - `GOOGLE_SITE_VERIFICATION` (opcional): token do Google Search Console (método “tag HTML”).
- A página `404.html` é usada automaticamente pela maioria dessas hospedagens.

Em hospedagem compartilhada sem build: rode `SITE_URL=... python build.py` no computador e envie o conteúdo de `dist/` por FTP.

## Estrutura

```
build.py               gerador: templates, SEO, JSON-LD, sitemap, robots
content/
  empresa.json         dados da empresa (fonte de verdade); null = não exibido
  veiculos.json        frota e especificações
  faq.json             perguntas frequentes; resposta null = oculta em produção
  avaliacoes.json      avaliações; só publica verificadas + autorizadas
static/
  css/styles.css       design system (tokens de cor, tipografia, componentes)
  js/app.js            filtros, comparação, fluxo de reserva, WhatsApp, mapa
  img/                 imagens (fotos da frota vão em img/frota/)
dist/                  saída gerada (não editar à mão)
```

Páginas: `/`, `/veiculos/`, `/veiculos/<modelo>/`, `/reserva/`, `/sobre/`, `/avaliacoes/`, `/perguntas-frequentes/`, `/contato/`, `/privacidade/`.

## Como atualizar o conteúdo

- **Preços**: `preco_diaria` em `veiculos.json` (número, ex.: `189`). Sem valor, o site mostra “a partir de” + “sob consulta”.
- **Fotos reais**: salve em `static/img/frota/` em WebP e liste em `imagens` como `{"src": "img/frota/kwid-vermelho.webp", "alt": "…", "w": 400, "h": 492, "foco": "50% 72%"}`. `foco` indica onde o carro está na foto (usado no recorte dos cards). Com 2 ou mais fotos, a galeria ganha miniaturas.
- **Novo veículo**: copie um bloco em `veiculos.json` e troque `slug`, dados e fotos. A página `/veiculos/<slug>/` é criada no próximo build.
- **Políticas** (idade, caução, cancelamento etc.): preencha a resposta em `faq.json` e, se quiser, em `empresa.json > politicas`.
- **Avaliações**: adicione em `avaliacoes.json` com `verificada: true` e `autorizada: true`. Nomes abreviados (ex.: “Thallis F.”) e sem data quando o Google só mostra “há X meses”. A nota média só aparece a partir de 3 avaliações publicadas (`MIN_REVIEWS_FOR_AVERAGE` em `build.py`).

## Como funciona a solicitação de reserva

O site **não confirma reservas nem recebe pagamentos**. O assistente em 4 etapas (veículo → período e local → nome → revisão) monta uma mensagem e abre o WhatsApp oficial (48 99816-3119) com tudo preenchido. A equipe confirma disponibilidade, valor e condições. O texto do site deixa claro que a solicitação não é uma reserva.

- Nenhum dado pessoal é enviado a servidor. O rascunho (sem nome e observações) fica no `sessionStorage` e some ao fechar a aba.
- Sem servidor, não há formulário para robôs atacarem: não é preciso captcha.

## Avaliações do Google: opções de integração

1. **Manual (atual)**: copiar avaliações do Perfil da Empresa para `avaliacoes.json`, com o link de cada uma. Custo zero e controle total.
2. **Places API (New) – Place Details**: retorna poucas avaliações (até 5) e a nota pública. Exige chave de API com faturamento ativo no Google Cloud, exibição das atribuições exigidas pelo Google e respeito às regras de cache. A chamada precisa ser feita no servidor ou no build, nunca com a chave exposta no navegador.
3. **Business Profile API**: acesso a todas as avaliações do perfil, mas exige OAuth do proprietário e aprovação de acesso pelo Google.

Antes de escolher a 2 ou a 3, confira os termos, custos e cotas vigentes na documentação oficial do Google.

## Analytics (opcional)

Os cliques importantes já geram eventos em `window.dataLayer`: `whatsapp_click`, `cta_click`, `vehicle_select`, `form_start`, `reserva_etapa`, `reserva_enviada`, `filter_change`, `compare_open`. Para medir, instale o Google Tag Manager com um banner de consentimento (LGPD) e crie as tags a partir desses eventos. Sem ferramenta instalada, nada é enviado.

## Painel administrativo (segunda etapa)

Como todo o conteúdo está em JSON, o caminho mais simples é um CMS baseado em Git (ex.: Decap CMS): a equipe edita veículos, preços, fotos, perguntas e avaliações em um painel com login, o que gera um commit, e a hospedagem refaz o build automaticamente. Para **guardar as solicitações recebidas** ou controlar disponibilidade da frota seria necessário um backend (banco de dados, autenticação, política de retenção dos dados). Isso só vale a pena com um sistema confiável de controle de frota.

## Testes realizados

- Desktop (1280 px) e celular (375 px) em todas as páginas, sem rolagem horizontal.
- Filtros (categoria, passageiros, câmbio, bagagem, ar-condicionado), estado vazio, URL compartilhável, limpar filtros.
- Comparação de até 3 veículos (limite, tabela, fechar).
- Página do veículo: resumo do período, validação de datas, link do WhatsApp com datas.
- Fluxo de reserva: pré-preenchimento vindo da página do veículo, validação por etapa com foco no campo, resumo com “Editar”, mensagem final do WhatsApp.
- Contato: validação e envio pelo WhatsApp; mapa carregado só ao clicar.
- Build de produção: nenhum “PENDENTE”/“EXEMPLO” publicado, um H1 por página, JSON-LD válido, links internos sem quebra.

Limitações: não testado em aparelhos reais (iOS/Android); o Google Maps embutido e a abertura do WhatsApp dependem de serviços externos.

## GitHub Pages (versão de teste)

O workflow `.github/workflows/pages.yml` gera e publica o site a cada push na branch `main`. Uma única vez, no GitHub: **Settings → Pages → Source: GitHub Actions**. O endereço fica `https://<usuario>.github.io/<repositorio>/`; o build ajusta os links para essa subpasta (`BASE_PATH`) e marca a cópia como `noindex`, para o Google não indexar a versão de teste.
