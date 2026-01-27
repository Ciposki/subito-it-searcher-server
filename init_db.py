import sqlite3
import os

def crea_database():
    db_name = "annunci.db"
    schema_file = "schema.sql"
    
    # Se er DB esiste già, non famo casini
    if os.path.exists(db_name):
        print(f"⚠️ Er database '{db_name}' esiste già. Lo salto.")
        return

    try:
        # Connessione (crea er file se non c'è)
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()

        # Legge lo schema SQL
        with open(schema_file, 'r') as f:
            sql_script = f.read()

        # Esegue lo schema
        cursor.executescript(sql_script)
        conn.commit()
        print(f"✅ Database '{db_name}' creato e tabelle pronte!")
        
    except Exception as e:
        print(f"❌ Errore: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    crea_database()
