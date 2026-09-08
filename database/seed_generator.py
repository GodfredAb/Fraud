"""
seed_generator.py
------------------
Generates synthetic users, devices, subscribers (IMSI/SIM), location
history, and a synthetic transaction history. Used by build_database.py
for the initial seed/load, and directly reusable to regenerate
data/synthetic.csv from scratch.

Everything here is deterministic given a seed, so re-running with the same
--seed reproduces the same dataset.
"""

import datetime as dt
import random

import numpy as np
import pandas as pd

FIRST_NAMES = [
    "Kwame", "Ama", "Kofi", "Akosua", "Kwabena", "Abena", "Kwaku", "Akua",
    "Yaw", "Yaa", "Kojo", "Afua", "Fiifi", "Esi", "Kwesi", "Adjoa",
    "Nana", "Efua", "Kobina", "Araba", "Sena", "Selorm", "Elikem", "Mawuli",
    "Naa", "Adjei", "Baaba", "Dede", "Ekow", "Aba",
]
LAST_NAMES = [
    "Mensah", "Owusu", "Boateng", "Asante", "Agyeman", "Osei", "Appiah",
    "Adjei", "Amoah", "Darko", "Frimpong", "Gyasi", "Nkrumah", "Sarpong",
    "Tetteh", "Addo", "Ansah", "Baidoo", "Danso", "Kusi",
]
GENDERS = ["M", "F"]
KYC_STATUSES_WEIGHTED = (
    ["verified"] * 90 + ["pending"] * 7 + ["suspended"] * 2 + ["rejected"] * 1
)
DEVICE_MANUFACTURERS = ["Samsung", "Tecno", "Infinix", "Itel", "Apple", "Nokia"]
DEVICE_MODELS = {
    "Samsung": ["Galaxy A14", "Galaxy A05", "Galaxy S21"],
    "Tecno": ["Spark 10", "Camon 20", "Pop 7"],
    "Infinix": ["Hot 40", "Smart 8", "Note 30"],
    "Itel": ["A70", "P40", "Vision 3"],
    "Apple": ["iPhone 12", "iPhone SE"],
    "Nokia": ["C21", "G22"],
}

# Ten of Ghana's real regions/regional capitals, weighted toward Greater
# Accra and Ashanti (the two largest population centers) - each synthetic
# subscriber is assigned ONE of these as their home region and jittered
# within it, so the population (and the Map/Geo-Location Deltas views)
# spans the whole country instead of clustering entirely in Accra.
GHANA_REGIONS = [
    {"region": "Greater Accra", "city": "Accra", "lat": 5.6037, "lon": -0.1870, "weight": 30},
    {"region": "Ashanti", "city": "Kumasi", "lat": 6.6885, "lon": -1.6244, "weight": 20},
    {"region": "Western", "city": "Sekondi-Takoradi", "lat": 4.9047, "lon": -1.7124, "weight": 8},
    {"region": "Central", "city": "Cape Coast", "lat": 5.1053, "lon": -1.2466, "weight": 7},
    {"region": "Eastern", "city": "Koforidua", "lat": 6.0940, "lon": -0.2591, "weight": 8},
    {"region": "Volta", "city": "Ho", "lat": 6.6018, "lon": 0.4713, "weight": 6},
    {"region": "Northern", "city": "Tamale", "lat": 9.4035, "lon": -0.8393, "weight": 8},
    {"region": "Upper East", "city": "Bolgatanga", "lat": 10.7856, "lon": -0.8514, "weight": 4},
    {"region": "Upper West", "city": "Wa", "lat": 10.0601, "lon": -2.5099, "weight": 3},
    {"region": "Bono", "city": "Sunyani", "lat": 7.3399, "lon": -2.3268, "weight": 6},
]

TXN_TYPES = ["CASH_IN", "CASH_OUT", "PAYMENT", "TRANSFER", "DEBIT"]
TXN_TYPE_WEIGHTS = [0.25, 0.25, 0.30, 0.15, 0.05]


def _luhn_check_digit(digits: str) -> str:
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d)
        if i % 2 == 0:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return str((10 - (total % 10)) % 10)


def generate_users(n: int, seed: int = 42):
    rng = random.Random(seed)
    users = []
    for i in range(1, n + 1):
        user_id = f"C{i}"
        full_name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
        digits = f"{rng.randint(0, 10**9 - 1):09d}"
        national_id = f"GHA-{digits}-{_luhn_check_digit(digits)}"
        dob = dt.date(1960, 1, 1) + dt.timedelta(days=rng.randint(0, 60 * 365))
        gender = rng.choice(GENDERS)
        msisdn = f"233{rng.choice(['24','54','55','20','27','50'])}{rng.randint(1000000,9999999)}"
        kyc_status = rng.choice(KYC_STATUSES_WEIGHTED)
        registration_date = dt.datetime.now() - dt.timedelta(days=rng.randint(30, 1500))

        users.append({
            "user_id": user_id,
            "full_name": full_name,
            "national_id": national_id,
            "date_of_birth": dob,
            "gender": gender,
            "msisdn": msisdn,
            "kyc_status": kyc_status,
            "registration_date": registration_date,
        })
    return users


