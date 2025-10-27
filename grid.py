import pandas as pd

# Wczytaj dane z pliku (np. "transactions.csv")
file_path = "transactions.csv"  # Podaj nazwę lub ścieżkę do pliku
transactions = pd.read_csv(file_path)

# Ruchy cenowe (scenariusze zmiany ceny futures, np. -10%, -5%, 0%, +5%, +10%)
price_moves = [-0.10, -0.05, 0, 0.05, 0.10]

# Lista na wyniki
all_results = []

# Obliczenia dla każdej transakcji
for _, row in transactions.iterrows():
    transaction_id = row["transaction_id"]
    P0 = row["P0"]  # Początkowa cena futures
    Q = row["Q"]  # Ilość towaru (np. liczba ton CO2)
    fixed_payment = row["fixed_payment"]  # Stała płatność gotówkowa
    
    # Przetwarzanie każdego scenariusza dla danej transakcji
    for move in price_moves:
        # Nowa cena futures (scenariusz)
        P_new = P0 * (1 + move)
        
        # Wartość nogi towarowej (PnL nogi futures)
        futures_pnl = Q * (P_new - P0)
        
        # Wartość nogi gotówkowej (stała)
        cash_pnl = -fixed_payment
        
        # Łączny PnL dla scenariusza
        total_pnl = futures_pnl + cash_pnl
        
        # Zapis wyników dla danego scenariusza i transakcji
        all_results.append({
            "Transaction ID": transaction_id,
            "Price Move (%)": move * 100,
            "Initial Futures Price": P0,
            "New Futures Price": P_new,
            "Futures Leg PnL": futures_pnl,
            "Cash Leg PnL": cash_pnl,
            "Total PnL": total_pnl
        })

# Konwersja wyników do DataFrame
results_df = pd.DataFrame(all_results)

# Obliczenie Initial Margin dla każdej transakcji
results_df["Initial Margin"] = results_df.groupby("Transaction ID")["Total PnL"].transform(lambda x: abs(x.min()))

# Wyświetlenie wyników
import ace_tools as tools; tools.display_dataframe_to_user(name="IM Calculation for All Transactions", dataframe=results_df)

# Zapis wyników do pliku (opcjonalnie)
results_df.to_csv("im_results.csv", index=False)











import pandas as pd
import os

# ====== PARAMETRY ======

file_path = "twoj_plik.xlsx"

# Grupy
G4 = ["EUR", "USD", "GBP", "JPY"]
Other_G10 = ["AUD", "CAD", "NZD", "NOK", "SEK", "CHF"]
Other_non_G10 = ["BRL", "CNY", "DKK", "HKD", "KRW", "MXN", "RUB", "SGD", "TRY", "ZAR"]

# Twoja finalna quote_priority (na podstawie zdjęcia, ograniczona do tych walut)
quote_priority = [
    "EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF",
    "NOK", "SEK", "DKK", "CNY", "HKD", "RUB",
    "TRY", "MXN", "JPY", "SGD", "ZAR"
]

# ====== KWOTOWANIE ======

def sort_currency_pair(a, b):
    if quote_priority.index(a) < quote_priority.index(b):
        return f"{a}/{b}"
    else:
        return f"{b}/{a}"

# ====== WYCZYTYWANIE SHEETÓW ======

xls = pd.ExcelFile(file_path)
sheet_names = xls.sheet_names

# ====== INICJALIZACJA SUM ======

group_sums = {"G4": 0, "Other_G10": 0, "Other_non_G10": 0}

# ====== LOGIKA GRUPOWANIA PAR ======

def assign_group(ccy1, ccy2):
    if ccy1 in G4 and ccy2 in G4:
        return "G4"
    elif (ccy1 in Other_G10 and ccy2 in Other_G10) or \
         (ccy1 in Other_G10 and ccy2 in G4) or \
         (ccy1 in G4 and ccy2 in Other_G10):
        return "Other_G10"
    elif (ccy1 in Other_non_G10 and (ccy2 in G4 or ccy2 in Other_G10)) or \
         (ccy2 in Other_non_G10 and (ccy1 in G4 or ccy1 in Other_G10)):
        return "Other_non_G10"
    else:
        return None

# ====== PRZETWARZANIE SHEETÓW ======

for base_ccy in sheet_names:
    df = pd.read_excel(file_path, sheet_name=base_ccy)
    cols = [col for col in df.columns if col not in ["others", "residuals"]]

    for col in cols:
        if base_ccy == col:
            continue  # pomijamy pary do samej siebie

        # Łączna wartość transakcji tej pary
        val = df[col].sum()
        if val == 0:
            continue

        # Przypisujemy do grupy
        group = assign_group(base_ccy, col)
        if group:
            group_sums[group] += val

# ====== PODSUMOWANIE ======

print("✅ Podsumowanie per grupa (na podstawie PAR):")
for group, val in group_sums.items():
    print(f"{group}: {val}")

# ====== ZAPIS DO EXCELA (opcjonalnie) ======

summary_df = pd.DataFrame(list(group_sums.items()), columns=["Group", "Total"])

with pd.ExcelWriter("podsumowanie_par.xlsx") as writer:
    summary_df.to_excel(writer, sheet_name="Group_Summary", index=False)

print("\n✅ Plik 'podsumowanie_par.xlsx' został utworzony!")









########

# Newton-Raphson fit of a SOFR OIS discount curve (global solve)
# Parametryzacja: x_j = ln P(tau_j) w węzłach tau_j; ln P(t) interpolujemy liniowo (log-linear).
# Instrumenty: par OIS quotes (upraszczamy harmonogram stałej nogi: dla T<=1Y jeden kupon, dla T>1Y rocznie).
# Autor: you + ChatGPT

import math
import numpy as np
from typing import List, Tuple, Dict

# ------------------------------
# 1) PRZYKŁADOWE KWOTOWANIA OIS
# ------------------------------
# T w latach, S w ułamku (np. 0.052 = 5.2%)
ois_quotes: List[Tuple[float, float]] = [
    (0.25, 0.0520),  # 3M
    (0.50, 0.0510),  # 6M
    (1.00, 0.0500),  # 1Y
    (2.00, 0.0475),  # 2Y
    (3.00, 0.0450),  # 3Y
]

# ------------------------------
# 2) HARMONOGRAM STAŁEJ NOGI
# ------------------------------
def build_fixed_leg_schedule(T: float) -> List[Tuple[float, float]]:
    """
    Zwraca listę (t_i, alpha_i) dla stałej nogi OIS.
    Reguła: jeśli T<=1Y -> pojedyncza płatność na końcu (alpha=T),
            jeśli T>1Y -> kupony roczne do T (alpha = długość okresu w latach).
    """
    if T <= 1.0 + 1e-12:
        return [(T, T)]
    out: List[Tuple[float, float]] = []
    t_prev = 0.0
    t = 1.0
    while t < T - 1e-12:
        out.append((t, t - t_prev))  # zwykle 1.0
        t_prev, t = t, t + 1.0
    out.append((T, T - t_prev))     # finał (zwykle 1.0)
    return out

