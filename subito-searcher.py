#!/usr/bin/env python3.7
import numpy as np
import random
import argparse
from contextlib import nullcontext
import requests
from bs4 import BeautifulSoup, Tag
import json
import os
import platform
import time as t
import sqlite3
import sys
from datetime import datetime, time
from curl_cffi import requests # <-- The Stealth Engine

# Use a session to keep cookies/connection alive like a real browser
parser = argparse.ArgumentParser()
parser.add_argument("--add", dest='name', help="name of new tracking to be added")
parser.add_argument("--url", help="url for your new tracking's search query")
parser.add_argument("--minPrice", help="minimum price for the query")
parser.add_argument("--maxPrice", help="maximum price for the query")
parser.add_argument("--delete", help="name of the search you want to delete")
parser.add_argument('--refresh', '-r', dest='refresh', action='store_true', help="refresh search results once")
parser.set_defaults(refresh=False)
parser.add_argument('--daemon', '-d', dest='daemon', action='store_true', help="keep refreshing search results forever (default delay 120 seconds)")
parser.set_defaults(daemon=False)
parser.add_argument('--activeHour', '-ah', dest='activeHour', help="Time slot. Hour when to be active in 24h notation")
parser.add_argument('--pauseHour', '-ph', dest='pauseHour', help="Time slot. Hour when to pause in 24h notation")
parser.add_argument('--delay', dest='delay', help="delay for the daemon option (in seconds)")
parser.set_defaults(delay=120)
parser.add_argument('--list', dest='list', action='store_true', help="print a list of current trackings")
parser.set_defaults(list=False)
parser.add_argument('--short_list', dest='short_list', action='store_true', help="print a more compact list")
parser.set_defaults(short_list=False)
parser.add_argument('--tgoff', dest='tgoff', action='store_true', help="turn off telegram messages")
parser.set_defaults(tgoff=False)
parser.add_argument('--notifyoff', dest='win_notifyoff', action='store_true', help="turn off windows notifications")
parser.set_defaults(win_notifyoff=False)
parser.add_argument('--addtoken', dest='token', help="telegram setup: add bot API token")
parser.add_argument('--addchatid', dest='chatid', help="telegram setup: add bot chat id")
parser.add_argument('--ntfy_server', dest='ntfy_server', help="Set ntfy server URL")
parser.add_argument('--ntfy_topic', dest='ntfy_topic', help="Set ntfy topic for notifications")
parser.add_argument('--ntfyoff', dest='ntfyoff', action='store_true', help="Turn off ntfy notifications")
parser.set_defaults(ntfyoff=False)

args = parser.parse_args()

session = requests.Session()
apiCredentials = dict()
ntfyConfig = dict()
ntfyConfigFile = "ntfy_config"
dbFile = "searches.tracked"
telegramApiFile = "telegram_api_credentials"

conn=None
cursor=None
#database connection

# Windows notifications
if platform.system() == "Windows":
    from win10toast import ToastNotifier
    toaster = ToastNotifier()

def connect_database():
    global conn, cursor # Dichiariamo le globali prima
    
    try:
        # Proviamo a connetterci
        conn = sqlite3.connect('annunci.db')
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.row_factory = sqlite3.Row 
        cursor = conn.cursor()
        # Test rapido per vedere se il DB risponde davvero
        conn.execute("SELECT 1")
        print("✅ Connessione riuscita: Il database è pronto!")
        
    except sqlite3.Error as e:
        # Se qualcosa va storto, stampiamo l'errore e chiudiamo tutto
        print(f"❌ Errore fatale al database: {e}")
        print("Uscita in corso...")
        sys.exit(1) # Esce dallo script con codice di errore 1



def load_api_credentials():
    '''A function to load the telegram api credentials from the json file'''
    global apiCredentials
    global telegramApiFile
    if not os.path.isfile(telegramApiFile):
        return

    with open(telegramApiFile) as file:
        apiCredentials = json.load(file)

def load_ntfy_config():
    '''A function to load the ntfy config from the json file'''
    global ntfyConfig
    global ntfyConfigFile
    if not os.path.isfile(ntfyConfigFile):
        return

    with open(ntfyConfigFile) as file:
        ntfyConfig = json.load(file)

