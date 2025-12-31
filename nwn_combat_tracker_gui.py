#!/usr/bin/env python3
"""
NWN Combat Tracker - Tkinter GUI Version (Modern UI)
Tracks your Attack Bonus and a specific target's stats in real-time.
"""

import re
import time
import os
import threading
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


# Color scheme - Dark modern theme
COLORS = {
    'bg_dark': '#0d1117',
    'bg_medium': '#161b22', 
    'bg_light': '#21262d',
    'bg_input': '#0d1117',
    'border': '#30363d',
    'text': '#e6edf3',
    'text_dim': '#7d8590',
    'accent': '#58a6ff',
    'accent_dim': '#388bfd',
    'gold': '#d4a017',
    'green': '#3fb950',
    'red': '#f85149',
    'orange': '#d29922',
    'purple': '#a371f7',
    # Damage type colors
    'dmg_fire': '#f85149',       # red
    'dmg_cold': '#79c0ff',       # light blue
    'dmg_acid': '#3fb950',       # green
    'dmg_negative': '#6e7681',   # gray (darker than text_dim)
    'dmg_divine': '#f0e68c',     # yellow (khaki)
    'dmg_electrical': '#58a6ff', # blue
    'dmg_magical': '#d2a8ff',    # light purple
    'dmg_pure': '#8957e5',       # darker purple
    'dmg_sonic': '#e3b341',      # yellow-orange
    'dmg_positive': '#ffffff',   # white
    'dmg_physical': '#e6edf3',   # normal text
}


# Target aliases for quick selection
TARGET_ALIASES = {
    "moore1": "XANASDEM - LEGION CAPTAIN",
    "moore2": "",
    "moore3": "",
    "moore4": "",
    "moore5": "",
    "goblin3": "General Korgan",
}

# Map damage types to color keys (partial match, case insensitive)
DAMAGE_TYPE_COLORS = {
    'fire': 'dmg_fire',
    'cold': 'dmg_cold',
    'acid': 'dmg_acid',
    'negative': 'dmg_negative',
    'divine': 'dmg_divine',
    'elec': 'dmg_electrical',  # matches Electrical
    'magic': 'dmg_magical',    # matches Magical
    'pure': 'dmg_pure',
    'sonic': 'dmg_sonic',
    'posi': 'dmg_positive',    # matches Positive Energy
    'phys': 'dmg_physical',    # matches Physical
}


@dataclass
class EnemySaves:
    name: str
    fortitude: Optional[int] = None
    reflex: Optional[int] = None
    will: Optional[int] = None
    
    def update_save(self, save_type: str, bonus: int):
        if save_type == 'fort':
            if self.fortitude is None or bonus > self.fortitude:
                self.fortitude = bonus
        elif save_type == 'ref':
            if self.reflex is None or bonus > self.reflex:
                self.reflex = bonus
        elif save_type == 'will':
            if self.will is None or bonus > self.will:
                self.will = bonus


@dataclass
class EnemyAC:
    name: str
    min_hit: Optional[int] = None
    max_miss: Optional[int] = None
    
    def record_hit(self, total: int):
        if self.min_hit is None or total < self.min_hit:
            self.min_hit = total
    
    def record_miss(self, total: int, was_nat1: bool = False):
        if not was_nat1:
            if self.max_miss is None or total > self.max_miss:
                self.max_miss = total
    
    def get_ac_estimate(self) -> str:
        if self.min_hit is not None and self.max_miss is not None:
            if self.max_miss + 1 == self.min_hit:
                return str(self.min_hit)
            elif self.max_miss < self.min_hit:
                return f"{self.max_miss + 1}-{self.min_hit}"
            else:
                return f"~{self.min_hit}"
        elif self.min_hit is not None:
            return f"≤{self.min_hit}"
        elif self.max_miss is not None:
            return f">{self.max_miss}"
        return "?"


@dataclass 
class AttackBonus:
    current: int = 0
    max_observed: int = 0
    last_updated: datetime = field(default_factory=datetime.now)
    recent_attacks: list = field(default_factory=list)  # [(timestamp, bonus), ...]
    window_seconds: int = 30  # Rolling window for max calculation
    
    def update(self, bonus: int):
        now = datetime.now()
        self.current = bonus
        self.recent_attacks.append((now, bonus))
        self._prune_old()
        self.max_observed = max(ab for _, ab in self.recent_attacks) if self.recent_attacks else bonus
        self.last_updated = now
    
    def _prune_old(self):
        """Remove attacks older than window_seconds"""
        cutoff = datetime.now() - timedelta(seconds=self.window_seconds)
        self.recent_attacks = [(t, ab) for t, ab in self.recent_attacks if t > cutoff]
    
    def refresh(self):
        """Call periodically to update max even without new attacks"""
        self._prune_old()
        if self.recent_attacks:
            self.max_observed = max(ab for _, ab in self.recent_attacks)


