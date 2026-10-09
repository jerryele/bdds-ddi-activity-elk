"""Generate the DHCP dashboard as Kibana saved objects (NDJSON).

Usage:  python build_dhcp_dashboard.py > dhcp-dashboard.ndjson
Import: curl -XPOST 'localhost:5601/api/saved_objects/_import?overwrite=true' -H 'kbn-xsrf: true' --form file=@dhcp-dashboard.ndjson
"""
import json

LAYER = "layer1"
ACT = "activity-dhcp"                # data view ids (created earlier)
STAT = "statistics-dhcp"
TOP = "statistics-topclients-dhcp"
V4 = "dhcp.version : 4"
V4STAT = 'payloadType : "dhcpv4-statistics"'


# ---- Lens column helpers -------------------------------------------------
def count(label="Count", flt=None):
    c = {"label": label, "dataType": "number", "operationType": "count", "isBucketed": False,
         "scale": "ratio", "sourceField": "___records___", "params": {"emptyAsNull": True}}
    if flt:
        c["filter"] = {"query": flt, "language": "kuery"}
    return c


def agg(op, label, field):
    return {"label": label, "dataType": "number", "operationType": op, "isBucketed": False,
            "scale": "ratio", "sourceField": field, "params": {"emptyAsNull": True}}


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


def lens(oid, title, dv, vis_type, visualization, columns, query):
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
            "references": [{"type": "index-pattern", "id": dv, "name": f"indexpattern-datasource-layer-{LAYER}"}],
            "coreMigrationVersion": "8.8.0", "typeMigrationVersion": "8.9.0"}


def metric(oid, title, dv, col, query):
    return lens(oid, title, dv, "lnsMetric",
                {"layerId": LAYER, "layerType": "data", "metricAccessor": "m"}, {"m": col}, query)


def xy(oid, title, dv, query, columns, accessors, x="x", split=None, kind="bar_stacked"):
    layer = {"layerId": LAYER, "accessors": accessors, "position": "top", "seriesType": kind,
             "showGridlines": False, "layerType": "data", "xAccessor": x}
    if split:
        layer["splitAccessor"] = split
    return lens(oid, title, dv, "lnsXY",
                {"legend": {"isVisible": True, "position": "right"}, "valueLabels": "hide",
                 "preferredSeriesType": kind, "layers": [layer]}, columns, query)


def donut(oid, title, dv, query, columns, group, metric_col):
    return lens(oid, title, dv, "lnsPie",
                {"shape": "donut", "layers": [{"layerId": LAYER, "primaryGroups": [group], "metrics": [metric_col],
                                               "numberDisplay": "percent", "categoryDisplay": "default",
                                               "legendDisplay": "default", "nestedLegend": False,
                                               "layerType": "data"}]}, columns, query)


def table(oid, title, dv, query, columns, order):
    return lens(oid, title, dv, "lnsDatatable",
                {"layerId": LAYER, "layerType": "data", "columns": [{"columnId": c} for c in order]}, columns, query)


# ---- Panels -------------------------------------------------------------
P = [
    # (object, x, y, w, h)
    (metric("dhcp-m-packets", "DHCP packets", ACT, count("Packets"), ""), 0, 0, 12, 8),
    (metric("dhcp-m-clients", "Unique clients (MAC)", ACT, agg("unique_count", "Unique clients", "dhcp.client_mac"), V4), 12, 0, 12, 8),
    (metric("dhcp-m-acks", "ACKs", ACT, count("ACK"), 'dhcp.message_type : "Ack"'), 24, 0, 12, 8),
    (metric("dhcp-m-naks", "NAKs", ACT, count("NAK"), 'dhcp.message_type : "Nak"'), 36, 0, 12, 8),

    (xy("dhcp-x-types", "Messages over time, by type", ACT, "",
        {"x": date_hist(), "t": terms("Message type", "dhcp.message_type", "y", 10), "y": count("Messages")},
        ["y"], split="t"), 0, 8, 32, 14),
    (donut("dhcp-d-types", "Message types", ACT, "",
           {"g": terms("Message type", "dhcp.message_type", "v", 10), "v": count("Messages")}, "g", "v"), 32, 8, 16, 14),

    (xy("dhcp-x-clients", "Active clients over time", ACT, V4,
        {"x": date_hist(), "y": agg("unique_count", "Unique clients", "dhcp.client_mac")},
        ["y"], kind="line"), 0, 22, 24, 14),
    (xy("dhcp-x-nak", "ACK vs NAK over time", ACT, "",
        {"x": date_hist(), "a": count("ACK", 'dhcp.message_type : "Ack"'), "n": count("NAK", 'dhcp.message_type : "Nak"')},
        ["a", "n"], kind="line"), 24, 22, 24, 14),

    (table("dhcp-t-macs", "Top clients (MAC)", ACT, V4,
           {"d": terms("Client MAC", "dhcp.client_mac", "c", 15), "c": count("Packets")}, ["d", "c"]), 0, 36, 16, 16),
    (table("dhcp-t-hosts", "Top hostnames", ACT, V4,
           {"d": terms("Hostname", "dhcp.hostname", "c", 15), "c": count("Packets")}, ["d", "c"]), 16, 36, 16, 16),
    (table("dhcp-t-nak", "Clients receiving NAK", ACT, 'dhcp.message_type : "Nak"',
           {"d": terms("Client MAC", "dhcp.client_mac", "c", 15), "c": count("NAKs")}, ["d", "c"]), 32, 36, 16, 16),

    # server-side counters reported by BDDS (statistics-dhcp)
    (xy("dhcp-x-srv", "Server packets received / sent (DHCPv4 statistics)", STAT, V4STAT,
        {"x": date_hist(), "r": agg("sum", "Received", "data.received"), "s": agg("sum", "Sent", "data.sent")},
        ["r", "s"], kind="bar"), 0, 52, 24, 14),
    (xy("dhcp-x-lps", "Leases per second (DHCPv4 statistics)", STAT, V4STAT,
        {"x": date_hist(), "l": agg("average", "Leases/s", "data.leasesPerSecond")},
        ["l"], kind="line"), 24, 52, 24, 14),
    (table("dhcp-t-topstat", "Top clients by server-reported count", TOP, "",
           {"d": terms("Client", "top_client.id", "c", 10), "k": terms("Type", "top_client.type", "c", 3),
            "c": agg("sum", "Count", "top_client.count")}, ["d", "k", "c"]), 0, 66, 48, 14),
]

objs = [p[0] for p in P]
panels, refs = [], []
for i, (o, x, y, w, h) in enumerate(P, 1):
    panels.append({"version": "8.17.0", "type": "lens", "gridData": {"x": x, "y": y, "w": w, "h": h, "i": str(i)},
                   "panelIndex": str(i), "embeddableConfig": {"enhancements": {}}, "panelRefName": f"panel_{i}"})
    refs.append({"name": f"panel_{i}", "type": "lens", "id": o["id"]})

objs.append({
    "type": "dashboard", "id": "bdds-dhcp-activity", "managed": False,
    "attributes": {
        "title": "BDDS DHCP Activity", "description": "DHCP activity and server statistics from BDDS (Kafka -> Logstash -> ES)",
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
