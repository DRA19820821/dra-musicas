# Suno Batch Music Processor

Este projeto implementa um sistema simplificado para gerar músicas a partir de lotes de arquivos JSON usando a API não oficial do Suno. O objetivo é servir como base para uma implementação mais completa, conforme descrito no roteiro fornecido.

## Visão Geral

O sistema é composto por um backend em **FastAPI** que oferece endpoints REST para:

* Carregar lotes de arquivos `.json` contendo letras (`letra`) e estilos (`estilo`).
* Selecionar o modelo Suno (ex.: `v4.5` ou `v5`) e outros parâmetros de geração.
* Processar cada faixa de forma assíncrona, com suporte a tentativas, extensões e preferências de formato (WAV/MP3).
* Acompanhar o progresso de cada lote e baixar os arquivos de áudio gerados.

Para fins de desenvolvimento e testes o projeto inclui um **stub** da API Suno (`app/suno_client_stub.py`) que gera arquivos WAV fictícios localmente. Quando você estiver pronto para integrar com o `gcui-art/suno-api` basta substituir as chamadas no stub por requisições HTTP reais.

Uma interface web simples em HTML/JS (`frontend/index.html`) é servida pelo próprio backend para facilitar o uso.

## Como executar

### Requisitos locais

* Python 3.10+
* `ffmpeg` (já instalado no container Docker)

### Executando sem Docker

1. Navegue até o diretório `backend` e instale as dependências:

   ```bash
   cd suno_music_processor/backend
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Inicie o servidor:

   ```bash
   uvicorn app.main:app --reload
   ```

3. Acesse `http://localhost:8000/` no navegador para usar a interface web.

### Usando Docker Compose

O arquivo `docker-compose.yml` define os serviços necessários. Por padrão o backend usa SQLite para persistência local. Para incluir o wrapper real do Suno, defina as variáveis `SUNO_COOKIE` e `TWOCAPTCHA_KEY` antes de subir os serviços:

```bash
export SUNO_COOKIE="<seu_cookie_da_conta_Suno>"
export TWOCAPTCHA_KEY="<sua_chave_2captcha>"
docker compose build
docker compose up
```

O backend ficará disponível em `http://localhost:8000/` e o wrapper Suno em `http://localhost:3000/`.

## Estrutura dos Arquivos

```
suno_music_processor/
├── backend/
│   ├── app/
│   │   ├── database.py        # Conexão e inicialização do banco (SQLAlchemy)
│   │   ├── models.py          # Definição das tabelas Lote, Faixa e EventoFaixa
│   │   ├── schemas.py         # Modelos Pydantic usados nas APIs
│   │   ├── suno_client_stub.py# Stub do cliente Suno
│   │   └── main.py            # Aplicação FastAPI
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   └── index.html            # Interface web básica para envio de lotes
├── generated_audio/          # Pasta onde os arquivos WAV são gravados pelo stub
├── docker-compose.yml        # Orquestração de serviços (backend, suno-api, etc.)
└── README.md
```

## Próximos Passos

* **Integração real com Suno:** Substitua as funções em `suno_client_stub.py` por chamadas HTTP para `suno-api`. Configure o serviço `suno-api` no `docker-compose.yml` com as variáveis de ambiente corretas.
* **Fila de Tarefas:** Migrar o processamento para Celery ou RQ com Redis para maior robustez e escalabilidade.
* **Banco de dados Postgres:** Adaptar `DATABASE_URL` para apontar para o serviço Postgres fornecido e ajustar o `docker-compose.yml` conforme necessário.
* **Conversão MP3→WAV:** Implementar a conversão real via `ffmpeg` quando a API retornar MP3 nativo.
* **Interface UX completa:** Expandir a UI para incluir filtros, relatórios CSV e controle de extend.

## Licença

Este projeto é distribuído sem garantia e tem como objetivo apenas fins educacionais e de prototipagem.