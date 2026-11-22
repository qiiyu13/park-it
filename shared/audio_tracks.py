"""Canonical gate audio track numbers.

These numbers match the files stored on the Compass/ENET controller (see
docs/parking-methods.md). Do NOT reuse the POS browser MP3 numbering — the
frontend maps these numbers to its own files.

1, 4, 8, 9, 10 are not documented by the controller vendor; 4 is treated as
"member tidak aktif" because that is what legacy installs used.
"""

# Welcome / entry
WELCOME = 7
TAKE_TICKET = 2

# Rejections
CARD_NOT_REGISTERED = 3
MEMBER_INACTIVE = 4
CARD_EXPIRED = 13
UNCLOSED_TRANSACTION = 14

# Guidance
PLEASE_WAIT = 5
THANK_YOU = 6

# Membership expiry warnings
EXPIRES_IN_5_DAYS = 11
EXPIRES_IN_1_DAY = 12
