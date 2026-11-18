#!/usr/bin/env python3
"""
Управление сетевыми ресурсами NetBird (/api/networks/{networkId}/resources):
создание (POST), обновление (PUT) и удаление (DELETE) с резолвингом имён сетей
и групп в произвольном регистре, поддержкой --dry-run и авто-бэкапом.
"""

import argparse
import json
import sys
from pathlib import Path
import requests

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from nb_client import BASE_URL, TOKEN, backup_resource, request  # noqa: E402


# def resolve_single_by_name(items: list[dict], target_name: str, entity_label: str) -> dict:
#     """Находит ровно один объект по имени без учёта регистра."""
#     needle = target_name.strip().casefold()
#     matches = [
#         item for item in (items or [])
#         if str(item.get("name", "")).strip().casefold() == needle
#     ]
#     if not matches:
#         available = ", ".join(sorted(str(i.get("name", "")) for i in (items or []))) or "нет"
#         raise ValueError(
#             f"{entity_label} с именем '{target_name}' не найдена. Доступные: {available}"
#         )
#     if len(matches) > 1:
#         ids = ", ".join(str(m.get("id")) for m in matches)
#         raise ValueError(
#             f"Найдено несколько объектов ({entity_label}) с именем '{target_name}' (IDs: {ids})."
#         )
#     return matches[0]

def resolve_single_by_name(items: list[dict], target_name: str, entity_label: str) -> dict:
    """Находит ровно один объект по имени без учёта регистра; при неточном совпадении подсказывает кандидатов."""
    needle = target_name.strip().casefold()
    exact = [
        item for item in (items or [])
        if str(item.get("name", "")).strip().casefold() == needle
    ]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        ids = ", ".join(str(m.get("id")) for m in exact)
        raise ValueError(
            f"Найдено несколько объектов ({entity_label}) с точным именем '{target_name}' (IDs: {ids})."
        )

    partial = [
        str(item.get("name", ""))
        for item in (items or [])
        if needle and needle in str(item.get("name", "")).strip().casefold()
    ]
    if partial:
        raise ValueError(
            f"{entity_label} с точным именем '{target_name}' не найдена. "
            f"Возможно, вы имели в виду: {', '.join(sorted(partial))}"
        )

    available = ", ".join(sorted(str(i.get("name", "")) for i in (items or []))) or "нет"
    raise ValueError(
        f"{entity_label} с именем '{target_name}' не найдена. Доступные: {available}"
    )
def cmd_lookup(args: argparse.Namespace) -> None:
    """Быстрый поиск сетей и групп по подстроке (без учёта регистра)."""
    q = (args.query or "").strip().casefold()
    networks = request("GET", "/networks") or []
    groups = request("GET", "/groups") or []

    matched_nets = [
        {"id": n.get("id"), "name": n.get("name")}
        for n in networks
        if not q or q in str(n.get("name", "")).casefold()
    ]
    matched_groups = [
        {"id": g.get("id"), "name": g.get("name")}
        for g in groups
        if not q or q in str(g.get("name", "")).casefold()
    ]

    print(json.dumps({"networks": matched_nets, "groups": matched_groups}, indent=2, ensure_ascii=False))
    
def resolve_group_ids(groups: list[dict], group_names: list[str]) -> list[str]:
    """Преобразует список имён групп (в любом регистре) в список уникальных ID."""
    resolved_ids: list[str] = []
    for raw_name in group_names:
        grp = resolve_single_by_name(groups, raw_name, "Группа")
        gid = grp["id"]
        if gid not in resolved_ids:
            resolved_ids.append(gid)
    return resolved_ids


def resolve_resource(
    network_id: str,
    resource_id: str | None = None,
    resource_name: str | None = None,
) -> dict:
    """Находит существующий ресурс внутри сети по ID или по имени (без учёта регистра)."""
    resources = request("GET", f"/networks/{network_id}/resources") or []
    if resource_id:
        for res in resources:
            if res.get("id") == resource_id:
                return res
        raise ValueError(f"Ресурс с ID '{resource_id}' не найден в сети '{network_id}'.")
    if resource_name:
        return resolve_single_by_name(resources, resource_name, "Ресурс сети")
    raise ValueError("Необходимо указать --id или --name для поиска ресурса.")


