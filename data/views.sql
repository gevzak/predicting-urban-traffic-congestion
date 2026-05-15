-- =============================================================================
-- Predicting Urban Traffic Congestion — SQL view definitions
-- Database: MariaDB 11.x
-- Depends on the schema in data/create.sql.
-- =============================================================================
-- Five views de-normalise the 3NF schema into query-ready forms for analysis
-- and modelling:
--
--   1. v_measurements_enriched          base denormalised join
--   2. v_ml_feature_set                 ML-ready features + 5-class target
--   3. v_class_balanced_training_sample up to 10k rows per target class
--   4. v_hourly_site_aggregates         hourly averages per (site, date)
--   5. v_site_class_distribution        per-(site, target) observation count
--
-- Note on target binning: v_ml_feature_set.target uses MariaDB NTILE(5),
-- which always produces five rank-based buckets and may split tied values
-- arbitrarily. The reference notebook uses pandas qcut(..., duplicates='drop'),
-- which can collapse buckets when many tied values exist (common at sites with
-- mostly-zero `cong`). Class labels may therefore differ slightly between the
-- two implementations.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1. v_measurements_enriched
-- Purpose: Flat row-per-observation join of TrafficMeasurements with the two
--          dimension tables. Foundation for the other views; also useful as a
--          generic "everything as one table" endpoint for ad-hoc analysis.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_measurements_enriched AS
SELECT
    m.observation_id,
    m.site_id,
    m.date_id,
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
JOIN Calendar     c ON c.date_id = m.date_id
JOIN TrafficSites s ON s.site_id = m.site_id;


-- -----------------------------------------------------------------------------
-- 2. v_ml_feature_set
-- Purpose: ML-ready feature table. One row per observation with:
--            - raw features:    flow, flow_pc, dsat, dsat_pc
--            - cyclical time:   sin_time, cos_time (from HOUR(start_time))
--            - day index:       day_num (0=Monday … 6=Sunday)
--            - 5-class target:  target ∈ {0,1,2,3,4} via per-site NTILE on cong
--          Mirrors the feature set used by notebooks/01_…_mlp.ipynb.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_ml_feature_set AS
SELECT
    e.observation_id,
    e.site_id,
    e.date_id,
    e.start_time,
    e.flow,
    e.flow_pc,
    e.dsat,
    e.dsat_pc,
    SIN(2 * PI() * HOUR(e.start_time) / 24) AS sin_time,
    COS(2 * PI() * HOUR(e.start_time) / 24) AS cos_time,
    CASE e.day_of_week
        WHEN 'Monday'    THEN 0
        WHEN 'Tuesday'   THEN 1
        WHEN 'Wednesday' THEN 2
        WHEN 'Thursday'  THEN 3
        WHEN 'Friday'    THEN 4
        WHEN 'Saturday'  THEN 5
        WHEN 'Sunday'    THEN 6
    END AS day_num,
    NTILE(5) OVER (PARTITION BY e.site_id ORDER BY e.cong) - 1 AS target
FROM v_measurements_enriched e;


-- -----------------------------------------------------------------------------
-- 3. v_class_balanced_training_sample
-- Purpose: Mitigate class imbalance (class 0 dominates ~70% of rows). Returns
--          up to 10 000 rows per `target` class, drawn by ROW_NUMBER over
--          PARTITION BY target ORDER BY RAND().
-- Caveat:  RAND() re-evaluates on every query — the sample is NOT stable across
--          calls. If reproducibility is required, T2.6 should snapshot the
--          result into a deterministic input file or use a hash-based selector.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_class_balanced_training_sample AS
SELECT
    observation_id,
    site_id,
    date_id,
    start_time,
    flow,
    flow_pc,
    dsat,
    dsat_pc,
    sin_time,
    cos_time,
    day_num,
    target
FROM (
    SELECT
        f.*,
        ROW_NUMBER() OVER (PARTITION BY f.target ORDER BY RAND()) AS rn
    FROM v_ml_feature_set f
) ranked
WHERE rn <= 10000;


-- -----------------------------------------------------------------------------
-- 4. v_hourly_site_aggregates
-- Purpose: Per (site_id, date_id, hour_of_day) averages of the four metrics
--          and their percentage counterparts. Useful for exploratory analysis,
--          per-hour feature engineering, and pre-computed aggregations the ML
--          pipeline can join on.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_hourly_site_aggregates AS
SELECT
    site_id,
    date_id,
    HOUR(start_time) AS hour_of_day,
    AVG(flow)    AS avg_flow,
    AVG(flow_pc) AS avg_flow_pc,
    AVG(cong)    AS avg_cong,
    AVG(cong_pc) AS avg_cong_pc,
    AVG(dsat)    AS avg_dsat,
    AVG(dsat_pc) AS avg_dsat_pc,
    COUNT(*)     AS interval_count
FROM TrafficMeasurements
GROUP BY site_id, date_id, HOUR(start_time);


-- -----------------------------------------------------------------------------
-- 5. v_site_class_distribution
-- Purpose: Per (site_id, target) observation counts. Surfaces how class
--          imbalance varies across sites — some sites have effectively no
--          variability in `cong` and end up with degenerate class
--          distributions, which matters for model evaluation per site.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_site_class_distribution AS
SELECT
    site_id,
    target,
    COUNT(*) AS observation_count
FROM v_ml_feature_set
GROUP BY site_id, target;


-- =============================================================================
-- Verification queries (run after data load to sanity-check the views)
-- =============================================================================
-- SELECT COUNT(*) FROM v_measurements_enriched;
--   -- expect: same row count as TrafficMeasurements (joins are inner; every
--   --         measurement row has a matching site_id and date_id by FK)
--
-- SELECT target, COUNT(*) AS n
--   FROM v_ml_feature_set
--   GROUP BY target
--   ORDER BY target;
--   -- expect: 5 rows, target = 0..4, with roughly equal counts within each
--   --         site (NTILE produces rank-based partitions of equal size per
--   --         site; aggregated counts may differ slightly across sites of
--   --         different sizes)
--
-- SELECT target, COUNT(*) AS n
--   FROM v_class_balanced_training_sample
--   GROUP BY target
--   ORDER BY target;
--   -- expect: 5 rows, each n <= 10000 (some classes may have fewer rows
--   --         total if the per-site NTILE produced sparse classes)
--
-- SELECT COUNT(DISTINCT site_id) FROM v_site_class_distribution;
--   -- expect: 61 (all sites represented)
-- =============================================================================
