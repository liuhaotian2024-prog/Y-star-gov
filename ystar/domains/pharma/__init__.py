"""
Y* Pharma Regulatory Domain Pack  —  v1.3.0

Encodes FDA/ICH regulatory submission constraints for multi-agent pipelines.

Regulatory anchors implemented in this version
-----------------------------------------------
  ICH E9(R1)   Statistical Analysis Plan: pre-specification, SAP amendments,
               primary/secondary/exploratory endpoint hierarchy, missing data
  ICH E6(R3)   GCP: source data integrity, audit trail, data custody chain
               §5.5 ALCOA+ data integrity (Attributable, Legible, Contemporaneous,
               Original, Accurate, Complete, Consistent, Enduring, Available, Traceable)
  ICH E3       CSR structure: mandatory sections, cross-reference integrity
  ICH M4(R1)   CTD module completeness (eCTD)
  21 CFR 11    Electronic records: audit trail, electronic signatures
  FDA 2023     Guidance on AI/ML-Based Software as Medical Device (SaMD)
  FDA Dec-2025 Agentic AI deployment guidelines
  WHO TRS 1033 Annex 4: Data integrity guidance
  PIC/S PI 041-1: Good Practices for Data Management and Integrity

Design principle
----------------
Every constraint here maps to a specific ICH/FDA clause.
The comment on each rule cites its source document and section number.
This traceability is itself a compliance asset.
"""