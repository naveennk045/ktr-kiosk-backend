"""
KDS / TMS shared time-window rules (Option B).

Option B — "live" board:
  - Include orders whose `created_at` (or future `kds_entered_at`) is within the last
    LIVE_ORDERS_WINDOW_MINUTES, AND
  - Also include any older order that is still not fully kitchen-complete (sticky incomplete),
    so slow tickets never disappear from the board solely due to age.
"""

LIVE_ORDERS_WINDOW_MINUTES = 30
