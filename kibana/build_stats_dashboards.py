"""Generate the DNS + DHCP *statistics* dashboards as Kibana saved objects (NDJSON).

Usage:  python build_stats_dashboards.py > stats-dashboards.ndjson
Import: curl -XPOST 'localhost:5601/api/saved_objects/_import?overwrite=true' -H 'kbn-xsrf: true' --form file=@stats-dashboards.ndjson

DNS statistics from BIND are cumulative counters  -> plotted as per-second rate (Lens counter_rate).
DHCP statistics from BDDS are per-minute window counts -> summed per time bucket.
"""
import json

LAYER = "layer1"
DNS_STAT = "statistics-dns"
DHCP_STAT = "statistics-dhcp"
TOP = "statistics-topclients-dhcp"
NS = "data.nsstats."
V4 = 'payloadType : "dhcpv4-statistics"'
V6 = 'payloadType : "dhcpv6-statistics"'


# ---- Lens column helpers -------------------------------------------------
def date_hist():
    return {"label": "@timestamp", "dataType": "date", "operationType": "date_histogram", "isBucketed": True,
            "scale": "interval", "sourceField": "@timestamp",
            "params": {"interval": "auto", "includeEmptyIntervals": True, "dropPartials": False}}


def agg(op, label, field, fmt=None):
    c = {"label": label, "dataType": "number", "operationType": op, "isBucketed": False,
         "scale": "ratio", "sourceField": field, "params": {"emptyAsNull": True}}
    if fmt:
        c["params"]["format"] = fmt
    return c


def last(label, field, fmt=None):
    c = {"label": label, "dataType": "number", "operationType": "last_value", "isBucketed": False,
         "scale": "ratio", "sourceField": field, "params": {"sortField": "@timestamp"}}
    if fmt:
        c["params"]["format"] = fmt
    return c


def rate(cols, key, label, field):
    """Counter -> per-second rate. Adds the helper max column and the counter_rate column; returns rate column id."""
    cols[key + "_max"] = agg("max", label + " (max)", field)
    cols[key] = {"label": label, "dataType": "number", "operationType": "counter_rate", "isBucketed": False,
                 "scale": "ratio", "references": [key + "_max"], "timeScale": "s",
                 "params": {"format": {"id": "number", "params": {"decimals": 2}}}}
    return key


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


def metric(oid, title, dv, col, query=""):
    return lens(oid, title, dv, "lnsMetric",
                {"layerId": LAYER, "layerType": "data", "metricAccessor": "m"}, {"m": col}, query)


def xy(oid, title, dv, columns, accessors, query="", kind="line", split=None):
    layer = {"layerId": LAYER, "accessors": accessors, "position": "top", "seriesType": kind,
             "showGridlines": False, "layerType": "data", "xAccessor": "x"}
    if split:
        layer["splitAccessor"] = split
    return lens(oid, title, dv, "lnsXY",
                {"legend": {"isVisible": True, "position": "bottom"}, "valueLabels": "hide",
                 "preferredSeriesType": kind, "layers": [layer]}, columns, query)


def table(oid, title, dv, columns, order, query=""):
    return lens(oid, title, dv, "lnsDatatable",
                {"layerId": LAYER, "layerType": "data", "columns": [{"columnId": c} for c in order]}, columns, query)


def rate_chart(oid, title, series, dv=DNS_STAT, kind="line"):
    """series: list of (label, field). One counter_rate line per series."""
    cols = {"x": date_hist()}
    acc = [rate(cols, f"r{i}", lbl, fld) for i, (lbl, fld) in enumerate(series)]
    return xy(oid, title, dv, cols, acc, kind=kind)


def sum_chart(oid, title, series, query, dv=DHCP_STAT, kind="bar_stacked"):
    cols = {"x": date_hist()}
    acc = []
    for i, (lbl, fld) in enumerate(series):
        cols[f"s{i}"] = agg("sum", lbl, fld)
        acc.append(f"s{i}")
    return xy(oid, title, dv, cols, acc, query=query, kind=kind)


