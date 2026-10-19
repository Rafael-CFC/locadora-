// Endereço do serviço do painel (Cloudflare Worker). Preencha depois de publicar o Worker.
// Em http://localhost o painel usa o servidor de simulação (tools/painel_dev.py).
window.PAINEL_API = ['localhost', '127.0.0.1'].includes(location.hostname)
  ? '/api'
  : 'https://locadora.fenianosrafael.workers.dev';
