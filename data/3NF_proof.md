## 3NF Verification Proof

- **First Normal Form (1NF) Pass:** All attributes are atomic (single values like int, float, date, time). There 
are no repeating groups or comma-separated lists in any cells. At the table level, all rows are unique given the use of
a primary key.
- **Second Normal Form (2NF) Pass:** The primary keys for all tables are atomic, so no partial dependencies are possible.
- **Third Normal Form (3NF) Pass:** The only risk of transitive dependency is between `date` and `day_of_week`. This was
handled by isolating this relationship in the `CALENDAR` table. All other attributes in `TRAFFIC_MEASUREMENTS` depend 
directly and only on `observation_id`.