# Zbuduj strukturę instrumentów (zapadalność, stawka, schedule)
instruments = []
for T, S in ois_quotes:
    instruments.append({"T": T, "S": S, "sched": build_fixed_leg_schedule(T)})

# ------------------------------
# 3) PARAMETRYZACJA KRZYWEJ
# ------------------------------
# Węzły = wszystkie daty płatności + zapadalności + 0.0
knot_times = sorted({0.0} | {T for T, _ in ois_quotes} | {t for T, _ in ois_quotes for (t, _) in build_fixed_leg_schedule(T)})

def weights_loglinear(t: float, knots: List[float]) -> np.ndarray:
    """
    Wagi w(tau) dla ln P(t) = sum_j w_j(t) * x_j (log-linear).
    Poza zakresem węzłów — ekstrapolacja liniowa na ostatnim segmencie.
    """
    K = len(knots)
    w = np.zeros(K)
    if t <= knots[0] + 1e-14:
        w[0] = 1.0
        return w
    if t >= knots[-1] - 1e-14:
        j0, j1 = K-2, K-1
        tau0, tau1 = knots[j0], knots[j1]
        lam = (t - tau0) / (tau1 - tau0) if tau1 > tau0 else 0.0
        w[j0] = 1.0 - lam
        w[j1] = lam
        return w
    # znajdź segment [k,k+1]
    k = max(i for i in range(K-1) if knots[i] <= t)
    k = min(k, K-2)
    tau0, tau1 = knots[k], knots[k+1]
    lam = (t - tau0) / (tau1 - tau0) if tau1 > tau0 else 0.0
    w[k] = 1.0 - lam
    w[k+1] = lam
    return w

def P_from_x(t: float, knots: List[float], x_all: np.ndarray) -> float:
    """DF P(t) z wektora x (x_j = ln P w węzłach), przy ln P(t) = w(t)^T x."""
    w = weights_loglinear(t, knots)
    return math.exp(float(np.dot(w, x_all)))

# ------------------------------
# 4) RESIDUA I JACOBIAN
# ------------------------------
# x_all: wektor ln P w węzłach; wymuszamy x(0)=ln P(0)=0, więc optymalizujemy tylko po węzłach od indeksu 1..K-1.
def residuals_and_jacobian(x_var: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    Zwraca (r, J) dla układu:
      r_k = S_k * sum_i alpha_i * P(t_i) + P(T_k) - 1 = 0
    Pochodna: dP/dx_j = P(t) * w_j(t).
    """
    # zbuduj pełny wektor x (x0=0)
    x_all = np.zeros(len(knot_times))
    x_all[1:] = x_var

    r_list = []
    J = np.zeros((len(instruments), len(x_var)))

    for k, inst in enumerate(instruments):
        T, S, sched = inst["T"], inst["S"], inst["sched"]
        P_T = P_from_x(T, knot_times, x_all)

        # suma stałej nogi
        sum_fixed = 0.0
        grad = np.zeros(len(x_var))  # d r_k / d x_var

        for (t_i, alpha_i) in sched:
            P_ti = P_from_x(t_i, knot_times, x_all)
            sum_fixed += alpha_i * P_ti
            w_all = weights_loglinear(t_i, knot_times)
            grad += S * alpha_i * P_ti * w_all[1:]  # bez węzła 0

        # residual
        r_k = S * sum_fixed + P_T - 1.0
        r_list.append(r_k)

        # d/dx P(T)
        w_T_all = weights_loglinear(T, knot_times)
        grad += P_T * w_T_all[1:]
        J[k, :] = grad

    return np.array(r_list), J

# ------------------------------
# 5) NEWTON-RAPHSON Z TŁUMIENIEM
# ------------------------------
def newton_solve(x0: np.ndarray, max_iter: int = 50, tol: float = 1e-12, damping: float = 1.0):
    """
    Klasyczny Newton na układ r(x)=0:
      J(x) dx = -r(x), x <- x + lambda*dx (z backtrackingiem).
    Rozwiązanie rzutowane least-squares (np.linalg.lstsq) na wypadek niekwadratowych/źle uwarunkowanych J.
    """
    x = x0.copy()
    r, J = residuals_and_jacobian(x)
    norm0 = np.linalg.norm(r)

    for it in range(1, max_iter + 1):
        dx, *_ = np.linalg.lstsq(J, -r, rcond=None)
        lam = damping
        base = np.linalg.norm(r)
        improved = False
        for _ in range(20):
            x_try = x + lam * dx
            r_try, _ = residuals_and_jacobian(x_try)
            if np.linalg.norm(r_try) < base:
                x = x_try
                r = r_try
                improved = True
                break
            lam *= 0.5
        if not improved:
            x = x + dx  # jeśli line-search nie pomógł, bierz pełen krok

        r, J = residuals_and_jacobian(x)
        if np.linalg.norm(r) < tol * max(1.0, norm0):
            break

    return x, r, J

# ------------------------------
# 6) INICJALIZACJA I ROZWIĄZANIE
# ------------------------------
# Płaska stopa startowa: r0 = średnia z kwotowań
avg_rate = np.mean([S for _, S in ois_quotes])
x0_var = np.array([-avg_rate * t for t in knot_times[1:]])  # ln P(t) ~ -r0*t

x_opt, r_fin, J_fin = newton_solve(x0_var, max_iter=50, tol=1e-14, damping=1.0)

# Pełny wektor ln P z x0=0
x_all = np.zeros(len(knot_times))
x_all[1:] = x_opt
discount_factors: Dict[float, float] = {t: float(math.exp(x_all[i])) for i, t in enumerate(knot_times)}

# ------------------------------
# 7) WERYFIKACJA: PAR RATE Z MODELU
# ------------------------------
def par_rate_from_curve(T: float) -> float:
    sched = build_fixed_leg_schedule(T)
    P_T = P_from_x(T, knot_times, x_all)
    denom = sum(alpha * P_from_x(ti, knot_times, x_all) for (ti, alpha) in sched)
    return (1.0 - P_T) / denom

model_check = [(T, S, par_rate_from_curve(T)) for (T, S) in ois_quotes]

# ------------------------------
# 8) WYDRUK / CSV (opcjonalnie)
# ------------------------------
try:
    import pandas as pd
    df_curve = (
        pd.DataFrame(
            {"t_years": list(discount_factors.keys()),
             "P(t)": list(discount_factors.values())}
        )
        .sort_values("t_years")
        .assign(zero_rate_simple=lambda d: np.where(d["t_years"]>0,
                                                    -np.log(d["P(t)"]) / d["t_years"],
                                                    0.0))
    )

    df_quotes = pd.DataFrame(
        [{"T": T, "S_market": S, "S_model": Sm, "abs_error_bp": (Sm - S) * 1e4}
         for (T, S, Sm) in model_check]
    ).sort_values("T")

    # Druk
    print("\n== Discount curve (SOFR OIS; Newton fit) ==")
    print(df_curve.to_string(index=False, float_format=lambda v: f"{v:.8f}"))

    print("\n== Market vs Model OIS Par Rates ==")
    print(df_quotes.to_string(index=False, float_format=lambda v: f"{v:.6f}"))

    # Zapis CSV (odkomentuj jeśli chcesz)
    # df_curve.to_csv("sofr_ois_discount_curve.csv", index=False)
    # df_quotes.to_csv("sofr_ois_fit_check.csv", index=False)
except Exception as e:
    # Jeśli nie masz pandas, zrób prosty wydruk
    print("\n== Discount curve (SOFR OIS; Newton fit) ==")
    for t in sorted(discount_factors.keys()):
        P = discount_factors[t]
        zr = 0.0 if t == 0 else -math.log(P)/t
        print(f"t={t:>4.2f}  P(t)={P:.8f}  zero_rate={zr:.8f}")

    print("\n== Market vs Model OIS Par Rates ==")
    for (T, S, Sm) in model_check:
        print(f"T={T:>4.2f}  S_mkt={S:.6f}  S_mod={Sm:.6f}  err_bp={(Sm-S)*1e4:.3f}")

print("\nKnots (years):", knot_times)
print("Converged residual L2-norm:", float(np.linalg.norm(r_fin)))







#********#
# -*- coding: utf-8 -*-
"""
USD OIS (SOFR) — ON / 1W / 1M
Globalny fit krzywej dyskontowej (log-linear na DF) metodą Newtona–Raphsona,
z poprawnymi konwencjami:
  - Day Count: ACT/360 (dla kuponu)
  - Kalendarz: UnitedStates(FederalReserve)
  - Spot lag: 1 business day (T+1)
  - BDC: Following dla tenorów <= 1M, Modified Following > 1M
  - ON start = dziś; 1W/1M start = SPOT (T+1)
  - Residuum OIS (forward-start):  S * sum(alpha_i * P(t_i)) + P(T) - P(start) = 0
    (dla ON: P(start)=P(0)=1)

Skrypt:
  1) Wylicza start/end i alpha (ACT/360) z QuantLib
  2) Buduje węzły czasowe (0, t_start, t_end)
  3) Definiuje interpolację log-linear na DF (ln P(t) liniowy między węzłami)
  4) Rozwiązuje układ r(x)=0 Newtonem
  5) Drukuje wyniki i błąd dopasowania do stawek rynkowych

