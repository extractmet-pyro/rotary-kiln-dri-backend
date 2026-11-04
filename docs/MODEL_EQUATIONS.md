# MODEL_EQUATIONS - Rotary-kiln DRI digital twin (rk-dri-physics 1.0.0)

Coordinate: z = 0 at the solids feed end, z = L at the discharge end. Solids move +z, freeboard gas moves -z
(counter-current). SI internally (kmol, kg, m, s, K, Pa, J). Normal volume: 0 C, 101.325 kPa (configurable).

## 1. Species, atom matrix and reactions
Solids (kmol; pseudo-species in kg): Fe2O3, Fe3O4, FeO, Fe, GANGUE*, C (char), VM*, ASH*, H2O(l), CaCO3, MgCO3, CaO, MgO,
S (organic), FeS, CaS. Gases (kmol): CO, CO2, H2, H2O, O2, N2, CH4, H2S, SO2. Elements: Fe O C H N S Ca Mg Si Al Ti P.
`*` pseudo-species carry assay-specific element vectors and enthalpy, so the element matrix stays exact.

| id | reaction | where |
|---|---|---|
| R01-R03 | 3Fe2O3+CO->2Fe3O4+CO2; Fe3O4+CO->3FeO+CO2; FeO+CO<->Fe+CO2 | bed (pellet) |
| R04-R06 | same with H2 -> H2O | bed |
| R07 | C + CO2 <-> 2CO (Boudouard) | bed |
| R08 | C + H2O <-> CO + H2 | bed |
| R09 | CO + H2O <-> CO2 + H2 (WGS, 50 % approach per cell) | freeboard |
| R10/R11 | C + O2 -> CO2 ; 2C + O2 -> 2CO, split by Arthur (1951) CO/CO2 = 2500 exp(-6240/T) | bed surface |
| R12-R14, R22 | CO, H2, CH4, H2S combustion (mixing-limited, efficiency eta_mix per cell) | freeboard |
| R15 | H2O(l) -> H2O(g) | bed |
| R16 | VM -> CO, CO2, H2, H2O, CH4, N2 + soot C (element-exact yields from ultimate analysis) | bed |
| R17/R18 | CaCO3 -> CaO + CO2 ; MgCO3 -> MgO + CO2 (driving force 1 - pCO2/Peq) | bed |
| R19-R21 | S + H2 -> H2S ; CaO + H2S -> CaS + H2O ; Fe + H2S -> FeS + H2 | bed |
| R23 | 2Fe + O2 -> 2FeO (re-oxidation at bed surface) | bed surface |

Stoichiometric matrix `nu` (23 x 25); `tests/physics/test_species_reactions.py` asserts `nu . E = 0` for every row.

## 2. Thermochemistry
Cp(T) = a + bT + c/T^2 (Maier-Kelley, up to two segments). Absolute enthalpy h_i(T) = dHf_i(298) + integral Cp dT, entropy
s_i(T) = S_i(298) + integral Cp/T dT, K(T) = exp(-sum nu_i g_i / RT). Reaction heat is never added separately: every
balance uses absolute (formation-inclusive) enthalpies, so reaction heat appears exactly once.
VM formation enthalpy is back-calculated from the coal NCV:  m_VM hf_VM = H(products of complete combustion) + NCV - m_w hf(H2O,l).
The O->CO split of volatile oxygen is chosen so devolatilisation is near-thermoneutral (+0.3 MJ/kg VM); an NCV that deviates
>7 % from Dulong, or |dH_devol| > 1.5 MJ/kg, raises a warning.
Kinetic driving forces for Fe-O equilibria use log10 K = A/T + B fits (Bogdandy & Engell type; FeO/Fe: 688/T - 0.90;
Fe3O4/FeO: -1834/T + 2.17; H2 analogues) cross-checked against the internal database (|dX| < 0.12, tested).

## 3. Solids transport (Kramers-Croockewit / Saeman)
Face volumetric flow  Q = (4 pi n R^3 / 3) X^(3/2) [ tan(alpha)/sin(beta) - (dh/dz)/tan(beta) ],  X = 2h/R - (h/R)^2,
with h from the local bed volume V_j = sum_i v_i n_ij (pellet volume via Fe atoms and bulk density; coal/char/ash with 0.85
interstitial factor). Outlet boundary h(L) = dam height. Explicit upwind sub-cycling with dt_sub <= 0.35 dz^2 / D_eff.
Cross-check: Sullivan (1927) empirical residence time. RTD: open-open axial dispersion E(t) for lab-cohort alignment.

