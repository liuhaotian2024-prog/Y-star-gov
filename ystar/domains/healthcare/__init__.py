"""
Y* Healthcare Domain Pack

Clinical and healthcare data management domain pack, applicable to:
  - PHI (Protected Health Information) access control
  - Clinical decision support agent pipelines
  - Consent-gated data operations
  - Audit-logged record access and modification
  - Regulatory compliance: HIPAA, GDPR Health, HL7 FHIR access patterns

This pack proves that the Y* kernel is industry-agnostic —
the same DomainPack interface applied to a third, unrelated domain.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from ystar.domains import DomainPack
from ystar import IntentContract, ConstitutionalContract, DelegationContract


class HealthcareDomainPack(DomainPack):
    """
    Healthcare domain pack.

    Roles available via make_contract():
      clinician, nurse, pharmacist, researcher,
      data_engineer, compliance_officer, audit_agent
    """

    def __init__(self, config=None):
        self._config = config

    @property
    def domain_name(self) -> str:
        return "healthcare"

    @property
    def version(self) -> str:
        return "1.0.0"

    def vocabulary(self) -> dict:
        return {
            "deny_keywords": [
                "phi_without_consent",
                "unencrypted_phi_export",
                "unauthorized_record_access",
                "re_identification_attempt",
                "bypass_hipaa",
                "bypass_gdpr",
            ],
            "role_names": [
                "clinician", "nurse", "pharmacist", "researcher",
                "data_engineer", "compliance_officer", "audit_agent",
            ],
            "param_names": [
                "patient_id", "consent_status", "data_sensitivity",
                "record_count", "retention_days", "anonymisation_level",
                "access_purpose", "audit_logged",
            ],
            "env_keywords": ["sandbox", "test_environment", "simulation", "de_identified"],
            "entity_list_patterns": [
                # "restricted patients: P001, P002"
                r"(?:restricted\s*patients?|blocked\s*patient\s*ids?)\s*[：:]\s*"
                r"([A-Z0-9][A-Z0-9_-]*(?:[,，\s]+[A-Z0-9][A-Z0-9_-]*)+)",
            ],
        }

    def constitutional_contract(self) -> ConstitutionalContract:
        """
        Healthcare constitutional layer:
          - PHI never exported without consent
          - All record access must be audit-logged
          - Re-identification attempts are absolutely prohibited
          - Data sensitivity level must be within role's clearance
        """
        cfg = self._config or {}
        extra_deny        = list(cfg.get("extra_deny", []))
        restricted_ids    = list(cfg.get("restricted_patient_ids", []))
        max_record_count  = cfg.get("max_record_count", 1_000_000)
        min_anon_level    = cfg.get("min_anonymisation_level", 0)

        return ConstitutionalContract(
            deny = [
                "phi_without_consent",
                "unencrypted_phi_export",
                "unauthorized_record_access",
                "re_identification_attempt",
                "bypass_hipaa",
                "bypass_gdpr",
            ] + extra_deny + restricted_ids,
            deny_commands = [
                "export_raw_phi ",
                "drop_audit_log ",
                "disable_encryption ",
            ],
            optional_invariant = [
                "consent_status == True",      # checked when consent_status is passed
                "audit_logged == True",        # checked when audit_logged is passed
            ],
            value_range = {
                "record_count":        {"max": max_record_count},
                "anonymisation_level": {"min": min_anon_level},
            },
        )

    def make_contract(self, role: str, context: dict = None) -> IntentContract:
        """
        Generate the IntentContract for the given role.
        All role contracts inherit from the constitutional layer.

        Args:
            role:    one of clinician | nurse | pharmacist | researcher |
                     data_engineer | compliance_officer | audit_agent
            context: optional overrides, e.g. {"max_record_count": 100}
        """
        ctx          = context or {}
        constitution = self.constitutional_contract()

        role_contracts = {
            "clinician": IntentContract(
                # Direct patient care; access to individual records with
                # active consent required; no bulk exports
                invariant   = ["clinician_authorized == True"],
                optional_invariant = ["consent_status == True"],
                value_range = {
                    "record_count":    {"max": ctx.get("max_record_count", 50)},
                    "retention_days":  {"max": ctx.get("max_retention_days", 365)},
                },
                deny = ["phi_without_consent", "unencrypted_phi_export",
                        "re_identification_attempt"],
                obligation_timing={
                    "acknowledgement": 900,       # 15 min to ack patient request
                    "status_update": 3600,        # 1 hour status update
                    "result_publication": 7200,   # 2 hours to publish clinical note
                    "escalation": 600,            # 10 min to escalate urgent case
                },
            ),

            "nurse": IntentContract(
                # Bedside care; narrower record access than clinicians
                invariant   = ["nurse_authorized == True"],
                optional_invariant = ["consent_status == True"],
                value_range = {
                    "record_count":   {"max": ctx.get("max_record_count", 20)},
                    "retention_days": {"max": ctx.get("max_retention_days", 90)},
                },
                deny = ["phi_without_consent", "unencrypted_phi_export",
                        "re_identification_attempt", "prescribe_without_order"],
                obligation_timing={
                    "acknowledgement": 600,       # 10 min to ack patient care task
                    "status_update": 1800,        # 30 min status update
                    "result_publication": 3600,   # 1 hour to document care
                    "escalation": 300,            # 5 min to escalate urgent issue
                },
            ),

            "pharmacist": IntentContract(
                # Medication management; access limited to medication-related records
                invariant   = ["pharmacist_authorized == True"],
                optional_invariant = ["consent_status == True"],
                value_range = {
                    "record_count":   {"max": ctx.get("max_record_count", 30)},
                    "retention_days": {"max": ctx.get("max_retention_days", 180)},
                },
                deny = ["phi_without_consent", "unencrypted_phi_export",
                        "re_identification_attempt",
                        "access_non_medication_records_without_approval"],
                obligation_timing={
                    "acknowledgement": 1800,      # 30 min to ack prescription
                    "status_update": 7200,        # 2 hours status update
                    "result_publication": 14400,  # 4 hours to dispense medication
                    "escalation": 900,            # 15 min to escalate drug interaction
                },
            ),

            "researcher": IntentContract(
                # Clinical research; must operate on de-identified data;
                # bulk access allowed but only at high anonymisation level
                invariant = ["researcher_authorized == True",
                             "irb_approved == True"],
                value_range = {
                    "record_count":        {"max": ctx.get("max_record_count",   10_000)},
                    "anonymisation_level": {"min": ctx.get("min_anon_level",        3)},  # fully de-identified
                    "data_sensitivity":    {"max": ctx.get("max_data_sensitivity",  2)},  # non-PHI only
                },
                deny = ["phi_without_consent", "re_identification_attempt",
                        "unencrypted_phi_export", "direct_patient_identifier_in_output"],
                obligation_timing={
                    "acknowledgement": 14400,     # 4 hours to ack research request
                    "status_update": 86400,       # 24 hours status update
                    "result_publication": 604800, # 7 days to publish research result
                    "escalation": 7200,           # 2 hours to escalate IRB issue
                },
            ),

            "data_engineer": IntentContract(
                # Pipeline / ETL; must never touch raw PHI; can only access
                # de-identified or aggregated datasets
                invariant = ["data_engineer_authorized == True"],
                value_range = {
                    "anonymisation_level": {"min": ctx.get("min_anon_level", 3)},
                    "record_count":        {"max": ctx.get("max_record_count", 1_000_000)},
                },
                deny = ["phi_without_consent", "unencrypted_phi_export",
                        "re_identification_attempt", "raw_phi_in_pipeline"],
                obligation_timing={
                    "acknowledgement": 7200,      # 2 hours to ack pipeline request
                    "status_update": 43200,       # 12 hours status update
                    "result_publication": 86400,  # 24 hours to complete ETL job
                    "escalation": 3600,           # 1 hour to escalate pipeline failure
                },
            ),

            "compliance_officer": IntentContract(
                invariant = ["compliance_role == True"],
                deny      = ["bypass_hipaa", "bypass_gdpr",
                             "suppress_audit_finding", "unauthorized_exception"],
                obligation_timing={
                    "acknowledgement": 3600,      # 1 hour to ack compliance check
                    "status_update": 28800,       # 8 hours status update
                    "result_publication": 86400,  # 24 hours to publish compliance report
                    "escalation": 1800,           # 30 min to escalate HIPAA violation
                },
            ),

            "audit_agent": IntentContract(
                # Read-only audit role; can read audit logs and flag violations
                # but cannot modify records or disable logging
                invariant = ["audit_authorized == True"],
                value_range = {
                    "record_count": {"max": ctx.get("max_record_count", 100_000)},
                },
                deny = ["modify_audit_log", "delete_audit_entry",
                        "phi_without_consent", "re_identification_attempt"],
                obligation_timing={
                    "acknowledgement": 7200,      # 2 hours to ack audit request
                    "status_update": 86400,       # 24 hours status update
                    "result_publication": 259200, # 3 days to publish audit report
                    "escalation": 3600,           # 1 hour to escalate audit finding
                },
            ),
        }

        base = role_contracts.get(role, IntentContract())
        return base.merge(constitution)


def make_clinical_delegation_chain(
    pack:                HealthcareDomainPack = None,
    max_record_count:    int   = 50,
    min_anonymisation:   int   = 0,
) -> "DelegationChain":
    """
    Build a standard clinical access delegation chain:
    Clinician → Nurse → Audit Agent

    v0.24.0: monotonicity enforced — audit_agent contract is a strict
    subset of nurse_contract; action_scope only narrows down the chain.
    """
    from ystar import DelegationChain, IntentContract
    import time

    if pack is None:
        pack = HealthcareDomainPack()

    ctx = {"max_record_count": max_record_count,
           "min_anon_level":   min_anonymisation}

    nurse_contract = pack.make_contract("nurse", {
        **ctx,
        "max_record_count": max(1, max_record_count // 2),
    })
    audit_contract_base = pack.make_contract("audit_agent", {
        **ctx,
        "max_record_count": max(1, max_record_count // 4),  # auditor sees LESS, read-only
    })
    # Inherit nurse_contract constraints so audit_contract ⊆ nurse_contract
    audit_contract = IntentContract(
        deny          = list(dict.fromkeys(audit_contract_base.deny + nurse_contract.deny)),
        deny_commands = list(dict.fromkeys(audit_contract_base.deny_commands + nurse_contract.deny_commands)),
        only_paths    = audit_contract_base.only_paths or nurse_contract.only_paths,
        only_domains  = audit_contract_base.only_domains or nurse_contract.only_domains,
        invariant     = list(dict.fromkeys(audit_contract_base.invariant + nurse_contract.invariant)),
        optional_invariant = list(dict.fromkeys(
            audit_contract_base.optional_invariant + nurse_contract.optional_invariant)),
        value_range   = {**nurse_contract.value_range, **audit_contract_base.value_range},
        name          = "audit_agent_inherited",
    )

    clinician_to_nurse = DelegationContract(
        principal        = "clinician",
        actor            = "nurse_agent",
        contract         = nurse_contract,
        action_scope     = ["read_record", "update_vitals", "read_audit_log", "flag_anomaly"],
        delegation_depth = 1,
        allow_redelegate = True,
        valid_until      = time.time() + 43_200,
    )
    nurse_to_audit = DelegationContract(
        principal        = "nurse_agent",
        actor            = "audit_agent",
        contract         = audit_contract,
        action_scope     = ["read_audit_log", "flag_anomaly"],   # ⊆ parent scope
        delegation_depth = 0,
        allow_redelegate = False,
        valid_until      = time.time() + 43_200,
    )

    return DelegationChain().append(clinician_to_nurse).append(nurse_to_audit)
