import json
from pathlib import Path


DASHBOARD_DIR = Path("/Users/benedikt/Projekte/measurepi/grafana/dashboards")


def datasource():
    return {"type": "prometheus", "uid": "prometheus"}


def text_panel(panel_id, title, content, x, y, w=24, h=3):
    return {
        "datasource": datasource(),
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "id": panel_id,
        "options": {"content": content, "mode": "markdown"},
        "pluginVersion": "11.1.5",
        "title": title,
        "type": "text",
    }


def stat_panel(panel_id, title, expr, x, y, w=6, h=4, color_mode="value"):
    return {
        "datasource": datasource(),
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "thresholds"},
                "thresholds": {"mode": "absolute", "steps": [{"color": "orange", "value": None}, {"color": "green", "value": 1}]},
            },
            "overrides": [],
        },
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "id": panel_id,
        "options": {
            "colorMode": color_mode,
            "graphMode": "none",
            "justifyMode": "center",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "showPercentChange": False,
            "textMode": "auto",
            "wideLayout": True,
        },
        "pluginVersion": "11.1.5",
        "targets": [{"editorMode": "code", "expr": expr, "instant": True, "refId": "A"}],
        "title": title,
        "type": "stat",
    }


def timeseries_panel(panel_id, title, targets, x, y, w=12, h=8, unit=None):
    panel = {
        "datasource": datasource(),
        "fieldConfig": {"defaults": {"color": {"mode": "palette-classic"}}, "overrides": []},
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "id": panel_id,
        "options": {"legend": {"displayMode": "table", "placement": "bottom", "showLegend": True}, "tooltip": {"mode": "multi", "sort": "desc"}},
        "pluginVersion": "11.1.5",
        "targets": targets,
        "title": title,
        "type": "timeseries",
    }
    if unit:
        panel["fieldConfig"]["defaults"]["unit"] = unit
    return panel


def bar_panel(panel_id, title, expr, x, y, w=12, h=8, unit=None):
    panel = {
        "datasource": datasource(),
        "fieldConfig": {"defaults": {"color": {"mode": "palette-classic"}}, "overrides": []},
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "id": panel_id,
        "options": {
            "barRadius": 0,
            "barWidth": 0.97,
            "fullHighlight": False,
            "groupWidth": 0.7,
            "legend": {"displayMode": "list", "placement": "bottom", "showLegend": False},
            "orientation": "horizontal",
            "showValue": "auto",
            "stacking": "none",
            "tooltip": {"mode": "single", "sort": "none"},
            "xTickLabelRotation": 0,
            "xTickLabelSpacing": 0,
        },
        "pluginVersion": "11.1.5",
        "targets": [{"editorMode": "code", "expr": expr, "instant": True, "legendFormat": "__auto", "refId": "A"}],
        "title": title,
        "type": "barchart",
    }
    if unit:
        panel["fieldConfig"]["defaults"]["unit"] = unit
    return panel


def table_panel(panel_id, title, targets, x, y, w=12, h=8):
    return {
        "datasource": datasource(),
        "fieldConfig": {"defaults": {"custom": {"align": "auto", "cellOptions": {"type": "auto"}, "inspect": False}}, "overrides": []},
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "id": panel_id,
        "options": {"cellHeight": "sm", "footer": {"countRows": False, "fields": "", "reducer": ["sum"], "show": False}, "showHeader": True},
        "pluginVersion": "11.1.5",
        "targets": targets,
        "title": title,
        "transformations": [{"id": "organize", "options": {}}],
        "type": "table",
    }


