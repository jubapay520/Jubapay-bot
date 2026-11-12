# BaixaTudo 🎬

Web app para baixar vídeos do **YouTube, TikTok, Instagram, Facebook, X** (e +1000 sites)
direto no iPhone. Funciona como app: abre em tela cheia, com ícone na Tela de Início.

> Uso pessoal. Baixe só conteúdo que você tem direito de guardar e respeite os criadores.

## Por que web app e não app da App Store?
A Apple **não aprova** apps que baixam vídeos do YouTube/Instagram, e instalar app próprio
fora da loja exige conta de desenvolvedor (US$ 99/ano) e reinstalar a cada 7 dias/1 ano.
Um web app (PWA) não tem nada disso: você manda o **link** para os amigos e pronto.

## Publicar (grátis) no Render
1. Crie conta em https://render.com e conecte seu GitHub.
2. **New → Web Service** → escolha este repositório.
3. **Root Directory:** `video-downloader` · **Runtime/Language:** `Docker`.
4. Em **Environment**, adicione `ACCESS_CODE` = uma senha para você e seus amigos.
5. Clique **Deploy**. Você recebe um link tipo `https://baixatudo.onrender.com`.

(No Railway funciona igual: New Project → Deploy from GitHub → Root Directory
`video-downloader` → variável `ACCESS_CODE`.)

> No plano grátis do Render o servidor "dorme" sem uso; o primeiro acesso demora ~1 min.

## Instalar no iPhone (manda isso pros amigos)
1. Abra o link no **Safari**.
2. Toque em **Compartilhar** (□↑) → **Adicionar à Tela de Início**.
3. Abra o BaixaTudo, digite o código de acesso, cole o link e toque **Baixar**.
4. Toque em **Salvar no iPhone** → **Salvar Vídeo** (vai pro Fotos).

## Variáveis de ambiente
| Variável | Para quê |
|---|---|
| `ACCESS_CODE` | Senha do app. **Use**, senão qualquer um usa seu servidor. |
| `YTDLP_COOKIES` | Conteúdo de um `cookies.txt` (extensão "Get cookies.txt LOCALLY"). Necessário se YouTube/Instagram bloquearem o servidor ("sign in to confirm you're not a bot"). Use uma conta secundária. |
| `MAX_FILESIZE_MB` | Limite por arquivo (padrão 500). |
| `MAX_PARALLEL` | Downloads simultâneos (padrão 3). |

## Problemas comuns
- **YouTube pede login / "não é um robô"**: o YouTube bloqueia muitos servidores na nuvem.
  Configure `YTDLP_COOKIES`.
- **Parou de funcionar num site**: faça "Manual Deploy → Clear cache & deploy" no Render
  para pegar a versão mais nova do yt-dlp (os sites mudam com frequência).

## Rodar no computador
```bash
pip install -r requirements.txt   # precisa do ffmpeg instalado
ACCESS_CODE=minhasenha python app.py   # abre em http://localhost:8000
```
