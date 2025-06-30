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
