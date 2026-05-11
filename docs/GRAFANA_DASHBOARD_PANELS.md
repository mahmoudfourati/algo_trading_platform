# Grafana Dashboard Panels - Production Observability

**Style**: Dark theme, preserve existing layout philosophy  
**Approach**: Add depth, not chaos  
**Target**: HFT/SIEM-grade observability

---

## DASHBOARD ARCHITECTURE

### Row Structure (Preserve existing + add new rows)

```
Row 1: Pipeline Health Overview (EXISTING - keep as-is)
  - Layer 1 Ingestion Rates
  - Validated/Scored Throughput
  
Row 2: Trust & Anomaly Overview (EXISTING - keep as-is)
  - Trust Score By Symbol
  - Anomaly Components By Symbol
  - System State

Row 3: **NEW** Trust Score Decomposition (FORENSIC)
  - Trust Subcomponents Timeline (T1-T5 + final)
  - Trust Degradation Heatmap
  - Trust Component Contribution

Row 4: **NEW** Anomaly Score Decomposition (FORENSIC)
  - Anomaly Subcomponents Timeline (IF, HST, MAD, Fused)
  - HMM Regime State Timeline
  - Feature Vector Heatmap

Row 5: **NEW** Layer 1 Deep Telemetry
  - Exchange Connection Health
  - TLS Failures & Reconnects
  - Consensus Divergence Details

Row 6: **NEW** Layer 2 Deep Telemetry
  - Model Inference Latency
  - Regime Transitions
  - Feature Extraction Performance

Row 7: **NEW** Layer 3-5 Telemetry
  - Strategy Indicators (RSI, MACD, BB)
  - Risk Metrics (Exposure, Drawdown, Circuit Breaker)
  - Execution Performance (Latency, Slippage, Retries)

Row 8: Pipeline Performance (EXISTING - enhance)
  - Pipeline Latency (keep)
  - Kafka Buffer Depths (keep)
  - **NEW** Kafka Consumer Lag
  - **NEW** Pipeline Bottleneck Heatmap

Row 9: Error Rates (EXISTING - keep as-is)
```

---

## PART 1: TRUST SCORE DECOMPOSITION PANELS

### Panel 1: Trust Subcomponents Timeline

**Type**: Time series  
**Position**: Row 3, Column 1-16 (full width)  
**Height**: 10 units

