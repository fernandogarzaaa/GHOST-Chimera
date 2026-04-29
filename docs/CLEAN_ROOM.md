# Clean-Room Implementation Notes

Chimera Pilot generalizes public resource-orchestration concepts into a local-first AI/tool/runtime scheduler. It is not a clone or fork of any proprietary quantum operating system.

## Allowed inputs

The implementation may use:

- public product pages;
- public research papers;
- public SDK documentation;
- open-source repositories with compatible licenses;
- independently written architecture notes.

## Disallowed inputs

The implementation must not use:

- proprietary source code;
- decompiled binaries;
- private endpoints;
- licensed internal files;
- copied UI text/assets;
- copied implementation details from non-open-source systems.

## Abstraction mapping

| Public orchestration concept | Ghost Chimera implementation |
|---|---|
| resource scheduler | `ChimeraScheduler` |
| backend capability map | `BackendCapabilities` |
| calibration/health probing | `ChimeraCalibrator` and `CalibrationStore` |
| task lifecycle | `TaskSpec`, `PilotExecution`, telemetry events |
| hybrid runtime orchestration | backend protocol plus fallback executor |
| fidelity/reliability scoring | reliability, latency, cost, privacy, and context scoring |

## Design principle

The project extracts architecture patterns, not code. All code in this repository is written against Ghost Chimera's own task IR and backend interfaces.