Autor: Ty + ChatGPT
"""

import math
import numpy as np
import QuantLib as ql

# ------------------------------------------------------------
# 0) PARAMETRY RYNKOWE (MOŻESZ PODMIENIĆ NA SWOJE)
# ------------------------------------------------------------
valuation_date = ql.Date(27, 10, 2025)  # "dzisiaj"
ql.Settings.instance().evaluationDate = valuation_date

# Przykładowe stawki rynkowe OIS (w UŁAMKU, nie w %!)
# PODMIEŃ NA SWOJE KWOTOWANIA.
quotes = {
    "ON": 0.05250,   # 5.250%
    "1W": 0.05200,   # 5.200%
    "1M": 0.05150,   # 5.150%
}

# ------------------------------------------------------------
# 1) KONWENCJE I FUNKCJE DATOWE
# ------------------------------------------------------------
cal = ql.UnitedStates(ql.UnitedStates.FederalReserve)  # kalendarz dla SOFR
dc_leg = ql.Actual360()          # day-count kuponu / α
dc_axis = ql.Actual365Fixed()    # "oś czasu" do wyznaczania t w latach (dowolny spójny DCC)
spot_lag = 1                     # USD OIS zwyczajowo T+1

def bdc_for(tenor: str) -> ql.BusinessDayConvention:
    """Following dla tenorów <= 1M, Modified Following dla dłuższych."""
    t = tenor.upper()
    return ql.Following if t in ("ON", "TN", "1W", "2W", "1M") else ql.ModifiedFollowing

def usd_ois_period(tenor: str):
    """
    Zwraca:
      tenor, alpha (ACT/360), t_start (lata), t_end (lata), start_date, end_date
    Zasady:
      - ON: start = dziś (adjust), end = +1d (adjust), BDC = Following
      - 1W/1M: start = SPOT (T+1, Following), end = start + tenor (BDC jak wyżej)
    """
    tenor = tenor.upper().strip()
    bdc = bdc_for(tenor)

    if tenor == "ON":
        start = cal.adjust(valuation_date, ql.Following)
        end   = cal.advance(start, 1, ql.Days, ql.Following)
    else:
        spot  = cal.advance(valuation_date, spot_lag, ql.Days, ql.Following)
        start = spot
        period = ql.Period(tenor)   # QuantLib rozpozna "1W", "1M", ...
        end   = cal.adjust(spot + period, bdc)

    alpha   = dc_leg.yearFraction(start, end)                    # ACT/360 dla kuponu
    t_start = dc_axis.yearFraction(valuation_date, start)        # czas do startu [lata]
    t_end   = dc_axis.yearFraction(valuation_date, end)          # czas do końca  [lata]
    return (tenor, float(alpha), float(t_start), float(t_end), start, end)

# Przygotuj listę instrumentów do dopasowania (ON, 1W, 1M)
tenors = ["ON", "1W", "1M"]
instruments = [usd_ois_period(t) for t in tenors]

# ------------------------------------------------------------
# 2) SIATKA WĘZŁÓW (KNOTS) I INTERPOLACJA LOG-LINEAR NA DF
# ------------------------------------------------------------
# Bierzemy 0.0 (dziś), wszystkie starty i końce, żeby DF w P(start) był "trafiony".
knot_times = {0.0}
for (_, _, t_s, t_e, _, _) in instruments:
    knot_times.add(t_s)
    knot_times.add(t_e)
knot_times = sorted(knot_times)

def weights_loglinear(t: float, knots: list[float]) -> np.ndarray:
    """
    Wagi do interpolacji ln P(t) liniowo między węzłami.
    Zwraca wektor w taki, że ln P(t) = w · x_all (x_all = ln P w węzłach).
    """
    K = len(knots)
    w = np.zeros(K)
    if t <= knots[0] + 1e-14:
        w[0] = 1.0
        return w
    if t >= knots[-1] - 1e-14:
        j0, j1 = K - 2, K - 1
        lam = (t - knots[j0]) / (knots[j1] - knots[j0])
        w[j0] = 1.0 - lam
        w[j1] = lam
        return w
    # t w środku: znajdź segment [k, k+1]
    k = max(i for i in range(K - 1) if knots[i] <= t)
    k = min(k, K - 2)
    lam = (t - knots[k]) / (knots[k + 1] - knots[k])
    w[k] = 1.0 - lam
    w[k + 1] = lam
    return w

def P_from_x(t: float, knots: list[float], x_all: np.ndarray) -> float:
    """Discount factor: P(t) = exp( w(t) · x ), gdzie x = ln P w węzłach."""
    return math.exp(float(np.dot(weights_loglinear(t, knots), x_all)))

# ------------------------------------------------------------
# 3) RESIDUA I JACOBIAN DLA OIS FORWARD-START
# ------------------------------------------------------------
# Dla ON/1W/1M używamy jednego kuponu stałej nogi (na końcu): sum(alpha_i P(t_i)) = alpha * P(T)
# Równanie fair value:
#     S * alpha * P(T) + P(T) - P(start) = 0
# gdzie S = par rate rynkowy, "start" = 0 (ON) albo spot (1W/1M).
def residuals_and_jacobian(x_var: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    x_var: ln P w węzłach od 1..K-1 (x0=0 => P(0)=1)
    Zwraca:
      r: wektor residuów dla instrumentów [ON, 1W, 1M]
      J: Jakobian (∂r/∂x_var)
    """
    # zbuduj pełny x (ln P) z x0=0
    x_all = np.zeros(len(knot_times))
    x_all[1:] = x_var

    r = np.zeros(len(instruments))
    J = np.zeros((len(instruments), len(x_var)))

    for k, (tenor, alpha, t_s, T, _, _) in enumerate(instruments):
        S = quotes[tenor]
        P_T = P_from_x(T, knot_times, x_all)
        P_s = P_from_x(t_s, knot_times, x_all)   # dla ON: t_s = 0.0 → P_s = 1.0

        # r_k = (S*alpha + 1) * P(T) - P(s)
        r[k] = (S * alpha + 1.0) * P_T - P_s

        # pochodne: d/dx [ (S*alpha + 1) P(T) - P(s) ]
        # dP/dx_j = P(t) * w_j(t)  (bo P = exp(w·x))
        w_T = weights_loglinear(T, knot_times)[1:]  # tylko zmienne (bez x0)
        w_s = weights_loglinear(t_s, knot_times)[1:]
        J[k, :] = (S * alpha + 1.0) * P_T * w_T - P_s * w_s

    return r, J

