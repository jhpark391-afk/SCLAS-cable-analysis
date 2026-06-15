# Literature Notes for SCLAS

These notes translate the two reference papers into implementation decisions for
the SCLAS GUI/backend contract.

## Chang and Chen 2019

Paper: *Mechanical behavior of submarine cable under coupled tension, torsion
and compressive loads*, Ocean Engineering 189, 106272.

Useful points for this project:

- Submarine power cables under axial tension can generate torsion because the
  armour wires are helical. The reverse coupling also appears: torsion can
  induce axial force.
- Tensile stiffness and torsional stiffness should not be treated as isolated
  scalar quantities once coupled loads are present. A stiffness matrix or at
  least coupling indicators should be reported.
- External water pressure and compressive loads can substantially reduce
  stiffness. The paper reports that coupled tension, torsion, and compression
  can reduce tensile stiffness by about 30 percent in a deep-water case.
- Lay angle is a design variable: larger helix/lay angles tend to increase
  torsional stiffness while reducing tensile stiffness.
- Contact between adjacent layers should block penetration while allowing
  relevant sliding. Penalty-type contact stiffness is a practical modelling
  parameter.

SCLAS implementation response:

- `analysis_conditions` includes twist, axial strain, hydrostatic pressure, and
  radial compression ratio.
- `result_summary.json` includes an axial-torsional stiffness matrix proxy.
- `study_scope` exposes torsion, tension-bending coupling, compression, and
  pressure-effect assessments as first-class backend requests.

## Menard and Cartraud 2023

Paper: *A computationally efficient finite element model for the analysis of the
non-linear bending behaviour of a dynamic submarine power cable*, Marine
Structures 91, 103465.

Useful points for this project:

- The bending response is governed by contact, friction, residual/initial
  pressure, and stick-slip transition between internal cable components.
- For small curvature, cable components tend to remain in a stick regime with
  high bending stiffness. As curvature grows, slip propagates and the response
  approaches a lower slip-zone stiffness.
- A periodic homogenized cell can reduce the 3D computational domain to a
  helical period while preserving the relevant contact interactions.
- Armour wires can be represented efficiently with beam elements and contact
  surface elements. This is a practical compromise between model size and local
  contact fidelity.
- Friction coefficient and residual contact pressure are calibration parameters.
  Recommended calibration targets are slip-zone bending stiffness and dissipated
  energy during the hysteresis cycle.
- Regularized Coulomb contact is helpful for convergence; the paper uses a small
  regularization fraction for the stick-slip transition.

SCLAS implementation response:

- `mesh.model_strategy` defaults to `periodic_homogenized_cell`.
- `mesh.armour_model` defaults to `beam_with_contact_surface`.
- `analysis_conditions.residual_contact_pressure_mpa` and
  `analysis_conditions.contact_regularization_beta` are passed to the backend.
- The placeholder backend reports stick/slip stiffness proxies, contact
  regularization, dissipated-energy calibration targets, and pressure/compression
  softening factors.

## Backend development priority

1. Preserve the current GUI contract: `result_data.csv` remains the bending
   moment-curvature loop.
2. Implement a real Abaqus bending case with periodic boundary conditions.
3. Calibrate friction and residual contact pressure against measured or
   reference hysteresis loops.
4. Add axial/torsion coupled load cases and report a stiffness matrix.
5. Add pressure/compression sweeps and bird-caging risk indicators.
6. Add local stress and displacement extraction for fatigue-oriented reporting.
