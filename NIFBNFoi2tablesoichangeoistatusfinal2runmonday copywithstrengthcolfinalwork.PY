import tkinter as tk
from tkinter import ttk, messagebox
from threading import Thread
from datetime import datetime, timedelta
import time
import random
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import re
import pandas as pd
from pathlib import Path
import math
import warnings
warnings.filterwarnings('ignore')

# ----------------- CONFIG -----------------
REFRESH_SECONDS = 185  # 15 minutes = 900 seconds
SYMBOLS = ["NIFTY", "BANKNIFTY"]
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

# Strike step sizes
STRIKE_STEPS = {
    "NIFTY": 50,
    "BANKNIFTY": 100
}

# Number of strikes above and below ATM
STRIKES_RANGE = 7

# LOT SIZES (CORRECTED)
LOT_SIZES = {
    "NIFTY": 65,
    "BANKNIFTY": 30
}

def format_number_lakh_cr(value):
    """Format number to show in lakhs/crores with proper suffix"""
    if value is None or value == 0:
        return "0"
    
    abs_value = abs(value)
    sign = "-" if value < 0 else ""
    
    if abs_value >= 10000000:  # 1 Crore and above
        value_in_cr = abs_value / 10000000
        return f"{sign}{value_in_cr:.1f}cr"
    elif abs_value >= 100000:  # 1 Lakh to below 1 Crore
        value_in_lakh = abs_value / 100000
        return f"{sign}{value_in_lakh:.1f}L"
    elif abs_value >= 1000:  # 1 Thousand to below 1 Lakh
        value_in_k = abs_value / 1000
        return f"{sign}{value_in_k:.1f}K"
    else:
        return f"{sign}{abs_value}"

def parse_number_string(num_str):
    """Parse number string from NSE table to integer"""
    if not num_str or str(num_str).strip() == '-' or str(num_str).strip() == '':
        return 0
    
    num_str = str(num_str).strip().replace(',', '')
    
    is_negative = False
    if num_str.startswith('-'):
        is_negative = True
        num_str = num_str[1:]
    
    try:
        num = float(num_str)
        if num.is_integer():
            num = int(num)
        else:
            num = int(round(num))
        return -num if is_negative else num
    except:
        return 0

def get_atm_strikes(spot_price, symbol):
    """Get strikes from 7 above to 7 below ATM"""
    step = STRIKE_STEPS[symbol]
    
    # Round spot to nearest strike
    atm_strike = round(spot_price / step) * step
    
    strikes = []
    for i in range(-STRIKES_RANGE, STRIKES_RANGE + 1):
        strike = atm_strike + (i * step)
        if strike > 0:
            strikes.append(strike)
    
    return sorted(strikes)

