import tkinter as tk
from tkinter import ttk
import config
import i18n

def build(app, parent) -> None:
    s = app.s
    def check(attr: str, key: str):
        var = tk.BooleanVar(value=bool(getattr(s, attr)))
        setattr(app, f'ex_{attr}_var', var)
        cb = ttk.Checkbutton(parent, variable=var, command=(lambda: setattr(s, attr, var.get())))
        app._l(cb, key).pack(anchor='w', padx=12, pady=3)
        return cb

    check('auto_mute_enabled', 'ex_mute')
    check('loot_vault_enabled', 'ex_loot')
    app._l(ttk.Button(parent, command=(lambda: open_vault(app))), 'ex_loot_open').pack(anchor='w', padx=34, pady=(0, 4))
    check('humanizer_enabled', 'ex_human')
    check('afk_mouse_look', 'ex_look')
    check('jitter_enabled', 'ex_jitter')
    jrow = ttk.Frame(parent)
    jrow.pack(anchor='w', padx=34, pady=(0, 2))
    app.ex_jpct_var = tk.StringVar(value=f'{s.wait_jitter_percent * 100:g}')
    app._l(ttk.Label(jrow), 'ex_jpct_pre').pack(side='left')
    ttk.Spinbox(jrow, from_=5, to=50, increment=1, width=4, textvariable=app.ex_jpct_var).pack(side='left', padx=3)
    app._l(ttk.Label(jrow), 'ex_jpct_post').pack(side='left')
    app.ex_jpct_var.trace_add('write', (lambda *_: (_on_pct(app), _refresh_preview(app, loop=False))))
    app.ex_jprev_var = tk.StringVar()
    ttk.Label(parent, textvariable=app.ex_jprev_var, foreground='#2a6').pack(anchor='w', padx=34, pady=(0, 4))
    _refresh_preview(app)
    check('mode_fix_enabled', 'ex_modefix')
    check('bus_drop_enabled', 'ex_bus')
    brow = ttk.Frame(parent)
    brow.pack(anchor='w', padx=34, pady=(0, 4))
    app.ex_dive_var = tk.StringVar(value=f'{s.bus_dive_seconds:g}')
    app._l(ttk.Label(brow), 'ex_dive_pre').pack(side='left')
    ttk.Spinbox(brow, from_=1, to=60, increment=1, width=5, textvariable=app.ex_dive_var).pack(side='left', padx=3)
    app._l(ttk.Label(brow), 'ex_dive_post').pack(side='left')
    app.ex_dive_var.trace_add('write', (lambda *_: app._on_afk_num('bus_dive_seconds', app.ex_dive_var, 1.0, 60.0)))
    check('pickaxe_afk_enabled', 'ex_pickaxe')
    prow = ttk.Frame(parent)
    prow.pack(anchor='w', padx=34, pady=(0, 4))
    app.ex_pmin_var = tk.StringVar(value=f'{s.pickaxe_min_s:g}')
    app.ex_pmax_var = tk.StringVar(value=f'{s.pickaxe_max_s:g}')
    app._l(ttk.Label(prow), 'ex_pick_pre').pack(side='left')
    ttk.Spinbox(prow, from_=1, to=3600, increment=5, width=5, textvariable=app.ex_pmin_var).pack(side='left', padx=3)
    app._l(ttk.Label(prow), 'ex_pick_mid').pack(side='left')
    ttk.Spinbox(prow, from_=1, to=3600, increment=5, width=5, textvariable=app.ex_pmax_var).pack(side='left', padx=3)
    app._l(ttk.Label(prow), 'ex_pick_post').pack(side='left')
    app.ex_pmin_var.trace_add('write', (lambda *_: app._on_afk_num('pickaxe_min_s', app.ex_pmin_var, 1.0, 3600.0)))
    app.ex_pmax_var.trace_add('write', (lambda *_: app._on_afk_num('pickaxe_max_s', app.ex_pmax_var, 1.0, 3600.0)))
    check('coffee_break_enabled', 'ex_coffee')
    check('reward_shot_enabled', 'ex_rshot')
    check('auto_calibrate', 'ex_calib')
    check('squad_check_enabled', 'ex_squad')
    row = ttk.Frame(parent)
    row.pack(anchor='w', padx=12, pady=(6, 2))
    app.ex_stuck_var = tk.StringVar(value=f'{s.stuck_timeout_min:g}')
    app._l(ttk.Label(row), 'ex_stuck_pre').pack(side='left')
    ttk.Spinbox(row, from_=0, to=240, increment=5, width=5, textvariable=app.ex_stuck_var).pack(side='left', padx=3)
    app._l(ttk.Label(row), 'ex_stuck_post').pack(side='left')
    app.ex_stuck_var.trace_add('write', (lambda *_: app._on_afk_num('stuck_timeout_min', app.ex_stuck_var, 0.0, 240.0)))
    check('rescue_remote_enabled', 'ex_rescue')

def wait_for_mode(s) -> float:
    return float({'B': s.wait_b, 'C': s.wait_c}.get(s.mode, s.afk_interval))

def preview_text(s) -> str:
    base = wait_for_mode(s)
    if not s.jitter_enabled:
        return i18n.t(s.lang, 'ex_jprev_off', base=base)
    lo, hi = config.jitter_range(base, s)
    return i18n.t(s.lang, 'ex_jprev', base=base, lo=lo, hi=hi)

def _on_pct(app) -> None:
    try:
        v = float(app.ex_jpct_var.get())
    except ValueError:
        pass
    else:
        if 5.0 <= v <= 50.0:
            app.s.wait_jitter_percent = v / 100.0
            return

def _refresh_preview(app, loop: bool=True) -> None:
    try:
        app.ex_jprev_var.set(preview_text(app.s))
    except Exception:
        pass
    if loop:
        try:
            app.root.after(500, (lambda: _refresh_preview(app)))
            return
        except Exception:
            pass

def open_vault(app) -> None:
    from loot_vault import LootVault
    if not LootVault().open_folder():
        app.log_q.put('loot_vault: could not open the folder')