def generate_devices_and_subscribers(users, seed: int = 42):
    """One device (IMEI) and one SIM (IMSI) per user, as the README
    describes. Returns (devices, subscribers) - build_database.py inserts
    these, gets back their DB-assigned SERIAL ids, and links them."""
    rng = random.Random(seed + 1)
    devices, subscribers = [], []
    for u in users:
        manufacturer = rng.choice(DEVICE_MANUFACTURERS)
        model = rng.choice(DEVICE_MODELS[manufacturer])
        imei = "".join(str(rng.randint(0, 9)) for _ in range(15))
        devices.append({
            "user_id": u["user_id"],
            "imei": imei,
            "manufacturer": manufacturer,
            "model": model,
        })

        imsi = "".join(str(rng.randint(0, 9)) for _ in range(15))
        subscribers.append({
            "user_id": u["user_id"],
            "imsi": imsi,
            "msisdn": u["msisdn"],
        })
    return devices, subscribers


def generate_locations(users, seed: int = 42, pings_per_user: int = 8):
    """Location ping history, chronologically increasing so the DB
    trigger's rolling current/average stay meaningful. Each user is
    assigned ONE home region (GHANA_REGIONS, weighted toward Greater
    Accra/Ashanti) and jittered within just that region (+-0.08deg,
    ~9km - comfortably inside a single region: the closest pair of
    region centers here, Central/Western, are ~52km apart) plus small
    per-ping noise, so "average location" is a stable per-user signal
    that spans the whole country rather than clustering in one city."""
    rng = random.Random(seed + 2)
    now = dt.datetime.now()
    weights = [r["weight"] for r in GHANA_REGIONS]
    locations = []
    for u in users:
        home_region = rng.choices(GHANA_REGIONS, weights=weights, k=1)[0]
        home_lat = home_region["lat"] + rng.uniform(-0.08, 0.08)
        home_lon = home_region["lon"] + rng.uniform(-0.08, 0.08)
        for p in range(pings_per_user):
            recorded_at = now - dt.timedelta(days=(pings_per_user - p) * rng.uniform(2, 6))
            locations.append({
                "user_id": u["user_id"],
                "latitude": round(home_lat + rng.uniform(-0.02, 0.02), 6),
                "longitude": round(home_lon + rng.uniform(-0.02, 0.02), 6),
                "recorded_at": recorded_at,
                "source": rng.choice(["cell_tower", "gps", "wifi", "agent_registration"]),
            })
    return locations


FRAUD_SUBTYPES = ("drain", "structuring", "rapid_fanout", "dormant_reactivation")
FRAUD_SUBTYPE_WEIGHTS = (0.40, 0.25, 0.25, 0.10)


