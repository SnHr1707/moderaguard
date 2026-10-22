"""The Kafka clients must wait for the broker, not crash (owner: M2).

Kafka takes a while to start, so the producer and consumer retry. This test
fakes an unreachable broker for the first attempts. It also guards against
library changes: kafka-python 3 removed NoBrokersAvailable, which once made
both services crash on start.
"""

import pytest
from kafka.errors import KafkaTimeoutError

import consumer
import producer


@pytest.fixture()
def flaky_kafka(monkeypatch):
    calls = {"n": 0}

    class Flaky:
        def __init__(self, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] < 3:
                raise KafkaTimeoutError("broker not up yet")

    for module in (consumer, producer):
        monkeypatch.setattr(module.time, "sleep", lambda s: None)
    monkeypatch.setattr(consumer, "KafkaConsumer", Flaky)
    monkeypatch.setattr(consumer, "KafkaProducer", Flaky)
    monkeypatch.setattr(producer, "KafkaProducer", Flaky)
    return calls


def test_consumer_retries_until_kafka_is_up(flaky_kafka):
    consumer.connect_kafka("kafka:9092")
    assert flaky_kafka["n"] >= 3


def test_producer_retries_until_kafka_is_up(flaky_kafka):
    producer.connect("kafka:9092")
    assert flaky_kafka["n"] == 3
