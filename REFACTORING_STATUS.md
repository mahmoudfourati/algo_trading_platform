# Refactoring Status

## Phase 1: Remove Primary Exchange Dependency ✅ IN PROGRESS

### Completed:
1. ✅ Updated `shared/schemas.py`:
   - Modified `ValidatedTick` to use consensus price as `mid_price`
   - Added `execution_venue_prices` dict for divergence checking
   - Deprecated `primary_exchange` field (kept for backward compatibility)
   - Updated `ScoredTick` to match

2. ✅ Updated `services/layer1_validated/service.py`:
   - Removed primary exchange filtering (no longer skips windows)
   - Uses consensus price for all downstream layers
   - Computes TLS health via majority vote across consensus sources
   - Builds `execution_venue_prices` map for Layer 5
   - Uses first consensus source for sequence tracking if primary unavailable

3. ✅ Updated `services/layer5_execution/engine.py`:
   - Added `check_execution_divergence()` method
   - Added `max_divergence_bps` parameter (default 50 bps = 0.5%)
   - Updated `submit_order()` to check divergence before execution
   - Rejects orders if venue price diverges >0.5% from consensus
   - Tracks divergence rejections in telemetry

### Remaining for Phase 1:
4. ⏳ Update `services/layer5_execution/service.py`:
   - Extract `consensus_price` and `execution_venue_prices` from approved order
   - Pass to `engine.submit_order()`
   - Add Prometheus metrics for divergence rejections

5. ⏳ Update Layer 4 to pass execution venue info:
   - Extract from ValidatedTick/ScoredTick
   - Include in ApprovedOrder

6. ⏳ Test Phase 1 changes:
   - Verify consensus price is used throughout
   - Verify divergence checking works
   - Verify system still runs if Binance is down

## Phase 2: Merge Ingestion + Validated ⏳ NOT STARTED

### Plan:
1. Create `services/layer1/` directory
2. Create `services/layer1/service.py` - merged service
3. Create `services/layer1/in_memory_queue.py` - async queue
4. Update `docker-compose.yml` - replace 2 services with 1
5. Create `services/layer1/Dockerfile`
6. Test merged service

### Benefits:
- Eliminate 5-10ms Kafka latency
- Simpler deployment (1 service instead of 2)
- Easier to reason about (no Kafka in the middle)
- Still publishes to Kafka for downstream layers

## Next Steps

1. Complete Phase 1 (Layer 5 service update)
2. Test Phase 1 thoroughly
3. Start Phase 2 (merge services)
4. Test Phase 2 thoroughly
5. Update documentation

## Testing Checklist

### Phase 1 Testing:
- [ ] System publishes ticks when Binance is in consensus
- [ ] System publishes ticks when Binance is NOT in consensus (NEW!)
- [ ] Consensus price is used in Layers 2-4
- [ ] Layer 5 rejects orders with >0.5% divergence
- [ ] Layer 5 accepts orders with <0.5% divergence
- [ ] Metrics show divergence rejections
- [ ] Audit logs show divergence events

### Phase 2 Testing:
- [ ] Merged service starts successfully
- [ ] Latency reduced by 5-10ms
- [ ] All metrics still work
- [ ] Downstream layers receive ticks
- [ ] No data loss during transition