def generate_transactions(user_ids, n: int = 2000, fraud_rate: float = 0.01, seed: int = 42) -> pd.DataFrame:
    """Bulk synthetic transaction history in PaySim-style raw columns
    (step, type, amount, nameOrig, oldbalanceOrg, newbalanceOrig, nameDest,
    oldbalanceDest, newbalanceDest, isFraud, isFlaggedFraud) - the same
    shape data/synthetic.csv ships in and the same shape
    export_transactions_from_db.py's BASE_QUERY produces. Balances are
    tracked per-user across the whole sequence so oldbalance/newbalance
    actually reconcile transaction to transaction, the way a real ledger
    would.

    Fraud is injected as one of four subtypes (FRAUD_SUBTYPES), matching
    feeder/feeder.py's live patterns minus sim_swap_drain (this pipeline has
    no device/IMEI columns at all - see ml/feature_engineering.py's
    load_and_standardize): drain (single large account-draining
    transaction), structuring (several sub-threshold transactions summing
    to a large total), rapid_fanout (several transactions to brand-new
    receivers in a burst), and dormant_reactivation (the account that's
    gone longest without transacting suddenly moves a large amount)."""
    rng = random.Random(seed + 3)
    np_rng = np.random.RandomState(seed + 3)

    balances = {uid: rng.uniform(200, 5000) for uid in user_ids}
    # Tracks each user's most recent step as a SENDER specifically (not as
    # receiver) - 0 means "has never sent". This is what the
    # dormant_account_reactivated rule's user_txn_count_so_far > 0 guard
    # actually checks, so the dormant pick below must only choose among
    # users who HAVE sent before (excluding step==0), or it would keep
    # picking never-active users and the rule could never fire on them.
    sender_last_step = {uid: 0 for uid in user_ids}
    rows = []
    step = 1
    txns_per_step = max(1, n // max(1, (n // 20)))  # spread across ~20 steps' worth of pacing
    since_step_bump = 0

    produced = 0
    while produced < n:
        is_fraud = rng.random() < fraud_rate
        subtype = rng.choices(FRAUD_SUBTYPES, weights=FRAUD_SUBTYPE_WEIGHTS, k=1)[0] if is_fraud else None

        if subtype == "dormant_reactivation":
            ever_sent = [u for u in user_ids if sender_last_step[u] > 0]
            if ever_sent:
                sender = min(ever_sent, key=lambda u: sender_last_step[u])
            else:
                sender = rng.choice(user_ids)
                subtype = "drain"  # no one has ever sent yet - just an ordinary drain
        else:
            sender = rng.choice(user_ids)
        sender_old = balances[sender]

        if subtype in ("structuring", "rapid_fanout"):
            # Burst pattern: several rows for this sender, 1 step apart (not
            # the same step, and not the normal txns_per_step-spaced
            # cadence) so they land inside each other's velocity window -
            # see ml/rules.py's velocity_6h_cutoff comment for why same-step
            # ties don't count. Deliberately jumps `step` ahead of the
            # normal pacing to guarantee separation; a minor, harmless
            # pacing skip in an otherwise uniformly-spaced synthetic feed.
            others = [u for u in user_ids if u != sender]
            receivers = rng.sample(others, min(rng.randint(3, 5), len(others)))
            bal = sender_old
            for i, receiver in enumerate(receivers):
                if subtype == "structuring":
                    amount = rng.uniform(300, 900)
                else:
                    amount = float(np_rng.exponential(250))
                amount = min(amount, bal) if bal > 0 else amount
                new_bal = max(bal - amount, 0.0)
                receiver_old = balances[receiver]
                receiver_new = receiver_old + amount
                rows.append({
                    "step": step + i, "type": "TRANSFER", "amount": round(amount, 2),
                    "nameOrig": sender, "oldbalanceOrg": round(bal, 2), "newbalanceOrig": round(new_bal, 2),
                    "nameDest": receiver, "oldbalanceDest": round(receiver_old, 2), "newbalanceDest": round(receiver_new, 2),
                    "isFraud": 1, "isFlaggedFraud": 0,
                })
                balances[receiver] = receiver_new
                bal = new_bal
            balances[sender] = bal
            sender_last_step[sender] = step + len(receivers) - 1
            produced += len(receivers)
            step += len(receivers)
            since_step_bump = 0
            continue

        # Single-row patterns: drain, dormant_reactivation (same shape, only
        # WHICH sender got picked differs), and ordinary non-fraud traffic.
        receiver = rng.choice([u for u in user_ids if u != sender])
        if subtype in ("drain", "dormant_reactivation"):
            txn_type = rng.choice(["TRANSFER", "CASH_OUT"])
            amount = max(sender_old * rng.uniform(0.85, 1.0), rng.uniform(2000, 8000))
            sender_new = max(sender_old - amount, 0.0)
        else:
            txn_type = rng.choices(TXN_TYPES, weights=TXN_TYPE_WEIGHTS, k=1)[0]
            amount = float(np_rng.exponential(180))
            amount = min(amount, sender_old) if sender_old > 0 else amount
            sender_new = max(sender_old - amount, 0.0)

        receiver_old = balances[receiver]
        receiver_new = receiver_old + amount

        balances[sender] = sender_new
        balances[receiver] = receiver_new

        if subtype == "dormant_reactivation":
            # Fast-forward the SHARED clock by 340-500 steps for this one
            # event, guaranteeing a gap of at least that size vs this
            # sender's real last transaction (which happened at or before
            # the current `step`) - see the matching comment in
            # feeder/feeder.py's generate_batch for why the clock itself
            # must jump (not just this row's own step): if only this row
            # were aged forward while `step` stayed behind, a later
            # ordinary pick of this same sender could land a smaller step
            # in between, or even an out-of-order (negative-gap) one.
            row_step = round(step + rng.uniform(340, 500))
            step = row_step + 1
            since_step_bump = 0
            sender_last_step[sender] = row_step
        else:
            row_step = step
            sender_last_step[sender] = step

        rows.append({
            "step": row_step,
            "type": txn_type,
            "amount": round(amount, 2),
            "nameOrig": sender,
            "oldbalanceOrg": round(sender_old, 2),
            "newbalanceOrig": round(sender_new, 2),
            "nameDest": receiver,
            "oldbalanceDest": round(receiver_old, 2),
            "newbalanceDest": round(receiver_new, 2),
            "isFraud": int(subtype is not None),
            "isFlaggedFraud": 0,
        })
        produced += 1

        since_step_bump += 1
        if since_step_bump >= txns_per_step:
            step += 1
            since_step_bump = 0

    return pd.DataFrame(rows)