```json
{
  "datasource": {
    "type": "prometheus",
    "uid": "prometheus"
  },
  "fieldConfig": {
    "defaults": {
      "color": {
        "mode": "palette-classic"
      },
      "custom": {
        "lineWidth": 2,
        "fillOpacity": 10,
        "gradientMode": "opacity",
        "axisPlacement": "auto",
        "axisLabel": "Score [0,1]"
      },
      "decimals": 3,
      "max": 1.0,
      "min": 0.0,
      "unit": "none",
      "thresholds": {
        "mode": "absolute",
        "steps": [
          {"color": "red", "value": 0.0},
          {"color": "orange", "value": 0.5},
          {"color": "yellow", "value": 0.7},
          {"color": "green", "value": 0.85}
        ]
      }
    },
    "overrides": [
      {
        "matcher": {"id": "byName", "options": "Trust Final"},
        "properties": [
          {"id": "custom.lineWidth", "value": 3},
          {"id": "color", "value": {"mode": "fixed", "fixedColor": "blue"}}
        ]
      },
      {
        "matcher": {"id": "byName", "options": "T1 TLS"},
        "properties": [
          {"id": "color", "value": {"mode": "fixed", "fixedColor": "purple"}}
        ]
      },
      {
        "matcher": {"id": "byName", "options": "T2 Consensus"},
        "properties": [
          {"id": "color", "value": {"mode": "fixed", "fixedColor": "green"}}
        ]
      },
      {
        "matcher": {"id": "byName", "options": "T3 Freshness"},
        "properties": [
          {"id": "color", "value": {"mode": "fixed", "fixedColor": "yellow"}}
        ]
      },
      {
        "matcher": {"id": "byName", "options": "T4 Sequence"},
        "properties": [
          {"id": "color", "value": {"mode": "fixed", "fixedColor": "orange"}}
        ]
      },
      {
        "matcher": {"id": "byName", "options": "T5 HashChain"},
        "properties": [
          {"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}
        ]
      }
    ]
  },
  "gridPos": {
    "h": 10,
    "w": 16,
    "x": 0,
    "y": 16
  },
  "id": 10,
  "options": {
    "legend": {
      "calcs": ["last", "min", "max", "mean"],
      "displayMode": "table",
      "placement": "right",
      "showLegend": true
    },
    "tooltip": {
      "mode": "multi",
      "sort": "desc"
    }
  },
  "targets": [
    {
      "expr": "layer1_validated_last_trust_score{symbol=\"BTC-USDT\"}",
      "legendFormat": "Trust Final",
      "refId": "A"
    },
    {
      "expr": "trust_subscore_t1_tls{symbol=\"BTC-USDT\"}",
      "legendFormat": "T1 TLS",
      "refId": "B"
    },
    {
      "expr": "trust_subscore_t2_consensus{symbol=\"BTC-USDT\"}",
      "legendFormat": "T2 Consensus",
      "refId": "C"
    },
    {
      "expr": "trust_subscore_t3_freshness{symbol=\"BTC-USDT\"}",
      "legendFormat": "T3 Freshness",
      "refId": "D"
    },
    {
      "expr": "trust_subscore_t4_sequence{symbol=\"BTC-USDT\"}",
      "legendFormat": "T4 Sequence",
      "refId": "E"
    },
    {
      "expr": "trust_subscore_t5_hashchain{symbol=\"BTC-USDT\"}",
      "legendFormat": "T5 HashChain",
      "refId": "F"
    },
    {
      "expr": "trust_subscore_t_availability{symbol=\"BTC-USDT\"}",
      "legendFormat": "T_Availability",
      "refId": "G"
    }
  ],
  "title": "Trust Score Decomposition - BTC-USDT (Forensic View)",
  "type": "timeseries",
  "transformations": []
}
```

### Panel 2: Trust Degradation Heatmap

**Type**: Heatmap  
**Position**: Row 3, Column 17-24  
**Height**: 10 units

```json
{
  "datasource": {
    "type": "prometheus",
    "uid": "prometheus"
  },
  "fieldConfig": {
    "defaults": {
      "custom": {
        "hideFrom": {
          "tooltip": false,
          "viz": false,
          "legend": false
        },
        "scaleDistribution": {
          "type": "linear"
        }
      }
    }
  },
  "gridPos": {
    "h": 10,
    "w": 8,
    "x": 16,
    "y": 16
  },
  "id": 11,
  "options": {
    "calculate": false,
    "cellGap": 2,
    "cellValues": {},
    "color": {
      "exponent": 0.5,
      "fill": "dark-red",
      "mode": "scheme",
      "reverse": false,
      "scale": "exponential",
      "scheme": "RdYlGn",
      "steps": 128
    },
    "exemplars": {
      "color": "rgba(255,0,255,0.7)"
    },
    "filterValues": {
      "le": 1e-9
    },
    "legend": {
      "show": true
    },
    "rowsFrame": {
      "layout": "auto"
    },
    "tooltip": {
      "show": true,
      "yHistogram": false
    },
    "yAxis": {
      "axisPlacement": "left",
      "reverse": false
    }
  },
  "targets": [
    {
      "expr": "sum by (primary_cause) (increase(trust_degradation_events_total{symbol=\"BTC-USDT\"}[5m]))",
      "format": "heatmap",
      "legendFormat": "{{primary_cause}}",
      "refId": "A"
    }
  ],
  "title": "Trust Degradation Events (Root Cause Heatmap)",
  "type": "heatmap"
}
```

### Panel 3: Trust Component Contribution (Stat Panel)

**Type**: Stat  
**Position**: Row 3, Column 17-24 (below heatmap)  
**Height**: 5 units

