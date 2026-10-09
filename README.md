# BDDS DDI Activity — Kafka + ELK (Docker)

收集并分析 BlueCat BDDS 的 DNS / DHCP **Activity** 与 **Statistics** 数据。

```
BDDS (BAM 里配置 Activity → Kafka)  →  Kafka  →  Logstash  →  Elasticsearch  →  Kibana
                                         └── Kafka UI (查看 topic / 消费组)
```

实验环境配置：Elasticsearch / Kibana 均**未开启认证**，Kafka 为 PLAINTEXT。不要直接暴露到不可信网络。

## 要求
- Linux（Ubuntu 22.04/24.04 验证过），Docker Engine + Docker Compose v2
- 建议 ≥ 8 GB 内存（默认 ES 堆 3g + Logstash 1g + Kafka 1g；可在 `.env` 调整）
- 7 天数据的磁盘估算：约 600 条 DNS 查询/分钟 ≈ 几百 MB（已去掉原始嵌套字段）

## 安装
```bash
tar xzf ddi-activity-elk.tar.gz && cd elk-activity
sudo ./install.sh            # 自动探测本机 IP；也可 ./install.sh 192.168.1.250
```
脚本会：设置 `vm.max_map_count` → 生成 `.env` → `docker compose up -d`（建 topic、ES 模板与 ILM）→ 导入 Kibana 数据视图和 4 个仪表盘。

> **`.env` 里的 `HOST_IP` 必须是 BDDS 能访问到的本机地址**。Kafka 会把它告诉客户端；写错的话 BDDS 能连上 9094 但无法写入。

## BDDS / BAM 侧配置
Activity 数据输出选择 Kafka，分别配置（DNS 与 DHCP 各一份，Statistics 同理）：

| 参数 | 值 |
|---|---|
| bootstrap server | `<HOST_IP>:9094` |
| topic | `activity-dns` / `activity-dhcp` / `statistics-dns` / `statistics-dhcp` |
| key field | `key` |

topic 由 `kafka-init` 创建，Kafka 关闭了自动建 topic，**名字必须完全一致**。

## 访问
| 服务 | 地址 |
|---|---|
| Kibana | `http://<HOST_IP>:5601`（Dashboards：BDDS DNS/DHCP Activity、BDDS DNS/DHCP Statistics） |
| Kafka UI | `http://<HOST_IP>:8082` |
| Elasticsearch | 仅本机 `127.0.0.1:9200` |

## 目录
```
docker-compose.yml        服务定义（所有环境差异来自 .env）
.env.example              HOST_IP、保留天数、端口、版本、堆内存
install.sh                一键安装
setup/                    ES 一次性初始化：ILM（保留天数）+ 索引模板 ddi（keyword、ip 类型、字段上限）
logstash/pipelines.yml    pipeline 列表（只有 consume）
logstash/pipelines/consume.conf   Kafka → 扁平化 → ES
kibana/*.ndjson           数据视图 + 4 个仪表盘（可直接导入）
kibana/build_*.py         仪表盘生成脚本（改面板就改这里，再重新生成 + import.sh）
kibana/import.sh          导入 Kibana 对象（幂等）
```

## 数据模型
索引按天：`activity-dns-*`、`activity-dhcp-*`、`statistics-dns-*`、`statistics-dhcp-*`、`statistics-topclients-dhcp-*`；保留 `RETENTION_DAYS` 天（Kafka 与 ES 同步）。

- **DNS Activity**：`dns.qname / qtype / rcode / answers / resolved_ips / min_ttl / latency_ms / client_ip / upstream_ip / stage / flags.*`，`source.*`、`destination.*`。原始 `requestData/responseData` 已丢弃。
- **DHCP Activity**：`dhcp.version / message_type / client_mac / hostname / requested_ip / client_ip / your_ip / lease_time / server_identifier / ...`（v6：`client_duid / ia_addrs / ...`）。
- **Statistics**：保留原始指标。BIND 统计是**累计计数器**（图里用 Counter rate 每秒速率）；DHCP 统计是**每分钟窗口计数**（求和）。DHCP `topClients` 拆成 `statistics-topclients-dhcp-*`，每个客户端一条文档。

## 运维
```bash
docker compose ps                      # 状态
docker compose logs -f logstash        # 解析问题看这里；失败事件带 _*_flatten_failure 标签
sh kibana/import.sh                    # 重新导入数据视图和仪表盘（覆盖）
```

**修改解析规则后回放（Kafka 保留 7 天）：**
```bash
docker compose stop logstash
# 删除要重建的索引（ES 禁止通配符删除，需逐个指定名称）
for i in $(curl -s "localhost:9200/_cat/indices/activity-*,statistics-*?h=index"); do curl -s -XDELETE localhost:9200/$i; done
docker exec kafka /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
  --group logstash-es --reset-offsets --to-earliest --all-topics --execute
docker compose up -d logstash
```

## 注意事项
- `logstash/pipelines/` 下只放一个读 Kafka 的 pipeline。如果把"写 Kafka"和"读 Kafka"放进同一个 pipeline，会形成死循环（已踩过）。
- 删除 Kafka topic 是异步的，删完立刻重建可能被随后生效的删除抹掉；等几十秒或确认 `--list` 后再建。
- 已有 Splunk 等占用 8088/8089 等端口时，本栈不使用这些端口（只用 9094、5601、8082）。
- 要上生产：开启 ES/Kibana 安全、Kafka 用 SASL/TLS、ES 多节点与副本、Kafka 多副本。