def print_queries():
    '''Una funzione per stampare le ricerche e i relativi annunci dal DB'''
    # 1. Prendiamo tutte le ricerche salvate
    cursor.execute("SELECT nome, url FROM ricerche")
    ricerche = cursor.fetchall()

    if not ricerche:
        print("\n📭 Nessuna ricerca tracciata nel database.")
        return

    for r in ricerche:
        nome_ricerca = r['nome']
        url_ricerca = r['url']
        
        print(f"\nsearch: {nome_ricerca}")
        print(f"query url: {url_ricerca}")

        # 2. Per ogni ricerca, prendiamo gli annunci collegati (JOIN mentale)
        cursor.execute("""
            SELECT titolo, prezzo, localita, link 
            FROM annunci 
            WHERE categoria = ?
        """, (nome_ricerca,))
        
        annunci = cursor.fetchall()

        if not annunci:
            print("  (Nessun annuncio trovato per questa ricerca)")
        else:
            for a in annunci:
                # Stampiamo i dati proprio come facevi prima
                print(f"\n {a['titolo']} : {a['prezzo']} --> {a['localita']}")
                print(f"  {a['link']}")


# printing a compact list of trackings
def print_sitrep():
    '''Una funzione per stampare la lista compatta delle ricerche dal DB'''
    # 1. Interroghiamo la tabella ricerche
    cursor.execute("SELECT nome, url, prezzo_min, prezzo_max FROM ricerche")
    ricerche = cursor.fetchall()

    if not ricerche:
        print("\n📭 Nessuna ricerca tracciata nel database.")
        return

    # Usiamo enumerate per mantenere il conteggio (i) come nello script originale
    for i, r in enumerate(ricerche, 1):
        print(f'\n{i}) search: {r["nome"]}')
        print(f"query url: {r['url']} ", end='')

        # Gestione dei filtri prezzo (nello schema SQL abbiamo i DEFAULT 0 e 99999)
        p_min = r['prezzo_min']
        p_max = r['prezzo_max']

        # Stampiamo il range solo se non è quello di default
        if p_min > 0 or p_max < 99999:
            print(" | ", end='')
            if p_min > 0:
                print(f"{int(p_min)} < ", end='')
            
            print("price", end='')
            
            if p_max < 99999:
                print(f" < {int(p_max)}", end='')
        
        print("\n")

def refresh(notify):
    '''Sveglia il bot e gli fa controllare tutte le ricerche attive nel DB'''
    try:
        # 1. Chiediamo al DB solo le ricerche che abbiamo segnato come 'attive'
        cursor.execute("SELECT nome, url, prezzo_min, prezzo_max FROM ricerche WHERE attiva = 1")
        ricerche = cursor.fetchall()

        if not ricerche:
            print(f"{datetime.now().strftime('%H:%M:%S')} - 💤 Nessuna ricerca attiva nel DB.")
            return

        # 2. Un unico ciclo per lanciarle tutte
        for r in ricerche:
            # Passiamo i dati alla funzione run_query (che abbiamo già adattato)
            run_query(
                url=r['url'], 
                name=r['nome'], 
                notify=notify, 
                min_price=r['prezzo_min'], 
                max_price=r['prezzo_max']
            )

    except requests.exceptions.ConnectionError:
        print(f"{datetime.now().strftime('%Y-%m-%d, %H:%M:%S')} - 🌐 Errore di connessione (Check internet!)")
    except requests.exceptions.Timeout:
        print(f"{datetime.now().strftime('%Y-%m-%d, %H:%M:%S')} - ⏳ Il server di Subito non risponde (Timeout)")
    except Exception as e:
        # Usiamo str(e) perché a volte printare l'oggetto Exception direttamente dà errore
        print(f"{datetime.now().strftime('%Y-%m-%d, %H:%M:%S')} - 🔥 Errore imprevisto: {str(e)}")

