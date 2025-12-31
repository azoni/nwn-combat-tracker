# NWN Combat Tracker

Real-time combat stats tracker for Neverwinter Nights. Parses the game's combat log and displays attack bonuses, AC estimates, damage breakdown, and more.

![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)

## Features

- **Attack Bonus Tracking** - Shows current and max AB with a 30-second rolling window to detect buff drops
- **DPS Calculator** - Live damage per second during fights
- **AC Estimation** - Narrows down enemy AC based on hits/misses
- **Save Tracking** - Records enemy Fort/Ref/Will saves from spell results
- **Damage Breakdown**
  - Weapon damage (normal vs crit averages)
  - Buff damage (elemental weapon effects)
  - Reflect damage (fire shields, etc.)
  - Damage taken by type with color coding
- **Concealment Detection** - Tracks enemy concealment percentage
- **Healing Counter** - Counts heal potions used by you and the target
- **Kill Timer** - Fight duration and kill confirmation

## Screenshot
<img width="707" height="806" alt="image" src="https://github.com/user-attachments/assets/bcb11c36-570a-400e-b569-7b63cd5ca4db" />

## Requirements

- Python 3.8+
- Tkinter (usually included with Python)
- NWN with combat logging enabled

## Setup

1. Enable combat logging in NWN:
   - Open `nwnplayer.ini`
   - Set `ClientChatLogging=1` under `[Game Options]`

2. Run the tracker:
   ```
   python nwn_combat_tracker_gui.py
   ```

3. Set your player name and log path (it'll remember these)

4. Either enter a target name or leave blank to auto-lock onto your first attack target

## Usage

- **Start Tracking** - Begins parsing the log file
- **New Target** - Clears current fight stats and waits for next target
- **Reset** - Clears all stats
- **Exact** checkbox - Match target name exactly vs partial match
- **Preset** dropdown - Quick select from saved target aliases

## Target Aliases

Edit the `TARGET_ALIASES` dict in the script to add shortcuts:

```python
TARGET_ALIASES = {
    "boss1": "XANASDEM - LEGION CAPTAIN",
    "dragon": "Ancient Red Dragon",
}
```

## Damage Type Colors

- Fire: red
- Cold: light blue
- Acid: green
- Electrical: blue
- Sonic: yellow-orange
- Positive: white
- Negative: gray
- Divine: yellow
- Magical: light purple
- Pure: dark purple

## Notes

- The tracker reads from the end of the log file, so start it before combat
- AC estimation works best with lots of attack rolls - the more swings, the tighter the estimate
- Max AB uses a 30-second rolling window, so if buffs drop mid-fight you'll see it
- DPS freezes at final value when target dies

## Building an Executable

```
pip install pyinstaller
pyinstaller --onefile --windowed --icon=nwn_tracker_icon.ico nwn_combat_tracker_gui.py
```

## License

MIT