class NWNCombatTracker:
    def __init__(self, player_name: str = "Azoni Stout", target_filter: str = "", exact_match: bool = False, reset_interval: int = 18, auto_track: bool = False):
        self.player_name = player_name
        self.target_filter = target_filter.lower()
        self.exact_match = exact_match
        self.reset_interval = reset_interval
        self.auto_track = auto_track  # Lock mode - lock onto first target
        
        self._compile_patterns()
        
        self.target_saves: Optional[EnemySaves] = None
        self.target_ac: Optional[EnemyAC] = None
        self.target_name: str = ""
        self.target_ab: Optional[int] = None
        self.attack_bonus = AttackBonus()
        
        self.hits = 0
        self.misses = 0
        self.crits = 0
        self.conceals = 0
        self.target_conceal_pct: Optional[int] = None
        self.damage_dealt = 0
        self.damage_dealt_crits = []
        self.damage_dealt_normal = []
        self.shield_damage_by_type: dict[str, int] = {}
        self.shield_damage_total = 0
        self.weapon_buff_damage_by_type: dict[str, int] = {}
        self.weapon_buff_damage_total = 0
        self.last_attack_was_player = False
        self.damage_taken = []  # All damage amounts taken from target
        self.damage_taken_by_type: dict[str, list[int]] = {}  # By damage type
        self.player_pots = 0
        self.target_pots = 0
        self.last_player_hit_was_crit = False
        self.last_target_hit_was_crit = False
        self.encounter_start: Optional[datetime] = None
        self.encounter_last: Optional[datetime] = None
        self.target_dead = False
        self.kill_time: Optional[datetime] = None
    
    def _compile_patterns(self):
        self.pat_prefix = re.compile(r'^\[CHAT WINDOW TEXT\]\s*\[[^\]]+\]\s*', re.IGNORECASE)
        
        self.pat_attack = re.compile(
            r'(?:Attack Of Opportunity\s*:\s*)?'
            r'(?P<attacker>.+?)\s+attacks\s+(?P<target>.+?)\s*:\s*'
            r'\*(?P<outcome>hit|miss|critical hit|parried|resisted)\*\s*'
            r'(?::\s*\((?P<roll>\d+)\s*\+\s*(?P<bonus>-?\d+)\s*=\s*(?P<total>\d+)\))?',
            re.IGNORECASE
        )
        
        self.pat_attack_conceal = re.compile(
            r'(?:Attack Of Opportunity\s*:\s*)?'
            r'(?P<attacker>.+?)\s+attacks\s+(?P<target>.+?)\s*:\s*'
            r'\*target concealed:\s*(?P<conceal>\d+)%\*\s*:\s*'
            r'\((?P<roll>\d+)\s*\+\s*(?P<bonus>-?\d+)\s*=\s*(?P<total>\d+)\)\s*:\s*'
            r'\*(?P<outcome>hit|miss|critical hit|parried|resisted)\*',
            re.IGNORECASE
        )
        
        self.pat_attack_conceal_pending = re.compile(
            r'(?:Attack Of Opportunity\s*:\s*)?'
            r'(?P<attacker>.+?)\s+attacks\s+(?P<target>.+?)\s*:\s*'
            r'\*target concealed:\s*(?P<conceal>\d+)%\*\s*:\s*'
            r'\((?P<roll>\d+)\s*\+\s*(?P<bonus>-?\d+)\s*=\s*(?P<total>\d+)\)\s*$',
            re.IGNORECASE
        )
        
        self.pat_conceal_miss = re.compile(
            r'(?P<attacker>.+?)\s+attacks\s+(?P<target>.+?)\s*:\s*'
            r'\*target concealed:\s*(?P<conceal>\d+)%\*\s*$',
            re.IGNORECASE
        )
        
        self.pat_save = re.compile(
            r'(?:SAVE:\s*)?(?P<target>.+?)\s*:\s*'
            r'(?P<save_type>Fort|Fortitude|Reflex|Will)\s+Save(?:\s+vs\.\s*[^:]+?)?\s*:\s*'
            r'\*(?P<outcome>success|failed)\*\s*:\s*'
            r'\((?P<roll>\d+)\s*\+\s*(?P<bonus>-?\d+)\s*(?:=\s*\d+\s*)?vs\.\s*DC:\s*(?P<dc>\d+)\)',
            re.IGNORECASE
        )
        
        self.pat_damage = re.compile(
            r'(?P<attacker>.+?)\s+damages\s+(?P<target>.+?):\s*(?P<amount>\d+)(?:\s*\((?P<breakdown>[^)]+)\))?',
            re.IGNORECASE
        )
        
        self.pat_damage_type = re.compile(r'(\d+)\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)', re.IGNORECASE)
        
        self.pat_potion = re.compile(r'(?P<user>.+?)\s+uses\s+(?P<potion>Potion of Heal.*)', re.IGNORECASE)
        self.pat_undead_heal = re.compile(r'(?P<caster>.+?)\s+casts\s+Harm Self \(Undead\)', re.IGNORECASE)
        self.pat_kill = re.compile(r'(?P<killer>.+?)\s+killed\s+(?P<target>.+)', re.IGNORECASE)
    
    def _strip_prefix(self, line: str) -> str:
        return self.pat_prefix.sub('', line).strip()
    
    def _is_player(self, name: str) -> bool:
        return self.player_name and self.player_name.lower() in name.lower()
    
    def _matches_target(self, name: str) -> bool:
        name = name.strip().rstrip('.!,').lower()
        # Lock mode: match current target, or any non-player target if none set yet
        if self.auto_track:
            if self._is_player(name):
                return False
            if self.target_name:
                return self.target_name.lower() == name
            else:
                return True
        
        # Manual mode: use filter
        if not self.target_filter:
            return False
        if self.exact_match:
            return self.target_filter == name
        return self.target_filter in name
    
    def _set_target(self, name: str):
        if not self.target_name:
            self.target_name = name.strip().rstrip('.!,')
            self.target_saves = EnemySaves(name=self.target_name)
            self.target_ac = EnemyAC(name=self.target_name)
    
    def _update_encounter_time(self):
        now = datetime.now()
        if self.encounter_start is None:
            self.encounter_start = now
        self.encounter_last = now
    
    def parse_line(self, line: str):
        line = self._strip_prefix(line.strip())
        if not line:
            return
        
        match = self.pat_attack_conceal.search(line)
        conceal = None
        is_conceal_pending = False
        
        if match:
            conceal = int(match.group('conceal'))
        else:
            match = self.pat_attack_conceal_pending.search(line)
            if match:
                conceal = int(match.group('conceal'))
                is_conceal_pending = True
            else:
                match = self.pat_attack.search(line)
        
        if match:
            attacker = match.group('attacker').strip()
            target = match.group('target').strip()
            outcome = (match.group('outcome') if 'outcome' in match.groupdict() and match.group('outcome') else '').lower()
            roll_str = match.group('roll')
            bonus_str = match.group('bonus')
            total_str = match.group('total')
            
            roll = int(roll_str) if roll_str else None
            bonus = int(bonus_str) if bonus_str else None
            total = int(total_str) if total_str else None
            
            is_hit = 'hit' in outcome and 'miss' not in outcome
            is_crit = 'critical' in outcome
            is_miss = outcome in ('miss', 'parried', 'resisted')
            was_nat1 = roll == 1 if roll else False
            
            if self._is_player(attacker) and self._matches_target(target):
                self._set_target(target)
                self._update_encounter_time()
                
                if conceal is not None:
                    self.target_conceal_pct = conceal
                
                if bonus is not None:
                    self.attack_bonus.update(bonus)
                
                if not is_conceal_pending:
                    if is_hit:
                        self.hits += 1
                        self.last_attack_was_player = True
                        if is_crit:
                            self.crits += 1
                            self.last_player_hit_was_crit = True
                        else:
                            self.last_player_hit_was_crit = False
                        if total is not None and self.target_ac:
                            self.target_ac.record_hit(total)
                    elif is_miss:
                        self.misses += 1
                        if total is not None and self.target_ac:
                            self.target_ac.record_miss(total, was_nat1)
            
            elif self._matches_target(attacker) and self._is_player(target):
                self._set_target(attacker)  # Start tracking when target attacks us
                self._update_encounter_time()
                if is_hit:
                    self.last_attack_was_player = False
                    if bonus is not None:
                        if self.target_ab is None or bonus > self.target_ab:
                            self.target_ab = bonus
                if is_crit:
                    self.last_target_hit_was_crit = True
                elif is_hit:
                    self.last_target_hit_was_crit = False
        
        if not match:
            cmatch = self.pat_conceal_miss.search(line)
            if cmatch:
                attacker = cmatch.group('attacker').strip()
                target = cmatch.group('target').strip()
                conceal = int(cmatch.group('conceal'))
                
                if self._is_player(attacker) and self._matches_target(target):
                    self._set_target(target)
                    self._update_encounter_time()
                    self.target_conceal_pct = conceal
                    self.conceals += 1
        
        match = self.pat_save.search(line)
        if match:
            target = match.group('target').strip()
            save_type = match.group('save_type').lower()
            bonus = int(match.group('bonus'))
            
            if save_type in ('fort', 'fortitude'):
                save_key = 'fort'
            elif save_type == 'reflex':
                save_key = 'ref'
            else:
                save_key = 'will'
            
            if self._matches_target(target):
                self._set_target(target)
                self._update_encounter_time()
                if self.target_saves:
                    self.target_saves.update_save(save_key, bonus)
        
        match = self.pat_damage.search(line)
        if match:
            attacker = match.group('attacker').strip()
            target = match.group('target').strip()
            amount = int(match.group('amount'))
            breakdown = match.group('breakdown')
            
            if self._is_player(attacker) and self._matches_target(target):
                self._set_target(target)
                self._update_encounter_time()
                
                is_single_type = False
                single_type_info = None
                if breakdown:
                    damage_types = []
                    for dmg_match in self.pat_damage_type.finditer(breakdown):
                        dmg_amount = int(dmg_match.group(1))
                        dmg_type = dmg_match.group(2).title()
                        if dmg_amount > 0:
                            damage_types.append((dmg_type, dmg_amount))
                    
                    if len(damage_types) == 1:
                        is_single_type = True
                        single_type_info = damage_types[0]
                
                if is_single_type:
                    dtype, damount = single_type_info
                    if self.last_attack_was_player:
                        self.weapon_buff_damage_total += amount
                        if dtype not in self.weapon_buff_damage_by_type:
                            self.weapon_buff_damage_by_type[dtype] = 0
                        self.weapon_buff_damage_by_type[dtype] += amount
                    else:
                        self.shield_damage_total += amount
                        if dtype not in self.shield_damage_by_type:
                            self.shield_damage_by_type[dtype] = 0
                        self.shield_damage_by_type[dtype] += amount
                else:
                    self.damage_dealt += amount
                    if self.last_player_hit_was_crit:
                        self.damage_dealt_crits.append(amount)
                    else:
                        self.damage_dealt_normal.append(amount)
                        
            elif self._matches_target(attacker) and self._is_player(target):
                self._set_target(attacker)  # Start tracking on damage received too
                self._update_encounter_time()
                self.damage_taken.append(amount)
                
                if breakdown:
                    for dmg_match in self.pat_damage_type.finditer(breakdown):
                        dmg_amount = int(dmg_match.group(1))
                        dmg_type = dmg_match.group(2).title()
                        # Record all types, even 0, for accurate hit counting
                        if dmg_type not in self.damage_taken_by_type:
                            self.damage_taken_by_type[dmg_type] = []
                        self.damage_taken_by_type[dmg_type].append(dmg_amount)
        
        match = self.pat_potion.search(line)
        if match:
            user = match.group('user').strip()
            if self._is_player(user):
                self.player_pots += 1
            elif self._matches_target(user):
                self._set_target(user)
                self._update_encounter_time()
                self.target_pots += 1
        
        match = self.pat_undead_heal.search(line)
        if match:
            caster = match.group('caster').strip()
            if self._matches_target(caster):
                self._set_target(caster)
                self._update_encounter_time()
                self.target_pots += 1
        
        match = self.pat_kill.search(line)
        if match:
            killer = match.group('killer').strip()
            target = match.group('target').strip().rstrip('.!,')  # Remove trailing punctuation
            if self._is_player(killer) and self._matches_target(target):
                self.target_dead = True
                self.kill_time = datetime.now()
    
    def reset(self):
        self.target_saves = None
        self.target_ac = None
        self.target_name = ""
        self.target_ab = None
        self.hits = 0
        self.misses = 0
        self.crits = 0
        self.conceals = 0
        self.target_conceal_pct = None
        self.damage_dealt = 0
        self.damage_dealt_crits = []
        self.damage_dealt_normal = []
        self.shield_damage_by_type = {}
        self.shield_damage_total = 0
        self.weapon_buff_damage_by_type = {}
        self.weapon_buff_damage_total = 0
        self.last_attack_was_player = False
        self.damage_taken = []
        self.damage_taken_by_type = {}
        self.player_pots = 0
        self.target_pots = 0
        self.last_player_hit_was_crit = False
        self.last_target_hit_was_crit = False
        self.encounter_start = None
        self.encounter_last = None
        self.target_dead = False
        self.kill_time = None


