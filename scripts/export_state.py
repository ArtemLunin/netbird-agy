#!/usr/bin/env python3
"""
Read-only экспорт текущей конфигурации NetBird (Networks, Resources, Routers, Groups, Policies)
в единый JSON-снимок в директории backups/.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import requests

# Добавляем папку scripts в sys.path для корректного импорта nb_client при запуске из корня проекта
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from nb_client import BASE_URL, TOKEN, request  # noqa: E402


def safe_get(endpoint: str) -> list | dict:
    """Выполняет GET-запрос с обработкой HTTP-ошибок без прерывания всего экспорта."""
    try:
        data = request("GET", endpoint)
        return data if data is not None else []
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        print(f"[WARN] Ошибка HTTP {status} при запросе {endpoint}: {exc}", file=sys.stderr)
        return []
    except requests.RequestException as exc:
        print(f"[ERROR] Сетевая ошибка при запросе {endpoint}: {exc}", file=sys.stderr)
        sys.exit(1)


def collect_state() -> dict:
    """Собирает полное состояние выбранных сущностей NetBird."""
    if not BASE_URL or not TOKEN:
        print("[ERROR] Не заданы NETBIRD_URL или NETBIRD_TOKEN в файле .env", file=sys.stderr)
        sys.exit(1)

    print("1/4 Выгрузка групп (/groups)...")
    groups = safe_get("/groups")

    print("2/4 Выгрузка политик доступа (/policies)...")
    policies = safe_get("/policies")

    print("3/4 Выгрузка сетей (/networks)...")
    networks = safe_get("/networks")

    print("4/4 Выгрузка ресурсов и роутеров для каждой сети...")
    total_resources = 0
    total_routers = 0

    enriched_networks = []
    for net in networks:
        net_id = net.get("id")
        if not net_id:
            continue

        resources = safe_get(f"/networks/{net_id}/resources")
        routers = safe_get(f"/networks/{net_id}/routers")

        total_resources += len(resources)
        total_routers += len(routers)

        net_copy = dict(net)
        net_copy["resources_details"] = resources
        net_copy["routers_details"] = routers
        enriched_networks.append(net_copy)

    return {
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "server_url": BASE_URL,
        "summary": {
            "networks_count": len(enriched_networks),
            "network_resources_count": total_resources,
            "network_routers_count": total_routers,
            "groups_count": len(groups),
            "policies_count": len(policies),
        },
        "networks": enriched_networks,
        "groups": groups,
        "policies": policies,
    }


def render_markdown_summary(snapshot: dict) -> str:
    """Формирует краткий читаемый отчет в формате Markdown."""
    s = snapshot["summary"]
    lines = [
        f"# NetBird State Snapshot ({snapshot['exported_at_utc']})",
        "",
        f"- **Сервер:** `{snapshot['server_url']}`",
        f"- **Сетей (Networks):** {s['networks_count']}",
        f"- **Сетевых ресурсов (Resources):** {s['network_resources_count']}",
        f"- **Сетевых роутеров (Routers):** {s['network_routers_count']}",
        f"- **Групп (Groups):** {s['groups_count']}",
        f"- **Политик (Policies):** {s['policies_count']}",
        "",
        "## Сети (Networks)",
    ]

    for net in snapshot["networks"]:
        lines.append(f"### {net.get('name')} (`{net.get('id')}`)")
        if net.get("description"):
            lines.append(f"*{net['description']}*")
        lines.append(
            f"- Ресурсов: {len(net.get('resources_details', []))}, "
            f"Роутеров: {len(net.get('routers_details', []))}"
        )
        for res in net.get("resources_details", []):
            state = "enabled" if res.get("enabled") else "disabled"
            lines.append(
                f"  - Ресурс: **{res.get('name')}** (`{res.get('address')}`, "
                f"тип: `{res.get('type')}`, {state})"
            )
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Read-only выгрузка конфигурации NetBird в папку backups/."
    )
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="Дополнительно сохранить читаемую сводку в .md файл рядом с JSON",
    )
    args = parser.parse_args()

    snapshot = collect_state()

    backups_dir = PROJECT_ROOT / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = backups_dir / f"netbird_state_{ts}.json"
    json_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")

    s = snapshot["summary"]
    print("\nГотово! Сводка выгруженных объектов:")
    print(f"  - Networks:  {s['networks_count']}")
    print(f"  - Resources: {s['network_resources_count']}")
    print(f"  - Routers:   {s['network_routers_count']}")
    print(f"  - Groups:    {s['groups_count']}")
    print(f"  - Policies:  {s['policies_count']}")
    print(f"JSON-снимок сохранён: {json_path}")

    if args.markdown:
        md_path = backups_dir / f"netbird_summary_{ts}.md"
        md_path.write_text(render_markdown_summary(snapshot), encoding="utf-8")
        print(f"Markdown-отчёт сохранён: {md_path}")


if __name__ == "__main__":
    main()
