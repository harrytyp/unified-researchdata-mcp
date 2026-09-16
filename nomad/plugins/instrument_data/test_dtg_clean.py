"""Unit test for the DTG cleaning (processor.clean_dtg and friends).

The recipe is the contract: forward-backward EWMA with span 50, every point
further than ±0.01 from the smoothed curve dropped as noise, gaps interpolated
and filled. So the test pins the numbers rather than just "it returns
something":

  - the EWMA is compared against pandas' ewm(span=...).mean(), which is what
    the notebook uses - if the two ever drift apart, curves stop matching the
    older figures,
  - a spike above delta has to be *gone*, not merely damped,
  - everything below delta has to survive untouched,
  - the curve must stay continuous (no NaNs left) and keep its length.

No network, no NOMAD.
"""
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)                    # sibling modules (processor, schema)
sys.path.insert(0, os.path.dirname(_HERE))   # the instrument_data package itself

try:                                          # run from the plugins dir
    from instrument_data.processor import (  # noqa: E402
        DTG_DELTA,
        DTG_SPAN,
        _ewma,
        _ewma_forward_backward,
        _fill_gaps,
        clean_dtg,
        dtg_for_plot,
    )
except ImportError:                           # run from inside the package
    from processor import (  # type: ignore # noqa: E402
        DTG_DELTA,
        DTG_SPAN,
        _ewma,
        _ewma_forward_backward,
        _fill_gaps,
        clean_dtg,
        dtg_for_plot,
    )

FAILS = []


def check(label, cond, detail=''):
    if not cond:
        FAILS.append(label)
    print(f'  [{"OK  " if cond else "FAIL"}] {label}{" - " + str(detail) if detail else ""}')


print('=== EWMA stimmt mit pandas ueberein (die Vorlage nutzt .ewm) ===')
try:
    import pandas as pd

    rng = np.random.default_rng(7)
    sig = np.cumsum(rng.normal(size=400))
    for span in (10, DTG_SPAN, 80):
        mine = _ewma(sig, span)
        theirs = pd.Series(sig).ewm(span=span).mean().to_numpy()
        check(f'span={span}: identisch zu pandas',
              np.allclose(mine, theirs, rtol=1e-12, atol=1e-12),
              f'max diff {np.max(np.abs(mine - theirs)):.2e}')
except ImportError:
    print('  (pandas nicht da - Vergleich uebersprungen)')

check('konstante Kurve bleibt konstant',
      np.allclose(_ewma(np.full(50, 3.5), DTG_SPAN), 3.5))
fb = _ewma_forward_backward(sig, DTG_SPAN)
check('vorwaerts/rueckwaerts ist symmetrisch in der Zeit',
      np.allclose(fb, _ewma_forward_backward(sig[::-1], DTG_SPAN)[::-1], atol=1e-12))

print()
print('=== Ausreisser wird entfernt, nicht nur gedaempft ===')
# A DTG peak clearly WIDER than the smoothing window, with a threshold scaled
# to the signal (delta as a fraction of the peak). The absolute 0.01 from the
# notebook does not transfer to a curve of this amplitude - that is asserted
# separately below, so the limitation is documented instead of surprising.
n = 2000
temp = np.linspace(25.0, 800.0, n)
sig_peak = -10.0 * np.exp(-0.5 * ((temp - 400.0) / 120.0) ** 2) - 0.4 * np.exp(
    -0.5 * ((temp - 650.0) / 150.0) ** 2)
scaled_delta = 0.05 * abs(np.min(sig_peak))          # 5% der Peaktiefe
dirty = sig_peak.copy()
spikes = [300, 301, 900, 1500, 1501, 1502]
dirty[spikes] = 6.0                                   # deutlich ueber delta
cleaned, smooth = clean_dtg(dirty, span=DTG_SPAN, delta=scaled_delta)
check('laenge bleibt erhalten', len(cleaned) == n, len(cleaned))
check('keine Luecken mehr', np.isfinite(cleaned).all())
check('Spitze ist weg', np.max(np.abs(cleaned - sig_peak)) < 1.0,
      f'max Abweichung {np.max(np.abs(cleaned - sig_peak)):.3f}')
check('Spitzenwert taucht nirgends mehr auf', np.max(cleaned) < 2.0, np.max(cleaned))
check('Spitze steckt auch nicht in der geglaetteten Kurve', np.max(smooth) < 2.0)
check('Hauptpeak bleibt erhalten (Tiefe)',
      abs(np.min(cleaned) - np.min(sig_peak)) < 0.5,
      f'min {np.min(cleaned):.2f} statt {np.min(sig_peak):.2f}')
