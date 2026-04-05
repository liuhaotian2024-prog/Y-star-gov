# Changelog

All notable changes to Y*gov will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.48.0] - 2026-04-03

### Added
- Foundation Sovereignty: Complete authority deepening across scope/compiler/provider layers
- Per-agent governance: Identity, write boundary, orchestration, and obligation scoping
- CIEU boot record and session config as single source of truth
- Immutable path protection (P5 TIER1) with tool restrictions
- Bash command write path extraction and validation
- CI/CD: GitHub Actions pytest automation (Python 3.11+3.12)
- Complete CLI Reference documentation

### Changed
- Generalized CausalEngine: Configurable DAG, domain-agnostic design
- GovernanceLoop slimdown: Extracted causal_feedback and proposal_submission modules
- Removed all hardcoded role names and paths for fully generic multi-agent support

### Fixed
- All 559 tests passing (4 e2e governance pipeline tests fixed for grace period handling)
- P0: Custom obligation timing keys now properly registered and supported
- P0: CIEUStore.log() → .write() restored omission setup CIEU recording
- P0: Accountability pack custom obligation key fallback
- Omission store registration and orchestrator pipeline wiring
- Silent exception handlers replaced with logged warnings
- FIX-6: Delegation chain loading
- FIX-7: Bash path normalization
- Synced setup.py version to 0.48.0 (was stuck at 0.41.1)
- Windows hook installation now uses .bat wrapper

### Performance
- Reduced high-frequency obligation trigger overhead
- Optimized check_hook() with agent_id routing (only loads relevant obligations)

## [0.47.0] - 2026-03-31

### Added
- Pearl Everywhere: Pearl L2-L3 causal reasoning integrated into Path A/B governance (C1-C6)
- Causal modularization: Split causal_engine.py (2714 lines) into 5 focused modules

### Changed
- System Convergence & Anti-Drift Principles v1 established

## [0.46.0] - 2026-03-29

### Added
- G1-G3 modularization: Split GovernanceLoop, CLI improvements, typed bridge suggestions

### Changed
- Cleaner module structure and organization

## [0.45.0] - 2026-03-28

### Added
- R1-R9 final polish: Eliminated legacy constitution loading, extracted policies, formal obligations
- Skill self-enhancement rule for continuous capability expansion

### Changed
- Near-perfect state achieved across all governance layers

## [0.44.0] - 2026-03-27

### Added
- Wave 4 Real Runtime Validation (N9-N10): Non-mock runtime tests, architecture regression tests
- Wave 3 Engineering Polish (N5-N8): Bridge suggestions, delegation policy, suggestion policy, escalation confirmation
- Wave 2 Foundation Sovereignty (N1-N4): Unified compiler, constitution provider, scope encoding
- F1-F6 hardcoded→policy migration, constitution provider migration, causal discovery tests

### Changed
- Functional-complete status achieved

## [0.43.0] - 2026-03-26

### Added
- Batch 4: Scenario Battery + Validation Report + Maintenance (T13, T14, T18)
- Batch 3: Bridge I/O Schema + Action Schema (T9, T10, T11, T12, T17)
- Batch 2: Path A/B final polish (T5, T6, T7, T8, T16, T17)
- Batch 1 P0: Amendment system, contract lifecycle, compile diagnostics
- Architecture freeze v1: "One foundation + three lines" restructure
- Contract Legitimacy Lifecycle: Full state machine

### Changed
- 100% Framework Complete with 304 tests
- Released to PyPI with complete metadata

### Fixed
- 12 claims verified through release audit

## [0.42.0] - 2026-03-22

### Added
- Pearl Level 2 & 3 causal reasoning in CausalEngine
- DirectLiNGAM: Pure-Python causal discovery via non-Gaussianity
- PC algorithm for causal structure discovery from CIEU data
- Temporal ordering in PC algorithm (SHD drops from 8 to 0)
- Path B: External Governance Agent (world-first: self + external governance symmetry)
- `ystar demo` command: Zero-config demonstration in <1ms

### Changed
- Integrated Pearl CausalEngine into full governance pipeline
- Model-agnostic nl_to_contract with input independence formalized

### Fixed
- CRITICAL: enforce() was silently failing, team ran on lightweight path only
- Path B cold-start: Exclude current observation from prior history count
- Path A bugs: Planner truncation + CausalEngine averaging
- 5 module integration gaps: Omission, causal, CIEU cross-wiring
- 6 user-journey issues: Version, doctor message, regex warnings, report auto-db, Path B cold-start

## [0.41.0] - 2026-03-20

### Added
- Initial public release
- OpenClaw adapter integration
- Natural language to contract compilation
- Dual-path governance (Path A: self-governance, Path B: external governance)
- CIEU evidence recording and audit
- Obligation trigger system
- Contract lifecycle management

### Changed
- Migrated from K9Audit to Y*gov branding
- Complete technical documentation

### Fixed
- Windows Git Bash path handling
- Doctor command detection bugs
- OpenClaw API compatibility

[0.48.0]: https://github.com/liuhaotian2024-prog/Y-star-gov/compare/v0.47.0...v0.48.0
[0.47.0]: https://github.com/liuhaotian2024-prog/Y-star-gov/compare/v0.46.0...v0.47.0
[0.46.0]: https://github.com/liuhaotian2024-prog/Y-star-gov/compare/v0.45.0...v0.46.0
[0.45.0]: https://github.com/liuhaotian2024-prog/Y-star-gov/compare/v0.44.0...v0.45.0
[0.44.0]: https://github.com/liuhaotian2024-prog/Y-star-gov/compare/v0.43.0...v0.44.0
[0.43.0]: https://github.com/liuhaotian2024-prog/Y-star-gov/compare/v0.42.0...v0.43.0
[0.42.0]: https://github.com/liuhaotian2024-prog/Y-star-gov/compare/v0.41.0...v0.42.0
[0.41.0]: https://github.com/liuhaotian2024-prog/Y-star-gov/releases/tag/v0.41.0
