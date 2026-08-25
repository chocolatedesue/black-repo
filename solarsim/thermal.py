"""Array thermal state and the temperature dependence of harvested power.

The illumination model answers *how much sunlight falls on the array*.  This
module answers the question one step further in: *how much of that sunlight
becomes electrical energy*, which is not a constant, because a photovoltaic
cell's efficiency falls as it heats up and the array's temperature swings by
more than 100 K every revolution.

Three effects are modelled, none of which the constant-efficiency chain in
:mod:`solarsim.power` can represent:

**Cell temperature.**  A sunlit array in LEO settles near +55 to +80 C and cools
towards -80 C in eclipse.  Triple-junction cells lose roughly 0.25 % of their
maximum-power point per kelvin, so the difference between an array assumed to
sit at its 28 C rating and one that actually runs at 65 C is of order -9 % in
delivered power -- a bias comparable to the entire annual irradiance modulation,
and one that is systematically *optimistic* in the direction that matters.

**The thermal transient.**  The panel does not reach equilibrium instantly.  Its
areal heat capacity gives a radiative time constant of a few minutes, which is a
substantial fraction of both the eclipse and the sunlit arc, so the array is
still cold for a while after sunrise -- briefly *more* efficient than its rating
-- and still warm for a while after entering eclipse.  Assuming instantaneous
equilibrium overstates the loss; ignoring temperature altogether understates it.
Only integrating the transient gets both signs right.

**Albedo and Earth infrared.**  Listed as excluded in earlier versions of this
model.  They contribute no useful photocurrent worth counting for a sun-tracking
array, but they are a genuine part of the *thermal* input, and leaving them out
biases the panel temperature low and therefore the efficiency high.  Including
them is what makes the temperature estimate defensible rather than indicative.

The convention throughout is *per unit array area*, so nothing here depends on
how big the array is.

References
----------
Gilmore, *Spacecraft Thermal Control Handbook*, Vol. I, Ch. 2 (environments)
and Ch. 3 (radiative balance).  ECSS-E-ST-10-04C for the albedo and outgoing
longwave radiation values.  Rauschenbach, *Solar Cell Array Design Handbook*,
Ch. 3, for the cell temperature coefficients.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .constants import (
    ALBEDO_MEAN,
    EARTH_IR_MEAN,
    R_EARTH,
    SOLAR_CONSTANT,
    STEFAN_BOLTZMANN,
)

ABS_ZERO_C = -273.15


# ---------------------------------------------------------------------------
# Earth as a radiation source
# ---------------------------------------------------------------------------
def earth_view_factor(r_km) -> np.ndarray:
    """Fraction of a nadir-facing flat plate's hemisphere filled by Earth.

    For a flat plate at geocentric distance ``r`` facing the centre of a sphere
    of radius ``R``, the diffuse view factor is exactly

        F = (R / r)^2

    which is the standard result for a small plate and a sphere it does not
    intersect (Gilmore Vol. I, Ch. 3).  At 550 km this is 0.848: Earth fills
    most of the downward hemisphere, which is why the infrared term is not
    negligible even though its flux density is modest.
    """
    r = np.asarray(r_km, dtype=float)
    return (R_EARTH / r) ** 2


def earth_fluxes(r_sat, r_sun, albedo: float = ALBEDO_MEAN,
                 earth_ir: float = EARTH_IR_MEAN):
    """Albedo and infrared irradiance at the spacecraft, for a nadir-facing plate.

    Returns ``(q_albedo, q_ir)`` in W/m^2.

    The infrared term is isotropic to good approximation and simply scales with
    the view factor.  The albedo term additionally requires the sub-satellite
    region to be *lit*: it is proportional to the cosine of the solar zenith
    angle at the sub-satellite point, and vanishes on the night side.  Using
    ``cos zeta`` rather than a more elaborate integral over the visible cap is
    the usual engineering treatment; it is accurate near the sub-solar point and
    conservative near the terminator, where the true value carries a limb
    contribution this form drops.

    Both terms are then attenuated by the plate's actual orientation at the call
    site -- what is returned here is the flux available to a surface pointed
    straight down, i.e. the geometric maximum.
    """
    r_sat = np.asarray(r_sat, dtype=float)
    r_sun = np.asarray(r_sun, dtype=float)

    r_mag = np.linalg.norm(r_sat, axis=-1)
    n_hat = r_sat / r_mag[..., None]                       # zenith at the sub-sat point
    s_hat = r_sun / np.linalg.norm(r_sun, axis=-1, keepdims=True)

    f = earth_view_factor(r_mag)
    cos_zeta = np.clip(np.sum(n_hat * s_hat, axis=-1), 0.0, 1.0)

    q_albedo = albedo * SOLAR_CONSTANT * f * cos_zeta
    q_ir = earth_ir * f
    return q_albedo, q_ir


# ---------------------------------------------------------------------------
# The panel
# ---------------------------------------------------------------------------
@dataclass
class ThermalPanel:
    """Optical and thermal properties of one square metre of solar array.

    Defaults describe a rigid honeycomb panel populated with coverglassed
    triple-junction cells -- the same platform the rest of the model assumes.

    ``alpha_solar`` is deliberately high and ``eps_front`` only moderate: a
    solar array is built to *absorb* sunlight, so it is a poor radiator relative
    to what it takes in, and it runs hot.  That is the physical reason the
    temperature correction below is a loss rather than a wash.
    """

    alpha_solar: float = 0.92        # solar absorptance, coverglassed cell face
    eps_front: float = 0.85          # infrared emittance, cell face
    eps_back: float = 0.80           # infrared emittance, rear face (Kapton/black)
    heat_capacity_j_m2k: float = 2700.0
    # ^ areal heat capacity: ~3 kg/m^2 of face sheet, honeycomb core, adhesive
    #   and cells at a mass-weighted c_p near 900 J/(kg K).  It sets the thermal
    #   time constant, which is what the transient result is sensitive to; the
    #   equilibrium temperatures do not depend on it at all.

    def radiative_time_constant_s(self, t_kelvin: float = 300.0) -> float:
        """Linearised time constant C / (4 eps_tot sigma T^3) at ``t_kelvin``.

        Around 300 K this is a few minutes.  Compared against an eclipse of tens
        of minutes it means the panel very nearly reaches its cold equilibrium
        before sunrise, but the warm-up after sunrise occupies a visible slice of
        the sunlit arc.
        """
        eps_tot = self.eps_front + self.eps_back
        return self.heat_capacity_j_m2k / (
            4.0 * eps_tot * STEFAN_BOLTZMANN * t_kelvin**3
        )

    def equilibrium_temperature_k(self, q_absorbed_w_m2, p_elec_w_m2=0.0):
        """Steady-state temperature for a given absorbed flux, in kelvin.

        Solves ``q_absorbed - p_elec = (eps_front + eps_back) sigma T^4``.  The
        electrical power leaves the panel as electricity rather than as heat, so
        a panel held at its maximum-power point is genuinely cooler than the same
        panel open-circuit -- a few kelvin at these efficiencies, included
        because it is free to include and moves the answer the *helpful* way.
        """
        eps_tot = self.eps_front + self.eps_back
        net = np.maximum(np.asarray(q_absorbed_w_m2, dtype=float)
                         - np.asarray(p_elec_w_m2, dtype=float), 0.0)
        return (net / (eps_tot * STEFAN_BOLTZMANN)) ** 0.25


@dataclass
class CellThermalResponse:
    """Temperature dependence of the maximum-power point.

    ``eta(T) = eta_ref * (1 + temp_coeff_per_k * (T - T_ref))``

    The linear form is accurate over the range a LEO array actually occupies;
    the underlying physics is the band-gap narrowing that drives ``V_oc`` down
    roughly linearly, partly offset by a small rise in ``J_sc``.

    ``temp_coeff_per_k`` is the *relative* maximum-power coefficient.  For
    qualified InGaP/GaAs/Ge triple-junction space cells it follows from the
    published gradients at AM0 and 28 C -- ``dV_mp/dT`` near -6.7 mV/K against a
    ``V_mp`` near 2.41 V, and ``dJ_mp/dT`` near +5.6 uA/cm^2/K against a
    ``J_mp`` near 16.3 mA/cm^2 -- giving

        (1/P) dP/dT = (1/V_mp) dV_mp/dT + (1/J_mp) dJ_mp/dT
                    = -0.278 %/K + 0.034 %/K  ~  -0.244 %/K

    so -0.0025 /K is used as the nominal.  The exact figure is vendor- and
    lot-specific and cells differ by a few hundredths of a percent per kelvin,
    which is why :mod:`experiments.run_energy` sweeps it rather than resting the
    conclusion on one value.  Note the sign convention: the coefficient is
    negative, so ``eta`` rises below ``t_ref_c`` and falls above it.
    """

    eta_ref: float = 0.30
    t_ref_c: float = 28.0            # AM0 rating temperature for space cells
    temp_coeff_per_k: float = -0.0025

    def efficiency_at(self, t_kelvin):
        """Cell efficiency at absolute temperature ``t_kelvin``.

        Clipped at zero: the linear extrapolation would go negative somewhere
        above 400 C, far outside any temperature an array survives, but the clip
        keeps a sweep over pathological coefficients well defined.

        The linear form is fitted over the range a datasheet characterises,
        roughly -50 to +100 C.  A LEO array in eclipse goes colder than that, and
        the model duly predicts an efficiency *above* the rating for the first
        minutes after sunrise.  The direction is right and the effect is real --
        post-eclipse power peaks are well documented -- but the magnitude is an
        extrapolation, and a real maximum-power tracker may not follow the array
        through it.  It contributes little to the integral, since it lasts a few
        minutes out of every revolution; the loss at high temperature, which
        lasts most of the sunlit arc, is what dominates.
        """
        t_c = np.asarray(t_kelvin, dtype=float) + ABS_ZERO_C
        return np.maximum(
            self.eta_ref * (1.0 + self.temp_coeff_per_k * (t_c - self.t_ref_c)),
            0.0,
        )

    def derate_at(self, t_kelvin):
        """Efficiency relative to the rating, ``eta(T) / eta_ref``.

        This is the factor that multiplies every generation figure the
        constant-efficiency model produces, which makes it the single number to
        quote when reporting what the correction costs.
        """
        return self.efficiency_at(t_kelvin) / self.eta_ref


# ---------------------------------------------------------------------------
# Transient integration
# ---------------------------------------------------------------------------
def panel_temperature(
    t_s,
    q_solar_w_m2,
    q_albedo_w_m2,
    q_ir_w_m2,
    panel: ThermalPanel | None = None,
    cell: CellThermalResponse | None = None,
    t_init_k: float | None = None,
    n_spinup: int = 2,
    extraction_factor: float = 1.0,
):
    """Integrate the panel's lumped-node temperature along a trace.

    The node balance, per unit area, is

        C dT/dt = alpha_s (q_solar + q_albedo) + eps_front q_ir
                  - (eps_front + eps_back) sigma T^4
                  - P_elec

    Solar and albedo are absorbed with the *solar* absorptance; Earth infrared
    arrives in the thermal band and is absorbed with the infrared emittance, by
    Kirchhoff's law.  ``P_elec`` is the power actually drawn off as electricity,
    which depends on the temperature being solved for -- the coupling is weak
    (a few kelvin) so it is evaluated at the previous step rather than iterated.

    ``extraction_factor`` scales the cell efficiency down to the fraction of the
    intercepted flux that actually leaves the panel as electricity: cells cover
    only ``f_pack`` of the substrate and deliver only ``f_deg`` of their
    beginning-of-life output, and the sunlight falling on the rest of the
    substrate is absorbed as heat like any other.  Leaving it at 1.0 credits the
    panel with removing more energy electrically than it really does, and so
    biases the temperature -- and therefore the efficiency -- optimistically.

    Integration uses the *exponential* update rather than plain forward Euler.
    Linearising the T^4 term about the current temperature gives a local
    relaxation towards an instantaneous equilibrium with a known time constant,
    and stepping that analytically is unconditionally stable.  It matters here:
    the radiative time constant is short compared with the eclipse boundary that
    a forward-Euler scheme would have to resolve, and a stable scheme lets the
    trace keep the 10 s slot spacing the scheduler wants instead of forcing a
    finer grid on the whole simulation.

    ``n_spinup`` passes over the trace carry the final temperature back to the
    start, so the result is the periodic steady state rather than a transient
    from an arbitrary initial guess.  Two passes are ample at a time constant of
    minutes against orbits of tens of minutes; the returned diagnostics report
    the residual drift so the assumption is checkable rather than assumed.

    Returns ``(t_kelvin, info)``.
    """
    panel = panel or ThermalPanel()
    cell = cell or CellThermalResponse()

    t_s = np.asarray(t_s, dtype=float)
    q_solar = np.asarray(q_solar_w_m2, dtype=float)
    q_albedo = np.asarray(q_albedo_w_m2, dtype=float)
    q_ir = np.asarray(q_ir_w_m2, dtype=float)

    eps_tot = panel.eps_front + panel.eps_back
    c_areal = panel.heat_capacity_j_m2k
    sigma = STEFAN_BOLTZMANN

    # Absorbed flux is fixed along the trace; only the emission and the
    # electrical extraction depend on the state.
    q_in = panel.alpha_solar * (q_solar + q_albedo) + panel.eps_front * q_ir

    n = t_s.size
    dt = np.diff(t_s, prepend=t_s[0] - (t_s[1] - t_s[0]) if n > 1 else 1.0)

    if t_init_k is None:
        # Start from the equilibrium of the mean absorbed flux: a sensible guess
        # that the spin-up passes then erase.
        t_init_k = float(panel.equilibrium_temperature_k(np.mean(q_in)))

    temperature = np.empty(n)
    t_cur = float(t_init_k)
    drift = float("nan")

    for sweep in range(max(1, n_spinup)):
        t_start = t_cur
        for k in range(n):
            # Electrical power drawn off at the previous temperature.
            p_elec = q_solar[k] * cell.efficiency_at(t_cur) * extraction_factor
            q_net_in = q_in[k] - p_elec

            # Linearise emission about t_cur:  sigma T^4 ~ sigma t_cur^4
            # + 4 sigma t_cur^3 (T - t_cur).  The balance then relaxes towards
            # t_eq with time constant tau, both of which are constant over the
            # step.
            h = 4.0 * eps_tot * sigma * t_cur**3          # W/(m^2 K)
            if h <= 0.0:                                   # pragma: no cover
                t_cur = max(t_cur, 1.0)
                temperature[k] = t_cur
                continue
            tau = c_areal / h
            t_eq = t_cur + (q_net_in - eps_tot * sigma * t_cur**4) / h
            decay = np.exp(-dt[k] / tau)
            t_cur = t_eq + (t_cur - t_eq) * decay
            t_cur = max(t_cur, 3.0)                        # keep it physical
            temperature[k] = t_cur
        drift = abs(t_cur - t_start)

    info = {
        "t_min_c": float(np.min(temperature) + ABS_ZERO_C),
        "t_max_c": float(np.max(temperature) + ABS_ZERO_C),
        "t_mean_c": float(np.mean(temperature) + ABS_ZERO_C),
        "t_sunlit_mean_c": (
            float(np.mean(temperature[q_solar > 0.0]) + ABS_ZERO_C)
            if np.any(q_solar > 0.0) else None
        ),
        "spinup_drift_k": float(drift),
        "time_constant_s": panel.radiative_time_constant_s(float(np.mean(temperature))),
        "n_spinup": int(max(1, n_spinup)),
    }
    return temperature, info
