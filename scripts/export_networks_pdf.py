#!/usr/bin/env python3
"""
Скрипт выгрузки всех сетей NetBird (Networks), их маршрутизаторов,
сетевых ресурсов и связанных политик в PDF-отчет backups/netbird_networks.pdf.
"""

import argparse
import html
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
import requests

# Настройка путей импорта
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from nb_client import BASE_URL, TOKEN, request  # noqa: E402


def safe_get(endpoint: str) -> list | dict:
    """Выполняет GET-запрос с обработкой HTTP-ошибок."""
    try:
        data = request("GET", endpoint)
        return data if data is not None else []
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        print(f"[WARN] HTTP {status} при запросе {endpoint}: {exc}", file=sys.stderr)
        return []
    except requests.RequestException as exc:
        print(f"[ERROR] Сетевая ошибка при запросе {endpoint}: {exc}", file=sys.stderr)
        sys.exit(1)


def collect_networks_data() -> dict:
    """Собирает список всех сетей и обогащает их деталями о роутерах, ресурсах, пирах и политиках."""
    if not BASE_URL or not TOKEN:
        print("[ERROR] Не заданы NETBIRD_URL или NETBIRD_TOKEN в .env", file=sys.stderr)
        sys.exit(1)

    print("1/5 Запрос списка сетей (/networks)...")
    networks = safe_get("/networks")

    print("2/5 Запрос списка узлов (/peers) для сопоставления роутеров...")
    peers_list = safe_get("/peers")
    peers_map = {p["id"]: p for p in peers_list if isinstance(p, dict) and "id" in p}

    print("3/5 Запрос списка групп (/groups)...")
    groups_list = safe_get("/groups")
    groups_map = {g["id"]: g.get("name", g["id"]) for g in groups_list if isinstance(g, dict) and "id" in g}

    print("4/5 Запрос политик безопасности (/policies)...")
    policies_list = safe_get("/policies")
    policies_map = {pol["id"]: pol for pol in policies_list if isinstance(pol, dict) and "id" in pol}

    print("5/5 Обогащение сетей ресурсами и роутерами...")
    enriched_networks = []
    total_resources = 0
    total_routers = 0

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
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "server_url": BASE_URL,
        "summary": {
            "networks_count": len(enriched_networks),
            "resources_count": total_resources,
            "routers_count": total_routers,
        },
        "networks": enriched_networks,
        "peers_map": peers_map,
        "groups_map": groups_map,
        "policies_map": policies_map,
    }


