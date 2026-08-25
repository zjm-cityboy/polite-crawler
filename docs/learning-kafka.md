# Kafka 学习文档（对照本项目实战）

> 定位：看完这份文档，你能讲清楚"爬到的数据是怎么'广播'给下游系统的"。

## 一、Kafka 是什么（一句话 + 比喻）

**Kafka = 一个超高吞吐的"消息邮局"**：生产者把消息投进主题（Topic），
任意多个消费者各自订阅取走，彼此不用认识。

比喻：
- 没有 Kafka：爬虫是**挨家挨户送报纸的报童**——每来一个新读者（下游系统），
  报童就要多跑一家（爬虫代码要加一个推送目标），报童病了报纸全停。
- 有 Kafka：报童只把报纸投进**报社的发行科**（Kafka），谁想看谁去订阅——
  加读者不用通知报童，报童请假发行科的存量照发。

## 二、为什么这个项目需要它（没有会怎样）

本项目的数据流（对标 NewsCrawl 的"入库 MySQL + Kafka 推送"分工）：

```
Scrapy 采集 ──→ PG 入库（本系统自己存档）
        └────→ Kafka articles 主题（对外分发口）
                  ├── 下游 A：RAG 语料入库程序
                  ├── 下游 B：舆情分析服务
                  └── 下游 C：监控告警
```

不加 Kafka 时：每新增一个下游，就要改爬虫代码加一路推送；下游挂了还会
反爬虫
（要不要重试？要不要缓冲？）—— 生产者和消费者**紧耦合**。
加 Kafka 后：爬虫只管往主题里发，下游各自消费、各自管自己的故障，
互不影响 —— **解耦** + **削峰**（高峰消息先积压在 Kafka，下游按自己的节奏消费）。

## 三、核心概念（最小必要知识）

| 概念 | 一句话解释 | 本项目对应 |
|---|---|---|
| **Topic 主题** | 消息的分类邮箱 | `articles` |
| **Producer 生产者** | 往主题投消息的一方 | 爬虫的 `KafkaPipeline` |
| **Consumer 消费者** | 从主题取消息的一方 | `kafka_consumer.py`（下游 demo） |
| **Partition 分区** | 主题内部的并行通道（一个主题可多分区，消息轮询分布） | `articles` 默认 1 分区 |
| **Offset 偏移量** | 消费者读到第几条的"书签"（提交后重启从书签继续） | 面板可查：`articles:0:3` = 分区0已积压3条 |
| **Consumer Group 消费者组** | 同组消费者瓜分分区（扩容单位） | `rag-ingest-demo` |

两个关键性质：
- **消息持久化**：消息写进磁盘按期限保留（默认 7 天），消费者"掉线重连"后从
  offset 继续，不丢消息；
- **顺序性**：同一分区内消息有序（不同分区不保证）。

## 四、在本项目中的两段代码（对照读）

### 生产者：`news_crawler/pipelines.py` 的 `KafkaPipeline`

```python
self.producer = KafkaProducer(
    bootstrap_servers=self.bootstrap,
    api_version=(3, 5, 0),                  # ← 踩坑修复，见下文
    value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode('utf-8'),
)
...
self.producer.send(self.topic, message)     # 异步：先入本地缓冲，后台批量发
...
self.producer.flush(timeout=10)             # 退出前必须 flush，否则缓冲区消息丢失
```

设计细节（面试可讲）：**消息体只带元数据+指纹，不带全文** —— 下游要全文
按 `url_fp` 回 PG 查，避免大正文在消息队列里反复搬运（生产环境常见瘦身做法）。

### 消费者：`kafka_consumer.py`

```python
KafkaConsumer('articles',
              group_id='rag-ingest-demo',
              auto_offset_reset='earliest',   # 新组从头读（默认 latest 会"收不到"）
              api_version=(3, 5, 0))
```

## 五、运维命令速查（本项目容器里直接可用）

```bash
# 列出所有主题（注意 Git Bash 要加 MSYS_NO_PATHCONV=1 防路径转换）
MSYS_NO_PATHCONV=1 docker exec crawler-kafka \
  /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:29092 --list

# 查主题积压量（分区:offset，offset 越大=消息越多）
MSYS_NO_PATHCONV=1 docker exec crawler-kafka \
  /opt/kafka/bin/kafka-get-offsets.sh --bootstrap-server kafka:29092 --topic articles

# 命令行消费者（直接在服务器上偷看消息内容）
MSYS_NO_PATHCONV=1 docker exec crawler-kafka \
  /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server kafka:29092 --topic articles --from-beginning
```

## 六、踩坑实录（本项目真实发生）

1. **kafka-python 不指定 api_version 会卡死**：kafka-python 2.0.2（2020 年
   的包）对 Kafka 3.7 的版本自动协商失败 —— 生产者首发报
   `Topic not found in cluster metadata` 告警，**消费者更隐蔽：订阅成功但
   永远收不到消息**。解法：两端都显式 `api_version=(3, 5, 0)`。
2. **双监听器（listeners）是容器化 Kafka 的核心配置**：
   - 容器网络内互访走 `PLAINTEXT://kafka:29092`（advertise 服务名）
   - 宿主机访问走 `PLAINTEXT_HOST://localhost:9092`
   配错 advertise 地址的典型症状：本机能连上、收 metadata 正常，但 fetch
   数据时去连一个不存在的地址然后超时。
3. **KRaft 模式**：Kafka 3.3+ 不再需要 Zookeeper（老教程里的
   `depends_on: zookeeper` 可以删了），单节点用 `KAFKA_PROCESS_ROLES:
   broker,controller` 一体化。
4. Git Bash 里 `/opt/kafka/...` 会被 MSYS 转成 `D:/Git/opt/...` —— 加
   `MSYS_NO_PATHCONV=1`（本项目第二次踩这个坑，第一次是挂载数据卷时）。

## 七、面试怎么答

**Q：为什么要上 Kafka，直接写库不行吗？**
要点：写库是"存"，Kafka 是"传"——两者解决不同问题。多下游分发场景下，Kafka 把生产者和消费者解耦（加下游不改爬虫）、削峰填谷（下游慢了消息积压不阻塞采集）、故障隔离（下游挂了爬虫照跑，恢复后从 offset 补消费）。如果只有一个消费者且实时性要求低，确实可以不上——说出适用边界比无脑上更加分。

**Q：怎么保证消息不丢？**
要点（本项目范围内的答案）：生产端 `send` 后必须 `flush` 再退出（缓冲区落盘）；Kafka 端消息持久化保留期内可重读；消费端 offset 手动提交策略（本项目用自动提交，讲清楚"至少一次/至多一次/恰好一次"三个语义更佳）。

## 八、延伸（下一步可以学）

- 多分区 + 消费者组扩容：一个主题 3 分区，同组 3 个消费者并行消费
- Kafka Streams / ksqlDB：在 Kafka 上直接做流式计算
- 与 RabbitMQ 的区别：Kafka 是日志型（消息保留、可回放），RabbitMQ 是队列型（取走即删）