# ------------------------------------------------------------
# 4) NEWTON–RAPHSON (BEZPIECZNY, Z MAŁYM TŁUMIENIEM KROKU)
# ------------------------------------------------------------
def newton_solve(x0: np.ndarray, max_iter: int = 50, tol: float = 1e-14, damping: float = 1.0):
    """
    Rozwiązuje r(x)=0:
      J(x) * dx = -r(x),  x <- x + λ * dx,  λ=damping (opcjonalny)
    Używa least-squares na wypadek słabego uwarunkowania Jakobianu.
    """
    x = x0.copy()
    r, J = residuals_and_jacobian(x)
    norm0 = np.linalg.norm(r)

    for _ in range(max_iter):
        dx, *_ = np.linalg.lstsq(J, -r, rcond=None)

        # proste tłumienie (możesz zostawić λ=1.0 — krótkie instrumenty i tak zbiegną szybko)
        lam = damping
        x_try = x + lam * dx
        r_try, J_try = residuals_and_jacobian(x_try)

        # jeśli poprawa — akceptuj; w przeciwnym razie bierz pełen krok
        if np.linalg.norm(r_try) < np.linalg.norm(r):
            x, r, J = x_try, r_try, J_try
        else:
            x = x + dx
            r, J = residuals_and_jacobian(x)

        if np.linalg.norm(r) < tol * max(1.0, norm0):
            break

    return x, r, J

# ------------------------------------------------------------
# 5) INICJALIZACJA (PŁASKA STOPA) I ROZWIĄZANIE
# ------------------------------------------------------------
avg_rate = float(np.mean(list(quotes.values())))
# ln P(t) ≈ -avg_rate * t → x0_var dla węzłów 1..K-1
x0_var = np.array([-avg_rate * t for t in knot_times[1:]], dtype=float)

x_opt, r_fin, J_fin = newton_solve(x0_var, max_iter=50, tol=1e-14, damping=1.0)

# pełny wektor ln P (x0=0 → P(0)=1)
x_all = np.zeros(len(knot_times))
x_all[1:] = x_opt

# ------------------------------------------------------------
# 6) PODGLĄD: DF, ZERO-RATE, SPRAWDZENIE PAR RATE
# ------------------------------------------------------------
# DF-y na węzłach
discount_factors = {t: P_from_x(t, knot_times, x_all) for t in knot_times}

print("== Węzły krzywej i DF (precyzyjny wydruk) ==")
for t in sorted(discount_factors.keys()):
    P = discount_factors[t]
    zr = 0.0 if t == 0.0 else -math.log(P) / t
    print(f"t={t:>9.6f}  P(t)={P:.12f}  zero={zr:.12f}")

# Weryfikacja dopasowania: dla jednokuponowych OIS (ON/1W/1M)
# S_model = (P(start) - P(T)) / (alpha * P(T))
print("\n== Market vs Model (par rates) ==")
for (tenor, alpha, t_s, T, sdate, edate) in instruments:
    P_T = P_from_x(T, knot_times, x_all)
    P_s = P_from_x(t_s, knot_times, x_all)
    S_model = (P_s - P_T) / (alpha * P_T)
    err_bp = (S_model - quotes[tenor]) * 1e4
    print(
        f"{tenor:>3s}  start={sdate}  end={edate} "
        f" alpha={alpha:.8f}  S_mkt={quotes[tenor]:.8f}  S_mod={S_model:.8f}  err_bp={err_bp:+.3f}"
    )

print("\nKnots (years):", [f"{t:.8f}" for t in knot_times])
print("Residual L2-norm:", float(np.linalg.norm(r_fin)))







#dupa#

# -*- coding: utf-8 -*-
"""
USD OIS (SOFR) — ON / 1W / 1M
Globalny fit krzywej dyskontowej metodą Newtona–Raphsona z log-linear na DF.
Konwencje:
  - Day Count: ACT/360 (kupon)
  - Kalendarz: UnitedStates(FederalReserve)
  - Spot lag: 1d (T+1)
  - BDC: Following (≤1M), Modified Following (>1M)
  - ON: start = dziś; 1W/1M: start = SPOT (T+1)
Równanie OIS (forward-start):
  (S*alpha + 1) * P(T) - P(start) = 0
"""