check('Hauptpeak bleibt an der Stelle',
      abs(int(np.argmin(cleaned)) - int(np.argmin(sig_peak))) < 10,
      f'{int(np.argmin(cleaned))} statt {int(np.argmin(sig_peak))}')
check('Kurve bleibt nah an der Vorlage (keine Zersaegung)',
      np.mean(np.abs(cleaned - sig_peak)) < 0.2,
      f'Mittel {np.mean(np.abs(cleaned - sig_peak)):.3f}')

# Documented limitation: the notebook's absolute delta was tuned for its own
# signal scale. On a curve of amplitude 10 it flags the peak itself (the
# smoother attenuates it by more than 0.01), and interpolating over those
# blocks flattens the curve - measured on a real export too.
flat_delta_clean, _ = clean_dtg(dirty, span=DTG_SPAN, delta=DTG_DELTA)
check('absolutes delta=0.01 glaettet einen Peak dieser Groesse weg (bekannt)',
      np.min(flat_delta_clean) > 0.7 * np.min(sig_peak),
      f'min {np.min(flat_delta_clean):.2f} statt {np.min(sig_peak):.2f}')

print()
print('=== Rauschen unterhalb delta bleibt stehen ===')
flat = -2.0 - 0.5 * np.exp(-0.5 * ((temp - 400.0) / 200.0) ** 2)
noisy = flat + np.random.default_rng(11).normal(scale=0.002, size=n)
c2, _ = clean_dtg(noisy, span=DTG_SPAN, delta=0.05)
check('feines Rauschen (0.002 < delta) wird nicht als Ausreisser gewertet',
      np.max(np.abs(c2 - noisy)) < 0.05, f'{np.max(np.abs(c2 - noisy)):.4f}')
c3, _ = clean_dtg(noisy, span=DTG_SPAN, delta=0.0001)
check('kleineres delta greift haerter',
      np.sum(np.abs(c3 - noisy) > 1e-9) >= np.sum(np.abs(c2 - noisy) > 1e-9))

print()
print('=== Luecken fuellen (interpolieren + vorne/hinten auffuellen) ===')
gappy = np.array([np.nan, np.nan, 1.0, np.nan, np.nan, 5.0, np.nan, np.nan])
filled = _fill_gaps(gappy)
check('vorne aufgefuellt', filled[0] == 1.0 and filled[1] == 1.0, filled.tolist())
check('dazwischen linear interpoliert (1 -> 5 ueber 3 Schritte)',
      abs(filled[3] - (1.0 + 4.0 / 3.0)) < 1e-9 and abs(filled[4] - (1.0 + 8.0 / 3.0)) < 1e-9,
      filled.tolist())
check('hinten aufgefuellt', filled[-1] == 5.0 and filled[-2] == 5.0)

print()
print('=== Randfaelle ===')
check('None -> (None, None)', clean_dtg(None) == (None, None))
check('zu kurz -> (None, None)', clean_dtg([1.0, 2.0]) == (None, None))
check('alles NaN -> (None, None)',
      clean_dtg([np.nan] * 50)[0] is None)
allsame, _ = clean_dtg([2.0] * 30)
check('konstante Eingabe kommt unveraendert durch', np.allclose(allsame, 2.0))
with_nans = np.full(300, 1.0)
with_nans[50:60] = np.nan
fixed, _ = clean_dtg(with_nans)
check('Luecken in der Eingabe werden verkraftet', np.isfinite(fixed).all())

print()
print('=== Welche Kurve wird geplottet? ===')
temp = list(np.linspace(25, 600, 20))
check('eigene DTG-Spalte hat Vorrang',
      np.allclose(dtg_for_plot({'temperature': temp, 'dtg': [1.0] * 20,
                                'mass_pct': [50.0] * 20}), [1.0] * 20))
grad = dtg_for_plot({'temperature': temp, 'mass_pct': list(np.linspace(100, 40, 20))})
check('ohne DTG-Spalte wird die Masse abgeleitet',
      grad is not None and abs(grad[5] - (40 - 100) / (600 - 25)) < 0.01,
      None if grad is None else round(float(grad[5]), 4))
mg = dtg_for_plot({'temperature': temp, 'mass_mg': list(np.linspace(10, 4, 20))})
check('mg-Fallback wird auf Prozent normiert und abgeleitet', mg is not None)
check('nichts Brauchbares -> None', dtg_for_plot({'temperature': temp}) is None)
check('leere Signale -> None', dtg_for_plot({}) is None)

print()
print('ERGEBNIS:', 'ALLE DTG-CHECKS BESTANDEN' if not FAILS
      else f'{len(FAILS)} FEHLER: ' + '; '.join(FAILS))
sys.exit(1 if FAILS else 0)
