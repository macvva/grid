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