import math
import numpy as np
import QuantLib as ql

# =========================
# 0) Parametry rynkowe
# =========================
valuation_date = ql.Date(27, 10, 2025)                 # dzisiaj
ql.Settings.instance().evaluationDate = valuation_date

cal = ql.UnitedStates(ql.UnitedStates.FederalReserve)  # kalendarz SOFR/US Gov
dc_leg  = ql.Actual360()                               # do α kuponu
dc_axis = ql.Actual365Fixed()                          # oś czasu (dowolna spójna); α zawsze ACT/360
spot_lag = 1                                           # USD OIS: T+1

# <<< PODMIEŃ NA SWOJE STAWKI (w UŁAMKU, np. 0.0520 = 5.20%) >>>
quotes = {
    "ON": 0.05250,
    "1W": 0.05200,
    "1M": 0.05150,
}

# =========================
# 1) Daty i α = ACT/360
# =========================
def bdc_for(tenor: str):
    t = tenor.upper()
    return ql.Following if t in ("ON", "TN", "1W", "2W", "1M") else ql.ModifiedFollowing

def usd_ois_period(tenor: str):
    """
    Zwraca: (tenor, alpha, t_start, t_end, start_date, end_date)
      - ON: start=dziś (Following), end=+1d (Following)
      - 1W/1M: start=SPOT (T+1, Following), end=adjust(spot+tenor, BDC)
    alpha = ACT/360; t_* = lata od valuation_date (dc_axis)
    """
    t = tenor.upper().strip()
    bdc = bdc_for(t)

    if t == "ON":
        start = cal.adjust(valuation_date, ql.Following)
        end   = cal.advance(start, 1, ql.Days, ql.Following)
    else:
        spot  = cal.advance(valuation_date, spot_lag, ql.Days, ql.Following)
        start = spot
        end   = cal.adjust(spot + ql.Period(t), bdc)

    alpha   = float(dc_leg.yearFraction(start, end))
    t_start = float(dc_axis.yearFraction(valuation_date, start))
    t_end   = float(dc_axis.yearFraction(valuation_date, end))
    return (t, alpha, t_start, t_end, start, end)

tenors = ["ON", "1W", "1M"]
instruments = [usd_ois_period(t) for t in tenors]

# =========================
# 2) Węzły i interpolacja
# =========================
# Węzły: 0.0 + wszystkie starty i końce (trafiamy dokładnie P(start) i P(T))
knot_times = {0.0}
for (_, _, t_s, t_e, _, _) in instruments:
    knot_times.add(t_s); knot_times.add(t_e)
knot_times = sorted(knot_times)

def weights_loglinear(t: float, knots: list[float], eps: float = 1e-14) -> np.ndarray:
    """
    Wagi do ln P(t) (log-linear). Snap do węzłów: jeżeli t≈węzeł → 100% tego węzła.
    """
    K = len(knots)
    w = np.zeros(K)
    # snap do węzła
    for i, tau in enumerate(knots):
        if abs(t - tau) <= eps:
            w[i] = 1.0
            return w
    if t < knots[0]:
        w[0] = 1.0; return w
    if t > knots[-1]:
        w[-1] = 1.0; return w
    # wewnątrz: segment [k, k+1]
    k = max(i for i in range(K-1) if knots[i] <= t)
    tau0, tau1 = knots[k], knots[k+1]
    lam = (t - tau0) / (tau1 - tau0)
    w[k]   = 1.0 - lam
    w[k+1] = lam
    return w

def P_from_x(t: float, knots: list[float], x_all: np.ndarray) -> float:
    """P(t) = exp( w(t) · x ), gdzie x = ln P w węzłach; x[0]=0 → P(0)=1."""
    return math.exp(float(np.dot(weights_loglinear(t, knots), x_all)))

# =========================
# 3) Residua i Jakobian
# =========================
# OIS (ON/1W/1M jednokuponowe):
#   r_k = (S_k*alpha_k + 1) * P(T_k) - P(start_k) = 0
def residuals_and_jacobian(x_var: np.ndarray):
    # x0=0 → P(0)=1 (nieoptymalizowany); zmienne to x[1..]
    x_all = np.zeros(len(knot_times))
    x_all[1:] = x_var

    r = np.zeros(len(instruments))
    J = np.zeros((len(instruments), len(x_var)))

    for k, (tenor, alpha, t_s, T, _, _) in enumerate(instruments):
        S = quotes[tenor]
        P_T = P_from_x(T,       knot_times, x_all)
        P_s = P_from_x(t_s,     knot_times, x_all)   # ON: t_s=0 → P_s=1

        # residuum
        r[k] = (S * alpha + 1.0) * P_T - P_s

        # Jakobian: (S*α + 1) * P(T) * w(T)  -  P(s) * w(s)
        w_T = weights_loglinear(T,   knot_times)[1:]  # bez x0
        w_s = weights_loglinear(t_s, knot_times)[1:]
        J[k, :] = (S * alpha + 1.0) * P_T * w_T - P_s * w_s

    return r, J

# =========================
# 4) Newton-Raphson
# =========================
def newton_solve(x0: np.ndarray, max_iter: int = 50, tol: float = 1e-14):
    x = x0.copy()
    r, J = residuals_and_jacobian(x)
    norm0 = np.linalg.norm(r)
    for _ in range(max_iter):
        dx, *_ = np.linalg.lstsq(J, -r, rcond=None)
        x += dx
        r, J = residuals_and_jacobian(x)
        if np.linalg.norm(r) < tol * max(1.0, norm0):
            break
    return x, r

# =========================
# 5) Inicjalizacja i solve
# =========================
avg_rate = float(np.mean(list(quotes.values())))
x0_var = np.array([-avg_rate * t for t in knot_times[1:]], dtype=float)  # ln P ≈ -r*t

x_opt, r_fin = newton_solve(x0_var)
x_all = np.zeros(len(knot_times))
x_all[1:] = x_opt

# =========================
# 6) Wyniki i kontrola
# =========================
discount_factors = {t: P_from_x(t, knot_times, x_all) for t in knot_times}

print("== Instrumenty (daty i α) ==")
for (tenor, alpha, t_s, t_e, sdate, edate) in instruments:
    print(f"{tenor:>3s}  start={sdate}  end={edate}  alpha={alpha:.10f}")

print("\n== DF na węzłach ==")
for t in knot_times:
    P = discount_factors[t]
    zr_cont = 0.0 if t == 0.0 else -math.log(P) / t  # zero (continuous comp) na osi dc_axis
    print(f"t={t:>9.6f}  P(t)={P:.12f}  zero_cont={zr_cont:.12f}")

