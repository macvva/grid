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