def print_dry_run(method: str, endpoint: str, payload: dict | None = None) -> None:
    print("[DRY-RUN] Мутирующий запрос не отправлен.")
    print(f"  Method:   {method}")
    print(f"  Endpoint: {BASE_URL}/{endpoint.lstrip('/')}")
    if payload is not None:
        print("  Payload:")
        print(json.dumps(payload, indent=2, ensure_ascii=False))


def cmd_create(args: argparse.Namespace) -> None:
    networks = request("GET", "/networks") or []
    groups = request("GET", "/groups") or []

    network = resolve_single_by_name(networks, args.network, "Сеть")
    network_id = network["id"]
    group_ids = resolve_group_ids(groups, args.groups)

    # Проверка на дубликат ресурса по имени в этой сети
    existing = request("GET", f"/networks/{network_id}/resources") or []
    needle = args.name.strip().casefold()
    if any(str(r.get("name", "")).strip().casefold() == needle for r in existing):
        raise ValueError(
            f"Ресурс '{args.name}' уже существует в сети '{network['name']}' ({network_id}). "
            "Используйте команду update."
        )

    payload: dict = {
        "name": args.name.strip(),
        "address": args.address.strip(),
        "enabled": not args.disabled,
        "groups": group_ids,
    }
    if args.description is not None:
        payload["description"] = args.description

    endpoint = f"/networks/{network_id}/resources"
    if args.dry_run:
        print_dry_run("POST", endpoint, payload)
        return

    created = request("POST", endpoint, payload)
    print(f"[SUCCESS] Ресурс '{created.get('name')}' создан в сети '{network['name']}'.")
    print(json.dumps(created, indent=2, ensure_ascii=False))


def cmd_update(args: argparse.Namespace) -> None:
    networks = request("GET", "/networks") or []
    network = resolve_single_by_name(networks, args.network, "Сеть")
    network_id = network["id"]

    current = resolve_resource(
        network_id,
        resource_id=args.id,
        resource_name=args.target_name or args.name,
    )
    resource_id = current["id"]

    # Собираем актуальный список group IDs (либо из новых имён, либо сохраняем текущие)
    if args.groups:
        groups = request("GET", "/groups") or []
        group_ids = resolve_group_ids(groups, args.groups)
    else:
        group_ids = [g["id"] for g in (current.get("groups") or []) if g.get("id")]

    if args.enabled is not None:
        enabled_val = args.enabled
    else:
        enabled_val = bool(current.get("enabled", True))

    payload: dict = {
        "name": (args.new_name or current.get("name", "")).strip(),
        "address": (args.address or current.get("address", "")).strip(),
        "enabled": enabled_val,
        "groups": group_ids,
    }
    if args.description is not None:
        payload["description"] = args.description
    elif current.get("description"):
        payload["description"] = current["description"]

    endpoint = f"/networks/{network_id}/resources/{resource_id}"
    if args.dry_run:
        print_dry_run("PUT", endpoint, payload)
        return

    backup_path = backup_resource(f"network_resource_{resource_id}", current)
    print(f"[BACKUP] Текущее состояние ресурса сохранено: {backup_path}")

    updated = request("PUT", endpoint, payload)
    print(f"[SUCCESS] Ресурс '{updated.get('name')}' ({resource_id}) обновлён.")
    print(json.dumps(updated, indent=2, ensure_ascii=False))