def delete(toDelete):
    '''Elimina una ricerca e tutti i suoi annunci dal DB in un colpo solo'''
    try:
        # 1. Eseguiamo il comando DELETE
        # Grazie a ON DELETE CASCADE, eliminando la ricerca cancelliamo 
        # automaticamente anche tutti gli annunci in 'annunci' legati a quel nome.
        cursor.execute("DELETE FROM ricerche WHERE nome = ?", (toDelete,))
        
        # 2. Rendiamo la modifica permanente
        conn.commit()

        # 3. Controlliamo se abbiamo effettivamente segato qualcosa
        if cursor.rowcount > 0:
            print(f"🗑️ Ricerca '{toDelete}' e relativi annunci eliminati dal DB.")
        else:
            print(f"⚠️ Nessuna ricerca trovata col nome '{toDelete}'.")

    except Exception as e:
        print(f"❌ Errore durante l'eliminazione di {toDelete}: {str(e)}")

def add(url, name, minPrice, maxPrice):
    '''Aggiunge o aggiorna una ricerca nel database SQL'''
    try:
        # 1. Pulizia dei prezzi (Sanitization)
        # Se arrivano come stringhe "null" o None, usiamo i limiti estremi
        try:
            mP = float(minPrice) if minPrice and str(minPrice).lower() != "null" else 0.0
        except ValueError:
            mP = 0.0

        try:
            MP = float(maxPrice) if maxPrice and str(maxPrice).lower() != "null" else 99999.0
        except ValueError:
            MP = 99999.0

        # 2. Il comando magico: INSERT OR REPLACE
        # Se 'name' esiste già, SQL sovrascrive la riga. Se non esiste, la crea.
        # È molto più veloce del vecchio queries.get(name) + delete(name)
        cursor.execute("""
            INSERT OR REPLACE INTO ricerche (nome, url, prezzo_min, prezzo_max, attiva)
            VALUES (?, ?, ?, ?, 1)
        """, (name, url, mP, MP))

        # 3. Rendiamo il tutto permanente
        conn.commit()
        
        print(f"✅ Ricerca '{name}' configurata! Il bot la monitorerà al prossimo refresh.")

    except Exception as e:
        print(f"❌ Errore durante l'aggiunta al database: {str(e)}")
def get_market_int(category):
    query="""
        SELECT prezzo FROM annunci
        WHERE categoria = ?
            AND ultimo_aggiornamento > datetime('now', '-21 days')
        ORDER BY ultimo_aggiornamento DESC;

    """
    cursor.execute(query,(category,))
    rows=cursor.fetchall()
    if len(rows)<20:
        return None
    prezzi = np.sort(np.array([r['prezzo'] for r in rows]))

    #Quartile 
    q1,q3 =np.percentile(prezzi,[25, 75])
    iqr=q3-q1

    low_bound=q1-1.5*iqr 
    up_bound=q3+1.5*iqr
    prezzi_cleaned= prezzi[(prezzi>=low_bound) & (prezzi<=up_bound)]
    if len(prezzi_cleaned)<10:return None 
    return {
        "mu":np.mean(prezzi_cleaned),
        "sigma":np.std(prezzi_cleaned),
        "count":len(prezzi_cleaned),
        "min_alert":q1,
    }