print("\n== Market vs Model (par rates) ==")
for (tenor, alpha, t_s, T, sdate, edate) in instruments:
    P_T = discount_factors[T]
    P_s = discount_factors[t_s]
    S_model = (P_s - P_T) / (alpha * P_T)
    err_bp = (S_model - quotes[tenor]) * 1e4
    print(f"{tenor:>3s}  S_mkt={quotes[tenor]:.8f}  S_mod={S_model:.8f}  err_bp={err_bp:+.3f}  "
          f"[start={sdate} → end={edate}, α={alpha:.8f}]")

print("\nKnots (years):", [f"{t:.8f}" for t in knot_times])
print("Residual L2-norm:", float(np.linalg.norm(r_fin)))






# -*- coding: utf-8 -*-
"""
USD OIS (SOFR) — Bootstrap krzywej dyskontowej
Konwencje:
  - Data wyceny: 27/10/2025
  - Spot lag: 2 dni (T+2)
  - Kalendarz: UnitedStates(FederalReserve)
  - BDC: ≤1M -> Following, >1M -> Modified Following
  - Day Count kuponu: ACT/360
  - Freq stałej nogi: rocznie dla >1Y, pojedyncza płatność dla ≤1Y
  - Interpolacja (gdy potrzebna): log-linear na DF po osi ACT/365F
"""

import math
from typing import List, Tuple
import QuantLib as ql

# ========= 1) PARAMETRY RYNKOWE =========
VAL_DATE = ql.Date(27, 10, 2025)
ql.Settings.instance().evaluationDate = VAL_DATE

CAL = ql.UnitedStates(ql.UnitedStates.FederalReserve)
DC_LEG = ql.Actual360()          # α kuponów OIS (ACT/360)
DC_AXIS = ql.Actual365Fixed()    # oś czasu do interpolacji (dowolna spójna)
SPOT_LAG = 2                     # T+2 (jak u Ciebie)

def bdc_for(tenor: str) -> ql.BusinessDayConvention:
    t = tenor.upper()
    return ql.Following if t in ("ON", "TN", "1W", "2W", "1M") else ql.ModifiedFollowing

# PRZYKŁADOWE STAWKI (ułamek!). PODMIEŃ NA SWOJE.
# Kolejność ma znaczenie (od najkrótszych do dłuższych).
QUOTES: List[Tuple[str, float]] = [
    ("ON", 0.05250),
    ("1W", 0.05200),
    ("1M", 0.05150),
    ("3M", 0.05080),
    ("6M", 0.05020),
    ("1Y", 0.04950),
    ("2Y", 0.04750),
    ("3Y", 0.04600),
]

# ========= 2) POMOCNICZE: SPOT, HARMONOGRAM, ALFY =========
def tenor_period(tenor: str) -> ql.Period:
    t = tenor.upper().strip()
    if t == "ON":         return ql.Period(1, ql.Days)
    if t.endswith("W"):   return ql.Period(int(t[:-1]), ql.Weeks)
    if t.endswith("M"):   return ql.Period(int(t[:-1]), ql.Months)
    if t.endswith("Y"):   return ql.Period(int(t[:-1]), ql.Years)
    raise ValueError(f"Nieznany tenor: {tenor}")

def spot_date() -> ql.Date:
    return CAL.advance(VAL_DATE, SPOT_LAG, ql.Days, ql.Following)

def build_ois_schedule(tenor: str):
    """
    Zwraca:
      start_date, end_date, coupons: List[(pay_date, alpha)]
    Reguły:
      - ON: start=dziś (Following), end=+1d (Following), 1 kupon
      - ≤1Y: start=SPOT, end=SPOT+tenor (BDC wg zasad), 1 kupon
      - >1Y: start=SPOT, end=SPOT+tenor (BDC=ModFoll), roczne kupony
    """
    t = tenor.upper().strip()

    if t == "ON":
        start = CAL.adjust(VAL_DATE, ql.Following)
        end   = CAL.advance(start, 1, ql.Days, ql.Following)
        alpha = DC_LEG.yearFraction(start, end)
        return start, end, [(end, alpha)]

    # forward-start
    s = spot_date()
    per = tenor_period(t)
    bdc = bdc_for(t)
    end = CAL.advance(s, per, bdc)

    # ile kuponów?
    # ≤1Y: pojedynczy
    if per.length() == 1 and per.units() in (ql.Months, ql.Weeks):
        alpha = DC_LEG.yearFraction(s, end)
        return s, end, [(end, alpha)]
    if per.units() == ql.Years and per.length() <= 1:
        alpha = DC_LEG.yearFraction(s, end)
        return s, end, [(end, alpha)]

    # >1Y: roczne kupony stałej nogi
    # budujemy schedule roczny od start do end; BDC: Modified Following, bez EOM
    rule = ql.DateGeneration.Forward
    sched = ql.Schedule(
        s, end, ql.Period(ql.Annual), CAL, ql.ModifiedFollowing, ql.ModifiedFollowing,
        rule, False
    )
    coupons = []
    for i in range(1, len(sched)):
        d_prev, d_pay = sched[i-1], sched[i]
        alpha = DC_LEG.yearFraction(d_prev, d_pay)
        coupons.append((d_pay, alpha))
    return s, end, coupons

# ========= 3) INTERPOLACJA LOG-LINEAR NA DF (po czasie ACT/365F) =========
def t_years(d: ql.Date) -> float:
    return DC_AXIS.yearFraction(VAL_DATE, d)

def loglinear_df_interpolate(query_date: ql.Date, known_dfs: dict) -> float:
    """
    Interpolacja log-linear DF między najbliższymi znanymi datami (po ACT/365F).
    known_dfs: dict[ql.Date] -> DF
    """
    if query_date in known_dfs:
        return known_dfs[query_date]

    # posortowane znane daty
    dates = sorted(known_dfs.keys())
    # skrajne przypadki
    if query_date <= dates[0]:
        return known_dfs[dates[0]]
    if query_date >= dates[-1]:
        return known_dfs[dates[-1]]

    # znajdź sąsiadów
    for i in range(1, len(dates)):
        d0, d1 = dates[i-1], dates[i]
        if d0 <= query_date <= d1:
            t0, t1, tq = t_years(d0), t_years(d1), t_years(query_date)
            lam = (tq - t0) / (t1 - t0)
            lnP = (1.0 - lam) * math.log(known_dfs[d0]) + lam * math.log(known_dfs[d1])
            return math.exp(lnP)
    raise RuntimeError("Interpolation failure.")