def build_overview():
    panels = [
        text_panel(
            1,
            "Scope",
            "Scope: schnelle Lage fuer alle UniFi-Access-Points. Dieses Dashboard beantwortet zuerst, ob alle APs online sind, welche Zone betroffen ist und welche APs bei Clients, CPU, Reboots oder Uplink-Traffic auffaellig werden.",
            0,
            0,
        ),
        stat_panel(2, "APs Online", 'sum(max by (ap_name) (unifi_ap_scrape_success{role="ap"}))', 0, 3),
        stat_panel(3, "EG Online", 'sum(max by (ap_name) (unifi_ap_scrape_success{role="ap",zone="EG"}))', 6, 3),
        stat_panel(4, "OG3 Online", 'sum(max by (ap_name) (unifi_ap_scrape_success{role="ap",zone="OG3"}))', 12, 3),
        stat_panel(5, "5 GHz Clients", 'sum(unifi_ap_ssid_clients{role="ap",band="5"})', 18, 3),
        bar_panel(6, "5 GHz Clients Per AP", 'sum by (ap_name) (unifi_ap_ssid_clients{role="ap",band="5"})', 0, 7, 12, 8),
        bar_panel(7, "Clients Per Zone", 'sum by (zone) (unifi_ap_ssid_clients{role="ap",band="5"})', 12, 7, 12, 8),
        timeseries_panel(
            8,
            "AP Uplink Throughput",
            [
                {"editorMode": "code", "expr": 'sum by (ap_name) (rate(unifi_ap_interface_in_octets_total{role="ap",if_name="eth0"}[5m]) * 8)', "legendFormat": "{{ap_name}} in", "refId": "A"},
                {"editorMode": "code", "expr": 'sum by (ap_name) (rate(unifi_ap_interface_out_octets_total{role="ap",if_name="eth0"}[5m]) * 8)', "legendFormat": "{{ap_name}} out", "refId": "B"},
            ],
            0,
            15,
            12,
            8,
            "bps",
        ),
        timeseries_panel(
            9,
            "CPU Average Per AP",
            [{"editorMode": "code", "expr": 'unifi_ap_cpu_load_percent_avg{role="ap"}', "legendFormat": "{{ap_name}}", "refId": "A"}],
            12,
            15,
            12,
            8,
            "percent",
        ),
        bar_panel(10, "Top AP CPU", 'topk(8, unifi_ap_cpu_load_percent_avg{role="ap"})', 0, 23, 8, 7, "percent"),
        bar_panel(11, "Recent Reboots (< 24h)", 'sort_desc((86400 - clamp_max(unifi_ap_uptime_seconds{role="ap"}, 86400)) > 0)', 8, 23, 8, 7),
        bar_panel(12, "AP Memory Available", 'unifi_ap_memory_kilobytes{role="ap",memory="avail"} / 1024', 16, 23, 8, 7, "decmbytes"),
        table_panel(
            13,
            "AP Inventory",
            [
                {
                    "editorMode": "code",
                    "expr": 'unifi_ap_info{role="ap"}',
                    "format": "table",
                    "instant": True,
                    "legendFormat": "__auto",
                    "refId": "A",
                }
            ],
            0,
            30,
            24,
            9,
        ),
        table_panel(
            14,
            "SSID Client Snapshot",
            [
                {
                    "editorMode": "code",
                    "expr": 'unifi_ap_ssid_clients{role="ap"}',
                    "format": "table",
                    "instant": True,
                    "legendFormat": "__auto",
                    "refId": "A",
                }
            ],
            0,
            39,
            24,
            9,
        ),
    ]

    return {
        "annotations": {"list": [{"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"}, "enable": True, "hide": True, "iconColor": "rgba(0, 211, 255, 1)", "name": "Annotations & Alerts", "type": "dashboard"}]},
        "editable": True,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 0,
        "id": None,
        "links": [],
        "panels": panels,
        "refresh": "30s",
        "schemaVersion": 39,
        "style": "dark",
        "tags": ["measurepi", "wifi", "ap"],
        "templating": {"list": []},
        "time": {"from": "now-24h", "to": "now"},
        "timepicker": {},
        "timezone": "",
        "title": "MeasurePi WLAN AP Overview",
        "uid": "measurepi-wlan-ap-overview",
        "version": 1,
        "weekStart": "",
    }