def generate_html(data: dict) -> str:
    """Генерирует чистый, стилизованный HTML-документ для конвертации в PDF."""
    summary = data["summary"]
    server_url = html.escape(data["server_url"])
    generated_at = html.escape(data["generated_at"])
    peers_map = data["peers_map"]
    policies_map = data["policies_map"]

    networks_html = []
    for idx, net in enumerate(data["networks"], 1):
        net_name = html.escape(net.get("name") or "Unnamed Network")
        net_id = html.escape(net.get("id") or "")
        net_desc = html.escape(net.get("description") or "—")
        routers = net.get("routers_details", [])
        resources = net.get("resources_details", [])
        policy_ids = net.get("policies", [])

        # Формируем таблицу роутеров
        if routers:
            routers_rows = []
            for r in routers:
                r_id = html.escape(r.get("id", ""))
                peer_id = r.get("peer")
                peer_info = peers_map.get(peer_id, {})
                peer_name = html.escape(peer_info.get("name") or peer_id or "—")
                peer_ip = html.escape(peer_info.get("ip") or "—")
                metric = r.get("metric", "—")
                masquerade = "Да (NAT)" if r.get("masquerade") else "Нет"
                enabled = "Включен" if r.get("enabled", True) else "Отключен"
                status_class = "badge-success" if r.get("enabled", True) else "badge-danger"

                routers_rows.append(f"""
                <tr>
                    <td><strong>{peer_name}</strong><br><span class="muted">{peer_ip}</span></td>
                    <td><span class="badge {status_class}">{enabled}</span></td>
                    <td>{masquerade}</td>
                    <td><code>{metric}</code></td>
                    <td class="mono">{r_id}</td>
                </tr>
                """)
            routers_table = f"""
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Маршрутизирующий узел (Peer)</th>
                        <th>Статус</th>
                        <th>Masquerade</th>
                        <th>Метрика</th>
                        <th>ID роутера</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(routers_rows)}
                </tbody>
            </table>
            """
        else:
            routers_table = "<p class='empty-note'>Нет привязанных маршрутизаторов</p>"

        # Формируем таблицу ресурсов
        if resources:
            resources_rows = []
            for res in resources:
                res_name = html.escape(res.get("name") or "—")
                res_type = html.escape(res.get("type") or "subnet")
                res_addr = html.escape(res.get("address") or "—")
                res_id = html.escape(res.get("id") or "")
                res_groups = res.get("groups") or []
                groups_str = ", ".join(html.escape(g.get("name", g.get("id", ""))) for g in res_groups) or "—"
                res_enabled = "Вкл" if res.get("enabled", True) else "Выкл"
                badge_class = "badge-primary" if res_type == "subnet" else "badge-warning"
                type_label = "Подсеть" if res_type == "subnet" else "Хост"

                resources_rows.append(f"""
                <tr>
                    <td><strong>{res_name}</strong></td>
                    <td><span class="badge {badge_class}">{type_label}</span></td>
                    <td><code>{res_addr}</code></td>
                    <td>{groups_str}</td>
                    <td><span class="badge {'badge-success' if res.get('enabled', True) else 'badge-muted'}">{res_enabled}</span></td>
                    <td class="mono">{res_id}</td>
                </tr>
                """)
            resources_table = f"""
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Имя ресурса</th>
                        <th>Тип</th>
                        <th>Адрес / CIDR</th>
                        <th>Группы доступа</th>
                        <th>Статус</th>
                        <th>ID ресурса</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(resources_rows)}
                </tbody>
            </table>
            """
        else:
            resources_table = "<p class='empty-note'>Сетевые ресурсы отсутствуют</p>"

        # Формируем блок политик
        policies_items = []
        for pid in policy_ids:
            pol = policies_map.get(pid)
            if pol:
                p_name = html.escape(pol.get("name", pid))
                p_rules = pol.get("rules", [])
                rules_desc = []
                for r in p_rules:
                    sources = ", ".join(s.get("name", "") for s in (r.get("sources") or [])) or "Любые"
                    destinations = ", ".join(d.get("name", "") for d in (r.get("destinations") or [])) or "Любые"
                    proto = r.get("protocol", "all").upper()
                    action = "Разрешить" if r.get("action") == "accept" else "Запретить"
                    rules_desc.append(f"• <strong>{action}</strong> ({proto}): {html.escape(sources)} &rarr; {html.escape(destinations)}")
                rules_html = "<br>".join(rules_desc) if rules_desc else "Правила по умолчанию"
                policies_items.append(f"""
                <div class="policy-card">
                    <div class="policy-header"><strong>{p_name}</strong> <span class="mono muted">({pid})</span></div>
                    <div class="policy-rules">{rules_html}</div>
                </div>
                """)
            else:
                policies_items.append(f"<div class='policy-card mono muted'>ID политики: {pid}</div>")

        policies_section = "".join(policies_items) if policies_items else "<p class='empty-note'>Политики доступа не привязаны</p>"

        networks_html.append(f"""
        <div class="network-card">
            <div class="network-header">
                <div class="network-title">
                    <span class="net-idx">#{idx}</span>
                    <span class="net-name">{net_name}</span>
                </div>
                <div class="network-meta">
                    <span class="badge badge-info">ID: {net_id}</span>
                    <span class="badge badge-primary">Роутеров: {len(routers)}</span>
                    <span class="badge badge-secondary">Ресурсов: {len(resources)}</span>
                </div>
            </div>

            {f'<div class="network-desc"><strong>Описание:</strong> {net_desc}</div>' if net_desc != '—' else ''}

            <div class="section-block">
                <div class="section-title">Маршрутизаторы (Network Routers)</div>
                {routers_table}
            </div>

            <div class="section-block">
                <div class="section-title">Сетевые ресурсы (Network Resources)</div>
                {resources_table}
            </div>

            <div class="section-block">
                <div class="section-title">Связанные политики безопасности (Policies)</div>
                <div class="policies-grid">
                    {policies_section}
                </div>
            </div>
        </div>
        """)

    full_html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>NetBird Networks Report</title>
    <style>
        @page {{
            size: A4;
            margin: 12mm;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            color: #1e293b;
            background-color: #ffffff;
            margin: 0;
            padding: 0;
            font-size: 11px;
            line-height: 1.45;
        }}
        .header {{
            border-bottom: 2px solid #2563eb;
            padding-bottom: 12px;
            margin-bottom: 18px;
            display: flex;
            justify-content: space-between;
            align-items: flex-end;
        }}
        .header-title h1 {{
            margin: 0 0 4px 0;
            font-size: 22px;
            color: #0f172a;
            letter-spacing: -0.5px;
        }}
        .header-title .subtitle {{
            color: #64748b;
            font-size: 11px;
        }}
        .header-meta {{
            text-align: right;
            color: #64748b;
            font-size: 10px;
        }}
        .summary-grid {{
            display: flex;
            gap: 12px;
            margin-bottom: 20px;
        }}
        .summary-box {{
            flex: 1;
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 6px;
            padding: 10px 14px;
            text-align: center;
        }}
        .summary-box .val {{
            font-size: 20px;
            font-weight: 700;
            color: #2563eb;
            margin-bottom: 2px;
        }}
        .summary-box .lbl {{
            font-size: 10px;
            color: #64748b;
            text-transform: uppercase;
            font-weight: 600;
            letter-spacing: 0.5px;
        }}
        .network-card {{
            background: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 8px;
            padding: 14px;
            margin-bottom: 18px;
            page-break-inside: avoid;
            box-shadow: 0 1px 3px rgba(0,0,0,0.03);
        }}
        .network-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #f1f5f9;
            padding-bottom: 8px;
            margin-bottom: 10px;
        }}
        .network-title {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .net-idx {{
            background: #2563eb;
            color: #ffffff;
            font-weight: bold;
            font-size: 10px;
            padding: 2px 6px;
            border-radius: 4px;
        }}
        .net-name {{
            font-size: 15px;
            font-weight: 700;
            color: #0f172a;
        }}
        .network-desc {{
            background: #f8fafc;
            padding: 6px 10px;
            border-radius: 4px;
            margin-bottom: 10px;
            font-size: 11px;
            color: #475569;
        }}
        .section-block {{
            margin-top: 12px;
        }}
        .section-title {{
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            color: #475569;
            letter-spacing: 0.5px;
            margin-bottom: 6px;
        }}
        .data-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 10px;
            margin-bottom: 8px;
        }}
        .data-table th {{
            background: #f1f5f9;
            color: #334155;
            text-align: left;
            padding: 6px 8px;
            font-weight: 600;
            border: 1px solid #e2e8f0;
        }}
        .data-table td {{
            padding: 5px 8px;
            border: 1px solid #e2e8f0;
            vertical-align: middle;
        }}
        .data-table tr:nth-child(even) td {{
            background: #f8fafc;
        }}
        .policies-grid {{
            display: flex;
            flex-direction: column;
            gap: 6px;
        }}
        .policy-card {{
            background: #f8fafc;
            border-left: 3px solid #2563eb;
            border-top: 1px solid #e2e8f0;
            border-right: 1px solid #e2e8f0;
            border-bottom: 1px solid #e2e8f0;
            padding: 6px 10px;
            border-radius: 0 4px 4px 0;
            font-size: 10px;
        }}
        .policy-header {{
            margin-bottom: 3px;
        }}
        .policy-rules {{
            color: #334155;
            line-height: 1.4;
        }}
        .badge {{
            display: inline-block;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 9px;
            font-weight: 600;
        }}
        .badge-primary {{ background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; }}
        .badge-secondary {{ background: #f5f3ff; color: #6d28d9; border: 1px solid #ddd6fe; }}
        .badge-success {{ background: #ecfdf5; color: #047857; border: 1px solid #a7f3d0; }}
        .badge-warning {{ background: #fffbeb; color: #b45309; border: 1px solid #fde68a; }}
        .badge-danger {{ background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; }}
        .badge-info {{ background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; }}
        .badge-muted {{ background: #f1f5f9; color: #64748b; border: 1px solid #e2e8f0; }}
        .mono {{
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            font-size: 9px;
        }}
        code {{
            background: #f1f5f9;
            padding: 2px 4px;
            border-radius: 3px;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            font-size: 9.5px;
            color: #0f172a;
        }}
        .muted {{
            color: #64748b;
        }}
        .empty-note {{
            color: #94a3b8;
            font-style: italic;
            font-size: 10px;
            margin: 4px 0;
        }}
        .footer {{
            margin-top: 24px;
            padding-top: 10px;
            border-top: 1px solid #e2e8f0;
            text-align: center;
            color: #94a3b8;
            font-size: 9px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <div class="header-title">
            <h1>Сетевые топологии NetBird (Networks)</h1>
            <div class="subtitle">Сервер: {server_url}</div>
        </div>
        <div class="header-meta">
            <div>Дата формирования: <strong>{generated_at}</strong></div>
            <div>Статус: <strong>Актуальный снимок</strong></div>
        </div>
    </div>

    <div class="summary-grid">
        <div class="summary-box">
            <div class="val">{summary['networks_count']}</div>
            <div class="lbl">Сетей (Networks)</div>
        </div>
        <div class="summary-box">
            <div class="val">{summary['routers_count']}</div>
            <div class="lbl">Маршрутизаторов</div>
        </div>
        <div class="summary-box">
            <div class="val">{summary['resources_count']}</div>
            <div class="lbl">Сетевых ресурсов</div>
        </div>
    </div>

    {''.join(networks_html)}

    <div class="footer">
        Отчет сформирован автоматически через NetBird API Client • Документ предназначен для внутреннего использования
    </div>
</body>
</html>
"""
    return full_html


def export_pdf(output_path: Path, keep_html: bool = False):
    """Выполняет полный цикл сборки данных, создания HTML и генерации PDF через wkhtmltopdf."""
    data = collect_networks_data()
    html_content = generate_html(data)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_html_path = output_path.with_suffix(".html")
    temp_html_path.write_text(html_content, encoding="utf-8")

    cmd = [
        "wkhtmltopdf",
        "--page-size", "A4",
        "--margin-top", "12mm",
        "--margin-bottom", "12mm",
        "--margin-left", "10mm",
        "--margin-right", "10mm",
        "--encoding", "UTF-8",
        "--enable-local-file-access",
        str(temp_html_path),
        str(output_path),
    ]

    print(f"Конвертация HTML в PDF ({output_path})...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[ERROR] Ошибка генерации PDF:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    if not keep_html and temp_html_path.exists():
        temp_html_path.unlink()

    file_size_kb = output_path.stat().st_size / 1024
    print(f"[SUCCESS] PDF-отчет успешно создан: {output_path} ({file_size_kb:.1f} KB)")


def main():
    parser = argparse.ArgumentParser(description="Экспорт сетей NetBird в PDF")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=PROJECT_ROOT / "backups" / "netbird_networks.pdf",
        help="Путь к результирующему PDF файлу",
    )
    parser.add_argument(
        "--keep-html",
        action="store_true",
        help="Сохранять промежуточный HTML файл",
    )
    args = parser.parse_args()

    export_pdf(args.output, args.keep_html)


if __name__ == "__main__":
    main()
