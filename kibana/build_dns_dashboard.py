"""Generate the DNS dashboard as Kibana saved objects (NDJSON).

Usage:  python build_dns_dashboard.py > dns-dashboard.ndjson
Import: curl -XPOST 'localhost:5601/api/saved_objects/_import?overwrite=true' -H 'kbn-xsrf: true' --form file=@dns-dashboard.ndjson
"""
import json

DV = "activity-dns"          # data view id (see README / data views created earlier)
LAYER = "layer1"
CLIENT_Q = 'dns.message_type : "ClientQuery"'
CLIENT_R = 'dns.message_type : "ClientResponse"'


# ---- Lens column helpers -------------------------------------------------
def count(label="Count", flt=None):
    c = {"label": label, "dataType": "number", "operationType": "count", "isBucketed": False,
         "scale": "ratio", "sourceField": "___records___", "params": {"emptyAsNull": True}}
    if flt:
        c["filter"] = {"query": flt, "language": "kuery"}
    return c


def uniq(label, field):
    return {"label": label, "dataType": "number", "operationType": "unique_count", "isBucketed": False,
            "scale": "ratio", "sourceField": field, "params": {"emptyAsNull": True}}


def pct(label, field, p):
    return {"label": label, "dataType": "number", "operationType": "percentile", "isBucketed": False,
            "scale": "ratio", "sourceField": field, "params": {"percentile": p}}


def date_hist():
    return {"label": "@timestamp", "dataType": "date", "operationType": "date_histogram", "isBucketed": True,
            "scale": "interval", "sourceField": "@timestamp",
            "params": {"interval": "auto", "includeEmptyIntervals": True, "dropPartials": False}}


def terms(label, field, order_col, size=10, dtype="string"):
    return {"label": label, "dataType": dtype, "operationType": "terms", "isBucketed": True,
            "scale": "ordinal", "sourceField": field,
            "params": {"size": size, "orderBy": {"type": "column", "columnId": order_col},
                       "orderDirection": "desc", "otherBucket": False, "missingBucket": False,
                       "parentFormat": {"id": "terms"}}}


def lens(oid, title, vis_type, visualization, columns, query):
    for c in columns.values():          # keep our labels instead of Lens auto-names ("Sum of data.received")
        if c["operationType"] != "date_histogram":
            c["customLabel"] = True
    state = {
        "visualization": visualization,
        "query": {"query": query, "language": "kuery"},
        "filters": [],
        "datasourceStates": {"formBased": {"layers": {LAYER: {
            "columns": columns, "columnOrder": list(columns.keys()), "incompleteColumns": {}}}}},
        "internalReferences": [],
        "adHocDataViews": {},
    }
    return {"type": "lens", "id": oid, "managed": False,
            "attributes": {"title": title, "description": "", "visualizationType": vis_type, "state": state},
            "references": [{"type": "index-pattern", "id": DV, "name": f"indexpattern-datasource-layer-{LAYER}"}],
            "coreMigrationVersion": "8.8.0", "typeMigrationVersion": "8.9.0"}


def metric(oid, title, col, query):
    return lens(oid, title, "lnsMetric",
                {"layerId": LAYER, "layerType": "data", "metricAccessor": "m"}, {"m": col}, query)


def xy(oid, title, query, columns, accessors, x="x", split=None, kind="bar_stacked"):
    layer = {"layerId": LAYER, "accessors": accessors, "position": "top", "seriesType": kind,
             "showGridlines": False, "layerType": "data", "xAccessor": x}
    if split:
        layer["splitAccessor"] = split
    return lens(oid, title, "lnsXY",
                {"legend": {"isVisible": True, "position": "right"}, "valueLabels": "hide",
                 "preferredSeriesType": kind, "layers": [layer]}, columns, query)


def donut(oid, title, query, columns, group, metric_col):
    return lens(oid, title, "lnsPie",
                {"shape": "donut", "layers": [{"layerId": LAYER, "primaryGroups": [group], "metrics": [metric_col],
                                               "numberDisplay": "percent", "categoryDisplay": "default",
                                               "legendDisplay": "default", "nestedLegend": False,
                                               "layerType": "data"}]}, columns, query)