```json
{
  "datasource": {
    "type": "prometheus",
    "uid": "prometheus"
  },
  "fieldConfig": {
    "defaults": {
      "color": {
        "mode": "thresholds"
      },
      "decimals": 3,
      "mappings": [],
      "max": 1,
      "min": 0,
      "thresholds": {
        "mode": "absolute",
        "steps": [
          {"color": "red", "value": null},
          {"color": "orange", "value": 0.5},
          {"color": "yellow", "value": 0.7},
          {"color": "green", "value": 0.85}
        ]
      },
      "unit": "none"
    },
    "overrides": []
  },
  "gridPos": {
    "h": 5,
    "w": 8,
    "x": 16,
    "y": 26
  },
  "id": 12,
  "options": {
    "colorMode": "background",
    "graphMode": "area",
    "justifyMode": "center",
    "orientation": "horizontal",
    "reduceOptions": {
      "calcs": ["lastNotNull"],
      "fields": "",
      "values": false
    },
    "textMode": "value_and_name"
  },
  "targets": [
    {
      "expr": "trust_subscore_t1_tls{symbol=\"BTC-USDT\"}",
      "legendFormat": "T1",
      "refId": "A"
    },
    {
      "expr": "trust_subscore_t2_consensus{symbol=\"BTC-USDT\"}",
      "legendFormat": "T2",
      "refId": "B"
    },
    {
      "expr": "trust_subscore_t3_freshness{symbol=\"BTC-USDT\"}",
      "legendFormat": "T3",
      "refId": "C"
    },
    {
      "expr": "trust_subscore_t4_sequence{symbol=\"BTC-USDT\"}",
      "legendFormat": "T4",
      "refId": "D"
    },
    {
      "expr": "trust_subscore_t5_hashchain{symbol=\"BTC-USDT\"}",
      "legendFormat": "T5",
      "refId": "E"
    }
  ],
  "title": "Current Trust Components (Instant Values)",
  "type": "stat"
}
```

---

## PART 2: ANOMALY SCORE DECOMPOSITION PANELS

### Panel 4: Anomaly Subcomponents Timeline

**Type**: Time series  
**Position**: Row 4, Column 1-16  
**Height**: 10 units

```json
{
  "datasource": {
    "type": "prometheus",
    "uid": "prometheus"
  },
  "fieldConfig": {
    "defaults": {
      "color": {
        "mode": "palette-classic"
      },
      "custom": {
        "lineWidth": 2,
        "fillOpacity": 15,
        "gradientMode": "opacity"
      },
      "decimals": 3,
      "max": 1.0,
      "min": 0.0,
      "unit": "none"
    },
    "overrides": [
      {
        "matcher": {"id": "byName", "options": "Fused Score"},
        "properties": [
          {"id": "custom.lineWidth", "value": 3},
          {"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}
        ]
      },
      {
        "matcher": {"id": "byName", "options": "MAD Guard"},
        "properties": [
          {"id": "custom.lineStyle", "value": {"dash": [10, 10], "fill": "dash"}},
          {"id": "custom.fillOpacity", "value": 0},
          {"id": "color", "value": {"mode": "fixed", "fixedColor": "purple"}}
        ]
      }
    ]
  },
  "gridPos": {
    "h": 10,
    "w": 16,
    "x": 0,
    "y": 31
  },
  "id": 13,
  "options": {
    "legend": {
      "calcs": ["last", "max", "mean"],
      "displayMode": "table",
      "placement": "right",
      "showLegend": true
    },
    "tooltip": {
      "mode": "multi",
      "sort": "desc"
    }
  },
  "targets": [
    {
      "expr": "anomaly_fused_score{symbol=\"BTC-USDT\"}",
      "legendFormat": "Fused Score",
      "refId": "A"
    },
    {
      "expr": "anomaly_subscore_if{symbol=\"BTC-USDT\"}",
      "legendFormat": "Isolation Forest",
      "refId": "B"
    },
    {
      "expr": "anomaly_subscore_hst{symbol=\"BTC-USDT\"}",
      "legendFormat": "Half-Space Trees",
      "refId": "C"
    },
    {
      "expr": "anomaly_mad_guard_active{symbol=\"BTC-USDT\"}",
      "legendFormat": "MAD Guard",
      "refId": "D"
    }
  ],
  "title": "Anomaly Score Decomposition - BTC-USDT (Forensic View)",
  "type": "timeseries"
}
```