def dashboard(oid, title, desc, panels_def):
    panels, refs = [], []
    for i, (o, x, y, w, h) in enumerate(panels_def, 1):
        panels.append({"version": "8.17.0", "type": "lens", "gridData": {"x": x, "y": y, "w": w, "h": h, "i": str(i)},
                       "panelIndex": str(i), "embeddableConfig": {"enhancements": {}}, "panelRefName": f"panel_{i}"})
        refs.append({"name": f"panel_{i}", "type": "lens", "id": o["id"]})
    return {
        "type": "dashboard", "id": oid, "managed": False,
        "attributes": {
            "title": title, "description": desc,
            "timeRestore": True, "timeFrom": "now-6h", "timeTo": "now",
            "refreshInterval": {"pause": False, "value": 60000},
            "optionsJSON": json.dumps({"useMargins": True, "syncColors": False, "syncCursor": True,
                                       "syncTooltips": False, "hidePanelTitles": False}),
            "panelsJSON": json.dumps(panels),
            "kibanaSavedObjectMeta": {"searchSourceJSON": json.dumps({"query": {"query": "", "language": "kuery"}, "filter": []})},
        },
        "references": refs, "coreMigrationVersion": "8.8.0", "typeMigrationVersion": "10.2.0"}


BYTES = {"id": "bytes", "params": {"decimals": 1}}
RES = "data.views.default.resolver."

# ======================= DNS statistics =======================
DNS = [
    (metric("dnsstat-m-mem", "Memory in use", DNS_STAT, last("Memory in use", "data.memory.InUse", BYTES)), 0, 0, 12, 8),
    (metric("dnsstat-m-cache", "Cache nodes", DNS_STAT, last("Cache nodes", RES + "cachestats.CacheNodes")), 12, 0, 12, 8),
    (metric("dnsstat-m-rec", "Recursion high-water", DNS_STAT, last("Recursion high-water", NS + "RecursHighwater")), 24, 0, 12, 8),
    (metric("dnsstat-m-tcp", "TCP connections high-water", DNS_STAT, last("TCP high-water", NS + "TCPConnHighWater")), 36, 0, 12, 8),

    (rate_chart("dnsstat-x-transport", "Queries per second, by transport",
                [("UDP", NS + "QryUDP"), ("TCP", NS + "QryTCP")]), 0, 8, 24, 14),
    (rate_chart("dnsstat-x-rcodes", "Responses per second, by rcode",
                [("NOERROR", "data.rcodes.NOERROR"), ("NXDOMAIN", "data.rcodes.NXDOMAIN"),
                 ("SERVFAIL", "data.rcodes.SERVFAIL"), ("REFUSED", "data.rcodes.REFUSED")]), 24, 8, 24, 14),

    (rate_chart("dnsstat-x-qtypes", "Queries per second, by type",
                [("A", "data.qtypes.A"), ("AAAA", "data.qtypes.AAAA"), ("HTTPS", "data.qtypes.HTTPS"),
                 ("PTR", "data.qtypes.PTR"), ("TXT", "data.qtypes.TXT")]), 0, 22, 24, 14),
    (rate_chart("dnsstat-x-auth", "Authoritative vs recursive answers per second",
                [("Authoritative", NS + "QryAuthAns"), ("Recursion", NS + "QryRecursion"),
                 ("Non-authoritative", NS + "QryNoauthAns")]), 24, 22, 24, 14),

    (rate_chart("dnsstat-x-cache", "Resolver cache hits vs misses per second",
                [("Cache hits", RES + "cachestats.CacheHits"), ("Cache misses", RES + "cachestats.CacheMisses")]),
     0, 36, 24, 14),
    (rate_chart("dnsstat-x-resolver", "Resolver problems per second",
                [("Timeouts", RES + "stats.QueryTimeout"), ("Retries", RES + "stats.Retry"),
                 ("SERVFAIL", RES + "stats.SERVFAIL"), ("Truncated", RES + "stats.Truncated")]), 24, 36, 24, 14),

    (rate_chart("dnsstat-x-drop", "Dropped / truncated / duplicate per second",
                [("Dropped", NS + "QryDropped"), ("Truncated", NS + "TruncatedResp"),
                 ("Duplicate", NS + "QryDuplicate")]), 0, 50, 24, 14),
    (xy("dnsstat-x-sock", "Active sockets", DNS_STAT,
        {"x": date_hist(), "a": agg("max", "UDP4 active", "data.sockstats.UDP4Active"),
         "b": agg("max", "TCP4 active", "data.sockstats.TCP4Active"),
         "c": agg("max", "TCP6 active", "data.sockstats.TCP6Active")}, ["a", "b", "c"]), 24, 50, 12, 14),
    (xy("dnsstat-x-mem", "Memory in use", DNS_STAT,
        {"x": date_hist(), "m": agg("max", "Memory in use", "data.memory.InUse", BYTES)}, ["m"]), 36, 50, 12, 14),
]