def table(oid, title, query, columns, order):
    return lens(oid, title, "lnsDatatable",
                {"layerId": LAYER, "layerType": "data", "columns": [{"columnId": c} for c in order]}, columns, query)


# ---- Panels -------------------------------------------------------------
P = [
    # (object, x, y, w, h)
    (metric("dns-m-queries", "Client queries", count("Client queries"), CLIENT_Q), 0, 0, 12, 8),
    (metric("dns-m-clients", "Unique clients", uniq("Unique clients", "dns.client_ip"), CLIENT_Q), 12, 0, 12, 8),
    (metric("dns-m-nxdomain", "NXDOMAIN responses", count("NXDOMAIN"), CLIENT_R + ' and dns.rcode : "NXDomain"'), 24, 0, 12, 8),
    (metric("dns-m-p95", "Latency P95 (ms)", pct("P95 latency (ms)", "dns.latency_ms", 95), CLIENT_R), 36, 0, 12, 8),

    (xy("dns-x-qps", "Client queries over time, by type", CLIENT_Q,
        {"x": date_hist(), "t": terms("Query type", "dns.qtype", "y", 6), "y": count("Queries")},
        ["y"], split="t"), 0, 8, 32, 14),
    (donut("dns-d-rcode", "Response codes", CLIENT_R,
           {"g": terms("Response code", "dns.rcode", "v", 8), "v": count("Responses")}, "g", "v"), 32, 8, 16, 14),

    (xy("dns-x-latency", "Client response latency (ms)", CLIENT_R,
        {"x": date_hist(), "p50": pct("P50", "dns.latency_ms", 50), "p95": pct("P95", "dns.latency_ms", 95)},
        ["p50", "p95"], kind="line"), 0, 22, 24, 14),
    (xy("dns-x-stage", "Messages over time, by stage", 'dns.direction : "query"',
        {"x": date_hist(), "s": terms("Stage", "dns.stage", "y", 4), "y": count("Queries")},
        ["y"], split="s", kind="line"), 24, 22, 24, 14),

    (table("dns-t-domains", "Top queried domains", CLIENT_Q,
           {"d": terms("Domain", "dns.qname", "c", 15), "c": count("Queries")}, ["d", "c"]), 0, 36, 16, 16),
    (table("dns-t-clients", "Top clients", CLIENT_Q,
           {"d": terms("Client", "dns.client_ip", "c", 15, "ip"), "c": count("Queries")}, ["d", "c"]), 16, 36, 16, 16),
    (table("dns-t-nx", "Top NXDOMAIN domains", CLIENT_R + ' and dns.rcode : "NXDomain"',
           {"d": terms("Domain", "dns.qname", "c", 15), "c": count("NXDOMAIN")}, ["d", "c"]), 32, 36, 16, 16),
]

objs = [p[0] for p in P]
panels, refs = [], []
for i, (o, x, y, w, h) in enumerate(P, 1):
    panels.append({"version": "8.17.0", "type": "lens", "gridData": {"x": x, "y": y, "w": w, "h": h, "i": str(i)},
                   "panelIndex": str(i), "embeddableConfig": {"enhancements": {}}, "panelRefName": f"panel_{i}"})
    refs.append({"name": f"panel_{i}", "type": "lens", "id": o["id"]})

objs.append({
    "type": "dashboard", "id": "bdds-dns-activity", "managed": False,
    "attributes": {
        "title": "BDDS DNS Activity", "description": "DNS client activity from BDDS dnstap (Kafka -> Logstash -> ES)",
        "timeRestore": True, "timeFrom": "now-1h", "timeTo": "now",
        "refreshInterval": {"pause": False, "value": 30000},
        "optionsJSON": json.dumps({"useMargins": True, "syncColors": False, "syncCursor": True,
                                   "syncTooltips": False, "hidePanelTitles": False}),
        "panelsJSON": json.dumps(panels),
        "kibanaSavedObjectMeta": {"searchSourceJSON": json.dumps({"query": {"query": "", "language": "kuery"}, "filter": []})},
    },
    "references": refs, "coreMigrationVersion": "8.8.0", "typeMigrationVersion": "10.2.0",
})

for o in objs:
    print(json.dumps(o, separators=(",", ":")))
