# Docker: KVS Job для MAX

Единая актуальная инструкция по запуску, переменным окружения, портам, данным, диагностике и остановке проекта находится в [README.md](README.md).

После создания `.env` быстрый локальный запуск:

```powershell
docker compose up --build
```

Mini App: <http://127.0.0.1:8000/miniapp>.

Проверка контейнеров и логов:

```powershell
docker compose ps
docker compose logs --tail=200 bot
```