def cmd_delete(args: argparse.Namespace) -> None:
    networks = request("GET", "/networks") or []
    network = resolve_single_by_name(networks, args.network, "Сеть")
    network_id = network["id"]

    current = resolve_resource(
        network_id,
        resource_id=args.id,
        resource_name=args.name,
    )
    resource_id = current["id"]
    endpoint = f"/networks/{network_id}/resources/{resource_id}"

    if args.dry_run:
        print_dry_run("DELETE", endpoint)
        print(f"  Target: {current.get('name')} ({current.get('address')}, id={resource_id})")
        return

    if not args.yes:
        print(
            f"Подтвердите удаление ресурса '{current.get('name')}' "
            f"[{current.get('address')}] (ID: {resource_id}) из сети '{network['name']}'."
        )
        answer = input("Введите 'yes' для подтверждения: ").strip().lower()
        if answer != "yes":
            print("[ABORTED] Удаление отменено пользователем.")
            return

    backup_path = backup_resource(f"network_resource_{resource_id}", current)
    print(f"[BACKUP] Копия удаляемого ресурса сохранена: {backup_path}")

    request("DELETE", endpoint)
    print(f"[SUCCESS] Ресурс '{current.get('name')}' ({resource_id}) удалён.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Управление ресурсами сетей NetBird (POST/PUT/DELETE) по именам сетей и групп."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # POST: create
    p_create = subparsers.add_parser("create", help="Создать новый ресурс в сети (POST)")
    p_create.add_argument("--network", required=True, help="Имя сети (регистр не важен)")
    p_create.add_argument("--name", required=True, help="Имя нового ресурса")
    p_create.add_argument(
        "--address",
        required=True,
        help="IP/CIDR или домен (например, 10.250.0.0/24, 192.168.1.10 или *.corp.local)",
    )
    p_create.add_argument(
        "--groups",
        nargs="+",
        required=True,
        help="Имена групп назначения через пробел (регистр не важен)",
    )
    p_create.add_argument("--description", default=None, help="Описание ресурса")
    p_create.add_argument("--disabled", action="store_true", help="Создать ресурс выключенным")
    p_create.add_argument("--dry-run", action="store_true", help="Только показать JSON-запрос без отправки")
    p_create.set_defaults(func=cmd_create)

    # PUT: update
    p_update = subparsers.add_parser("update", help="Обновить существующий ресурс сети (PUT)")
    p_update.add_argument("--network", required=True, help="Имя сети (регистр не важен)")
    target_grp = p_update.add_mutually_exclusive_group(required=True)
    target_grp.add_argument("--name", dest="target_name", help="Текущее имя ресурса (регистр не важен)")
    target_grp.add_argument("--id", help="ID ресурса")
    p_update.add_argument("--new-name", help="Новое имя ресурса")
    p_update.add_argument("--address", help="Новый адрес/подсеть/домен")
    p_update.add_argument("--groups", nargs="+", help="Новый список имён групп (регистр не важен)")
    p_update.add_argument("--description", default=None, help="Новое описание")
    state_grp = p_update.add_mutually_exclusive_group()
    state_grp.add_argument("--enable", dest="enabled", action="store_true", default=None, help="Включить ресурс")
    state_grp.add_argument("--disable", dest="enabled", action="store_false", help="Выключить ресурс")
    p_update.add_argument("--dry-run", action="store_true", help="Только показать JSON-запрос без отправки")
    p_update.set_defaults(func=cmd_update)

    # DELETE: delete
    p_delete = subparsers.add_parser("delete", help="Удалить ресурс из сети (DELETE)")
    p_delete.add_argument("--network", required=True, help="Имя сети (регистр не важен)")
    del_grp = p_delete.add_mutually_exclusive_group(required=True)
    del_grp.add_argument("--name", help="Имя удаляемого ресурса (регистр не важен)")
    del_grp.add_argument("--id", help="ID удаляемого ресурса")
    p_delete.add_argument("--yes", action="store_true", help="Подтвердить удаление без интерактивного запроса")
    p_delete.add_argument("--dry-run", action="store_true", help="Только показать запрос без удаления")
    p_delete.set_defaults(func=cmd_delete)

    p_lookup = subparsers.add_parser("lookup", help="Поиск сетей и групп по фрагменту имени")
    p_lookup.add_argument("--query", default="", help="Фрагмент имени (пусто — вывести все)")
    p_lookup.set_defaults(func=cmd_lookup)
    
    return parser


def main() -> None:
    if not BASE_URL or not TOKEN:
        print("[ERROR] Не заданы NETBIRD_URL или NETBIRD_TOKEN в файле .env", file=sys.stderr)
        sys.exit(1)

    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except ValueError as exc:
        print(f"[VALIDATION ERROR] {exc}", file=sys.stderr)
        sys.exit(2)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        body = exc.response.text if exc.response is not None else ""
        print(f"[HTTP ERROR {status}] {exc}\n{body}", file=sys.stderr)
        sys.exit(1)
    except requests.RequestException as exc:
        print(f"[NETWORK ERROR] {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