# ======================= DHCP statistics =======================
DHCP = [
    (metric("dhcpstat-m-rx", "Received (DHCPv4)", DHCP_STAT, agg("sum", "Received", "data.received"), V4), 0, 0, 12, 8),
    (metric("dhcpstat-m-tx", "Sent (DHCPv4)", DHCP_STAT, agg("sum", "Sent", "data.sent"), V4), 12, 0, 12, 8),
    (metric("dhcpstat-m-nak", "NAKs sent (DHCPv4)", DHCP_STAT, agg("sum", "NAK sent", "data.nakSent"), V4), 24, 0, 12, 8),
    (metric("dhcpstat-m-rx6", "Received (DHCPv6)", DHCP_STAT, agg("sum", "Received", "data.received"), V6), 36, 0, 12, 8),

    (sum_chart("dhcpstat-x-v4io", "DHCPv4 packets received / sent", [("Received", "data.received"), ("Sent", "data.sent")],
               V4, kind="bar"), 0, 8, 24, 14),
    (xy("dhcpstat-x-lps", "Leases per second", DHCP_STAT,
        {"x": date_hist(), "p": terms("Protocol", "payloadType", "l", 2), "l": agg("average", "Leases/s", "data.leasesPerSecond")},
        ["l"], split="p"), 24, 8, 24, 14),

    (sum_chart("dhcpstat-x-dora", "DHCPv4 message flow (Discover / Offer / Request / ACK / NAK)",
               [("Discover", "data.discoverReceived"), ("Offer", "data.offerSent"), ("Request", "data.requestReceived"),
                ("ACK", "data.ackSent"), ("NAK", "data.nakSent")], V4, kind="line"), 0, 22, 24, 14),
    (sum_chart("dhcpstat-x-v4other", "DHCPv4 decline / release / inform",
               [("Decline", "data.declineReceived"), ("Release", "data.releaseReceived"), ("Inform", "data.informReceived")],
               V4), 24, 22, 24, 14),

    (sum_chart("dhcpstat-x-v6io", "DHCPv6 packets received / sent", [("Received", "data.received"), ("Sent", "data.sent")],
               V6, kind="bar"), 0, 36, 24, 14),
    (sum_chart("dhcpstat-x-v6flow", "DHCPv6 message flow",
               [("Solicit", "data.solicitReceived"), ("Advertise", "data.advertiseSent"), ("Request", "data.requestReceived"),
                ("Reply", "data.replySent"), ("Renew", "data.renewReceived"), ("Rebind", "data.rebindReceived"),
                ("Info-request", "data.infoRequestReceived")], V6, kind="line"), 24, 36, 24, 14),

    (table("dhcpstat-t-mac", "Top clients, DHCPv4 (MAC)", TOP,
           {"d": terms("Client", "top_client.id", "c", 10), "c": agg("sum", "Count", "top_client.count")},
           ["d", "c"], 'top_client.type : "mac"'), 0, 50, 24, 14),
    (table("dhcpstat-t-duid", "Top clients, DHCPv6 (DUID)", TOP,
           {"d": terms("Client", "top_client.id", "c", 10), "c": agg("sum", "Count", "top_client.count")},
           ["d", "c"], 'top_client.type : "duid"'), 24, 50, 24, 14),
]

objs = [p[0] for p in DNS] + [p[0] for p in DHCP]
objs.append(dashboard("bdds-dns-statistics", "BDDS DNS Statistics",
                      "BIND statistics from BDDS (cumulative counters shown as per-second rates)", DNS))
objs.append(dashboard("bdds-dhcp-statistics", "BDDS DHCP Statistics",
                      "DHCPv4/v6 server statistics reported by BDDS (per-minute windows)", DHCP))
for o in objs:
    print(json.dumps(o, separators=(",", ":")))