def is_nwn_log_file(filename: str) -> bool:
    name_lower = filename.lower()
    if name_lower.startswith('nwclientlog'):
        remainder = name_lower[11:]
        if remainder == '' or remainder == '.txt':
            return True
        if remainder.isdigit():
            return True
        if len(remainder) > 4 and remainder[:-4].isdigit() and remainder.endswith('.txt'):
            return True
    return False


def find_latest_log(log_dir: str) -> Optional[str]:
    if not os.path.isdir(log_dir):
        return None
    
    log_files = []
    for f in os.listdir(log_dir):
        if is_nwn_log_file(f):
            full_path = os.path.join(log_dir, f)
            if os.path.isfile(full_path):
                mtime = os.path.getmtime(full_path)
                log_files.append((full_path, mtime))
    
    if not log_files:
        return None
    
    log_files.sort(key=lambda x: x[1], reverse=True)
    return log_files[0][0]


class NWNTrackerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("NWN Combat Tracker")
        self.root.geometry("550x780")
        self.root.minsize(500, 720)
        self.root.resizable(True, True)
        self.root.configure(bg=COLORS['bg_dark'])
        
        self.default_paths = [
            r"C:\Users\charl\OneDrive\Documents\Neverwinter Nights\logs",
            os.path.expanduser("~/Documents/Neverwinter Nights/logs"),
        ]
        
        self.tracker: Optional[NWNCombatTracker] = None
        self.running = False
        self.log_thread: Optional[threading.Thread] = None
        self.log_path = ""
        self.file_position = 0
        
        self._create_widgets()
        self._auto_detect_log()
        self._try_detect_player()  # Try to auto-detect player name silently
    
    def _create_widgets(self):
        # Main container
        main = tk.Frame(self.root, bg=COLORS['bg_dark'], padx=16, pady=12)
        main.pack(fill='both', expand=True)
        
        # ═══════════════════════════════════════════════════════════
        # HEADER (compact)
        # ═══════════════════════════════════════════════════════════
        header = tk.Frame(main, bg=COLORS['bg_dark'])
        header.pack(fill='x', pady=(0, 12))
        
        tk.Label(header, text="⚔", font=('Segoe UI', 20), 
                bg=COLORS['bg_dark'], fg=COLORS['gold']).pack(side='left')
        
        tk.Label(header, text=" NWN Combat Tracker", font=('Segoe UI', 14, 'bold'),
                bg=COLORS['bg_dark'], fg=COLORS['text']).pack(side='left', padx=(4, 0))
        
        self.status_label = tk.Label(header, text="● Stopped", font=('Segoe UI', 9),
                                    bg=COLORS['bg_dark'], fg=COLORS['text_dim'])
        self.status_label.pack(side='right')
        
        # ═══════════════════════════════════════════════════════════
        # CONFIG SECTION (compact)
        # ═══════════════════════════════════════════════════════════
        config_frame = tk.Frame(main, bg=COLORS['bg_medium'], relief='flat')
        config_frame.pack(fill='x', pady=(0, 10))
        config_frame.configure(highlightbackground=COLORS['border'], highlightthickness=1)
        
        config_inner = tk.Frame(config_frame, bg=COLORS['bg_medium'], padx=12, pady=10)
        config_inner.pack(fill='x', padx=1, pady=1)
        
        # Grid for config fields
        fields = tk.Frame(config_inner, bg=COLORS['bg_medium'])
        fields.pack(fill='x')
        fields.columnconfigure(1, weight=1)
        
        # Style comboboxes (do this once before creating them)
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Dark.TCombobox', 
                       fieldbackground=COLORS['bg_input'],
                       background=COLORS['bg_light'],
                       foreground=COLORS['text'],
                       arrowcolor=COLORS['text'],
                       bordercolor=COLORS['border'],
                       lightcolor=COLORS['bg_input'],
                       darkcolor=COLORS['bg_input'])
        style.map('Dark.TCombobox',
                 fieldbackground=[('readonly', COLORS['bg_input'])],
                 selectbackground=[('readonly', COLORS['bg_light'])],
                 selectforeground=[('readonly', COLORS['text'])])
        
        # Style the dropdown menu
        self.root.option_add('*TCombobox*Listbox.background', COLORS['bg_medium'])
        self.root.option_add('*TCombobox*Listbox.foreground', COLORS['text'])
        self.root.option_add('*TCombobox*Listbox.selectBackground', COLORS['accent'])
        self.root.option_add('*TCombobox*Listbox.selectForeground', 'white')
        
        # Player field with detect button
        tk.Label(fields, text="Player", font=('Segoe UI', 9),
                bg=COLORS['bg_medium'], fg=COLORS['text_dim'], width=8, anchor='w').grid(row=0, column=0, sticky='w', pady=2)
        
        player_row = tk.Frame(fields, bg=COLORS['bg_medium'])
        player_row.grid(row=0, column=1, sticky='ew', pady=2)
        player_row.columnconfigure(0, weight=1)
        
        self.player_var = tk.StringVar(value="")
        player_entry = tk.Entry(player_row, textvariable=self.player_var, font=('Segoe UI', 10),
                               bg=COLORS['bg_input'], fg=COLORS['text'], 
                               insertbackground=COLORS['text'], relief='flat',
                               highlightthickness=1, highlightbackground=COLORS['border'],
                               highlightcolor=COLORS['accent'])
        player_entry.grid(row=0, column=0, sticky='ew', ipady=4)
        
        detect_btn = tk.Button(player_row, text="Detect", command=self._detect_player,
                              bg=COLORS['bg_light'], fg=COLORS['text'], relief='flat',
                              font=('Segoe UI', 8), padx=8, cursor='hand2',
                              activebackground=COLORS['border'], activeforeground=COLORS['text'])
        detect_btn.grid(row=0, column=1, padx=(6, 0))
        
        # Target field
        tk.Label(fields, text="Target", font=('Segoe UI', 9),
                bg=COLORS['bg_medium'], fg=COLORS['text_dim'], width=8, anchor='w').grid(row=1, column=0, sticky='w', pady=2)
        
        target_row = tk.Frame(fields, bg=COLORS['bg_medium'])
        target_row.grid(row=1, column=1, sticky='ew', pady=2)
        target_row.columnconfigure(0, weight=1)
        
        self.target_var = tk.StringVar()
        self.target_entry = tk.Entry(target_row, textvariable=self.target_var, font=('Segoe UI', 10),
                               bg=COLORS['bg_input'], fg=COLORS['text'],
                               insertbackground=COLORS['text'], relief='flat',
                               highlightthickness=1, highlightbackground=COLORS['border'],
                               highlightcolor=COLORS['accent'])
        self.target_entry.grid(row=0, column=0, sticky='ew', ipady=4)
        
        self.exact_var = tk.BooleanVar(value=False)
        exact_cb = tk.Checkbutton(target_row, text="Exact", variable=self.exact_var,
                                 bg=COLORS['bg_medium'], fg=COLORS['text'], 
                                 selectcolor=COLORS['bg_input'], activebackground=COLORS['bg_medium'],
                                 activeforeground=COLORS['text'], font=('Segoe UI', 9),
                                 highlightthickness=0)
        exact_cb.grid(row=0, column=1, padx=(8, 0))
        
        # Preset dropdown
        tk.Label(fields, text="Preset", font=('Segoe UI', 9),
                bg=COLORS['bg_medium'], fg=COLORS['text_dim'], width=8, anchor='w').grid(row=2, column=0, sticky='w', pady=2)
        
        alias_list = [f"{k}: {v}" for k, v in TARGET_ALIASES.items() if v]
        self.alias_var = tk.StringVar()
        
        alias_combo = ttk.Combobox(fields, textvariable=self.alias_var, values=alias_list, 
                                  state="readonly", font=('Segoe UI', 9), style='Dark.TCombobox')
        alias_combo.grid(row=2, column=1, sticky='ew', pady=2, ipady=2)
        alias_combo.bind("<<ComboboxSelected>>", self._on_alias_select)
        
        # Log path
        tk.Label(fields, text="Log", font=('Segoe UI', 9),
                bg=COLORS['bg_medium'], fg=COLORS['text_dim'], width=8, anchor='w').grid(row=3, column=0, sticky='w', pady=2)
        
        log_row = tk.Frame(fields, bg=COLORS['bg_medium'])
        log_row.grid(row=3, column=1, sticky='ew', pady=2)
        log_row.columnconfigure(0, weight=1)
        
        self.log_var = tk.StringVar()
        log_entry = tk.Entry(log_row, textvariable=self.log_var, font=('Segoe UI', 8),
                            bg=COLORS['bg_input'], fg=COLORS['text_dim'],
                            insertbackground=COLORS['text'], relief='flat',
                            highlightthickness=1, highlightbackground=COLORS['border'],
                            highlightcolor=COLORS['accent'])
        log_entry.grid(row=0, column=0, sticky='ew', ipady=4)
        
        browse_btn = tk.Button(log_row, text="📁", command=self._browse_log,
                              bg=COLORS['bg_light'], fg=COLORS['text'], relief='flat',
                              font=('Segoe UI', 9), padx=8, cursor='hand2',
                              activebackground=COLORS['border'], activeforeground=COLORS['text'])
        browse_btn.grid(row=0, column=1, padx=(6, 0))
        
        # ═══════════════════════════════════════════════════════════
        # BUTTONS (compact)
        # ═══════════════════════════════════════════════════════════
        btn_frame = tk.Frame(main, bg=COLORS['bg_dark'])
        btn_frame.pack(fill='x', pady=(0, 10))
        
        self.start_btn = tk.Button(btn_frame, text="▶  Start Tracking", command=self._toggle_tracking,
                                  bg=COLORS['accent'], fg='white', relief='flat',
                                  font=('Segoe UI', 9, 'bold'), padx=14, pady=6, cursor='hand2',
                                  activebackground=COLORS['accent_dim'], activeforeground='white')
        self.start_btn.pack(side='left')
        
        self.new_target_btn = tk.Button(btn_frame, text="⟳  New Target", command=self._new_target,
                                  bg=COLORS['bg_light'], fg=COLORS['green'], relief='flat',
                                  font=('Segoe UI', 9, 'bold'), padx=12, pady=6, cursor='hand2',
                                  activebackground=COLORS['border'], activeforeground=COLORS['green'])
        self.new_target_btn.pack(side='left', padx=(8, 0))
        
        self.reset_btn = tk.Button(btn_frame, text="↺  Reset", command=self._reset_stats,
                                  bg=COLORS['bg_light'], fg=COLORS['text'], relief='flat',
                                  font=('Segoe UI', 9), padx=12, pady=6, cursor='hand2',
                                  activebackground=COLORS['border'], activeforeground=COLORS['text'])
        self.reset_btn.pack(side='left', padx=(8, 0))
        
        # ═══════════════════════════════════════════════════════════
        # STATS DISPLAY
        # ═══════════════════════════════════════════════════════════
        stats_frame = tk.Frame(main, bg=COLORS['bg_dark'], highlightbackground=COLORS['border'],
                              highlightthickness=1)
        stats_frame.pack(fill='both', expand=True)
        
        self.stats_text = tk.Text(stats_frame, wrap='word', font=('Consolas', 11),
                                 bg=COLORS['bg_dark'], fg=COLORS['text'], relief='flat',
                                 padx=16, pady=12, cursor='arrow', 
                                 selectbackground=COLORS['bg_light'],
                                 highlightthickness=0)
        self.stats_text.pack(fill='both', expand=True)
        self.stats_text.config(state='disabled')
        
        # Configure text tags for styling (colors only for performance)
        self.stats_text.tag_configure('header', foreground=COLORS['accent'])
        self.stats_text.tag_configure('target_name', foreground=COLORS['gold'])
        self.stats_text.tag_configure('label', foreground=COLORS['text_dim'])
        self.stats_text.tag_configure('value', foreground=COLORS['text'])
        self.stats_text.tag_configure('highlight', foreground=COLORS['green'])
        self.stats_text.tag_configure('warning', foreground=COLORS['orange'])
        self.stats_text.tag_configure('danger', foreground=COLORS['red'])
        self.stats_text.tag_configure('muted', foreground=COLORS['text_dim'])
        self.stats_text.tag_configure('big', foreground=COLORS['text'])
        # Damage type colors
        for color_key in COLORS:
            if color_key.startswith('dmg_'):
                self.stats_text.tag_configure(color_key, foreground=COLORS[color_key])
    
    def _on_alias_select(self, event):
        selection = self.alias_var.get()
        if selection:
            alias = selection.split(":")[0]
            target = TARGET_ALIASES.get(alias, "")
            if target:
                self.target_var.set(target)
                self.exact_var.set(True)
                self.target_entry.config(fg=COLORS['text'], state='normal')
    
    def _try_detect_player(self):
        """Silently try to detect player name on startup"""
        name = self._scan_log_for_player()
        if name:
            self.player_var.set(name)
    
    def _detect_player(self):
        """Detect player name with user feedback"""
        name = self._scan_log_for_player()
        if name:
            self.player_var.set(name)
        else:
            messagebox.showinfo("Detect Player", "Could not detect player name.\nTry gaining XP or using a heal potion, then detect again.")
    
    def _scan_log_for_player(self):
        """Scan log file for player name patterns"""
        log_path = self.log_var.get().strip()
        if not log_path or not os.path.exists(log_path):
            return None
        
        if os.path.isdir(log_path):
            log_file = find_latest_log(log_path)
            if not log_file:
                return None
        else:
            log_file = log_path
        
        # Patterns to detect player name
        # Note: logs have format [CHAT WINDOW TEXT] [Timestamp] Content
        # Use (?:\[.*?\]\s*)* to skip any number of bracketed prefixes
        prefix = r'^(?:\[.*?\]\s*)*'
        pat_xp = re.compile(prefix + r'(?P<n>.+?)\s+Experience Points Gained:', re.IGNORECASE)
        pat_selfcast = re.compile(prefix + r'(?P<n>.+?)\s+casts\s+.+?\s+on\s+(?P<t>.+?)\.?\s*$', re.IGNORECASE)
        pat_uses = re.compile(prefix + r'(?P<n>.+?)\s+uses\s+Potion of Heal', re.IGNORECASE)
        # [ShortName] FullName: [Talk] - but after all prefixes are stripped
        pat_talk = re.compile(prefix + r'\[.+?\]\s+(?P<n>.+?):\s+\[Talk\]', re.IGNORECASE)
        # PlayerName: [TELEPORT] or other menu actions
        pat_action = re.compile(prefix + r'(?P<n>.+?):\s+\[(TELEPORT|RAID)\]', re.IGNORECASE)
        
        candidates = {}
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f.readlines()[-500:]:
                    # [Talk] pattern - most reliable
                    m = pat_talk.search(line)
                    if m:
                        name = m.group('n').strip()
                        if 1 < len(name) < 40 and not name.startswith('['):
                            candidates[name] = candidates.get(name, 0) + 15
                    
                    # XP pattern - very reliable
                    m = pat_xp.search(line)
                    if m:
                        name = m.group('n').strip()
                        if 1 < len(name) < 40 and not name.startswith('['):
                            candidates[name] = candidates.get(name, 0) + 10
                    
                    # Action menu pattern
                    m = pat_action.search(line)
                    if m:
                        name = m.group('n').strip()
                        if 1 < len(name) < 40 and not name.startswith('['):
                            candidates[name] = candidates.get(name, 0) + 8
                    
                    # Self-cast pattern
                    m = pat_selfcast.search(line)
                    if m and m.group('n').strip() == m.group('t').strip():
                        name = m.group('n').strip()
                        if len(name) > 1 and not name.startswith('['):
                            candidates[name] = candidates.get(name, 0) + 5
                    
                    # Uses heal potion
                    m = pat_uses.search(line)
                    if m:
                        name = m.group('n').strip()
                        if 1 < len(name) < 40 and not name.startswith('['):
                            candidates[name] = candidates.get(name, 0) + 3
            
            return max(candidates, key=candidates.get) if candidates else None
        except:
            return None

    def _browse_log(self):
        path = filedialog.askdirectory(title="Select NWN Logs Directory")
        if path:
            self.log_var.set(path)
    
    def _auto_detect_log(self):
        for path in self.default_paths:
            if os.path.exists(path):
                self.log_var.set(path)
                return
    
    def _toggle_tracking(self):
        if self.running:
            self._stop_tracking()
        else:
            self._start_tracking()
    
    def _start_tracking(self):
        player = self.player_var.get().strip()
        if not player:
            messagebox.showerror("Error", "Please enter your player name")
            return
        
        target = self.target_var.get().strip()
        lock_mode = not target  # Auto lock mode if no target specified
        
        log_path = self.log_var.get().strip()
        if not log_path or not os.path.exists(log_path):
            messagebox.showerror("Error", "Please select a valid log path")
            return
        
        if os.path.isdir(log_path):
            log_file = find_latest_log(log_path)
            if not log_file:
                messagebox.showerror("Error", "No NWN log files found")
                return
            self.log_path = log_file
        else:
            self.log_path = log_path
        
        self.tracker = NWNCombatTracker(
            player_name=player,
            target_filter=target,
            exact_match=self.exact_var.get(),
            auto_track=lock_mode
        )
        
        with open(self.log_path, 'r', encoding='utf-8', errors='ignore') as f:
            f.seek(0, 2)
            self.file_position = f.tell()
        
        self.running = True
        self.start_btn.config(text="⏹  Stop Tracking", bg=COLORS['red'])
        
        if lock_mode:
            self.status_label.config(text="● Waiting to lock...", fg=COLORS['orange'])
        else:
            self.status_label.config(text="● Tracking", fg=COLORS['green'])
        
        self.log_thread = threading.Thread(target=self._tail_log, daemon=True)
        self.log_thread.start()
        
        self._update_display()
    
    def _stop_tracking(self):
        self.running = False
        self.start_btn.config(text="▶  Start Tracking", bg=COLORS['accent'])
        self.status_label.config(text="● Stopped", fg=COLORS['text_dim'])
    
    def _reset_stats(self):
        if self.tracker:
            self.tracker.reset()
            self._render_stats()
    
    def _new_target(self):
        """Clear current target and wait for new one"""
        if self.tracker:
            self.tracker.reset()
            self.tracker.auto_track = True
            self.target_var.set("")
            self.status_label.config(text="● Waiting to lock...", fg=COLORS['orange'])
            self._render_stats()
    
    def _tail_log(self):
        while self.running:
            try:
                current_size = os.path.getsize(self.log_path)
                
                if current_size > self.file_position:
                    with open(self.log_path, 'r', encoding='utf-8', errors='ignore') as f:
                        f.seek(self.file_position)
                        new_lines = f.readlines()
                        self.file_position = f.tell()
                        
                        for line in new_lines:
                            self.tracker.parse_line(line)
                
                elif current_size < self.file_position:
                    self.file_position = 0
                
            except Exception as e:
                print(f"Error: {e}")
            
            time.sleep(0.5)
    
    def _update_display(self):
        if self.running:
            self._render_stats()
            
            # Lock mode: when target is found, fill in the field and update status
            if (self.tracker and self.tracker.auto_track and 
                self.tracker.target_name and not self.target_var.get()):
                # Target locked! Fill in the field
                self.target_var.set(self.tracker.target_name)
                self.target_entry.config(state='normal', fg=COLORS['text'])
                self.exact_var.set(True)
                self.tracker.auto_track = False
                self.tracker.exact_match = True
                self.tracker.target_filter = self.tracker.target_name.lower()
                self.status_label.config(text="● Locked", fg=COLORS['green'])
            
            self.root.after(1000, self._update_display)
    
    def _render_stats(self):
        if not self.tracker:
            return
        
        t = self.tracker
        ab = t.attack_bonus
        ab.refresh()  # Update rolling max
        
        self.stats_text.config(state='normal')
        self.stats_text.delete(1.0, 'end')
        
        # ATTACK BONUS
        self._insert("YOUR ATTACK BONUS\n", 'header')
        self._insert(f"+{ab.current}", 'big')
        self._insert(f" current     ", 'muted')
        self._insert(f"+{ab.max_observed}", 'highlight')
        self._insert(f" max", 'muted')
        
        # Calculate DPS if we have damage and time
        if t.target_name and t.encounter_start:
            if t.target_dead and t.kill_time:
                duration = (t.kill_time - t.encounter_start).seconds
            else:
                duration = (datetime.now() - t.encounter_start).seconds
            total_dmg = t.damage_dealt + t.weapon_buff_damage_total + t.shield_damage_total
            if duration > 0 and total_dmg > 0:
                dps = total_dmg / duration
                self._insert(f"     {dps:.0f}", 'highlight')
                self._insert(" dps", 'muted')
        
        self._insert("\n\n")
        
        if t.target_name:
            # TARGET INFO
            self._insert(f"{t.target_name}", 'target_name')
            if t.target_dead:
                self._insert("  DEAD", 'danger')
            self._insert("\n")
            
            # Stats line
            parts = []
            if t.encounter_start:
                if t.target_dead and t.kill_time:
                    duration = (t.kill_time - t.encounter_start).seconds
                    parts.append(f"Killed in {duration}s")
                else:
                    duration = (t.encounter_last - t.encounter_start).seconds if t.encounter_last else 0
                    parts.append(f"Fight: {duration}s")
            if t.target_ab is not None:
                parts.append(f"AB +{t.target_ab}")
            if t.target_ac:
                parts.append(f"AC {t.target_ac.get_ac_estimate()}")
            if t.target_conceal_pct:
                parts.append(f"{t.target_conceal_pct}% conceal")
            if parts:
                self._insert("  ".join(parts) + "\n", 'muted')
            
            # Saves
            if t.target_saves:
                s = t.target_saves
                fort = f"+{s.fortitude}" if s.fortitude is not None else "?"
                ref = f"+{s.reflex}" if s.reflex is not None else "?"
                will = f"+{s.will}" if s.will is not None else "?"
                self._insert(f"Saves: Fort {fort}  Ref {ref}  Will {will}\n", 'muted')
            
            self._insert("\n")
            
            # DAMAGE DEALT
            self._insert("DAMAGE DEALT\n", 'header')
            total_attacks = t.hits + t.misses + t.conceals
            if total_attacks > 0:
                hit_rate = t.hits / total_attacks * 100
                self._insert(f"{t.hits} hits  {t.misses} miss  {t.crits} crit", 'value')
                if t.conceals > 0:
                    self._insert(f"  {t.conceals} conceal", 'value')
                self._insert(f"  ({hit_rate:.0f}%)\n", 'muted')
            
            total_damage = t.damage_dealt + t.weapon_buff_damage_total + t.shield_damage_total
            avg_normal = sum(t.damage_dealt_normal) / len(t.damage_dealt_normal) if t.damage_dealt_normal else 0
            avg_crit = sum(t.damage_dealt_crits) / len(t.damage_dealt_crits) if t.damage_dealt_crits else 0
            
            self._insert(f"{total_damage}", 'big')
            self._insert(f" total\n", 'muted')
            
            if t.damage_dealt > 0:
                self._insert(f"  {t.damage_dealt} weapon (avg {avg_normal:.0f}, crit {avg_crit:.0f})\n", 'muted')
            if t.weapon_buff_damage_total > 0:
                self._insert(f"  {t.weapon_buff_damage_total} buffs (", 'muted')
                parts = sorted(t.weapon_buff_damage_by_type.items())
                for i, (k, v) in enumerate(parts):
                    color_tag = self._get_dmg_color(k)
                    self._insert(f"{v} {k[:4]}", color_tag)
                    if i < len(parts) - 1:
                        self._insert(", ", 'muted')
                self._insert(")\n", 'muted')
            if t.shield_damage_total > 0:
                self._insert(f"  {t.shield_damage_total} reflect (", 'muted')
                parts = sorted(t.shield_damage_by_type.items())
                for i, (k, v) in enumerate(parts):
                    color_tag = self._get_dmg_color(k)
                    self._insert(f"{v} {k[:4]}", color_tag)
                    if i < len(parts) - 1:
                        self._insert(", ", 'muted')
                self._insert(")\n", 'muted')
            
            self._insert("\n")
            
            # DAMAGE TAKEN
            self._insert("DAMAGE TAKEN\n", 'header')
            total_taken = sum(t.damage_taken)
            num_hits = len(t.damage_taken)
            
            if total_taken > 500:
                self._insert(f"{total_taken}", 'danger')
            else:
                self._insert(f"{total_taken}", 'big')
            self._insert(f" from {num_hits} hits", 'muted')
            if num_hits > 0:
                avg_hit = total_taken / num_hits
                self._insert(f"  avg {avg_hit:.0f}", 'muted')
            self._insert("\n")
            
            # Show damage by type with avg and max
            if t.damage_taken_by_type:
                for dtype in sorted(t.damage_taken_by_type.keys()):
                    amts = t.damage_taken_by_type[dtype]
                    total_type = sum(amts)
                    if total_type == 0:
                        continue  # Skip types with all 0s
                    avg_type = total_type / len(amts) if amts else 0
                    max_type = max(amts) if amts else 0
                    color_tag = self._get_dmg_color(dtype)
                    self._insert(f"  {dtype[:4]}: ", 'muted')
                    self._insert(f"{total_type}", color_tag)
                    self._insert(f"  avg {avg_type:.0f}", 'muted')
                    if max_type > avg_type * 1.5:  # Show max if notably higher (likely crit)
                        self._insert(f"  max {max_type}", 'warning')
                    self._insert("\n")
            
            # HEALING
            if t.player_pots > 0 or t.target_pots > 0:
                self._insert("\n")
                self._insert("HEALING\n", 'header')
                self._insert(f"You: {t.player_pots}  Target: {t.target_pots}\n", 'value')
        
        else:
            # Waiting state
            self._insert("\n")
            if t.auto_track:
                self._insert("LOCK MODE\n", 'highlight')
                self._insert("Waiting for your first attack...\n", 'muted')
            else:
                self._insert("Waiting for target...\n", 'muted')
                self._insert(f"Looking for: {t.target_filter}\n", 'value')
        
        self.stats_text.config(state='disabled')
    
    def _insert(self, text: str, tag: str = None):
        if tag:
            self.stats_text.insert('end', text, tag)
        else:
            self.stats_text.insert('end', text)
    
    def _get_dmg_color(self, dtype: str) -> str:
        """Get the color tag for a damage type"""
        dtype_lower = dtype.lower()
        for key, color in DAMAGE_TYPE_COLORS.items():
            if key in dtype_lower:
                return color
        return 'value'  # default


def main():
    root = tk.Tk()
    
    # Try to set DPI awareness on Windows for sharper text
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except:
        pass
    
    app = NWNTrackerGUI(root)
    
    # Apply dark title bar after window is created (Windows 10/11)
    def apply_dark_titlebar():
        try:
            from ctypes import windll, c_int, byref, sizeof
            root.update()
            HWND = windll.user32.GetParent(root.winfo_id())
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            windll.dwmapi.DwmSetWindowAttribute(HWND, DWMWA_USE_IMMERSIVE_DARK_MODE, byref(c_int(1)), sizeof(c_int))
            # Force a redraw
            root.withdraw()
            root.deiconify()
        except:
            pass
    
    root.after(100, apply_dark_titlebar)
    root.mainloop()


if __name__ == "__main__":
    main()