## 4. Bed chemistry per cell
* Interstitial CO/(CO+CO2) = X solved by bisection from the CO2 balance
  R_red(X) + S_CO2 + G_ex(1-X_fb) - R_B(X) - (1-X)(R_B + S_CO + S_CO2 + G_ex) = 0 .
* H2/H2O pair equilibrated with X via WGS; H-pair fraction from lagged release.
* Pellet: three-interface shrinking core (Fe | FeO | Fe3O4 | Fe2O3), film k_f = Sh D/(2 r0), product-layer diffusion
  De = D_Fuller eps/tau (eps rises with oxygen removal), reversible first-order interfacial rates
  4 pi r_i^2 k_i (1 + 1/K_i)(C_i - C_eq,i). 4x4 tridiagonal system; affine in bulk concentration -> fast bisection.
* Boudouard: r = k_B(T) R_f (8/d)^0.5 n_C (pCO2 - pCO^2/K_B)/(1 + K_CO pCO); reverse branch damped.
* Fast first-order processes (drying, devolatilisation, calcination, S release) use backward Euler r = k n/(1 + k dt).
* Positivity limiter scales whole reaction extents (stoichiometry preserved) so no inventory or gas supply goes negative.

## 5. Energy balances
Bed (transient):  dH_s/dt = H_adv,in - H_adv,out + H_feed - sum(gas released) h_g(T_s) + sum(gas drawn) h_g(T_g)
+ Q_gs + Q_cw + Q_wb - H_dust ;  T_s from Newton inversion of H_s = sum n_i h_i(T_s).
Freeboard gas (quasi-steady, marched z = L -> 0):  sum F_out h(T_g) + sum F_drawn h(T_g) + Q_gs + Q_gw = H_in + H_air + sum F_rel h(T_s).
Wall: radial finite-volume conduction (refractory layers, k(T) = k0(1 + c(T - 298)), steel shell), backward Euler,
inner face gets the *exact* gas-side flux (affine wall response, solved jointly with the gas Newton) plus linearised
bed exchange; outer face: Churchill-Chu natural + Churchill-Bernstein forced convection + radiation.
Closures: Tscheng & Watkinson (1979) gas-bed/gas-wall convection; gray-gas emissivity 1 - exp(-kappa (pCO2+pH2O) L_m) with a
particle-cloud term; covered wall-bed penetration theory with gas-film contact resistance; exposed wall-bed radiation through
(1 - eps_g).

## 6. Steady and transient solvers
Steady state = pseudo-transient continuation of the same operator with wall heat capacity scaled (does not change the
steady solution) until max|dT/dt| (bed, gas, hot face) < tol and inventory drift < 1e-3 /h. Transient = true capacities,
dt = 60 s default, scheduled input changes. Both log mass, element and enthalpy in/out/accumulation every logged step.

## 7. Derived metallurgy and energy accounting
Fe_total = 2 MW_Fe/MW_Fe2O3 m_Fe2O3 + 3 MW_Fe/MW_Fe3O4 m_Fe3O4 + MW_Fe/MW_FeO m_FeO + m_Fe + Fe(FeS) (+ ash Fe, reported
separately); metallization = 100 m_Fe / Fe_total of the magnetic DRI stream (after cooler and separator, excluding
non-magnetic char/ash). Energy ledger: E_chem = sum n_i [h_i(298) - h_ref,i] with reference = fully oxidised elements;
closes exactly against the absolute-enthalpy balance because non-oxygen elements are conserved.

## 8. Off-gas train, cooler, separation
DSC capture; ABC trim air to target dry O2 with complete combustion of CO/H2/CH4/H2S/char dust and heat-loss fraction;
WHRB duty to exit-gas temperature, steam via enthalpy rise; ID-fan power from actual volume and pressure rise; cooler
exponential approach with UA and optional O2 ingress re-oxidation; magnetic separation misplacement fractions.

## 9. Accretion risk proxy (unvalidated)
risk = r_T (0.35 + 0.65 (0.4 r_FeO + 0.3 r_ash + 0.2 r_basicity + 0.1 r_dust)), r_T = logistic((T_contact - (IDT - 120))/35),
T_contact = (T_hot face + T_bed)/2. A risk index - not a ring thickness.

## 10. Reduced models
GP surrogate (ARD-RBF + white noise, logit metallization) trained on a 65-point Latin-hypercube DOE of converged physics
steady states; FOPDT step responses identified from physics step tests. Used by the EKF and MPC; fidelity reported with
every prediction (6-fold CV RMSE and local GP sigma).
