-- =============================================================================
-- Predicting Urban Traffic Congestion — SQL view definitions
-- Database: MariaDB 11.x (DBRepo container)
-- Depends on the schema in data/create.sql.
-- =============================================================================
-- Three views de-normalise the 3NF schema into query-ready slices that the
-- experiment can pull through the DBRepo REST API. All three are expressible
-- in DBRepo's structured query model (joins + filters; no computed columns,
-- aggregations, or window functions). Feature engineering — cyclical time
-- encoding, target binning, class balancing, hourly aggregation — happens
-- downstream in Python after fetching from these views.
--
--   1. v_measurements_enriched      base denormalised join of all three tables
--   2. v_weekday_measurements       same join, filtered to Monday–Friday
--   3. v_peak_hour_measurements     same join, filtered to morning + evening rush
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1. v_measurements_enriched
-- Purpose: One row per traffic measurement, joined with TrafficSites and
--          Calendar so callers receive `day_of_week` alongside the metric
--          columns without rewriting the join in their own code. Main data
--          source for the ML pipeline.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_measurements_enriched AS
SELECT
    m.observation_id,
    m.site_id,
    m.date,
    c.day_of_week,
    m.start_time,
    m.end_time,
    m.flow,
    m.flow_pc,
    m.cong,
    m.cong_pc,
    m.dsat,
    m.dsat_pc
FROM TrafficMeasurements m
JOIN Calendar     c ON c.date = m.date
JOIN TrafficSites s ON s.site_id = m.site_id;


-- -----------------------------------------------------------------------------
-- 2. v_weekday_measurements
-- Purpose: Measurements taken on weekdays only. Weekend traffic patterns
--          differ markedly from weekday patterns, and a weekday-only training
--          set is a reasonable default for the congestion classifier.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_weekday_measurements AS
SELECT
    m.observation_id,
    m.site_id,
    m.date,
    c.day_of_week,
    m.start_time,
    m.end_time,
    m.flow,
    m.flow_pc,
    m.cong,
    m.cong_pc,
    m.dsat,
    m.dsat_pc
FROM TrafficMeasurements m
JOIN Calendar     c ON c.date = m.date
JOIN TrafficSites s ON s.site_id = m.site_id
WHERE c.day_of_week NOT IN ('SA', 'SU');


-- -----------------------------------------------------------------------------
-- 3. v_peak_hour_measurements
-- Purpose: Measurements taken during the morning rush (07:00–09:00) and the
--          evening rush (17:00–19:00). Congestion is concentrated in these
--          windows, so this slice has a less extreme class imbalance than
--          the full dataset and is useful as a training subset for the
--          higher-congestion target classes.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_peak_hour_measurements AS
SELECT
    m.observation_id,
    m.site_id,
    m.date,
    c.day_of_week,
    m.start_time,
    m.end_time,
    m.flow,
    m.flow_pc,
    m.cong,
    m.cong_pc,
    m.dsat,
    m.dsat_pc
FROM TrafficMeasurements m
JOIN Calendar     c ON c.date = m.date
JOIN TrafficSites s ON s.site_id = m.site_id
WHERE m.start_time IN (
    '07:00', '07:15', '07:30', '07:45',
    '08:00', '08:15', '08:30', '08:45', '09:00',
    '17:00', '17:15', '17:30', '17:45',
    '18:00', '18:15', '18:30', '18:45', '19:00'
);


-- =============================================================================
-- Verification queries (sanity-check after data is loaded)
-- =============================================================================
-- SELECT COUNT(*) FROM v_measurements_enriched;
--   -- expect: same count as TrafficMeasurements (inner joins are FK-aligned)
--
-- SELECT day_of_week, COUNT(*) FROM v_weekday_measurements
--   GROUP BY day_of_week;
--   -- expect: 5 rows, MO/TU/WE/TH/FR, none for SA/SU
--
-- SELECT SUBSTRING(start_time, 1, 2) AS h, COUNT(*) FROM v_peak_hour_measurements
--   GROUP BY h ORDER BY h;
--   -- expect: rows only for hours 07,08,09,17,18,19 (boundary hour 09 and 19
--   --         included by the <= comparison)
-- =============================================================================
