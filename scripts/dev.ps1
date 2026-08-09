# Local development scripts (Windows PowerShell)

## Start full stack with Docker (PostgreSQL + worker + web)

```powershell
docker compose up --build
```

## Start PostgreSQL only

```powershell
docker compose up -d db
```

## Local web

```powershell
cd apps/web
npm install
npm run dev
```

## Local worker

```powershell
pip install -e ./apps/worker[dev]
python -c "import open_signal; print(open_signal.__version__)"
```

## Checks

```powershell
# worker
ruff check python
.\scripts\test.ps1

# web
cd apps/web
npm run typecheck
npm run build
```
