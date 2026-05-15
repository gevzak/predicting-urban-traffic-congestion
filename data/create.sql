CREATE TABLE IF NOT EXISTS TrafficSites (
    site_id VARCHAR(8) PRIMARY KEY, -- Site Serial Number
);

CREATE TABLE IF NOT EXISTS Calendar (
    date_id DATE PRIMARY KEY,
    day_of_week VARCHAR(10) NOT NULL -- Extracted from 'day' field
);

CREATE TABLE IF NOT EXISTS TrafficMeasurements (
    observation_id BIGSERIAL PRIMARY KEY,
    site_id VarChar(8),
    date_id DATE,
    start_time TIME,
    end_time TIME,
    flow INT, -- Raw flow count
    flow_pc INT, -- Flow percentage
    cong INT, -- Congestion level
    cong_pc INT,
    dsat INT, -- Degree of saturation
    dsat_pc INT,
    CONSTRAINT fk_site 
        FOREIGN KEY (site_id)
        REFERENCES TrafficSites(site_id),
    CONSTRAINT fk_date 
        FOREIGN KEY (date_id) 
        REFERENCES Calendar(date_id)
);