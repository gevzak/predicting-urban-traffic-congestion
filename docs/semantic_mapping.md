# Semantic Mapping (T2.2)

This table maps all meaningful attributes in our traffic measurement database to semantic concepts from domain-specific ontologies. All URIs have been verified to resolve successfully.

## TrafficMeasurements Table

| Column |  Ontology  |                  Concept URI                   |   Concept Label   |                      Justification                                                                                                                                                          |
|--------|------------|------------------------------------------------|-------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| flow   | SSN/SOSA   |       http://www.w3.org/ns/ssn/Property        | observed property | SSN is the W3C international standard for describing sensor observations. It is widely adopted in IoT and smart city projects, providing interoperable definitions for traffic sensor data. |
| flow_pc| QUDT       |       http://qudt.org/vocab/unit/PERCENT       |      Percent      | QUDT is the internationally recognized standard for engineering quantities. It provides precise, machine-readable definitions for percentage-based metrics used in transportation analysis. |
| cong   | SAREF4AUTO | https://saref.etsi.org/saref4auto/Lane_traffic | Lane - traffic    | SAREF4AUTO is the ETSI standard ontology for automotive and urban traffic applications. Using it aligns our dataset with European intelligent transportation standards. |
| cong_pc| QUDT       |       http://qudt.org/vocab/unit/PERCENT       |      Percent      | QUDT provides standardized, version-controlled definitions for percentage units. This ensures consistent interpretation across open science datasets and engineering tools. |
| dsat   | SSN/SOSA   |       http://www.w3.org/ns/ssn/Property        | observed property | SSN provides a robust framework for describing measured properties and their provenance. This ensures reproducibility and interoperability in traffic research workflows. |
| dsat_pc| QUDT       |       http://qudt.org/vocab/unit/PERCENT       |      Percent      | QUDT's curated vocabulary guarantees unambiguous, machine-actionable interpretation of percentage metrics in FAIR-compliant research data. |