def fetch_option_chain_nse(symbol="NIFTY"):
    """Fetch option chain data from NSE including OI and Change in OI values"""
    try:
        print(f"[{symbol}] Fetching option chain from NSE...")
        
        options = Options()
        options.add_argument('--headless=new')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--disable-logging')
        options.add_argument('--log-level=3')
        options.add_argument(f"user-agent={random.choice(USER_AGENTS)}")
        options.add_experimental_option('excludeSwitches', ['enable-logging', 'enable-automation'])
        options.add_experimental_option('useAutomationExtension', False)
        
        driver = None
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            from selenium.webdriver.chrome.service import Service
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
        except ImportError:
            driver = webdriver.Chrome(options=options)
        except Exception as e:
            print(f"[{symbol}] WebDriver error: {e}")
            return None, None, None
        
        try:
            url = "https://www.nseindia.com/option-chain"
            driver.get(url)
            time.sleep(8)
            
            wait = WebDriverWait(driver, 20)
            
            try:
                select_element = wait.until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "select#equity_optionchain_select")
                ))
                
                driver.execute_script("arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('change'));", 
                                      select_element, symbol)
                print(f"[{symbol}] Selected {symbol} from dropdown")
                time.sleep(3)
            except Exception as e:
                print(f"[{symbol}] Could not select symbol dropdown: {e}")
            
            page_source = driver.page_source
            soup = BeautifulSoup(page_source, 'html.parser')
            
            spot_price = None
            spot_element = soup.find('span', {'id': 'equity_underlyingVal'})
            if spot_element:
                spot_text = spot_element.get_text(strip=True)
                numbers = re.findall(r'[\d,]+\.?\d*', spot_text)
                if numbers:
                    spot_price = float(numbers[0].replace(',', ''))
                    print(f"[{symbol}] Found spot price: {spot_price}")
            
            option_data = {}
            nse_change_data = {}  # Store NSE's Change in OI values
            
            table = soup.find('table', {'id': 'optionChainTable-indices'})
            if not table:
                tables = soup.find_all('table', class_='common_table')
                for t in tables:
                    if 'option-chain' in str(t).lower():
                        table = t
                        break
            
            if table:
                rows = table.find_all('tr')
                
                for row_idx, row in enumerate(rows):
                    cells = row.find_all(['td', 'th'])
                    if len(cells) < 23:
                        continue
                    
                    cell_texts = [cell.get_text(strip=True) for cell in cells]
                    
                    if len(cell_texts) > 11:
                        strike_text = cell_texts[11]
                        
                        if ',' in strike_text and '.' in strike_text:
                            try:
                                strike_price = float(strike_text.replace(',', ''))
                                
                                # Get OI values (absolute values)
                                call_oi_text = cell_texts[1] if len(cell_texts) > 1 else '0'
                                put_oi_text = cell_texts[21] if len(cell_texts) > 21 else '0'
                                
                                # Get CHANGE IN OI values from NSE (columns 2 and 20)
                                call_chg_text = cell_texts[2] if len(cell_texts) > 2 else '0'
                                put_chg_text = cell_texts[20] if len(cell_texts) > 20 else '0'
                                
                                call_oi = parse_number_string(call_oi_text)
                                put_oi = parse_number_string(put_oi_text)
                                call_chg = parse_number_string(call_chg_text)
                                put_chg = parse_number_string(put_chg_text)
                                
                                if call_oi > 0 or put_oi > 0:
                                    option_data[strike_price] = {
                                        'call_oi': call_oi,
                                        'put_oi': put_oi
                                    }
                                    # Store NSE's Change in OI values
                                    nse_change_data[strike_price] = {
                                        'call_chg': call_chg,
                                        'put_chg': put_chg
                                    }
                            except Exception as e:
                                continue
            
            return option_data, nse_change_data, spot_price
            
        except Exception as e:
            print(f"[{symbol}] Error during page processing: {e}")
            return None, None, None
        finally:
            if driver:
                driver.quit()
            
    except Exception as e:
        print(f"[{symbol}] Error fetching NSE data: {str(e)[:200]}")
        return None, None, None