def build_zone_detail():
    panels = [
        text_panel(
            1,
            "Scope",
            "Scope: Detailansicht fuer eine AP-Zone und einzelne APs. Dieses Dashboard fokussiert auf die gewaehlte Zone, den AP, das Band und die zugehoerigen SSIDs oder Radios.",
            0,
            0,
        ),
        stat_panel(2, "AP Online", 'sum(max by (ap_name) (unifi_ap_scrape_success{role="ap",zone=~"${zone:regex}",ap_name=~"${ap:regex}"}))', 0, 3),
        stat_panel(3, "Clients", 'sum(unifi_ap_ssid_clients{role="ap",zone=~"${zone:regex}",ap_name=~"${ap:regex}",band=~"${band:regex}"})', 6, 3),
        stat_panel(4, "Uptime Hours", 'max(unifi_ap_uptime_seconds{role="ap",zone=~"${zone:regex}",ap_name=~"${ap:regex}"}) / 3600', 12, 3),
        stat_panel(5, "CPU Avg", 'max(unifi_ap_cpu_load_percent_avg{role="ap",zone=~"${zone:regex}",ap_name=~"${ap:regex}"})', 18, 3),
        bar_panel(6, "Clients Per AP", 'sum by (ap_name, band) (unifi_ap_ssid_clients{role="ap",zone=~"${zone:regex}",band=~"${band:regex}"})', 0, 7, 12, 8),
        table_panel(
            7,
            "AP Table",
            [{"editorMode": "code", "expr": 'unifi_ap_info{role="ap",zone=~"${zone:regex}"}', "format": "table", "instant": True, "legendFormat": "__auto", "refId": "A"}],
            12,
            7,
            12,
            8,
        ),
        timeseries_panel(
            8,
            "Selected AP Throughput",
            [
                {"editorMode": "code", "expr": 'sum by (ap_name) (rate(unifi_ap_interface_in_octets_total{role="ap",zone=~"${zone:regex}",ap_name=~"${ap:regex}",if_name="eth0"}[5m]) * 8)', "legendFormat": "{{ap_name}} in", "refId": "A"},
                {"editorMode": "code", "expr": 'sum by (ap_name) (rate(unifi_ap_interface_out_octets_total{role="ap",zone=~"${zone:regex}",ap_name=~"${ap:regex}",if_name="eth0"}[5m]) * 8)', "legendFormat": "{{ap_name}} out", "refId": "B"},
            ],
            0,
            15,
            12,
            8,
            "bps",
        ),
        timeseries_panel(
            9,
            "Selected AP Clients By SSID",
            [{"editorMode": "code", "expr": 'unifi_ap_ssid_clients{role="ap",zone=~"${zone:regex}",ap_name=~"${ap:regex}",band=~"${band:regex}"}', "legendFormat": "{{ssid}} ({{band}})", "refId": "A"}],
            12,
            15,
            12,
            8,
        ),
        timeseries_panel(
            10,
            "CPU And Load",
            [
                {"editorMode": "code", "expr": 'unifi_ap_cpu_load_percent_avg{role="ap",zone=~"${zone:regex}",ap_name=~"${ap:regex}"}', "legendFormat": "{{ap_name}} CPU", "refId": "A"},
                {"editorMode": "code", "expr": 'unifi_ap_load_average{role="ap",zone=~"${zone:regex}",ap_name=~"${ap:regex}",window="5m"}', "legendFormat": "{{ap_name}} load-5", "refId": "B"},
            ],
            0,
            23,
            12,
            8,
            "percent",
        ),
        timeseries_panel(
            11,
            "Memory Available And Cached",
            [
                {"editorMode": "code", "expr": 'unifi_ap_memory_kilobytes{role="ap",zone=~"${zone:regex}",ap_name=~"${ap:regex}",memory="avail"} / 1024', "legendFormat": "{{ap_name}} avail", "refId": "A"},
                {"editorMode": "code", "expr": 'unifi_ap_memory_kilobytes{role="ap",zone=~"${zone:regex}",ap_name=~"${ap:regex}",memory="cached"} / 1024', "legendFormat": "{{ap_name}} cached", "refId": "B"},
            ],
            12,
            23,
            12,
            8,
            "decmbytes",
        ),
        table_panel(
            12,
            "Radio Inventory",
            [{"editorMode": "code", "expr": 'unifi_ap_radio_info{role="ap",zone=~"${zone:regex}",ap_name=~"${ap:regex}",band=~"${band:regex}",radio_name=~"${radio:regex}"}', "format": "table", "instant": True, "legendFormat": "__auto", "refId": "A"}],
            0,
            31,
            12,
            8,
        ),
        table_panel(
            13,
            "Selected AP SSIDs",
            [{"editorMode": "code", "expr": 'unifi_ap_ssid_clients{role="ap",zone=~"${zone:regex}",ap_name=~"${ap:regex}",band=~"${band:regex}"}', "format": "table", "instant": True, "legendFormat": "__auto", "refId": "A"}],
            12,
            31,
            12,
            8,
        ),
        table_panel(
            14,
            "Selected AP Interfaces",
            [{"editorMode": "code", "expr": 'unifi_ap_interface_oper_status{role="ap",zone=~"${zone:regex}",ap_name=~"${ap:regex}"}', "format": "table", "instant": True, "legendFormat": "__auto", "refId": "A"}],
            0,
            39,
            24,
            9,
        ),
    ]

    return {
        "annotations": {"list": [{"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"}, "enable": True, "hide": True, "iconColor": "rgba(0, 211, 255, 1)", "name": "Annotations & Alerts", "type": "dashboard"}]},
        "editable": True,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 0,
        "id": None,
        "links": [],
        "panels": panels,
        "refresh": "30s",
        "schemaVersion": 39,
        "style": "dark",
        "tags": ["measurepi", "wifi", "ap"],
        "templating": {
            "list": [
                {
                    "current": {"selected": True, "text": "EG", "value": "EG"},
                    "datasource": datasource(),
                    "definition": 'label_values(unifi_ap_info{role="ap"}, zone)',
                    "hide": 0,
                    "includeAll": False,
                    "label": "Zone",
                    "multi": False,
                    "name": "zone",
                    "options": [],
                    "query": {"query": 'label_values(unifi_ap_info{role="ap"}, zone)', "refId": "StandardVariableQuery"},
                    "refresh": 1,
                    "regex": "",
                    "sort": 1,
                    "type": "query",
                },
                {
                    "allValue": ".*",
                    "current": {"selected": True, "text": "All", "value": ".*"},
                    "datasource": datasource(),
                    "definition": 'label_values(unifi_ap_info{role="ap",zone=~"${zone:regex}"}, ap_name)',
                    "hide": 0,
                    "includeAll": True,
                    "label": "AP",
                    "multi": False,
                    "name": "ap",
                    "options": [],
                    "query": {"query": 'label_values(unifi_ap_info{role="ap",zone=~"${zone:regex}"}, ap_name)', "refId": "StandardVariableQuery"},
                    "refresh": 1,
                    "regex": "",
                    "sort": 1,
                    "type": "query",
                },
                {
                    "allValue": ".*",
                    "current": {"selected": True, "text": "All", "value": ".*"},
                    "datasource": datasource(),
                    "definition": 'label_values(unifi_ap_ssid_clients{role="ap",zone=~"${zone:regex}",ap_name=~"${ap:regex}"}, band)',
                    "hide": 0,
                    "includeAll": True,
                    "label": "Band",
                    "multi": False,
                    "name": "band",
                    "options": [],
                    "query": {"query": 'label_values(unifi_ap_ssid_clients{role="ap",zone=~"${zone:regex}",ap_name=~"${ap:regex}"}, band)', "refId": "StandardVariableQuery"},
                    "refresh": 1,
                    "regex": "",
                    "sort": 1,
                    "type": "query",
                },
                {
                    "allValue": ".*",
                    "current": {"selected": True, "text": "All", "value": ".*"},
                    "datasource": datasource(),
                    "definition": 'label_values(unifi_ap_radio_info{role="ap",zone=~"${zone:regex}",ap_name=~"${ap:regex}",band=~"${band:regex}"}, radio_name)',
                    "hide": 0,
                    "includeAll": True,
                    "label": "Radio",
                    "multi": False,
                    "name": "radio",
                    "options": [],
                    "query": {"query": 'label_values(unifi_ap_radio_info{role="ap",zone=~"${zone:regex}",ap_name=~"${ap:regex}",band=~"${band:regex}"}, radio_name)', "refId": "StandardVariableQuery"},
                    "refresh": 1,
                    "regex": "",
                    "sort": 1,
                    "type": "query",
                },
            ]
        },
        "time": {"from": "now-24h", "to": "now"},
        "timepicker": {},
        "timezone": "",
        "title": "MeasurePi WLAN AP Zone Detail",
        "uid": "measurepi-wlan-ap-zone-detail",
        "version": 1,
        "weekStart": "",
    }


def main():
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    (DASHBOARD_DIR / "measurepi-wlan-ap-overview.json").write_text(json.dumps(build_overview(), indent=2) + "\n", encoding="utf-8")
    (DASHBOARD_DIR / "measurepi-wlan-ap-zone-detail.json").write_text(json.dumps(build_zone_detail(), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