# ========= 4) BOOTSTRAP =========
def bootstrap_ois(quotes: List[Tuple[str, float]]):
    """
    Zwraca:
      dfs: dict[ql.Date] -> DF (obejmuje wszystkie płatności i końce)
      instruments: list z informacjami o harmonogramach (do debug/wydruku)
    """
    dfs = {VAL_DATE: 1.0}  # P(0)=1
    instruments_info = []

    for tenor, S in quotes:
        start, end, coupons = build_ois_schedule(tenor)
        # zadbaj, by P(start) było znane (dla ON start=VAL_DATE)
        if start not in dfs:
            dfs[start] = loglinear_df_interpolate(start, dfs)

        # suma znanych kuponów poza ostatnim
        sum_known = 0.0
        for d_pay, a in coupons[:-1]:
            if d_pay not in dfs:
                dfs[d_pay] = loglinear_df_interpolate(d_pay, dfs)
            sum_known += a * dfs[d_pay]

        # ostatni kupon:
        d_last, a_last = coupons[-1]

        # w zależności od liczby kuponów:
        # - 1 kupon: P(T) = P(s) / (1 + S * alpha_last)
        # - m>1 :    P(T) = (P(s) - S * sum_{i<m} alpha_i P(t_i)) / (1 + S * alpha_last)
        P_s = dfs[start]  # DF na start

        numerator = P_s - S * sum_known
        denominator = 1.0 + S * a_last
        P_T = numerator / denominator

        dfs[d_last] = P_T

        instruments_info.append({
            "tenor": tenor, "S": S, "start": start, "end": end,
            "coupons": coupons, "alpha_total": sum(a for _, a in coupons)
        })

    return dfs, instruments_info

# ========= 5) URUCHOMIENIE I WYDRUK =========
dfs, info = bootstrap_ois(QUOTES)

# Posortowane węzły i wydruk DF/zero (continuous comp) z dużą precyzją
nodes = sorted(dfs.keys(), key=lambda d: int(d.serialNumber()))

print("== Węzły (daty) i DF ==")
for d in nodes:
    P = dfs[d]
    t = t_years(d)
    zr_cont = 0.0 if t == 0.0 else -math.log(P) / t
    print(f"{d}  t={t:>9.6f}  P(t)={P:.12f}  zero_cont={zr_cont:.12f}")

# Kontrola: par rate z krzywej = (P(start) - P(T)) / (sum alpha_i P(t_i))
print("\n== Market vs Model (par OIS) ==")
for ins in info:
    tenor, S = ins["tenor"], ins["S"]
    start, end = ins["start"], ins["end"]
    coupons = ins["coupons"]

    P_s = dfs[start]
    P_T = dfs[end]
    denom = sum(a * dfs[d] for (d, a) in coupons)  # sum alpha_i P(t_i)

    S_model = (P_s - P_T) / denom
    err_bp = (S_model - S) * 1e4
    alpha_tot = sum(a for _, a in coupons)
    print(f"{tenor:>3s}  start={start}  end={end}  alpha_sum={alpha_tot:.8f}  "
          f"S_mkt={S:.8f}  S_mod={S_model:.8f}  err_bp={err_bp:+.3f}")








# -*- coding: utf-8 -*-
"""
USD OIS (SOFR) — Bootstrap krzywej dyskontowej z kotwicą ON/TN
Konwencje:
  - Data wyceny: 27/10/2025
  - Spot lag: 2 dni (T+2)
  - Kalendarz: UnitedStates(FederalReserve)
  - BDC: ≤1M -> Following, >1M -> Modified Following
  - Day Count kuponu: ACT/360
  - Interpolacja: log-linear na DF po osi czasu ACT/365F
  - Kotwica: P(T+1) z ON, P(T+2) (spot) z TN — jeśli brak TN, przyjmujemy TN = ON
"""

import math
from typing import List, Tuple, Dict
import QuantLib as ql

# ========= 1) PARAMETRY RYNKOWE =========
VAL_DATE = ql.Date(27, 10, 2025)
ql.Settings.instance().evaluationDate = VAL_DATE

CAL = ql.UnitedStates(ql.UnitedStates.FederalReserve)
DC_LEG = ql.Actual360()          # α kuponów OIS (dla nogi stałej)
DC_AXIS = ql.Actual365Fixed()    # oś czasu do interpolacji (dowolna spójna)
SPOT_LAG = 2                     # T+2

def bdc_for(tenor: str):
    t = tenor.upper()
    return ql.Following if t in ("ON", "TN", "1W", "2W", "1M") else ql.ModifiedFollowing

# ===== PODMIEŃ NA SWOJE STAWKI (ułamek, nie %) =====
# Możesz dodać TN; jeśli nie dodasz, kod użyje TN=ON.
QUOTES: List[Tuple[str, float]] = [
    ("ON", 0.05250),
    # ("TN", 0.05245),    # możesz odkomentować, jeśli masz TN z rynku
    ("1W", 0.05200),
    ("1M", 0.05150),
    ("3M", 0.05080),
    ("6M", 0.05020),
    ("1Y", 0.04950),
    ("2Y", 0.04750),
    ("3Y", 0.04600),
]

# ========= 2) POMOCNICZE: SPOT, HARMONOGRAM, ALFY =========
def tenor_period(tenor: str) -> ql.Period:
    t = tenor.upper().strip()
    if t == "ON":         return ql.Period(1, ql.Days)
    if t == "TN":         return ql.Period(1, ql.Days)  # TN to też 1 dzień, ale od T+1 do T+2
    if t.endswith("W"):   return ql.Period(int(t[:-1]), ql.Weeks)
    if t.endswith("M"):   return ql.Period(int(t[:-1]), ql.Months)
    if t.endswith("Y"):   return ql.Period(int(t[:-1]), ql.Years)
    raise ValueError(f"Nieznany tenor: {tenor}")

def spot_date() -> ql.Date:
    return CAL.advance(VAL_DATE, SPOT_LAG, ql.Days, ql.Following)