### Panel 5: HMM Regime State Timeline

**Type**: State timeline  
**Position**: Row 4, Column 17-24  
**Height**: 5 units

```json
{
  "datasource": {
    "type": "prometheus",
    "uid": "prometheus"
  },
  "fieldConfig": {
    "defaults": {
      "color": {
        "mode": "thresholds"
      },
      "custom": {
        "lineWidth": 0,
        "fillOpacity": 100
      },
      "mappings": [
        {
          "options": {
            "0": {"text": "Low Vol", "color": "green"},
            "1": {"text": "Normal", "color": "yellow"},
            "2": {"text": "High Vol", "color": "red"}
          },
          "type": "value"
        }
      ],
      "thresholds": {
        "mode": "absolute",
        "steps": [
          {"color": "green", "value": null},
          {"color": "yellow", "value": 1},
          {"color": "red", "value": 2}
        ]
      }
    }
  },
  "gridPos": {
    "h": 5,
    "w": 8,
    "x": 16,
    "y": 31
  },
  "id": 14,
  "options": {
    "mergeValues": true,
    "showValue": "always",
    "alignValue": "center",
    "rowHeight": 0.9,
    "legend": {
      "displayMode": "list",
      "placement": "bottom",
      "showLegend": true
    }
  },
  "targets": [
    {
      "expr": "hmm_regime_state{symbol=\"BTC-USDT\"}",
      "legendFormat": "Regime",
      "refId": "A"
    }
  ],
  "title": "HMM Regime State (State Timeline)",
  "type": "state-timeline"
}
```

### Panel 6: Feature Vector Heatmap

**Type**: Heatmap  
**Position**: Row 4, Column 17-24 (below state timeline)  
**Height**: 5 units

```json
{
  "datasource": {
    "type": "prometheus",
    "uid": "prometheus"
  },
  "fieldConfig": {
    "defaults": {
      "custom": {
        "hideFrom": {
          "tooltip": false,
          "viz": false,
          "legend": false
        }
      }
    }
  },
  "gridPos": {
    "h": 5,
    "w": 8,
    "x": 16,
    "y": 36
  },
  "id": 15,
  "options": {
    "calculate": false,
    "cellGap": 1,
    "color": {
      "exponent": 0.5,
      "fill": "dark-blue",
      "mode": "scheme",
      "reverse": false,
      "scheme": "Spectral",
      "steps": 64
    },
    "exemplars": {
      "color": "rgba(255,0,255,0.7)"
    },
    "filterValues": {
      "le": 1e-9
    },
    "legend": {
      "show": true
    },
    "rowsFrame": {
      "layout": "auto"
    },
    "tooltip": {
      "show": true,
      "yHistogram": true
    },
    "yAxis": {
      "axisPlacement": "left",
      "reverse": false,
      "unit": "short"
    }
  },
  "targets": [
    {
      "expr": "anomaly_feature_raw_return{symbol=\"BTC-USDT\"}",
      "format": "heatmap",
      "legendFormat": "raw_return",
      "refId": "A"
    },
    {
      "expr": "anomaly_feature_rolling_volatility{symbol=\"BTC-USDT\"}",
      "format": "heatmap",
      "legendFormat": "rolling_vol",
      "refId": "B"
    },
    {
      "expr": "anomaly_feature_spread_divergence{symbol=\"BTC-USDT\"}",
      "format": "heatmap",
      "legendFormat": "spread_z",
      "refId": "C"
    },
    {
      "expr": "anomaly_feature_latency_anomaly{symbol=\"BTC-USDT\"}",
      "format": "heatmap",
      "legendFormat": "latency_z",
      "refId": "D"
    },
    {
      "expr": "anomaly_feature_trust_degradation{symbol=\"BTC-USDT\"}",
      "format": "heatmap",
      "legendFormat": "trust_delta",
      "refId": "E"
    }
  ],
  "title": "Anomaly Feature Vector (Heatmap)",
  "type": "heatmap"
}
```

