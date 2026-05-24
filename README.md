# Warranty Platform — Backend Deployment

This folder contains everything needed to deploy the **Backend (NestJS)**, **AI Service (FastAPI)**, **PostgreSQL**, and **Qdrant** on an EC2 instance using Docker Compose.

## Contents

| Folder/File | Description |
|---|---|
| `backend/` | NestJS REST API — auth, documents, review, query, dashboard |
| `ai-service/` | FastAPI AI service — OCR pipeline, embeddings, vector search, LLM reasoning |
| `infra/postgres/init.sql` | Database initialization script (users, documents, reviews, sessions, messages tables) |
| `docker-compose.prod.yml` | Production compose file — runs Postgres, Qdrant, Backend, and AI Service |
| `.env.example` | Environment variable template |
| `.dockerignore` | Files excluded from Docker build context |

## Prerequisites

- **Docker** ≥ 20.10 and **Docker Compose** ≥ 2.0
- **AWS credentials** with access to S3, SQS, and Textract
- **OpenAI / Anthropic API keys** for LLM and embedding services
- **Cohere API key** (optional, for reranking)

## Deployment

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in all required values
nano .env
```

### 2. Start all services

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

### 3. Verify services are running

```bash
docker compose -f docker-compose.prod.yml ps
```

### 4. View logs

```bash
# All services
docker compose -f docker-compose.prod.yml logs -f

# Specific service
docker compose -f docker-compose.prod.yml logs -f backend
docker compose -f docker-compose.prod.yml logs -f ai-service
docker compose -f docker-compose.prod.yml logs -f postgres
docker compose -f docker-compose.prod.yml logs -f qdrant
```

### 5. Update after code changes

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

### 6. Stop all services

```bash
docker compose -f docker-compose.prod.yml down
```

## Port Mapping

| Service | Port | URL |
|---|---|---|
| Backend (NestJS) | 3001 | `http://<EC2_IP>:3001` |
| AI Service (FastAPI) | 8000 | `http://<EC2_IP>:8000` |
| PostgreSQL | 5432 | Internal — accessible from backend and ai-service containers |
| Qdrant (HTTP) | 6333 | `http://<EC2_IP>:6333` |
| Qdrant (gRPC) | 6334 | `http://<EC2_IP>:6334` |

## Architecture

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Postgres   │◄───│   Backend    │───►│  AI Service  │
│   :5432      │    │   :3001      │    │   :8000      │
└──────────────┘    └──────────────┘    └──────────────┘
                           │                    │
                           ▼                    ▼
                    ┌──────────────┐    ┌──────────────┐
                    │  AWS S3/SQS  │    │   Qdrant     │
                    │  Textract    │    │   :6333      │
                    └──────────────┘    └──────────────┘
                                               │
                                        ┌──────────────┐
                                        │ OpenAI/Claude│
                                        └──────────────┘
```

## Notes

- **Qdrant** runs as a Docker container on the same EC2 instance. Data is persisted in the `qdrant_data` volume.
- **Frontend** is deployed separately to Vercel — see `frontend-deploy/`.
- The `init.sql` script runs automatically on first Postgres startup. To re-initialize, remove the volumes: `docker compose -f docker-compose.prod.yml down -v`.
