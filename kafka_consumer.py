"""Kafka 下游消费者示例：订阅 articles 主题，打印收到的文章元数据。

角色演示：下游系统（RAG 入库程序 / 数据分析 / 监控告警）只需要
订阅同一个主题就能拿到爬虫产出，完全不需要改动爬虫一行代码
—— 这就是"生产者/消费者解耦"（架构图里 Kafka 那一格存在的意义）。

用法（先把 compose 里的 kafka 跑起来）：
  python kafka_consumer.py                       # 本机默认 localhost:9092
  KAFKA_BOOTSTRAP=kafka:9092 python kafka_consumer.py   # 容器网络内
"""

import json
import os

from kafka import KafkaConsumer

BOOTSTRAP = os.environ.get('KAFKA_BOOTSTRAP', 'localhost:9092')
TOPIC = os.environ.get('KAFKA_TOPIC', 'articles')


def main():
    # group_id：消费者组名 —— 同组的多个消费者自动分区摊派（横向扩容）
    # auto_offset_reset='earliest'：第一次启动从最早的消息开始读
    #（默认 latest 只读启动之后的新消息，第一次演示会"什么都收不到"）
    # api_version 显式指定：kafka-python 2.0.2 自动协商在 Kafka 3.x broker
    # 上会卡住（订阅后永远收不到消息）—— 已实测踩坑
    consumer = KafkaConsumer(
        TOPIC,
        bootstrap_servers=BOOTSTRAP,
        group_id='rag-ingest-demo',
        auto_offset_reset='earliest',
        api_version=(3, 5, 0),
        value_deserializer=lambda b: json.loads(b.decode('utf-8')),
    )
    print(f'已订阅主题 [{TOPIC}]（{BOOTSTRAP}），等待消息…… Ctrl+C 退出')
    for msg in consumer:
        article = msg.value
        print(f"[收到] {article['title'] or '(无标题)'} | "
              f"{article['url']}")


if __name__ == '__main__':
    main()
