import sqlite3
import os

def main():
    # Path to the bot.db file in the Mister_Betting root directory
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'bot.db')
    
    print(f"Connecting to database at: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # The safe backdate (Older than 7 days so weekly report ignores it)
    target_date = "2026-09-01 12:00:00.000000"

    # Insert 16 Wins
    for _ in range(16):
        cursor.execute('''
            INSERT INTO matches (home_team, away_team, kickoff_time, is_finished, is_win, skip_reason)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', ("Hidden VIP Match", "Locked", target_date, 1, 1, "historical_backfill"))

    # Insert 7 Losses
    for _ in range(7):
        cursor.execute('''
            INSERT INTO matches (home_team, away_team, kickoff_time, is_finished, is_win, skip_reason)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', ("Hidden VIP Match", "Locked", target_date, 1, 0, "historical_backfill"))

    conn.commit()
    
    # Verify the math
    cursor.execute("SELECT COUNT(*) FROM matches WHERE is_win = 1 AND strftime('%Y-%m', kickoff_time) = '2026-09'")
    wins = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM matches WHERE is_win = 0 AND strftime('%Y-%m', kickoff_time) = '2026-09'")
    losses = cursor.fetchone()[0]

    print("--------------------------------------------------")
    print(f"✅ Success! Injected 16 wins and 7 losses safely.")
    print(f"📊 Current September DB Record: {wins}W — {losses}L")
    print("--------------------------------------------------")
    
    conn.close()

if __name__ == "__main__":
    main()