class OptionChainMonitor:
    def __init__(self, root):
        self.root = root
        self.root.title("NSE Option Chain Monitor - 15 Minute Timeframe Analysis (ATM ±7 Strikes)")
        self.root.geometry("1600x900")
        
        # Data storage for each symbol
        self.oi_history = {symbol: [] for symbol in SYMBOLS}  # For absolute OI values (TABLE 1)
        self.nse_change_history = {symbol: [] for symbol in SYMBOLS}  # For NSE direct changes (TABLE 2)
        self.last_spot = {symbol: None for symbol in SYMBOLS}
        self.last_update_time = {symbol: None for symbol in SYMBOLS}
        
        # Store current strikes being monitored
        self.current_strikes = {symbol: [] for symbol in SYMBOLS}
        
        # Store previous data for comparison
        self.previous_call_oi = {symbol: None for symbol in SYMBOLS}
        self.previous_put_oi = {symbol: None for symbol in SYMBOLS}
        self.previous_nse_call_chg = {symbol: None for symbol in SYMBOLS}
        self.previous_nse_put_chg = {symbol: None for symbol in SYMBOLS}
        
        # Create UI
        self.create_ui()
        
        # Start monitoring
        self.start_monitoring()
    
    def create_ui(self):
        """Create the UI with two tables for each symbol"""
        # Configure ttk styles for black text
        style = ttk.Style()
        style.configure("Treeview", foreground="black", background="white", fieldbackground="white")
        style.configure("Treeview.Heading", foreground="black", background="#f0f0f0")
        
        # Create notebook for tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Create tabs for NIFTY and BANKNIFTY
        for symbol in SYMBOLS:
            self.create_symbol_tab(symbol)
        
        # Control buttons frame
        self.create_control_buttons()
    
    def create_symbol_tab(self, symbol):
        """Create a tab for a symbol with two tables"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text=symbol)
        
        # Info frame
        info_frame = ttk.Frame(tab)
        info_frame.pack(fill='x', padx=10, pady=5)
        
        # Current spot label
        spot_label = tk.Label(info_frame, text=f"Current Spot: --", 
                              font=("Arial", 12, "bold"), fg="#000000")
        spot_label.pack(side='left', padx=10)
        
        # Strikes range label
        strikes_label = tk.Label(info_frame, text=f"Monitoring: Waiting for data...", 
                                 font=("Arial", 10), fg="#000000")
        strikes_label.pack(side='left', padx=20)
        
        # Lot size label
        lot_label = tk.Label(info_frame, text=f"Lot Size: {LOT_SIZES[symbol]}", 
                            font=("Arial", 10), fg="#000000")
        lot_label.pack(side='left', padx=20)
        
        # Last update label
        update_label = tk.Label(info_frame, text="Last Update: --", 
                                font=("Arial", 10), fg="#000000")
        update_label.pack(side='right', padx=10)
        
        # Store labels
        self.spot_labels = getattr(self, 'spot_labels', {})
        self.update_labels = getattr(self, 'update_labels', {})
        self.strikes_labels = getattr(self, 'strikes_labels', {})
        self.spot_labels[symbol] = spot_label
        self.update_labels[symbol] = update_label
        self.strikes_labels[symbol] = strikes_label
        
        # ========== TABLE 1: ABSOLUTE OI VALUES (Current OI from Option Chain) ==========
        table1_frame = ttk.LabelFrame(tab, text="📊 TABLE 1: ABSOLUTE OI VALUES (Current Open Interest from Option Chain)", padding=10)
        table1_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        # Scrollbars for table 1
        v_scrollbar1 = ttk.Scrollbar(table1_frame, orient="vertical")
        h_scrollbar1 = ttk.Scrollbar(table1_frame, orient="horizontal")
        
        # Columns for table 1 - added 'strength' after 'dif'
        columns = ("date", "time", "ltp", "call_oi", "put_oi", "dif", "strength", "net_pcr", "sentiment")
        
        table1 = ttk.Treeview(table1_frame, columns=columns, show="headings",
                              yscrollcommand=v_scrollbar1.set,
                              xscrollcommand=h_scrollbar1.set,
                              height=10)
        
        v_scrollbar1.config(command=table1.yview)
        h_scrollbar1.config(command=table1.xview)
        
        v_scrollbar1.pack(side="right", fill="y")
        h_scrollbar1.pack(side="bottom", fill="x")
        
        # Configure columns for table 1
        column_config = {
            "date": {"text": "Date", "width": 100},
            "time": {"text": "Time", "width": 80},
            "ltp": {"text": "LTP", "width": 100},
            "call_oi": {"text": "Call OI (Absolute)", "width": 150},
            "put_oi": {"text": "Put OI (Absolute)", "width": 150},
            "dif": {"text": "DIF (Put - Call)", "width": 180},
            "strength": {"text": "Strength", "width": 150},
            "net_pcr": {"text": "Net PCR", "width": 100},
            "sentiment": {"text": "Sentiment", "width": 100}
        }
        
        for col, config in column_config.items():
            table1.heading(col, text=config["text"])
            table1.column(col, width=config["width"], anchor="center")
        
        table1.pack(side="left", fill="both", expand=True)
        
        # Configure tags for coloring
        table1.tag_configure("Bullish", foreground="green", background="#e8f5e9")
        table1.tag_configure("Bearish", foreground="red", background="#ffebee")
        table1.tag_configure("Neutral", foreground="orange", background="#fff3e0")
        table1.tag_configure("dif_positive", foreground="green")
        table1.tag_configure("dif_negative", foreground="red")
        table1.tag_configure("dif_zero", foreground="black")
        table1.tag_configure("increasing", foreground="green", font=("Arial", 9, "bold"))
        table1.tag_configure("decreasing", foreground="red", font=("Arial", 9, "bold"))
        # Strength tags with capsule background
        table1.tag_configure("bullish_strength", foreground="darkgreen", background="#a5d6a7", font=("Arial", 9, "bold"))
        table1.tag_configure("bearish_strength", foreground="darkred", background="#ef9a9a", font=("Arial", 9, "bold"))
        table1.tag_configure("neutral_strength", foreground="orange", background="#fff3e0")
        
        # ========== TABLE 2: NSE CHANGE IN OI VALUES ==========
        table2_frame = ttk.LabelFrame(tab, text="📊 TABLE 2: CHANGE IN OI VALUES (As reported by NSE)", padding=10)
        table2_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        # Scrollbars for table 2
        v_scrollbar2 = ttk.Scrollbar(table2_frame, orient="vertical")
        h_scrollbar2 = ttk.Scrollbar(table2_frame, orient="horizontal")
        
        table2 = ttk.Treeview(table2_frame, columns=columns, show="headings",
                              yscrollcommand=v_scrollbar2.set,
                              xscrollcommand=h_scrollbar2.set,
                              height=10)
        
        v_scrollbar2.config(command=table2.yview)
        h_scrollbar2.config(command=table2.xview)
        
        v_scrollbar2.pack(side="right", fill="y")
        h_scrollbar2.pack(side="bottom", fill="x")
        
        # Configure columns for table 2
        for col, config in column_config.items():
            heading_text = config["text"].replace("Absolute", "Change")
            if col == "strength":
                heading_text = "Strength"
            table2.heading(col, text=heading_text)
            table2.column(col, width=config["width"], anchor="center")
        
        table2.pack(side="left", fill="both", expand=True)
        
        # Configure tags for table 2
        table2.tag_configure("Bullish", foreground="green", background="#e8f5e9")
        table2.tag_configure("Bearish", foreground="red", background="#ffebee")
        table2.tag_configure("Neutral", foreground="orange", background="#fff3e0")
        table2.tag_configure("dif_positive", foreground="green")
        table2.tag_configure("dif_negative", foreground="red")
        table2.tag_configure("dif_zero", foreground="black")
        table2.tag_configure("increasing", foreground="green", font=("Arial", 9, "bold"))
        table2.tag_configure("decreasing", foreground="red", font=("Arial", 9, "bold"))
        # Strength tags with capsule background
        table2.tag_configure("bullish_strength", foreground="darkgreen", background="#a5d6a7", font=("Arial", 9, "bold"))
        table2.tag_configure("bearish_strength", foreground="darkred", background="#ef9a9a", font=("Arial", 9, "bold"))
        table2.tag_configure("neutral_strength", foreground="orange", background="#fff3e0")
        
        # Store tree references
        self.tables = getattr(self, 'tables', {})
        self.nse_tables = getattr(self, 'nse_tables', {})
        self.tables[symbol] = table1
        self.nse_tables[symbol] = table2
    
    def create_control_buttons(self):
        """Create control buttons at the bottom"""
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill='x', padx=10, pady=10)
        
        # Export button
        export_btn = tk.Button(btn_frame, text="📊 Export to Excel", 
                               command=self.export_to_excel,
                               font=("Arial", 10, "bold"),
                               bg="#4CAF50", fg="white", padx=10, pady=5)
        export_btn.pack(side='left', padx=5)
        
        # Clear history button
        clear_btn = tk.Button(btn_frame, text="🗑️ Clear History", 
                              command=self.clear_history,
                              font=("Arial", 10, "bold"),
                              bg="#f44336", fg="white", padx=10, pady=5)
        clear_btn.pack(side='left', padx=5)
        
        # Manual refresh button
        refresh_btn = tk.Button(btn_frame, text="🔄 Manual Refresh", 
                                command=self.manual_refresh,
                                font=("Arial", 10, "bold"),
                                bg="#2196F3", fg="white", padx=10, pady=5)
        refresh_btn.pack(side='right', padx=5)
        
        # Status label
        self.status_label = tk.Label(btn_frame, text="Status: Initializing...", 
                                     font=("Arial", 9), fg="#000000")
        self.status_label.pack(side='right', padx=10)
    
    def calculate_absolute_oi_values(self, option_data, selected_strikes):
        """Calculate absolute OI values (for TABLE 1)"""
        total_call_oi = 0
        total_put_oi = 0
        
        for strike in selected_strikes:
            strike_data = option_data.get(strike, {'call_oi': 0, 'put_oi': 0})
            
            call_oi = strike_data.get('call_oi', 0)
            put_oi = strike_data.get('put_oi', 0)
            
            # Apply lot size
            lot_size = LOT_SIZES.get("NIFTY" if strike < 50000 else "BANKNIFTY", 65)
            total_call_oi += call_oi * lot_size
            total_put_oi += put_oi * lot_size
        
        return total_call_oi, total_put_oi
    
    def calculate_nse_direct_changes(self, nse_change_data, selected_strikes):
        """Calculate aggregated NSE direct Change in OI values (for TABLE 2)"""
        total_call_chg = 0
        total_put_chg = 0
        
        for strike in selected_strikes:
            if strike in nse_change_data:
                call_chg = nse_change_data[strike].get('call_chg', 0)
                put_chg = nse_change_data[strike].get('put_chg', 0)
                
                lot_size = LOT_SIZES.get("NIFTY" if strike < 50000 else "BANKNIFTY", 65)
                total_call_chg += call_chg * lot_size
                total_put_chg += put_chg * lot_size
        
        return total_call_chg, total_put_chg
    
    def calculate_multiple(self, total_call, total_put):
        """Calculate how many times one is larger than the other"""
        if total_call == 0 and total_put == 0:
            return 0, "equal"
        
        abs_call = abs(total_call)
        abs_put = abs(total_put)
        
        if abs_call > abs_put:
            if abs_put == 0:
                return 999, "call_dominant"
            multiple = abs_call / abs_put
            return multiple, "call_dominant"
        elif abs_put > abs_call:
            if abs_call == 0:
                return 999, "put_dominant"
            multiple = abs_put / abs_call
            return multiple, "put_dominant"
        else:
            return 1, "equal"
    
    def determine_sentiment(self, dif, net_pcr):
        """Determine sentiment based on DIF and PCR"""
        if dif > 0 and net_pcr > 1:
            return "Bullish"
        elif dif < 0 and net_pcr < 1:
            return "Bearish"
        elif dif > 0:
            return "Bullish"
        elif dif < 0:
            return "Bearish"
        else:
            return "Neutral"
    
    def get_strength_text(self, call_val, put_val, signed=False):
        """
        Compute Strength column as a capsule-like bar with percentage and dots.
        If signed=True (for Change in OI), direction is based on the actual difference (put - call).
        If signed=False (for Absolute OI), direction is based on which absolute value is larger.
        """
        if signed:
            # Use signed values: direction based on (put - call)
            diff = put_val - call_val
            if diff > 0:
                direction = "bullish"
            elif diff < 0:
                direction = "bearish"
            else:
                direction = "neutral"
            
            # Dominance percentage = abs(diff) / max(abs(call_val), abs(put_val)) * 100, capped at 100
            max_abs = max(abs(call_val), abs(put_val))
            if max_abs == 0:
                dominance = 0
            else:
                dominance = abs(diff) / max_abs * 100
                if dominance > 100:
                    dominance = 100
            dominance = round(dominance)
        else:
            # Original logic for absolute OI (both non-negative)
            abs_call = abs(call_val)
            abs_put = abs(put_val)
            if abs_call == 0 and abs_put == 0:
                return "0%", "neutral_strength"
            if abs_put > abs_call:
                direction = "bullish"
                dominance = (abs_put - abs_call) / abs_put * 100
            elif abs_call > abs_put:
                direction = "bearish"
                dominance = (abs_call - abs_put) / abs_call * 100
            else:
                direction = "neutral"
                dominance = 0
            dominance = round(dominance)

        # Now build the display text
        if dominance < 30:
            # No bar, just sign + percentage
            if direction == "bullish":
                return f"+{dominance}%", "bullish_strength"
            elif direction == "bearish":
                return f"-{dominance}%", "bearish_strength"
            else:
                return "0%", "neutral_strength"
        else:
            # Build a 10‑block bar
            filled = min(10, round(dominance / 10))
            empty = 10 - filled
            bar = "█" * filled + "░" * empty

            # Dots based on range
            if 30 <= dominance <= 40:
                dots = "●"
            elif 41 <= dominance <= 59:
                dots = "●●"
            elif 60 <= dominance <= 79:
                dots = "●●●"
            else:  # 80–100
                dots = "●●●●"

            if direction == "bullish":
                return f"{bar} +{dominance}% {dots}", "bullish_strength"
            elif direction == "bearish":
                return f"{bar} -{dominance}% {dots}", "bearish_strength"
            else:
                return f"{bar} 0%", "neutral_strength"
    
    def format_with_trend(self, value, previous_value, formatted_value):
        """Add trend indicator to formatted value"""
        if previous_value is None:
            return formatted_value
        
        if value > previous_value:
            return f"{formatted_value} ↑"
        elif value < previous_value:
            return f"{formatted_value} ↓"
        else:
            return formatted_value
    
    def update_table(self, tree, record, is_change_table=False):
        """Update a table with new record"""
        if tree:
            # Get previous values for trend comparison
            symbol = None
            for sym in SYMBOLS:
                if tree == self.tables.get(sym) or tree == self.nse_tables.get(sym):
                    symbol = sym
                    break
            
            # Format numbers with lakh/cr format and add trend indicators
            if not is_change_table:
                # TABLE 1: Absolute OI values
                call_formatted = format_number_lakh_cr(record["call_oi"])
                put_formatted = format_number_lakh_cr(record["put_oi"])
                
                # Add trend indicators for TABLE 1
                if symbol and self.previous_call_oi[symbol] is not None:
                    if record["call_oi"] > self.previous_call_oi[symbol]:
                        call_formatted = f"{call_formatted} ↑"
                    elif record["call_oi"] < self.previous_call_oi[symbol]:
                        call_formatted = f"{call_formatted} ↓"
                
                if symbol and self.previous_put_oi[symbol] is not None:
                    if record["put_oi"] > self.previous_put_oi[symbol]:
                        put_formatted = f"{put_formatted} ↑"
                    elif record["put_oi"] < self.previous_put_oi[symbol]:
                        put_formatted = f"{put_formatted} ↓"
            else:
                # TABLE 2: Change in OI values (NSE direct changes)
                call_formatted = format_number_lakh_cr(record["call_oi"])
                put_formatted = format_number_lakh_cr(record["put_oi"])
                
                # Add trend indicators for TABLE 2
                if symbol and self.previous_nse_call_chg[symbol] is not None:
                    if record["call_oi"] > self.previous_nse_call_chg[symbol]:
                        call_formatted = f"{call_formatted} ↑"
                    elif record["call_oi"] < self.previous_nse_call_chg[symbol]:
                        call_formatted = f"{call_formatted} ↓"
                
                if symbol and self.previous_nse_put_chg[symbol] is not None:
                    if record["put_oi"] > self.previous_nse_put_chg[symbol]:
                        put_formatted = f"{put_formatted} ↑"
                    elif record["put_oi"] < self.previous_nse_put_chg[symbol]:
                        put_formatted = f"{put_formatted} ↓"
            
            # Format DIF with multiple
            dif_value = record["dif"]
            multiple = record["multiple"]
            dominance = record["dominance"]
            
            if is_change_table:
                tag_suffix = " [Change]"
            else:
                tag_suffix = ""
            
            if dominance == "call_dominant":
                if multiple >= 999:
                    dif_str = f"{format_number_lakh_cr(dif_value)} (∞x Call){tag_suffix}"
                else:
                    dif_str = f"{format_number_lakh_cr(dif_value)} ({multiple:.1f}x Call){tag_suffix}"
            elif dominance == "put_dominant":
                if multiple >= 999:
                    dif_str = f"{format_number_lakh_cr(dif_value)} (∞x Put){tag_suffix}"
                else:
                    dif_str = f"{format_number_lakh_cr(dif_value)} ({multiple:.1f}x Put){tag_suffix}"
            else:
                dif_str = f"{format_number_lakh_cr(dif_value)} (1x){tag_suffix}"
            
            # Compute Strength column: pass signed flag for TABLE 2
            strength_text, strength_tag = self.get_strength_text(record["call_oi"], record["put_oi"], signed=is_change_table)
            
            # Format LTP
            ltp_str = f"{record['ltp']:,.2f}" if record['ltp'] else "--"
            
            values = (
                record["date"],
                record["time"],
                ltp_str,
                call_formatted,
                put_formatted,
                dif_str,
                strength_text,
                record["net_pcr"],
                record["sentiment"]
            )
            
            # Determine tags for coloring
            tags = [record["sentiment"], strength_tag]
            
            # Add DIF color tag
            if dif_value > 0:
                tags.append("dif_positive")
            elif dif_value < 0:
                tags.append("dif_negative")
            else:
                tags.append("dif_zero")
            
            # Insert at top (most recent first)
            tree.insert("", 0, values=values, tags=tags)
            
            # Keep only last 100 records visible
            children = tree.get_children()
            if len(children) > 100:
                tree.delete(children[-1])
    
    def fetch_and_process(self, symbol):
        """Fetch data and process for a symbol"""
        try:
            print(f"[{symbol}] Fetching data...")
            self.status_label.config(text=f"Status: Fetching {symbol}...", fg="blue")
            
            # Fetch option chain data with NSE change values
            option_data, nse_change_data, spot_price = fetch_option_chain_nse(symbol)
            
            if option_data is None or not option_data:
                print(f"[{symbol}] Failed to fetch data or no data received")
                self.status_label.config(text=f"Status: Failed to fetch {symbol}", fg="red")
                return
            
            if spot_price is None:
                print(f"[{symbol}] Could not get spot price")
                return
            
            current_time = datetime.now()
            
            # Get dynamic strikes based on current spot price
            selected_strikes = get_atm_strikes(spot_price, symbol)
            self.current_strikes[symbol] = selected_strikes
            
            # Update strikes label
            if symbol in self.strikes_labels:
                min_strike = min(selected_strikes)
                max_strike = max(selected_strikes)
                self.strikes_labels[symbol].config(
                    text=f"Monitoring: {min_strike} to {max_strike} (ATM ±{STRIKES_RANGE})"
                )
            
            # ========== TABLE 1: ABSOLUTE OI VALUES (Current OI from Option Chain) ==========
            total_call_oi, total_put_oi = self.calculate_absolute_oi_values(option_data, selected_strikes)
            
            dif_oi = total_put_oi - total_call_oi
            multiple_oi, dominance_oi = self.calculate_multiple(total_call_oi, total_put_oi)
            net_pcr_oi = abs(total_put_oi / total_call_oi) if total_call_oi != 0 else 0
            sentiment_oi = self.determine_sentiment(dif_oi, net_pcr_oi)
            
            oi_record = {
                "date": current_time.strftime("%d-%m-%Y"),
                "time": current_time.strftime("%H:%M:%S"),
                "ltp": spot_price,
                "call_oi": total_call_oi,
                "put_oi": total_put_oi,
                "dif": dif_oi,
                "multiple": multiple_oi,
                "dominance": dominance_oi,
                "net_pcr": round(net_pcr_oi, 2),
                "sentiment": sentiment_oi
            }
            
            # Store previous values before updating
            self.previous_call_oi[symbol] = self.previous_call_oi.get(symbol)
            self.previous_put_oi[symbol] = self.previous_put_oi.get(symbol)
            
            # Add comparison info to console
            if self.previous_call_oi[symbol] is not None:
                call_change = total_call_oi - self.previous_call_oi[symbol]
                put_change = total_put_oi - self.previous_put_oi[symbol]
                print(f"[{symbol}] TABLE 1 - Call OI Change: {format_number_lakh_cr(call_change)} ({'↑' if call_change > 0 else '↓' if call_change < 0 else '='})")
                print(f"[{symbol}] TABLE 1 - Put OI Change: {format_number_lakh_cr(put_change)} ({'↑' if put_change > 0 else '↓' if put_change < 0 else '='})")
            
            self.oi_history[symbol].append(oi_record)
            self.update_table(self.tables[symbol], oi_record, is_change_table=False)
            
            # Update previous values
            self.previous_call_oi[symbol] = total_call_oi
            self.previous_put_oi[symbol] = total_put_oi
            
            print(f"[{symbol}] TABLE 1 - ABSOLUTE OI: Call: {format_number_lakh_cr(total_call_oi)}, Put: {format_number_lakh_cr(total_put_oi)}")
            
            # ========== TABLE 2: NSE CHANGE IN OI VALUES ==========
            total_nse_call_chg, total_nse_put_chg = self.calculate_nse_direct_changes(nse_change_data, selected_strikes)
            
            if total_nse_call_chg != 0 or total_nse_put_chg != 0:
                dif_nse = total_nse_put_chg - total_nse_call_chg
                multiple_nse, dominance_nse = self.calculate_multiple(total_nse_call_chg, total_nse_put_chg)
                net_pcr_nse = abs(total_nse_put_chg / total_nse_call_chg) if total_nse_call_chg != 0 else 0
                sentiment_nse = self.determine_sentiment(dif_nse, net_pcr_nse)
                
                nse_record = {
                    "date": current_time.strftime("%d-%m-%Y"),
                    "time": current_time.strftime("%H:%M:%S"),
                    "ltp": spot_price,
                    "call_oi": total_nse_call_chg,
                    "put_oi": total_nse_put_chg,
                    "dif": dif_nse,
                    "multiple": multiple_nse,
                    "dominance": dominance_nse,
                    "net_pcr": round(net_pcr_nse, 2),
                    "sentiment": sentiment_nse
                }
                
                # Store previous NSE values before updating
                self.previous_nse_call_chg[symbol] = self.previous_nse_call_chg.get(symbol)
                self.previous_nse_put_chg[symbol] = self.previous_nse_put_chg.get(symbol)
                
                # Add comparison info to console
                if self.previous_nse_call_chg[symbol] is not None:
                    nse_call_change = total_nse_call_chg - self.previous_nse_call_chg[symbol]
                    nse_put_change = total_nse_put_chg - self.previous_nse_put_chg[symbol]
                    print(f"[{symbol}] TABLE 2 - NSE Call Change: {format_number_lakh_cr(nse_call_change)} ({'↑' if nse_call_change > 0 else '↓' if nse_call_change < 0 else '='})")
                    print(f"[{symbol}] TABLE 2 - NSE Put Change: {format_number_lakh_cr(nse_put_change)} ({'↑' if nse_put_change > 0 else '↓' if nse_put_change < 0 else '='})")
                
                self.nse_change_history[symbol].append(nse_record)
                self.update_table(self.nse_tables[symbol], nse_record, is_change_table=True)
                
                # Update previous NSE values
                self.previous_nse_call_chg[symbol] = total_nse_call_chg
                self.previous_nse_put_chg[symbol] = total_nse_put_chg
                
                print(f"[{symbol}] TABLE 2 - CHANGE IN OI: Call Δ: {format_number_lakh_cr(total_nse_call_chg)}, Put Δ: {format_number_lakh_cr(total_nse_put_chg)}")
            else:
                print(f"[{symbol}] No change data available from NSE")
            
            self.last_spot[symbol] = spot_price
            self.last_update_time[symbol] = current_time
            
            # Update UI labels
            self.update_ui_labels(symbol, spot_price, current_time)
            self.status_label.config(text=f"Status: Updated {symbol} at {current_time.strftime('%H:%M:%S')}", fg="green")
            
        except Exception as e:
            print(f"[{symbol}] Error: {e}")
            import traceback
            traceback.print_exc()
            self.status_label.config(text=f"Status: Error in {symbol}", fg="red")
    
    def update_ui_labels(self, symbol, spot_price, update_time):
        """Update UI labels"""
        if symbol in self.spot_labels:
            self.spot_labels[symbol].config(text=f"Current Spot: {spot_price:,.2f}")
        
        if symbol in self.update_labels:
            self.update_labels[symbol].config(text=f"Last Update: {update_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    def monitor_symbol(self, symbol):
        """Monitor a single symbol in a loop"""
        time.sleep(2)
        
        while True:
            try:
                self.fetch_and_process(symbol)
                time.sleep(REFRESH_SECONDS)
            except Exception as e:
                print(f"[{symbol}] Monitor error: {e}")
                time.sleep(60)
    
    def start_monitoring(self):
        """Start monitoring threads for all symbols"""
        for symbol in SYMBOLS:
            thread = Thread(target=self.monitor_symbol, args=(symbol,), daemon=True)
            thread.start()
            time.sleep(3)
    
    def manual_refresh(self):
        """Manually refresh all symbols"""
        self.status_label.config(text="Status: Manual refresh initiated...", fg="blue")
        
        for symbol in SYMBOLS:
            thread = Thread(target=self.fetch_and_process, args=(symbol,), daemon=True)
            thread.start()
    
    def export_to_excel(self):
        """Export data to Excel file"""
        if not any(self.oi_history.values()) and not any(self.nse_change_history.values()):
            messagebox.showwarning("No Data", "No data to export. Please wait for data collection.")
            return
        
        try:
            export_dir = Path("exports")
            export_dir.mkdir(exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            with pd.ExcelWriter(export_dir / f"option_chain_data_{timestamp}.xlsx", engine='openpyxl') as writer:
                for symbol in SYMBOLS:
                    # Export Table 1 (Absolute OI Values)
                    if self.oi_history[symbol]:
                        df1 = pd.DataFrame(self.oi_history[symbol])
                        df1 = df1.iloc[::-1].reset_index(drop=True)
                        df1.to_excel(writer, sheet_name=f"{symbol}_Absolute_OI", index=False)
                    
                    # Export Table 2 (NSE Change in OI)
                    if self.nse_change_history[symbol]:
                        df2 = pd.DataFrame(self.nse_change_history[symbol])
                        df2 = df2.iloc[::-1].reset_index(drop=True)
                        df2.to_excel(writer, sheet_name=f"{symbol}_Change_in_OI", index=False)
            
            messagebox.showinfo("Export Successful", f"Data exported to:\nexports/option_chain_data_{timestamp}.xlsx")
            
        except Exception as e:
            messagebox.showerror("Export Failed", f"Error exporting data: {str(e)}")
    
    def clear_history(self):
        """Clear all history data"""
        if messagebox.askyesno("Confirm Clear", "Are you sure you want to clear all history data?"):
            for symbol in SYMBOLS:
                self.oi_history[symbol] = []
                self.nse_change_history[symbol] = []
                
                # Reset previous values
                self.previous_call_oi[symbol] = None
                self.previous_put_oi[symbol] = None
                self.previous_nse_call_chg[symbol] = None
                self.previous_nse_put_chg[symbol] = None
                
                if symbol in self.tables:
                    for item in self.tables[symbol].get_children():
                        self.tables[symbol].delete(item)
                
                if symbol in self.nse_tables:
                    for item in self.nse_tables[symbol].get_children():
                        self.nse_tables[symbol].delete(item)
            
            self.status_label.config(text="Status: History cleared", fg="orange")

def main():
    root = tk.Tk()
    app = OptionChainMonitor(root)
    
    def on_closing():
        print("Application closing...")
        root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()