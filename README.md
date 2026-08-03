# Reviews API

Расширяемый сборщик отзывов об организациях из 2ГИС и Яндекс Карт. Отзывы
сохраняются в PostgreSQL и выдаются клиентским проектам через API с обязательной
изоляцией данных.

Проект появился из практической задачи: одному сайту нужны отзывы одной компании,
другому — нескольких филиалов, а источники отдают разные поля и по-разному ведут
себя при ошибках. Поэтому здесь нет одного «универсального парсера». Каждый
источник вынесен в отдельный адаптер, а всё остальное — хранение, обновления,
доступ клиентов и история синхронизаций — работает с общей моделью данных.

## Схема

```text
2ГИС ─────┐
          ├─> адаптеры ─> нормализация ─> PostgreSQL ─> клиентский REST API
Яндекс ───┘                     │
                               └─> история запусков, ошибки и повторные попытки
```

## Что реализовано

- Несколько организаций и несколько источников на один проект.
- Провайдеры `2gis` и `yandex` с единым интерфейсом расширения.
- Имя автора, необязательный аватар, дата публикации и изменения, оценка и полный текст.
- Фото и видео в отдельной таблице с исходной и preview-ссылкой.
- Идемпотентный upsert по ID отзыва источника.
- История синхронизаций, статусы, ошибки, счётчики и retry/backoff.
- Ежедневный последовательный runner со случайной задержкой между источниками.
- Клиентские Bearer-ключи, каждый из которых привязан ровно к одному проекту.
- Административный API, защищённый отдельным `X-Admin-Key`.
- Сбор 2ГИС через Chromium без обязательного платного API-ключа.

## Как работает 2ГИС без ключа

По умолчанию провайдер запускает Chromium, открывает публичную вкладку
отзывов 2ГИС и перехватывает JSON-запрос веб-приложения. Временный ключ веб-клиента
используется только внутри этой браузерной сессии и нигде не сохраняется. Остальные
страницы отзывов запрашиваются последовательно через ту же сессию.

В Docker обычный Chromium работает внутри невидимого виртуального дисплея Xvfb.
Классический headless-режим оставлен опцией, но 2ГИС сейчас чаще направляет его на
CAPTCHA, поэтому `REW_TWOGIS_BROWSER_HEADLESS=false` является штатной настройкой.

Доступные режимы:

- `browser` — режим по умолчанию, настроенный API-ключ не нужен;
- `api` — только официальный API, требуется `REW_TWOGIS_REVIEWS_API_KEY`;
- `auto` — сначала официальный API при наличии ключа, затем Chromium при ошибке.

Изменения сайта или bot-protection могут потребовать обновления адаптера. CAPTCHA
система не обходит: такая ситуация записывается как ошибка синхронизации.

## Быстрый запуск

```bash
cp .env.example .env
# Обязательно замените REW_ADMIN_API_KEY и REW_API_KEY_PEPPER.
docker compose up --build
```

Docker-образ устанавливает Chromium и его системные зависимости автоматически.
После запуска доступны:

- API: `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`
- Проверка: `GET http://localhost:8000/health`

## Первичная настройка через API

Во всех административных запросах передаётся `X-Admin-Key` из `.env`.

Создание проекта:

```bash
curl -X POST http://localhost:8000/admin/projects \
  -H "X-Admin-Key: YOUR_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"Сайт клиента","slug":"client-site"}'
```

Создание клиентского API-ключа (секрет возвращается только один раз):

```bash
curl -X POST http://localhost:8000/admin/projects/PROJECT_UUID/api-keys \
  -H "X-Admin-Key: YOUR_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"production"}'
```

Добавление организации:

```bash
curl -X POST http://localhost:8000/admin/projects/PROJECT_UUID/organizations \
  -H "X-Admin-Key: YOUR_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"Моя организация"}'
```

Привязка 2ГИС:

```bash
curl -X POST http://localhost:8000/admin/organizations/ORGANIZATION_UUID/sources \
  -H "X-Admin-Key: YOUR_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"provider":"2gis","url":"https://2gis.ru/city/firm/BRANCH_ID/tab/reviews"}'
```

Для Яндекс Карт используется `provider: "yandex"` и ссылка вида
`https://yandex.ru/maps/org/name/ORGANIZATION_ID/`.

## Клиентский API

```bash
curl http://localhost:8000/v1/organizations \
  -H "Authorization: Bearer rew_live_..."

curl "http://localhost:8000/v1/reviews?page=1&page_size=50" \
  -H "Authorization: Bearer rew_live_..."

curl "http://localhost:8000/v1/organizations/ORGANIZATION_UUID/reviews?provider=2gis" \
  -H "Authorization: Bearer rew_live_..."
```

Клиент не передаёт `project_id`: проект определяется только по хешу API-ключа.
Запросы к организациям и отзывам дополнительно фильтруются по владельцу.

## Плановый запуск

Cron вызывает один последовательный процесс:

```bash
docker compose run --rm api rew-api sync-due
```

Пример crontab находится в `deploy/cron.example`. Между источниками процесс ждёт
случайное время из диапазона `REW_SYNC_DELAY_MIN_SECONDS` —
`REW_SYNC_DELAY_MAX_SECONDS`. Ошибка одного источника сохраняется в БД и не мешает
обработать остальные.

Полезные команды:

```bash
rew-api init-db
rew-api create-project --name "Client" --slug client
rew-api create-key --project client --name production
rew-api create-organization --project client --name "Company"
rew-api add-source --organization ORGANIZATION_UUID --provider 2gis --url URL
rew-api sync-source --id 1
rew-api sync-due --delay-min 20 --delay-max 60
```

## Добавление нового сервиса

Новый источник реализует `ReviewProvider` из
`src/rew_api/providers/base.py` и регистрируется в `ProviderRegistry`. Модели БД,
синхронизатор и клиентский API уже работают с нормализованными `ProviderReview` и
`ProviderMedia`.

## Локальная разработка

```bash
python -m venv .venv
.venv/Scripts/activate
python -m pip install -e ".[dev]"
python -m playwright install chromium
rew-api init-db
pytest
ruff check .
uvicorn rew_api.main:app --reload
```

В репозитории 11 тестов: изоляция данных между проектами, идемпотентная
синхронизация и разбор ответов провайдеров. CI запускает `pytest` и `ruff` на
каждом push и pull request.

Перед production-использованием нужно получить подходящие разрешения на
автоматизированное получение и хранение данных от владельцев источников. Задержки
снижают нагрузку на сайты, но сами по себе не являются таким разрешением.