---

## PART 3: LAYER-SPECIFIC TELEMETRY PANELS

### Panel 7: Exchange Connection Health Matrix

**Type**: Stat  
**Position**: Row 5, Column 1-8  
**Height**: 6 units

```json
{
  "datasource": {
    "type": "prometheus",
    "uid": "prometheus"
  },
  "fieldConfig": {
    "defaults": {
      "color": {
        "mode": "thresholds"
      },
      "mappings": [
        {
          "options": {
            "0": {"text": "DOWN", "color": "dark-red"},
            "1": {"text": "UP", "color": "dark-green"}
          },
          "type": "value"
        }
      ],
      "thresholds": {
        "mode": "absolute",
        "steps": [
          {"color": "red", "value": null},
          {"color": "green", "value": 1}
        ]
      }
    }
  },
  "gridPos": {
    "h": 6,
    "w": 8,
    "x": 0,
    "y": 41
  },
  "id": 16,
  "options": {
    "colorMode": "background",
    "graphMode": "none",
    "justifyMode": "center",
    "orientation": "auto",
    "reduceOptions": {
      "calcs": ["lastNotNull"],
      "fields": "",
      "values": false
    },
    "textMode": "value_and_name"
  },
  "targets": [
    {
      "expr": "exchange_connection_health",
      "legendFormat": "{{exchange_id}}",
      "refId": "A"
    }
  ],
  "title": "Exchange Connection Health",
  "type": "stat"
}
```

### Panel 8: TLS Failures & Reconnects

**Type**: Time series  
**Position**: Row 5, Column 9-16  
**Height**: 6 units

```json
{
  "datasource": {
    "type": "prometheus",
    "uid": "prometheus"
  },
  "fieldConfig": {
    "defaults": {
      "color": {
        "mode": "palette-classic"
      },
      "custom": {
        "lineWidth": 1,
        "fillOpacity": 0,
        "drawStyle": "bars",
        "barAlignment": 0,
        "lineInterpolation": "linear",
        "spanNulls": false,
        "showPoints": "never",
        "pointSize": 5,
        "stacking": {
          "mode": "normal",
          "group": "A"
        }
      },
      "unit": "ops"
    }
  },
  "gridPos": {
    "h": 6,
    "w": 8,
    "x": 8,
    "y": 41
  },
  "id": 17,
  "options": {
    "legend": {
      "calcs": ["sum"],
      "displayMode": "table",
      "placement": "right",
      "showLegend": true
    },
    "tooltip": {
      "mode": "multi",
      "sort": "desc"
    }
  },
  "targets": [
    {
      "expr": "sum by (exchange_id) (rate(tls_pin_mismatch_total[1m]))",
      "legendFormat": "TLS fail {{exchange_id}}",
      "refId": "A"
    },
    {
      "expr": "sum by (exchange_id) (rate(exchange_websocket_reconnects_total[1m]))",
      "legendFormat": "Reconnect {{exchange_id}}",
      "refId": "B"
    }
  ],
  "title": "TLS Failures & WebSocket Reconnects",
  "type": "timeseries"
}
```

### Panel 9: Consensus Divergence Details

**Type**: Time series  
**Position**: Row 5, Column 17-24  
**Height**: 6 units

