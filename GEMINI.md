# NetBird Self-Hosted API Manager

## 1. Среда выполнения и общие правила
- **Рабочая директория:** `/home/artem/projects/netbird`
- **Интерпретатор Python:** строго `.venv/bin/python` (Python 3.15, управляемый через `uv`). Никогда не используй системный `/usr/bin/python3`.
- **Установленные зависимости:** `requests`, `python-dotenv`.
- **Сетевой доступ (Sandbox):** все скрипты в `scripts/*.py` обращаются по сети к `netbird.diaservis.ua` — при их вызове через Bash **сразу передавай `BypassSandbox: true`** с первой попытки, не тратя шаг на тестовый запуск в offline-песочнице.
- **Экономия контекста:** не читай исходный код готовых скриптов в `scripts/`, если их интерфейс уже описан в разделе 5 — сразу вызывай их с нужными флагами.
- **Обработка `null` в ответах API:** списочные поля (`sources`, `destinations`, `groups`) в ответах NetBird могут приходить как `null` (`None`). Всегда используй конструкцию `(item.get("field") or [])` вместо `item.get("field", [])`.

## 2. Подключение к NetBird API
- **Конфигурация:** URL сервера и токен берутся исключительно из `.env` (`NETBIRD_URL` и `NETBIRD_TOKEN`) средствами `python-dotenv` внутри Python-скриптов.
- **Запрет на чтение секретов:** никогда не читай содержимое файла `.env` напрямую и не выводи значение `NETBIRD_TOKEN` в консоль или логи.
- **Базовый префикс API:** `${NETBIRD_URL}/api`
- **Заголовок авторизации:** `Authorization: Token <NETBIRD_TOKEN>`

## 3. Спецификации OpenAPI (`docs/openapi/`)
Полные схемы эндпоинтов, параметров пути и JSON-структур запросов находятся в `docs/openapi/`:
- `docs/openapi/networks.yml` — сети (`/api/networks`), сетевые ресурсы (`/api/networks/{networkId}/resources`) и роутеры сетей (`/api/networks/{networkId}/routers`).
- `docs/openapi/peers.yml` — узлы (пиры) и их параметры.
- `docs/openapi/groups.yml` — группы пиров и ресурсов.
- `docs/openapi/policies.yml` — политики контроля доступа (ACL).
- `docs/openapi/routes.yml` — классические сетевые маршруты (Network Routes).
- `docs/openapi/dns.yml` — DNS-серверы и зоны.
- `docs/openapi/setup-keys.yml` — ключи регистрации.
- `docs/openapi/users.yml` — пользователи и токены.

### Правило сверки со схемами
Перед написанием нового скрипта `scripts/manage_*.py` **обязательно прочитай соответствующий `.yml` файл** из `docs/openapi/`, чтобы проверить:
1. Точный URI эндпоинта и обязательные параметры пути (`networkId`, `resourceId`, `routerId` и др.).
2. Обязательные поля (`required`) в `requestBody` (например, `metric`, `masquerade`, `enabled` для `NetworkRouterRequest`).
3. Взаимоисключающие поля (например, в `NetworkRouterRequest` нельзя одновременно задавать `peer` и `peer_groups`).
4. Единый стиль новых скриптов: `argparse`, поддержка `--dry-run`, авто-бэкап перед `PUT`/`DELETE` и вывод тела ответа сервера при HTTP-ошибках `400`/`422`.

## 4. Правила безопасности и предохранители (CRITICAL)
1. **Обязательный флаг `--dry-run`:** каждый скрипт, выполняющий мутирующие запросы (`POST`, `PUT`, `DELETE`), обязан поддерживать `--dry-run` (вывод HTTP-метода, полного URL и JSON-payload без отправки запроса). Первый запуск перед изменением конфигурации всегда выполняется с `--dry-run`, боевой запуск — только после явного подтверждения пользователя.
2. **Автоматический бэкап:** перед отправкой любого `PUT` или `DELETE` запроса скрипт сохраняет актуальный снимок ресурса в `backups/` (директория игнорируется Git).
3. **Защита от удаления (`DELETE`):** перед удалением выведи пользователю точные `id`, имя, адрес/тип удаляемого объекта и дождись явного подтверждения.

## 5. Готовые скрипты в проекте (`scripts/`)
- `scripts/nb_client.py` — базовый HTTP-клиент (`request(method, endpoint, payload)`) и утилита резервного копирования (`backup_resource(name, data)`).
- `scripts/export_state.py` — read-only выгрузка полного снимка (Networks, Resources, Routers, Groups, Policies) в `backups/netbird_state_*.json`. Поддерживает флаг `--markdown`.
- `scripts/export_networks_pdf.py` — генерация PDF-отчета по сетям, роутерам, ресурсам и политикам через `wkhtmltopdf`. Поддерживает `--output <путь>` (по умолчанию `backups/netbird_networks.pdf`) и `--keep-html`.
- `scripts/manage_network_resources.py` — управление сетевыми ресурсами (`host`, `subnet`, `domain`) в `/api/networks/{networkId}/resources` по именам сетей и групп в произвольном регистре:
  - `create`: `--network`, `--name`, `--address`, `--groups`, `--description`, `--disabled`, `--dry-run`
  - `update`: `--network`, `--name` (или `--id`), `--new-name`, `--address`, `--groups`, `--description`, `--enable` / `--disable`, `--dry-run`
  - `delete`: `--network`, `--name` (или `--id`), `--yes`, `--dry-run`
  - `lookup`: `--query "<фрагмент>"`

## 6. Интерактивный режим управления ресурсами (Wizard-режим)
Если пользователь ставит задачу в свободной форме без полного набора параметров (например: «создай новую подсеть 10.255.53.0/24»), веди диалог в формате опроса:
1. **Сбор обязательных полей:** для `create` нужны `address` (IP/CIDR/домен), `network` (сеть), `name` (имя ресурса) и `groups` (одна или несколько групп), опционально — `description`. Если не хватает нескольких полей, запроси их одним списком. Не подставляй `--network` молча, если сеть не указана и не следует явно из контекста текущего диалога.
2. **Нечёткий поиск:** при вводе фрагмента имени сети или группы (например, `corp` или `bab`) выполни `.venv/bin/python scripts/manage_network_resources.py lookup --query "<ввод>"`. Точное совпадение принимай сразу; при частичном совпадении переспроси подтверждение у пользователя.
3. **Проверка перед отправкой:** когда все поля собраны, выполни `create ... --dry-run`, покажи `Endpoint` и JSON-payload и запроси подтверждение перед боевым запуском.