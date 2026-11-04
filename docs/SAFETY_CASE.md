# SAFETY_CASE - analytic system boundary and HAZOP-style review list

**Default: SAFE_ADVISORY_ONLY.** The software has no actuator write path; it is not an SIS, BMS, alarm system or ESD.
Browser -> Render API is simulation/recommendation only. A future supervisory link requires a separate on-premises gateway
(unit conversion, action whitelist, fresh-data check, interlock/permit checks, rate bounds, two-person confirmation, logging),
management of change, independent fail-safe design and plant authority sign-off. Manual emergency exit of any trial must be
independent of model code. PLC/DCS keep local control and SIS/BMS protection. No public OPC UA server or internet-reachable PLC.

| Hazard | Causes | Early symptoms | Existing protection (verify) | Twin diagnosis | Operator advice | Permissive / safe degradation |
|---|---|---|---|---|---|---|
| CO release / duct leak | seal failure, draft loss | ambient CO, draft rise | CO detectors, permits | exit CO vs model, draft alert | restore draft, evacuate per SOP | no recommendation while draft abnormal |
| Overpressure / ID-fan loss | fan trip, blockage | positive draft | fan interlocks, emergency stack | draft deviation | trip SOP | MPC blocked (invalid data) |
| Over-temperature / hotspot | excess air, refractory loss | shell hotspot, TC rise | scanner alarms | shell vs model | reduce local air, inspect | thermal soft constraints |
| Accretion / ring | high T, low-fusion ash, FeO | shell cooling, torque | inspection | risk proxy + ML-C | adjust T/air, plan cleaning | risk term |
| Coal fire / dust explosion | hot coal, dust | CO in bins | inerting, detectors | not modelled | SOP | n/a |
| Air ingress / re-oxidation | seal wear | O2 high, cooler T high | seals, cooler interlocks | O2/N2 balance, cooler model | repair, cool | gate on cooler data |
| Moisture excursion / fines | rain, poor pellets | exit T drop | raw-material QA | DV input | adjust feed/air | feed-forward |
| Stale/malicious sensor, crash | comms, cyber | frozen data, NIS fail | DCS alarms | quality flags, EKF NIS | local control | advisory alarm |

References (cite, do not claim certification): Ministry of Steel (India) Process-Based Safety Guidelines (2024, SG/32 coal-
based DRI); NIST SP 800-82 Rev. 3; OPC UA Part 2 Security; IEC 61511 / IEC 62443 (site programme).