```json
{
  "datasource": {
    "type": "prometheus",
    "uid": "prometheus"
  },
  "fieldConfig": {
    "defaults": {
      "color": {
        "mode": "palette-classic"
      },
      "custom": {
        "lineWidth": 2,
        "fillOpacity": 10,
        "axisPlacement": "auto"
      },
      "unit": "short"
    },
    "overrides": [
      {
        "matcher": {"id": "byFrameRefID", "options": "B"},
        "properties": [
          {"id": "unit", "value": "bps"},
          {"id": "custom.axisPlacement", "value": "right"}
        ]
      }
    ]
  },
  "gridPos": {
    "h": 6,
    "w": 8,
    "x": 16,
    "y": 41
  },
  "id": 18,
  "options": {
    "legend": {
      "calcs": ["last", "max"],
      "displayMode": "table",
      "placement": "bottom",
      "showLegend": true
    },
    "tooltip": {
      "mode": "multi",
      "sort": "desc"
    }
  },
  "targets": [
    {
      "expr": "consensus_divergent_source_count",
      "legendFormat": "Divergent sources {{symbol}}",
      "refId": "A"
    },
    {
      "expr": "consensus_divergence_max_bps",
      "legendFormat": "Max divergence (bps) {{symbol}}",
      "refId": "B"
    }
  ],
  "title": "Consensus Divergence Details",
  "type": "timeseries"
}
```

---

## PROMQL QUERY PATTERNS

### Trust Score Forensics

```promql
# Identify which component caused trust drop
topk(1, 
  (trust_subscore_t1_tls < bool 0.5) * 1 +
  (trust_subscore_t2_consensus < bool 0.5) * 2 +
  (trust_subscore_t3_freshness < bool 0.3) * 3 +
  (trust_subscore_t4_sequence < bool 0.5) * 4 +
  (trust_subscore_t5_hashchain < bool 0.5) * 5
)

# Trust score moving average (5min)
avg_over_time(layer1_validated_last_trust_score[5m])

# Trust score volatility (stddev)
stddev_over_time(layer1_validated_last_trust_score[5m])

# Correlation: trust drop with anomaly spike
(
  deriv(layer1_validated_last_trust_score[1m]) < -0.1
) and (
  anomaly_fused_score > 0.8
)
```

### Anomaly Attribution

```promql
# Which model triggered the anomaly?
max by (symbol) (
  (anomaly_subscore_if > 0.9) * 1 +
  (anomaly_subscore_hst > 0.9) * 2 +
  (anomaly_mad_guard_active == 1) * 3
)

# Regime transition frequency
rate(hmm_regime_transitions_total[5m])

# Feature vector outlier detection
abs(anomaly_feature_raw_return) > 3 * stddev_over_time(anomaly_feature_raw_return[1h])
```

### Pipeline Bottleneck Detection

```promql
# Identify slowest pipeline stage
topk(1, 
  histogram_quantile(0.99, 
    rate(pipeline_stage_latency_ms_bucket[5m])
  ) by (stage)
)

# Kafka consumer lag (critical)
kafka_consumer_lag_seconds > 30

# Backpressure detection
pipeline_backpressure_ratio > 0.8
```

---

## COLOR SCHEME (Dark Theme)

### Trust Score Components
- **T1 (TLS)**: `#9933FF` (Purple) - Security-critical
- **T2 (Consensus)**: `#00FF00` (Green) - Agreement
- **T3 (Freshness)**: `#FFFF00` (Yellow) - Timeliness
- **T4 (Sequence)**: `#FF9900` (Orange) - Integrity
- **T5 (HashChain)**: `#FF0000` (Red) - Audit trail
- **Final Trust**: `#0099FF` (Blue) - Bold, primary

### Anomaly Components
- **Fused Score**: `#FF0000` (Red) - Alert
- **Isolation Forest**: `#FF6600` (Orange-Red)
- **Half-Space Trees**: `#FFCC00` (Gold)
- **MAD Guard**: `#9933FF` (Purple) - Dashed line

### State Colors
- **NORMAL**: `#00FF00` (Green)
- **CONSERVATIVE**: `#FFFF00` (Yellow)
- **DEGRADED**: `#FF9900` (Orange)
- **HALT**: `#FF0000` (Red)

### HMM Regime
- **Low Vol**: `#00FF00` (Green)
- **Normal**: `#FFFF00` (Yellow)
- **High Vol**: `#FF0000` (Red)

---

**Next**: I'll create the implementation guide and SRE operational recommendations.