def run_query(url, name, notify, min_price, max_price):
    '''Versione ottimizzata: Log media mobile e fix notifiche primo avvio'''
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f" {timestamp} - 🕵️ Caccia aperta per: \"{name}\"")

    try:
        #Market data 
        stats=get_market_int(name)
        mu=stats['mu'] if stats else 0
        sigma=stats['sigma'] if stats else 0

        status_media = f"{mu:.2f}€ (σ:{sigma:.1f})" if mu > 0 else "Inizializzazione..."
        print(f"   📊 Mercato (21gg): {status_media}")

        # 1. CACHE BUSTER & JITTER (Evita il blocco del daemon)
        t.sleep(random.uniform(3, 7)) 
        bust_url = f"{url}&t={int(t.time())}" if "?" in url else f"{url}?t={int(t.time())}"

        response = session.get(
            bust_url, 
            impersonate="chrome110",
            headers={"Accept-Language": "it-IT,it;q=0.9", "Cache-Control": "no-cache"},
            timeout=20
        )
        response.raise_for_status() 
        
        script_tag = BeautifulSoup(response.text, 'html.parser').find('script', id='__NEXT_DATA__')
        if not script_tag: return

        items_list = json.loads(script_tag.string)['props']['pageProps']['initialState']['items']['list']

        # 2. LOG MEDIA MOBILE (Refresh ogni giro)
        cursor.execute("SELECT AVG(prezzo) FROM annunci WHERE categoria = ?", (name,))
        res = cursor.fetchone()
        media_attuale = res[0] if res and res[0] else 0
        
        # Log visibile in console
        status_media = f"{media_attuale:.2f}€" if media_attuale > 0 else "Calcolo in corso..."
        print(f"   📊 Media attuale mercato: {status_media}")

        msg = []
        low_bound = float(min_price) if str(min_price).lower() != "null" else 0
        high_bound = float(max_price) if str(max_price).lower() != "null" else float('inf')

        for item_wrapper in items_list:
            product = item_wrapper.get('item')
            if not product: continue

            link = product.get('urls', {}).get('default', '')
            title = product.get('subject', 'No Title')
            is_sold = product.get('sold', False)
            location = product.get('geo', {}).get('town', {}).get('value', 'Unknown')
            
            try:
                raw_p = product.get('features', {}).get('/price', {}).get('values', [{}])[0].get('key')
                price = int(raw_p) if raw_p else 0
            except: price = 0

            if is_sold:
                cursor.execute("DELETE FROM annunci WHERE link = ?", (link,))
                conn.commit()
                continue

            if price < low_bound or price > high_bound:
                continue

            cursor.execute("SELECT prezzo FROM annunci WHERE link = ?", (link,))
            row = cursor.fetchone()

            if row is None:
                # --- NUOVO ELEMENTO ---
                cursor.execute("INSERT INTO annunci (link, titolo, prezzo, categoria, localita,data_scoperta, ultimo_aggiornamento) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)", 
                               (link, title, price, name, location))
                conn.commit() # Commit immediato per il daemon

                if mu == 0:
                    print(f"   ✨ [FIRST SCAN] {title} - {price}€")
                else:
                    # CALCOLO Z-SCORE: quanto è lontano dalla media?
                    z = (price - mu) / sigma if sigma > 0 else 0
                    
                    if z <= -1.0: # Diventiamo un po' più permissivi per non perde nulla
                        if z <= -2.0:
                            tag = "🚨 AFFARE IMPERDIBILE (Z-Score estremo)"
                        elif z <= -1.5:
                            tag = "🔥 VERO AFFARE (Ottimo margine)"
                        else:
                            tag = "💰 BUON PREZZO (Da valutare)"
                    else:
                        print(f"   ☁️  [SAVE] {title} - {price}€ (z:{z:.2f}) - Non abbastanza economico")
            else:
                # --- RIBASSI ---
                old_price = row[0]
                if price < old_price:
                    cursor.execute("""
                        UPDATE annunci 
                        SET prezzo = ?, ultimo_aggiornamento = CURRENT_TIMESTAMP 
                        WHERE link = ?
                    """, (price, link))
                    msg.append(f"📉 RIBASSO: {title}\n💰 {price}€ (Era: {old_price}€)\n🔗 {link}")
                    print(f"   📉 [DROP] {title}: {old_price}€ -> {price}€")
                else:
                    # Aggiorniamo comunque il timestamp per tenerlo nei 21 giorni
                    cursor.execute("UPDATE annunci SET ultimo_aggiornamento = CURRENT_TIMESTAMP WHERE link = ?", (link,))
                
                conn.commit()
        # 4. NOTIFY
        if msg and notify:
            send_telegram_messages(msg)
            
    except Exception as e:
        print(f"   ❌ Errore critico {name}: {str(e)}")
def save_api_credentials():
    '''A function to save the telegram api credentials into the telegramApiFile'''
    with open(telegramApiFile, 'w') as file:
        file.write(json.dumps(apiCredentials))

def save_ntfy_config():
    '''A function to save the ntfy config into the ntfyConfigFile'''
    with open(ntfyConfigFile, 'w') as file:
        file.write(json.dumps(ntfyConfig))

