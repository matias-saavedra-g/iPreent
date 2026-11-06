"""Which tools people reach for most, so the home screens can put them first.

Each tool has a prior weight: our guess at how often it gets used (the weights add up to 1).
Every use adds to a decayed count, so the order slowly follows what this person actually prints.
The apps compute the order once when they start, never while someone is looking at it: tools that
jump around under the finger are worse than a fixed order (split-menu research, Sears &
Shneiderman 1994; Findlater & McGrenere 2004).

Port: android/.../Features.kt (same functions, same test cases).
"""

DECAY = 0.9          # each use shrinks older counts by 10%
PRIOR_SCALE = 10.0   # counts level off at 1 / (1 - DECAY) = 10, so habit can outweigh the guess

# Windows app modes. Photos and documents first (what these printers are bought for), then notes,
# receipts (small shops), templates (cards, tags, journal stickers), checklists, banners and codes.
DESKTOP = {"photo": 0.22, "document": 0.19, "text": 0.16, "receipt": 0.13, "template": 0.10, "list": 0.09,
           "banner": 0.05, "qr": 0.04, "barcode": 0.02}

# Command-line subcommands, for the home screen and the order in `ipreent --help`.
CLI = {"print": 0.27, "text": 0.22, "receipt": 0.14, "status": 0.07, "template": 0.07, "preview": 0.07,
       "queue": 0.05, "scan": 0.04, "feed": 0.03, "settings": 0.02, "forget": 0.01, "bench": 0.01}


def record_use(usage, key, decay=DECAY):
    """New usage counts after one use of `key` (older uses fade)."""
    out = {k: v * decay for k, v in usage.items()}
    out[key] = out.get(key, 0.0) + 1.0
    return out


def score(weights, usage, key):
    return PRIOR_SCALE * weights.get(key, 0.0) + usage.get(key, 0.0)


def ranked(weights, usage=None):
    """Keys of `weights`, most likely first. Ties keep the prior order."""
    usage = usage or {}
    return sorted(weights, key=lambda k: (-score(weights, usage, k), -weights[k], k))
