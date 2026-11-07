# Smart Features — Printer Paper Counter

## Purpose

Track remaining paper for each thermal printer and alert operators before paper runs out. Prevents ticket/receipt print failures that could disrupt vehicle flow.

## Configuration

```env
PRINTER_PAPER_COUNTER_ENABLED=true
PRINTER_PAPER_WARNING_THRESHOLD=50      # yellow warning when remaining ≤ this
PRINTER_PAPER_CRITICAL_THRESHOLD=10     # red alert + Telegram notification when remaining ≤ this
```

## How It Works

### Software Counter (Primary)

Each printer record in the database has a `paper_remaining` column:

```
┌─────────────────┐
│ printers table   │
├─────────────────┤
│ id               │
│ gate_id          │
│ type             │ ← network / serial
│ ip_address       │
│ paper_remaining  │ ← decremented on each print
│ paper_capacity   │ ← total per roll (default: 300)
│ last_refilled_at │
└─────────────────┘
```

### Counter Logic

```python
# On each successful print
printer.paper_remaining -= 1

# Alert thresholds
if printer.paper_remaining <= CRITICAL_THRESHOLD:
    → Red alert on dashboard
    → Telegram notification to operator
    → If paper_remaining == 0:
        → Refuse to print
        → Show barcode on LED display instead
        → Log as "PRINT_SKIPPED_NO_PAPER"

elif printer.paper_remaining <= WARNING_THRESHOLD:
    → Yellow warning on dashboard
```

### Paper Refill Flow

1. Operator loads new paper roll
2. Opens admin panel → Printers → selects printer
3. Clicks **"Paper Refilled"** button
4. Sets count (default: `paper_capacity` from printer config)
5. `paper_remaining` reset, `last_refilled_at` updated

### Hardware Status (Bonus)

When the thermal printer supports ESC/POS `DLE EOT` status query:

```
DLE EOT 1 → Paper status
  Bit 5 = 1: Paper near end
  Bit 6 = 1: Paper ended
```

If supported, the `print_worker` queries this status after each print and cross-references with the software counter.

### Dashboard Display

```
┌─────────────────────────────────────────┐
│ PRINTER STATUS                          │
├──────────┬──────────┬───────┬───────────┤
│ Gate     │ Printer  │ Paper │ Status    │
├──────────┼──────────┼───────┼───────────┤
│ GATE-IN-1│ 192.168.1.10 │ 245/300│ ● OK     │
│ GATE-IN-2│ 192.168.1.11 │  42/300│ ● Warning│
│ GATE-OUT │ 192.168.1.12 │   5/300│ ● Critical│
└──────────┴──────────┴───────┴───────────┘
```

### Fallback When Disabled

When `PRINTER_PAPER_COUNTER_ENABLED=false`:
- No paper tracking or alerts
- Prints are attempted regardless
- Existing error handling catches actual print failures
