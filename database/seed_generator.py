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

# Accra, Ghana as the center of gravity for synthetic location pings.
CENTER_LAT, CENTER_LON = 5.6037, -0.1870

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
    """Location ping history, jittered around Accra, chronologically
    increasing so the DB trigger's rolling current/average stay meaningful."""
    rng = random.Random(seed + 2)
    now = dt.datetime.now()
    locations = []
    for u in users:
        # Each user has their own small home-range jitter, plus per-ping noise,
        # so "average location" is a stable, meaningful per-user signal.
        home_lat = CENTER_LAT + rng.uniform(-0.15, 0.15)
        home_lon = CENTER_LON + rng.uniform(-0.15, 0.15)
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


def generate_transactions(user_ids, n: int = 2000, fraud_rate: float = 0.01, seed: int = 42) -> pd.DataFrame:
    """Bulk synthetic transaction history in PaySim-style raw columns
    (step, type, amount, nameOrig, oldbalanceOrg, newbalanceOrig, nameDest,
    oldbalanceDest, newbalanceDest, isFraud, isFlaggedFraud) - the same
    shape data/synthetic.csv ships in and the same shape
    export_transactions_from_db.py's BASE_QUERY produces. Balances are
    tracked per-user across the whole sequence so oldbalance/newbalance
    actually reconcile transaction to transaction, the way a real ledger
    would."""
    rng = random.Random(seed + 3)
    np_rng = np.random.RandomState(seed + 3)

    balances = {uid: rng.uniform(200, 5000) for uid in user_ids}
    rows = []
    step = 1
    txns_per_step = max(1, n // max(1, (n // 20)))  # spread across ~20 steps' worth of pacing
    since_step_bump = 0

    for _ in range(n):
        sender, receiver = rng.sample(user_ids, 2)
        txn_type = rng.choices(TXN_TYPES, weights=TXN_TYPE_WEIGHTS, k=1)[0]
        is_fraud = rng.random() < fraud_rate
        sender_old = balances[sender]

        if is_fraud:
            txn_type = rng.choice(["TRANSFER", "CASH_OUT"])
            amount = max(sender_old * rng.uniform(0.85, 1.0), rng.uniform(2000, 8000))
            sender_new = max(sender_old - amount, 0.0)
        else:
            amount = float(np_rng.exponential(180))
            amount = min(amount, sender_old) if sender_old > 0 else amount
            sender_new = max(sender_old - amount, 0.0)

        receiver_old = balances[receiver]
        receiver_new = receiver_old + amount

        balances[sender] = sender_new
        balances[receiver] = receiver_new

        rows.append({
            "step": step,
            "type": txn_type,
            "amount": round(amount, 2),
            "nameOrig": sender,
            "oldbalanceOrg": round(sender_old, 2),
            "newbalanceOrig": round(sender_new, 2),
            "nameDest": receiver,
            "oldbalanceDest": round(receiver_old, 2),
            "newbalanceDest": round(receiver_new, 2),
            "isFraud": int(is_fraud),
            "isFlaggedFraud": 0,
        })

        since_step_bump += 1
        if since_step_bump >= txns_per_step:
            step += 1
            since_step_bump = 0

    return pd.DataFrame(rows)
