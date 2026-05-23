#!/bin/bash
# Purpose: Pre-create all Kafka topics with explicit partition counts
# This ensures topics exist before services start, preventing auto-create race conditions

set -e

KAFKA_BROKER="${KAFKA_BROKER:-kafka:9092}"
PARTITIONS="${PARTITIONS:-1}"
REPLICATION_FACTOR="${REPLICATION_FACTOR:-1}"

echo "Creating Kafka topics on broker: $KAFKA_BROKER"
echo "Partitions: $PARTITIONS, Replication Factor: $REPLICATION_FACTOR"
echo ""

# Wait for Kafka to be ready
echo "Waiting for Kafka to be ready..."
until kafka-broker-api-versions --bootstrap-server $KAFKA_BROKER > /dev/null 2>&1; do
  echo "Kafka not ready yet, waiting..."
  sleep 2
done
echo "Kafka is ready!"
echo ""

# Create topics
TOPICS=(
  "market.ticks.raw"
  "market.ticks.validated"
  "market.ticks.scored"
  "trading.signals"
  "trading.orders.approved"
  "trading.orders.executed"
  "audit.events"
)

for TOPIC in "${TOPICS[@]}"; do
  echo "Creating topic: $TOPIC"
  kafka-topics --bootstrap-server $KAFKA_BROKER \
    --create \
    --if-not-exists \
    --topic $TOPIC \
    --partitions $PARTITIONS \
    --replication-factor $REPLICATION_FACTOR \
    --config retention.ms=86400000 \
    --config segment.ms=3600000
  echo "✓ Topic $TOPIC created"
  echo ""
done

echo "All topics created successfully!"
echo ""
echo "Listing all topics:"
kafka-topics --bootstrap-server $KAFKA_BROKER --list
