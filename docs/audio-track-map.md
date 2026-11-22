# Audio Track Map (Gate + POS)

Numbering below follows the **controller** (Compass `\xa6MTxxxxx\xa9`, ENET
`:PLAYTRACKx;`). Canonical constants live in `shared/audio_tracks.py`; do not
invent new numbers — any change must match the files on the controller.

## Controller tracks (confirmed)

| Track | Meaning | Constant |
|---|---|---|
| 2 | Silakan ambil tiket | `TAKE_TICKET` |
| 3 | Kartu tidak terdaftar | `CARD_NOT_REGISTERED` |
| 4 | Member tidak aktif | `MEMBER_INACTIVE` |
| 5 | Mohon tunggu / hubungi petugas | `PLEASE_WAIT` |
| 6 | Terima kasih | `THANK_YOU` |
| 7 | Selamat datang | `WELCOME` |
| 11 | Masa berlaku habis dalam 5 hari | `EXPIRES_IN_5_DAYS` |
| 12 | Masa berlaku habis dalam 1 hari | `EXPIRES_IN_1_DAY` |
| 13 | Kartu habis masa berlaku | `CARD_EXPIRED` |
| 14 | Kartu belum selesai transaksi | `UNCLOSED_TRANSACTION` |

Tracks 1, 8, 9, 10 are **not documented** by the controller vendor. Track 4 is
used as “member tidak aktif” because legacy installs used it that way.

## Where each track is played

| Event | Track |
|---|---|
| RFID card not registered | 3 |
| Member inactive | 4 |
| Member expired | 13 |
| Anti-passback (card still has ACTIVE transaction) | 14 |
| Vehicle quota per card full | 14 |
| Membership expires in 5 days (warning, still allowed) | 11 |
| Membership expires in 1 day (warning, still allowed) | 12 |
| Gate opened successfully | 6 |
| Help button | 5 |
| Cash ticket flow | 2 |

## POS browser files (`frontend/public/audio`)

The POS uses its own mp3 files. `AUDIO_TRACK_MAP` in `stores/gate.js` maps the
controller numbers above to these files, so a `play_audio` event from the
server always plays the matching meaning:

| Track | File |
|---|---|
| 1 | `001_selamat_datang.mp3` |
| 2 | `002_ambil_tiket.mp3` |
| 3 | `003_kartu_tidak_valid.mp3` |
| 4 | `004_member_tidak_aktif.mp3` |
| 5 | `005_tunggu_petugas.mp3` |
| 6 | `009_terima_kasih.mp3` |
| 7 | `001_selamat_datang.mp3` |
| 8 | `008_hubungi_petugas.mp3` |
| 9 | `009_terima_kasih.mp3` |
| 10 | `010_pembayaran_berhasil.mp3` |
| 11 | `012_waktu_habis.mp3` |
| 12 | `012_waktu_habis.mp3` |
| 13 | `003_kartu_tidak_valid.mp3` |
| 14 | `011_transaksi_gagal.mp3` |

`006_saldo_kurang.mp3` and `007_kartu_salah.mp3` have no controller-track
equivalent and are only used by older UI flows.

## Per-gate override

`gates.hardware_config.audio.track_map` can remap a canonical number to a
different controller track (e.g. `{"14": 12}`) for sites whose controller has a
different file set. The daemon applies the map before sending the command.