def build_ois_schedule(tenor: str):
    """
    Zwraca:
      start_date, end_date, coupons: List[(pay_date, alpha)]
    Reguły:
      - ON: start=dziś (Following), end=+1d (Following), 1 kupon
      - TN: start=T+1, end=T+2 (oba Following), 1 kupon
      - ≤1Y: start=SPOT, end=SPOT+tenor (BDC wg zasad), 1 kupon
      - >1Y: start=SPOT, end=SPOT+tenor (BDC=ModFoll), roczne kupony
    """
    t = tenor.upper().strip()

    if t == "ON":
        start = CAL.adjust(VAL_DATE, ql.Following)
        end   = CAL.advance(start, 1, ql.Days, ql.Following)
        alpha = DC_LEG.yearFraction(start, end)
        return start, end, [(end, alpha)]

    if t == "TN":
        d0 = CAL.adjust(VAL_DATE, ql.Following)          # dziś (adjusted)
        start = CAL.advance(d0, 1, ql.Days, ql.Following)  # jutro (T+1)
        end   = CAL.advance(start, 1, ql.Days, ql.Following)  # pojutrze (T+2)
        alpha = DC_LEG.yearFraction(start, end)
        return start, end, [(end, alpha)]

    # forward-start od SPOT
    s = spot_date()
    per = tenor_period(t)
    bdc = bdc_for(t)
    end = CAL.advance(s, per, bdc)

    # ≤1Y → 1 kupon
    if (per.units() in (ql.Weeks, ql.Months)) or (per.units() == ql.Years and per.length() <= 1):
        alpha = DC_LEG.yearFraction(s, end)
        return s, end, [(end, alpha)]

    # >1Y → roczne kupony stałej nogi
    sched = ql.Schedule(
        s, end, ql.Period(ql.Annual),
        CAL, ql.ModifiedFollowing, ql.ModifiedFollowing,
        ql.DateGeneration.Forward, False
    )
    coupons = []
    for i in range(1, len(sched)):
        d_prev, d_pay = sched[i-1], sched[i]
        alpha = DC_LEG.yearFraction(d_prev, d_pay)
        coupons.append((d_pay, alpha))
    return s, end, coupons

# ========= 3) INTERPOLACJA LOG-LINEAR NA DF =========
def t_years(d: ql.Date) -> float:
    return DC_AXIS.yearFraction(VAL_DATE, d)

def loglinear_df_interpolate(query_date: ql.Date, known_dfs: Dict[ql.Date, float]) -> float:
    """Interpolacja log-linear DF między najbliższymi znanymi datami (po ACT/365F)."""
    if query_date in known_dfs:
        return known_dfs[query_date]
    dates = sorted(known_dfs.keys(), key=lambda x: int(x.serialNumber()))
    if query_date <= dates[0]:
        return known_dfs[dates[0]]
    if query_date >= dates[-1]:
        return known_dfs[dates[-1]]
    for i in range(1, len(dates)):
        d0, d1 = dates[i-1], dates[i]
        if d0 <= query_date <= d1:
            t0, t1, tq = t_years(d0), t_years(d1), t_years(query_date)
            lam = (tq - t0) / (t1 - t0)
            lnP = (1.0 - lam) * math.log(known_dfs[d0]) + lam * math.log(known_dfs[d1])
            return math.exp(lnP)
    raise RuntimeError("Interpolation failure.")

# ========= 4) KOTWICA ON/TN =========
def anchor_ON_TN_dfs(quotes: List[Tuple[str, float]]) -> Dict[ql.Date, float]:
    """
    Wyznacza DF do T+1 (koniec ON) i DF do T+2 (koniec TN = SPOT).
    Jeśli brak TN w kwotowaniach — przyjmuje TN = ON.
    Zwraca dict: {VAL_DATE:1, d1:P(T+1), d2:P(T+2)}
    """
    d0 = CAL.adjust(VAL_DATE, ql.Following)
    d1 = CAL.advance(d0, 1, ql.Days, ql.Following)  # koniec ON
    d2 = CAL.advance(d1, 1, ql.Days, ql.Following)  # koniec TN = SPOT

    quotes_dict = dict(quotes)
    S_ON = quotes_dict.get("ON")
    if S_ON is None:
        raise ValueError("Brakuje kwotowania 'ON' — wymagane do kotwiczenia.")
    S_TN = quotes_dict.get("TN", S_ON)  # jeśli TN brak, użyj TN = ON

    a_ON = DC_LEG.yearFraction(d0, d1)
    a_TN = DC_LEG.yearFraction(d1, d2)

    P_d1 = 1.0 / (1.0 + S_ON * a_ON)     # DF do T+1
    P_d2 = P_d1 / (1.0 + S_TN * a_TN)    # DF do T+2 (spot)

    return {VAL_DATE: 1.0, d1: P_d1, d2: P_d2}

# ========= 5) BOOTSTRAP =========
def bootstrap_ois(quotes: List[Tuple[str, float]]):
    """
    Zwraca:
      dfs: dict[ql.Date] -> DF (obejmuje wszystkie płatności i końce)
      instruments: lista info o harmonogramach (do kontroli)
    """
    dfs = anchor_ON_TN_dfs(quotes)  # kotwica ON/TN (P(T+1), P(T+2))
    instruments_info = []

    for tenor, S in quotes:
        if tenor in ("ON", "TN"):
            # ON/TN już wykorzystane do kotwicy — nic nie liczymy.
            continue

        start, end, coupons = build_ois_schedule(tenor)

        # P(start) MUSI być znane (dla T+2 już jest z kotwicy)
        if start not in dfs:
            dfs[start] = loglinear_df_interpolate(start, dfs)

        # suma znanych kuponów oprócz ostatniego
        sum_known = 0.0
        for d_pay, a in coupons[:-1]:
            if d_pay not in dfs:
                dfs[d_pay] = loglinear_df_interpolate(d_pay, dfs)
            sum_known += a * dfs[d_pay]

        # ostatni kupon
        d_last, a_last = coupons[-1]
        P_s = dfs[start]
        P_T = (P_s - S * sum_known) / (1.0 + S * a_last)

        dfs[d_last] = P_T

        instruments_info.append({
            "tenor": tenor, "S": S, "start": start, "end": end,
            "coupons": coupons, "alpha_total": sum(a for _, a in coupons)
        })

    return dfs, instruments_info

# ========= 6) URUCHOMIENIE I WYDRUK =========
dfs, info = bootstrap_ois(QUOTES)

nodes = sorted(dfs.keys(), key=lambda d: int(d.serialNumber()))

print("== Kotwica ON/TN/Spot ==")
for d in nodes[:3]:  # VAL_DATE, T+1, T+2
    print(f"{d}  P={dfs[d]:.12f}")

print("\n== Węzły (daty) i DF ==")
for d in nodes:
    P = dfs[d]
    t = t_years(d)
    zr_cont = 0.0 if t == 0.0 else -math.log(P) / t
    print(f"{d}  t={t:>9.6f}  P(t)={P:.12f}  zero_cont={zr_cont:.12f}")

print("\n== Market vs Model (par OIS) ==")
for ins in info:
    tenor, S = ins["tenor"], ins["S"]
    start, end = ins["start"], ins["end"]
    coupons = ins["coupons"]

    P_s = dfs[start]
    P_T = dfs[end]
    denom = sum(a * dfs[d] for (d, a) in coupons)  # sum alpha_i * P(t_i)
    S_model = (P_s - P_T) / denom
    err_bp = (S_model - S) * 1e4
    alpha_tot = sum(a for _, a in coupons)

    print(f"{tenor:>3s}  start={start}  end={end}  alpha_sum={alpha_tot:.8f}  "
          f"S_mkt={S:.8f}  S_mod={S_model:.8f}  err_bp={err_bp:+.3f}")


