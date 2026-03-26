"""
Y* Pharma Regulatory Domain Pack  —  v1.1.0

Encodes FDA/ICH regulatory submission constraints for multi-agent pipelines.

Regulatory anchors implemented in this version
-----------------------------------------------
  ICH E9(R1)   Statistical Analysis Plan: pre-specification, SAP amendments,
               primary/secondary/exploratory endpoint hierarchy, missing data
  ICH E6(R3)   GCP: source data integrity, audit trail, data custody chain
  ICH E3       CSR structure: mandatory sections, cross-reference integrity
  ICH M4(R1)   CTD module completeness (eCTD)
  21 CFR 11    Electronic records: audit trail, electronic signatures
  FDA 2023     Guidance on AI/ML-Based Software as Medical Device (SaMD)
  FDA Dec-2025 Agentic AI deployment guidelines

Design principle
----------------
Every constraint here maps to a specific ICH/FDA clause.
The comment on each rule cites its source document and section number.
This traceability is itself a compliance asset.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from ystar.domains import DomainPack
from ystar import IntentContract, ConstitutionalContract


# ══════════════════════════════════════════════════════════════════════════════
# ICH E9(R1) Statistical Analysis Plan rules
# ══════════════════════════════════════════════════════════════════════════════

# Primary endpoint: must be pre-specified before unblinding
# Source: ICH E9(R1) Section 3.1 "Confirmatory analysis"
_SAP_PRIMARY_ENDPOINT_RULES = {
    "value_range": {
        # alpha level: ICH E9 recommends 0.05 two-sided for confirmatory
        "alpha_level":          {"max": 0.05},
        # CI width: must be pre-specified; >20% often triggers FDA query
        "confidence_interval_width": {"max": 0.20},
        # Missing data: <5% MCAR generally acceptable; >15% requires sensitivity
        "missing_data_pct":     {"max": 0.15},
        # Multiplicity: if >1 primary, must use pre-specified alpha correction
        "primary_endpoint_count": {"max": 3},
    },
    "deny": [
        "post_hoc_primary_endpoint",      # E9(R1) §3.1: primary must be pre-specified
        "endpoint_modified_after_unblinding",  # E9(R1) §3.2: no changes post-unblind
        "unadjusted_multiplicity",        # E9(R1) §3.3: multiplicity control required
    ],
}

# SAP amendment rules
# Source: ICH E9(R1) Section 4 "Analysis set definitions"
_SAP_AMENDMENT_RULES = {
    "deny": [
        "sap_amended_after_unblinding_undocumented",  # E9(R1) §4: amendments need audit trail
        "analysis_population_changed_post_randomisation_undocumented",
    ],
    "optional_invariant": [
        "sap_amendment_timestamp < unblinding_timestamp",  # must precede unblinding
    ],
}

# Missing data handling
# Source: ICH E9(R1) Section 5 "Handling of missing data"
_MISSING_DATA_RULES = {
    "deny": [
        "missing_data_imputation_undocumented",   # E9(R1) §5.1: method must be pre-specified
        "complete_case_analysis_without_sensitivity",  # E9(R1) §5.3: need sensitivity analysis
        "last_observation_carried_forward_as_primary",  # EMA/FDA: LOCF no longer acceptable as primary
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
# ICH E6(R3) GCP — Source data integrity rules
# ══════════════════════════════════════════════════════════════════════════════

# Source data custody
# Source: ICH E6(R3) Section 4.9 "Source documents and data"
_GCP_SOURCE_DATA_RULES = {
    "deny": [
        "source_data_modified_without_audit_trail",  # E6(R3) §4.9.0: all changes tracked
        "source_data_deleted",                        # E6(R3) §4.9.0: data must be retained
        "unvalidated_source",                         # E6(R3) §4.9.0: only validated systems
        "data_transcription_without_verification",    # E6(R3) §4.9.2: double verification required
        "sdtm_derivation_undocumented",              # CDISC: all derivations must be documented
    ],
    "optional_invariant": [
        "data_source_status == 'GCP_certified'",
        "part11_audit_logged == True",
    ],
}

# Investigator site data quality
# Source: ICH E6(R3) Section 5.18 "Monitoring"
_SITE_DATA_QUALITY_RULES = {
    "value_range": {
        # Protocol deviation rate: >15% triggers FDA inspection concern
        "protocol_deviation_rate":  {"max": 0.15},
        # Query response time: ICH E6 expects timely resolution
        "data_query_age_days":      {"max": 30},
        # Source data verification rate: risk-based, but <80% needs justification
        "sdv_completion_rate":      {"min": 0.80},
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# ICH E3 — Clinical Study Report structure rules
# ══════════════════════════════════════════════════════════════════════════════

# Mandatory CSR sections
# Source: ICH E3 Section 4 "Contents of the clinical study report"
_CSR_MANDATORY_SECTIONS = [
    "title_page",          # E3 §4.1
    "synopsis",            # E3 §4.2
    "table_of_contents",   # E3 §4.3
    "ethics_section",      # E3 §4.4
    "investigators_list",  # E3 §4.5
    "introduction",        # E3 §4.6
    "study_objectives",    # E3 §4.7
    "investigational_plan",# E3 §4.8
    "study_patients",      # E3 §4.9
    "efficacy_evaluation", # E3 §4.10
    "safety_evaluation",   # E3 §4.11
    "discussion_conclusions", # E3 §4.12
    "reference_list",      # E3 §4.13
]

_CSR_RULES = {
    "deny": [
        "causal_claim_without_rct",      # E3 §4.12: conclusions must match study design
        "promotional_language",           # E3 §4.1: CSR is scientific, not promotional
        "unapproved_endpoint",           # E3 §4.10: only pre-specified endpoints
        "unvalidated_source",            # E3 §4.10: all data sources cited
        "missing_section_unlabelled",    # E3 §4: all required sections must be present
    ],
    "optional_invariant": [
        "citation_in_approved_dossier == True",
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
# 21 CFR Part 11 — Electronic records rules
# ══════════════════════════════════════════════════════════════════════════════

# Source: 21 CFR 11.10 "Controls for closed systems"
_PART11_RULES = {
    "deny": [
        "delete_audit_entry ",           # 21 CFR 11.10(e): audit trail inviolable
        "modify_source_data ",           # 21 CFR 11.10(e): changes must be tracked, not deleted
        "disable_audit_trail ",          # 21 CFR 11.10(e): audit trail must be enabled
        "electronic_signature_missing",  # 21 CFR 11.50: signature required on records
        "system_access_uncontrolled",    # 21 CFR 11.10(d): access must be limited
    ],
    "optional_invariant": [
        "part11_audit_logged == True",
        "electronic_signature_valid == True",
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
# ICH M4(R1) — CTD completeness rules
# ══════════════════════════════════════════════════════════════════════════════

# Source: ICH M4(R1) "Organisation of the Common Technical Document"
_CTD_MODULES = {
    "module_1": "administrative_and_prescribing_info",
    "module_2": "summaries",
    "module_3": "quality",
    "module_4": "nonclinical_study_reports",
    "module_5": "clinical_study_reports",
}

_CTD_RULES = {
    "value_range": {
        # completeness score 0-1; must be 1.0 for NDA submission
        "ctd_module_complete":      {"min": 1},
        "ctd_cross_reference_valid": {"min": 1},
    },
    "deny": [
        "ctd_module_missing",            # M4: all modules required
        "ctd_cross_reference_broken",    # M4: all cross-refs must resolve
        "ectd_validation_failed",        # FDA: eCTD must pass validation criteria
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
# Safety reporting rules (ICH E2A / FDA IND safety reporting)
# ══════════════════════════════════════════════════════════════════════════════

# Source: ICH E2A "Clinical Safety Data Management"
_SAFETY_RULES = {
    "deny": [
        "suppress_adverse_event",        # E2A §III: all AEs must be recorded
        "sae_report_delayed",            # E2A §III.C: SAEs within 15 days
        "causality_assessment_missing",  # E2A §IV: causality must be assessed
        "death_report_delayed",          # 21 CFR 312.32: deaths within 7 days
    ],
    "value_range": {
        # SAE count threshold for automatic human escalation
        "adverse_event_count":  {"max": 0},   # any SAE → human review
        # Serious-to-mild ratio: if >30% SAEs, triggers special review
        "sae_to_total_ae_ratio": {"max": 0.30},
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# ICH E8(R1) — Study quality factors (2021 revision)
# ══════════════════════════════════════════════════════════════════════════════
#
# ICH E8(R1) introduced a risk-based approach to clinical trial design quality.
# It identifies "Quality Tolerance Limits" (QTLs) that must be pre-specified
# and monitored. Critical quality attributes must be identified before the trial
# begins, not after issues emerge.
# Source: ICH E8(R1) "General Considerations for Clinical Studies" (2021)

# Quality Tolerance Limits — must be pre-specified
# Source: ICH E8(R1) §2.3 "Study Quality"
_QTL_RULES = {
    "deny": [
        "qtl_not_prespecified",              # E8(R1) §2.3: QTLs must be defined upfront
        "critical_to_quality_factor_missing",# E8(R1) §2.2: CtQ factors must be identified
        "risk_proportion_assessment_missing",# E8(R1) §2.3: risk assessment required
        "qtl_breach_undocumented",           # E8(R1) §2.3: breaches must trigger action
    ],
    "value_range": {
        # Primary endpoint data completeness: E8(R1) recommends >98% for primary
        "primary_endpoint_completeness": {"min": 0.95},
        # Consent rate: dropout >20% requires protocol amendment review
        "consent_withdrawal_rate":        {"max": 0.20},
        # Site activation on time: >40% delay triggers protocol concern
        "site_activation_delay_rate":     {"max": 0.40},
    },
}

# Estimands framework — ICH E9(R1) extension via E8(R1)
# Source: ICH E8(R1) §2.2 + ICH E9(R1) Addendum on Estimands
_ESTIMAND_RULES = {
    "deny": [
        "estimand_not_defined",              # E9(R1) Addendum: estimand must be explicit
        "intercurrent_event_strategy_missing",  # E9(R1) Addendum §3: strategy required
        "treatment_policy_strategy_undocumented",
        "hypothetical_strategy_without_sensitivity",
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
# FDA 2023 AI/ML SaMD — Artificial Intelligence in Medical Devices
# ══════════════════════════════════════════════════════════════════════════════
#
# FDA's 2023 guidance on AI/ML-Based Software as a Medical Device (SaMD) and
# its December 2025 Agentic AI deployment represent the most current regulatory
# framework specifically applicable to AI agents in clinical contexts.
#
# Key concept: "Predetermined Change Control Plan" (PCCP) — AI systems must
# declare in advance what kinds of changes they are allowed to make autonomously,
# and what requires human review. This maps directly to Y*'s DelegationContract.
#
# Sources:
#   FDA (2023) "Artificial Intelligence and Machine Learning (AI/ML)-Based Software
#               as a Medical Device (SaMD) Action Plan"
#   FDA (2023) "Marketing Submission Recommendations for a Predetermined Change
#               Control Plan for Artificial Intelligence/Machine Learning-Enabled
#               Device Software Functions"
#   FDA (Dec 2025) "Agentic AI Deployment Guidelines"

# PCCP — Predetermined Change Control Plan rules
# Source: FDA 2023 PCCP Guidance §3.1 "Description of Modifications"
_PCCP_RULES = {
    "deny": [
        "ai_model_change_outside_pccp",      # PCCP §3.1: only pre-declared changes allowed
        "ai_output_threshold_changed_autonomously",  # PCCP §3.2: threshold changes need review
        "training_data_scope_expanded_undocumented", # PCCP §4: data changes must be declared
        "algorithm_retrained_without_validation",    # FDA AI/ML: retraining requires validation
        "ai_decision_not_explainable",       # FDA AI/ML Action Plan §5: explainability required
        "human_override_pathway_missing",    # FDA Dec 2025: human override must always exist
    ],
    "optional_invariant": [
        "pccp_version_current == True",      # PCCP must reference current approved version
        "ai_model_version_locked == True",   # model version must be fixed at submission
    ],
}

# SaMD clinical evaluation rules
# Source: FDA AI/ML Action Plan §3 "Good Machine Learning Practice (GMLP)"
_SAMD_CLINICAL_RULES = {
    "deny": [
        "training_test_data_overlap",        # GMLP §1: no leakage between train/test
        "performance_metric_not_clinically_meaningful",  # GMLP §5: metrics must be clinical
        "subgroup_performance_not_reported", # GMLP §6: must report across demographic subgroups
        "distribution_shift_unmonitored",    # GMLP §7: real-world performance must be tracked
        "model_card_missing",                # FDA 2023: documentation of model characteristics
    ],
    "value_range": {
        # Model performance: sensitivity for safety-critical outputs
        "model_sensitivity":  {"min": 0.90},  # FDA guidance: high sensitivity for safety
        "model_specificity":  {"min": 0.85},
        # Demographic subgroup performance gap
        "subgroup_performance_gap": {"max": 0.10},  # >10% gap triggers equity concern
    },
}

# Agentic AI specific rules
# Source: FDA Dec 2025 "Agentic AI Deployment Guidelines"
_AGENTIC_AI_RULES = {
    "deny": [
        "agent_action_outside_declared_scope",    # FDA Dec 2025: agents must stay in scope
        "agent_to_agent_handoff_unvalidated",     # FDA Dec 2025: handoffs must be validated
        "autonomous_clinical_decision_without_hitl",  # FDA: HITL required for clinical decisions
        "agent_audit_trail_incomplete",           # FDA Dec 2025: full action logging required
        "bias_assessment_missing",                # FDA AI/ML: bias must be assessed and documented
    ],
    "optional_invariant": [
        "hitl_checkpoint_passed == True",         # human-in-the-loop checkpoint
        "agent_scope_validated == True",          # agent stayed within declared scope
        "part11_audit_logged == True",
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
# PharmaDomainPack
# ══════════════════════════════════════════════════════════════════════════════

class PharmaDomainPack(DomainPack):
    """
    FDA regulatory submission domain pack.

    v1.2.0 additions vs v1.1.0:
      - ICH E8(R1): Quality Tolerance Limits, CtQ factors, estimands framework
      - FDA 2023 AI/ML SaMD: PCCP, GMLP, model card, subgroup performance
      - FDA Dec 2025 Agentic AI: HITL checkpoints, agent scope validation,
        agent-to-agent handoff validation, full audit trail
      - 2 new roles: ai_system_validator, pccp_manager

    Roles (11 total):
      data_manager          ICH E6(R3): clinical data package custody
      statistical_analyst   ICH E9(R1): SAP-bounded analysis only
      medical_writer        ICH E3: CSR/CTD narrative, citation whitelist
      regulatory_affairs    ICH M4(R1): CTD assembly, region requirements
      submission_packager   final eCTD, strictest constraints
      quality_reviewer      21 CFR 11: read-only QC gate
      compliance_officer    exception handling, documented only
      safety_officer        ICH E2A: AE/SAE monitoring and reporting
      biostatistics_lead    ICH E9(R1): SAP governance and amendment control
      ai_system_validator   FDA AI/ML SaMD: GMLP validation, model card  [NEW v1.2.0]
      pccp_manager          FDA 2023 PCCP: AI change control governance    [NEW v1.2.0]
    """

    def __init__(self, config: dict = None):
        self._config = config or {}

    @property
    def domain_name(self) -> str:
        return "pharma"

    @property
    def version(self) -> str:
        return "1.2.0"

    @property
    def schema_version(self) -> str:
        return self._config.get("schema_version", "1.2.0")

    def vocabulary(self) -> dict:
        return {
            "deny_keywords": [
                # ICH E9(R1)
                "post_hoc_primary_endpoint",
                "endpoint_modified_after_unblinding",
                "unadjusted_multiplicity",
                "sap_amended_after_unblinding_undocumented",
                "missing_data_imputation_undocumented",
                "last_observation_carried_forward_as_primary",
                # ICH E6(R3)
                "source_data_modified_without_audit_trail",
                "source_data_deleted",
                "unvalidated_source",
                "data_transcription_without_verification",
                # ICH E3
                "causal_claim_without_rct",
                "promotional_language",
                "unapproved_endpoint",
                # 21 CFR 11
                "delete_audit_entry",
                "modify_source_data",
                "electronic_signature_missing",
                # ICH E2A
                "suppress_adverse_event",
                "sae_report_delayed",
                "death_report_delayed",
                # ICH E8(R1)
                "qtl_not_prespecified",
                "critical_to_quality_factor_missing",
                "estimand_not_defined",
                # FDA AI/ML SaMD
                "ai_model_change_outside_pccp",
                "training_test_data_overlap",
                "human_override_pathway_missing",
                "autonomous_clinical_decision_without_hitl",
                "agent_action_outside_declared_scope",
                "agent_to_agent_handoff_unvalidated",
                "bias_assessment_missing",
            ],
            "role_names": [
                "data_manager", "statistical_analyst", "medical_writer",
                "regulatory_affairs", "submission_packager",
                "quality_reviewer", "compliance_officer",
                "safety_officer", "biostatistics_lead",
                "ai_system_validator", "pccp_manager",
            ],
            "param_names": [
                # ICH E9(R1)
                "alpha_level", "confidence_interval_width",
                "missing_data_pct", "primary_endpoint_count",
                "sap_amendment_timestamp", "unblinding_timestamp",
                # ICH E8(R1)
                "primary_endpoint_completeness",
                "consent_withdrawal_rate",
                "qtl_breach_count",
                # ICH E6(R3)
                "data_source_status", "protocol_deviation_rate",
                "data_query_age_days", "sdv_completion_rate",
                # ICH E3 / M4
                "citation_in_approved_dossier",
                "ctd_module_complete", "ctd_cross_reference_valid",
                # ICH E2A
                "adverse_event_count", "sae_to_total_ae_ratio",
                "causality_assessment_status",
                # FDA AI/ML SaMD
                "model_sensitivity", "model_specificity",
                "subgroup_performance_gap",
                "ai_model_version_locked",
                "pccp_version_current",
                "hitl_checkpoint_passed",
                "agent_scope_validated",
                # 21 CFR 11
                "part11_audit_logged", "electronic_signature_valid",
                # Process
                "analysis_plan_locked", "region_requirements_met",
                "eclinical_trail_id_registered", "sample_size",
            ],
            "env_keywords": [
                "sandbox", "test_submission", "simulation",
                "pre_ind", "phase_1", "phase_2", "phase_3",
                "pivotal", "supportive",
            ],
        }

    def constitutional_contract(self) -> ConstitutionalContract:
        """
        Universal pharma constitutional layer.

        Encodes the non-negotiable floor across ALL ICH/FDA sources:
          ICH E9(R1): no post-hoc endpoints, no undocumented SAP changes
          ICH E6(R3): no data manipulation, GCP integrity
          ICH E8(R1): QTLs must be pre-specified, CtQ factors required
          ICH E2A:    no safety signal suppression
          ICH E3:     no promotional claims in scientific documents
          FDA AI/ML SaMD: PCCP compliance, HITL for clinical decisions
          FDA Dec 2025:   agent scope and handoff validation
          21 CFR 11:  audit trail inviolable, electronic signatures required
        """
        cfg = self._config

        all_deny = sorted(set(
            _SAP_PRIMARY_ENDPOINT_RULES["deny"]
            + _SAP_AMENDMENT_RULES["deny"]
            + _MISSING_DATA_RULES["deny"]
            + _GCP_SOURCE_DATA_RULES["deny"]
            + _CSR_RULES["deny"]
            + _PART11_RULES["deny"]
            + _CTD_RULES["deny"]
            + _SAFETY_RULES["deny"]
            + _QTL_RULES["deny"]           # ICH E8(R1)
            + _ESTIMAND_RULES["deny"]      # ICH E9(R1) Addendum
            + _PCCP_RULES["deny"]          # FDA AI/ML SaMD
            + _SAMD_CLINICAL_RULES["deny"] # FDA GMLP
            + _AGENTIC_AI_RULES["deny"]    # FDA Dec 2025
            + list(cfg.get("extra_deny", []))
        ))

        return ConstitutionalContract(
            deny = all_deny,
            deny_commands = [
                "delete_audit_entry ",
                "modify_source_data ",
                "disable_audit_trail ",
                "suppress_adverse_event ",
                "override_statistical_plan ",
                "retrain_model_without_validation ",   # FDA AI/ML GMLP
                "bypass_pccp ",                        # FDA 2023 PCCP
            ],
            optional_invariant = [
                "part11_audit_logged == True",
                "data_source_status == 'GCP_certified'",
                "electronic_signature_valid == True",
                "hitl_checkpoint_passed == True",      # FDA Dec 2025
                "agent_scope_validated == True",       # FDA Dec 2025
            ],
            value_range = {
                "alpha_level":                   {"max": cfg.get("alpha", 0.05)},
                "confidence_interval_width":     {"max": cfg.get("max_ci_width", 0.20)},
                "missing_data_pct":              {"max": cfg.get("max_missing_pct", 0.15)},
                "adverse_event_count":           {"max": cfg.get("sae_auto_threshold", 0)},
                # ICH E8(R1)
                "primary_endpoint_completeness": {"min": cfg.get("min_ep_completeness", 0.95)},
                "consent_withdrawal_rate":       {"max": cfg.get("max_withdrawal", 0.20)},
                # FDA AI/ML SaMD
                "subgroup_performance_gap":      {"max": cfg.get("max_subgroup_gap", 0.10)},
            },
        )

    def make_contract(self, role: str, context: dict = None) -> IntentContract:
        """
        Return the IntentContract for the given pipeline role.

        Each role is scoped to its ICH-defined function.
        Constraints are strictly monotone: every role ⊆ constitutional layer.
        """
        ctx          = context or {}
        cfg          = self._config        # pack-level config (alpha, sae_auto_threshold, …)
        constitution = self.constitutional_contract()

        role_contracts = {

            # ── ICH E6(R3): Data custody ─────────────────────────────────────
            "data_manager": IntentContract(
                # Owns and locks the Clinical Data Package (CDP).
                # ICH E6(R3) §4.9: responsible for source data integrity.
                invariant = [
                    "eclinical_trail_id_registered == True",
                    "analysis_plan_locked == True",
                ],
                optional_invariant = [
                    "data_source_status == 'GCP_certified'",
                    "part11_audit_logged == True",
                ],
                value_range = {
                    "sample_size":              {"min": ctx.get("min_sample_size", 1)},
                    "protocol_deviation_rate":  {"max": ctx.get("max_dev_rate", 0.10)},
                    "sdv_completion_rate":      {"min": ctx.get("min_sdv", 0.80)},
                    "data_query_age_days":      {"max": ctx.get("max_query_age", 30)},
                },
                deny = [
                    "unvalidated_source",
                    "source_data_modified_without_audit_trail",
                    "source_data_deleted",
                    "data_transcription_without_verification",
                    "sdtm_derivation_undocumented",
                    "missing_data_imputation_undocumented",
                ],
            ),

            # ── ICH E9(R1): Statistical analysis ─────────────────────────────
            "statistical_analyst": IntentContract(
                # Runs only pre-specified analyses from the locked SAP.
                # ICH E9(R1) §3.1: confirmatory analysis must be pre-specified.
                invariant = [
                    "analysis_plan_locked == True",
                    "citation_in_approved_dossier == True",
                ],
                optional_invariant = [
                    "part11_audit_logged == True",
                    "sap_amendment_timestamp < unblinding_timestamp",
                ],
                value_range = {
                    "alpha_level":               {"max": ctx.get("alpha",
                                                  cfg.get("alpha", 0.05))},
                    "confidence_interval_width": {"max": ctx.get("max_ci_width",
                                                  cfg.get("max_ci_width", 0.15))},
                    "missing_data_pct":          {"max": ctx.get("max_missing",
                                                  cfg.get("max_missing_pct", 0.10))},
                    "primary_endpoint_count":    {"max": ctx.get("max_primary", 2)},
                    # Read SAE threshold from pack config OR context override
                    "adverse_event_count":       {"max": ctx.get("sae_threshold",
                                                  cfg.get("sae_auto_threshold", 0))},
                },
                deny = [
                    "unapproved_endpoint",
                    "post_hoc_primary_endpoint",
                    "endpoint_modified_after_unblinding",
                    "unadjusted_multiplicity",
                    "sap_amended_after_unblinding_undocumented",
                    "last_observation_carried_forward_as_primary",
                    "complete_case_analysis_without_sensitivity",
                    "override_statistical_plan",
                ],
            ),

            # ── ICH E9(R1) §4: SAP governance ────────────────────────────────
            "biostatistics_lead": IntentContract(
                # Governs SAP amendments. Only role that can approve SAP changes,
                # but only BEFORE unblinding.
                # ICH E9(R1) §4: amendments must be documented with rationale.
                invariant = [
                    "sap_amendment_documented == True",
                ],
                optional_invariant = [
                    "sap_amendment_timestamp < unblinding_timestamp",
                    "part11_audit_logged == True",
                ],
                deny = [
                    "sap_amended_after_unblinding_undocumented",
                    "endpoint_modified_after_unblinding",
                    "unadjusted_multiplicity",
                    "post_hoc_primary_endpoint",
                ],
            ),

            # ── ICH E2A: Safety monitoring ────────────────────────────────────
            "safety_officer": IntentContract(
                # Monitors and reports AEs/SAEs.
                # ICH E2A §III: all AEs recorded; SAEs within 15 days; deaths within 7 days.
                invariant = [
                    "causality_assessment_status != 'not_done'",
                ],
                optional_invariant = [
                    "part11_audit_logged == True",
                ],
                value_range = {
                    # Safety officer has tighter SAE threshold than statistical analyst
                    "adverse_event_count":   {"max": 0},  # every SAE → review
                    "sae_to_total_ae_ratio": {"max": 0.30},
                },
                deny = [
                    "suppress_adverse_event",
                    "sae_report_delayed",
                    "death_report_delayed",
                    "causality_assessment_missing",
                ],
            ),

            # ── ICH E3: Medical writing ───────────────────────────────────────
            "medical_writer": IntentContract(
                # Drafts CSR / CTD Module 5 narrative.
                # ICH E3 §4: conclusions must match study design; no promotional language.
                invariant = [
                    "citation_in_approved_dossier == True",
                ],
                optional_invariant = [
                    "part11_audit_logged == True",
                ],
                deny = [
                    "unvalidated_source",
                    "causal_claim_without_rct",
                    "promotional_language",
                    "unapproved_endpoint",
                    "missing_section_unlabelled",
                    "post_hoc_primary_endpoint",
                ],
            ),

            # ── ICH M4(R1): Regulatory dossier assembly ───────────────────────
            "regulatory_affairs": IntentContract(
                # Assembles region-specific CTD dossier per ICH M4(R1).
                invariant = [
                    "region_requirements_met == True",
                    "citation_in_approved_dossier == True",
                ],
                optional_invariant = [
                    "part11_audit_logged == True",
                ],
                value_range = {
                    "ctd_module_complete":       {"min": ctx.get("min_ctd", 1)},
                    "ctd_cross_reference_valid": {"min": 1},
                },
                deny = [
                    "unvalidated_source",
                    "unapproved_endpoint",
                    "promotional_language",
                    "ctd_module_missing",
                    "ctd_cross_reference_broken",
                ],
            ),

            # ── ICH M4 + 21 CFR 11: Final eCTD packaging ─────────────────────
            "submission_packager": IntentContract(
                # Creates the final eCTD submission package.
                # Strictest role: all prior checks must pass before packaging.
                invariant = [
                    "citation_in_approved_dossier == True",
                    "region_requirements_met == True",
                    "analysis_plan_locked == True",
                ],
                optional_invariant = [
                    "part11_audit_logged == True",
                    "electronic_signature_valid == True",
                    "ctd_module_complete == True",
                    "ectd_validation_failed == False",
                ],
                deny = [
                    "unvalidated_source",
                    "unapproved_endpoint",
                    "promotional_language",
                    "ctd_module_missing",
                    "ectd_validation_failed",
                    "delete_audit_entry",
                    "modify_source_data",
                    "electronic_signature_missing",
                ],
            ),

            # ── 21 CFR 11: QC gate ────────────────────────────────────────────
            "quality_reviewer": IntentContract(
                # Read-only QC gate; can flag but cannot modify any record.
                # 21 CFR 11.10: all access controlled and logged.
                invariant = [
                    "citation_in_approved_dossier == True",
                ],
                optional_invariant = [
                    "part11_audit_logged == True",
                ],
                deny = [
                    "modify_source_data",
                    "delete_audit_entry",
                    "suppress_adverse_event",
                    "disable_audit_trail",
                ],
            ),

            # ── Exception handling ────────────────────────────────────────────
            "compliance_officer": IntentContract(
                # May grant exceptions, but only with documented justification.
                invariant = [
                    "exception_documented == True",
                ],
                deny = [
                    "suppress_adverse_event",
                    "delete_audit_entry",
                    "override_statistical_plan",
                    "endpoint_modified_after_unblinding",
                ],
            ),

            # ── FDA AI/ML SaMD: Model validation ─────────────────────────────
            "ai_system_validator": IntentContract(
                # Validates AI/ML models per FDA Good Machine Learning Practice (GMLP).
                # Source: FDA 2023 AI/ML Action Plan §3 "Good Machine Learning Practice"
                # Responsible for: model card, performance metrics, subgroup analysis,
                # distribution shift monitoring, bias assessment.
                invariant = [
                    "model_card_present == True",
                    "bias_assessment_complete == True",
                ],
                optional_invariant = [
                    "part11_audit_logged == True",
                    "ai_model_version_locked == True",
                ],
                value_range = {
                    "model_sensitivity":       {"min": ctx.get("min_sensitivity", 0.90)},
                    "model_specificity":       {"min": ctx.get("min_specificity", 0.85)},
                    "subgroup_performance_gap":{"max": ctx.get("max_subgroup_gap", 0.10)},
                },
                deny = [
                    "training_test_data_overlap",
                    "performance_metric_not_clinically_meaningful",
                    "subgroup_performance_not_reported",
                    "distribution_shift_unmonitored",
                    "model_card_missing",
                    "bias_assessment_missing",
                    "algorithm_retrained_without_validation",
                    # Agentic AI specific (FDA Dec 2025)
                    "agent_to_agent_handoff_unvalidated",
                    "agent_audit_trail_incomplete",
                ],
            ),

            # ── FDA 2023 PCCP: Change control governance ──────────────────────
            "pccp_manager": IntentContract(
                # Governs the Predetermined Change Control Plan for AI/ML systems.
                # Source: FDA 2023 "Marketing Submission Recommendations for PCCP"
                # Only role that can authorise AI model changes — but only those
                # pre-declared in the approved PCCP.
                invariant = [
                    "pccp_version_current == True",
                    "change_within_pccp_scope == True",
                ],
                optional_invariant = [
                    "part11_audit_logged == True",
                    "hitl_checkpoint_passed == True",
                ],
                deny = [
                    "ai_model_change_outside_pccp",
                    "ai_output_threshold_changed_autonomously",
                    "training_data_scope_expanded_undocumented",
                    "algorithm_retrained_without_validation",
                    "human_override_pathway_missing",
                    "autonomous_clinical_decision_without_hitl",
                    "agent_action_outside_declared_scope",
                    "bypass_pccp",
                ],
            ),
        }

        base = role_contracts.get(role, IntentContract())
        return base.merge(constitution)