def send_ntfy_messages(messages):
    for msg in messages:
        if not args.ntfyoff and "ntfy_server" in ntfyConfig and "ntfy_topic" in ntfyConfig:
            url = f"{ntfyConfig['ntfy_server'].rstrip('/')}/{ntfyConfig['ntfy_topic']}"
            try:
                requests.post(url, data=msg.encode('utf-8'))
            except Exception as e:
                print(f"Failed to send ntfy notification: {e}")

def is_ntfy_active():
    '''A function to check if ntfy is active, i.e. if the ntfy config is present and not disabled'''
    return not args.ntfyoff and "ntfy_server" in ntfyConfig and "ntfy_topic" in ntfyConfig

def is_telegram_active():
    '''A function to check if telegram is active, i.e. if the api credentials are present

    Returns
    -------
    bool
        True if telegram is active, False otherwise
    '''
    return not args.tgoff and "chatid" in apiCredentials and "token" in apiCredentials
def send_telegram_messages(messages):
    '''Versione Pro: Usa POST, gestisce i crash e pulisce i testi'''
    token = apiCredentials["token"]
    chat_id = apiCredentials["chatid"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    for msg in messages:
        # 1. Prepariamo il pacchetto dati
        payload = {
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False
        }

        try:
            # 2. Invio tramite POST (molto più stabile del GET)
            # Usiamo la sessione globale se disponibile, o requests liscio
            response = requests.post(url, json=payload, timeout=10)
            
            # 3. Se Telegram dà errore, lo scriviamo nel log
            if response.status_code != 200:
                print(f"   ⚠️ Telegram Error ({response.status_code}): {response.text}")
            else:
                print(f"   📨 Notifica inviata con successo!")

        except Exception as e:
            print(f"   ❌ Errore critico durante l'invio: {str(e)}")
def in_between(now, start, end):
    '''A function to check if a time is in between two other times

    Arguments
    ---------
    now: datetime
        the time to check
    start: datetime
        the start time
    end: datetime
        the end time

    Example usage
    -------------
    >>> in_between(datetime.now(), datetime(2021, 5, 20, 0, 0, 0), datetime(2021, 5, 20, 23, 59, 59))
    '''
    if start < end:
        return start <= now < end
    elif start == end:
        return True
    else: # over midnight e.g., 23:30-04:15
        return start <= now or now < end

if __name__ == '__main__':

    ### Setup commands ###

    load_api_credentials()
    load_ntfy_config()
    connect_database()
    if args.list:
        print(datetime.now().strftime("%Y-%m-%d, %H:%M:%S") + " printing current status...")
        print_queries()

    if args.short_list:
        print(datetime.now().strftime("%Y-%m-%d, %H:%M:%S") + " printing quick sitrep...")
        print_sitrep()

    if args.url is not None and args.name is not None:
        add(args.url, args.name, args.minPrice if args.minPrice is not None else "null", args.maxPrice if args.maxPrice is not None else "null")
        run_query(args.url, args.name, False, args.minPrice if args.minPrice is not None else "null", args.maxPrice if args.maxPrice is not None else "null",)
        print(datetime.now().strftime("%Y-%m-%d, %H:%M:%S") + " Query added.")

    if args.delete is not None:
        delete(args.delete)

    if args.activeHour is None:
        args.activeHour="0"

    if args.pauseHour is None:
        args.pauseHour="0"

    # NTFY setup (save config if new args passed)
    if args.ntfy_server is not None and args.ntfy_topic is not None:
        ntfyConfig["ntfy_server"] = args.ntfy_server
        ntfyConfig["ntfy_topic"] = args.ntfy_topic
        save_ntfy_config()

    # Telegram setup

    if args.token is not None and args.chatid is not None:
        apiCredentials["token"] = args.token
        apiCredentials["chatid"] = args.chatid
        save_api_credentials()

    ### Run commands ###

    if args.refresh:
        refresh(True)



    if args.daemon:
        notify = False # Don't flood with notifications the first time
        while True:
            if in_between(datetime.now().time(), time(int(args.activeHour)), time(int(args.pauseHour))):
                refresh(notify)
                notify = True
                print()
                print(str(args.delay) + " seconds to next poll.")

            t.sleep(int(args.delay))
    conn.close()
    print("Database connection closed")
