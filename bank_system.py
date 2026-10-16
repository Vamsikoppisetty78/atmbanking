"""
bank_system.py
----------------
All banking logic for the MiniBank mini project.
Pure Python: no web framework code lives here at all.

Maps to the syllabus units:
  Unit I   - control flow, exceptions (try/except), operators, data types
  Unit II  - functions, default args, *args/**kwargs, strings
  Unit III - dictionaries, tuples, sets
  Unit IV  - files (text/CSV/pickle), OOP: classes, inheritance,
             encapsulation, polymorphism
  Unit V   - functional programming (map/filter/reduce/lambda),
             JSON, NumPy/Pandas analytics
"""

import json
import csv
import pickle
import os
import random
import string
from datetime import datetime
from functools import reduce

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
ACCOUNTS_FILE = os.path.join(DATA_DIR, "accounts.json")
TXN_LOG_FILE = os.path.join(DATA_DIR, "transactions.csv")
PICKLE_BACKUP = os.path.join(DATA_DIR, "accounts_backup.pkl")

os.makedirs(DATA_DIR, exist_ok=True)


# =====================================================================
# Unit IV - Object Oriented Programming
# Classes and Objects, Constructor, Inheritance, Encapsulation,
# Polymorphism, Class Attributes vs Data Attributes
# =====================================================================

class Account:
    """Base class for every account type. Demonstrates encapsulation:
    the password is stored as a name-mangled (double-underscore) attribute
    and can only be read/changed through methods."""

    bank_name = "MiniBank"          # class attribute (shared by all objects)

    def __init__(self, name, username, password, account_number,
                 card_number, balance=0.0):
        self._name = name
        self._username = username
        self.__password = password             # encapsulated data attribute
        self.account_number = account_number
        self.card_number = card_number
        self.balance = float(balance)
        self.account_type = "Generic"
        self.transactions = []                  # list of tuples, Unit III
        self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ---- controlled access to the private password (encapsulation) ----
    def check_password(self, attempt):
        return self.__password == attempt

    def set_password(self, new_password):
        self.__password = new_password

    # ---- core operations, with Unit I style validation/exceptions ----
    def deposit(self, amount, note="Deposit"):
        if amount <= 0:
            raise ValueError("Deposit amount must be positive")
        self.balance += amount
        self._log_transaction("Deposit", amount, note)
        return self.balance

    def withdraw(self, amount, note="Withdraw"):
        if amount <= 0:
            raise ValueError("Withdraw amount must be positive")
        if amount > self.balance:
            raise ValueError("Insufficient balance")
        self.balance -= amount
        self._log_transaction("Withdraw", amount, note)
        return self.balance

    def transfer_out(self, amount, to_account):
        self.withdraw(amount, note=f"Transfer to {to_account}")

    def transfer_in(self, amount, from_account):
        self.deposit(amount, note=f"Transfer from {from_account}")

    def _log_transaction(self, txn_type, amount, note=""):
        record = (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            txn_type,
            round(amount, 2),
            round(self.balance, 2),
            note,
        )                                        # tuple - Unit III
        self.transactions.append(record)
        self._append_csv(record)

    def _append_csv(self, record):
        """Unit IV: writing CSV files."""
        write_header = not os.path.exists(TXN_LOG_FILE)
        with open(TXN_LOG_FILE, "a", newline="") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(
                    ["timestamp", "type", "amount", "balance_after", "note", "account"]
                )
            writer.writerow(list(record) + [self.account_number])

    def interest_rate(self):
        """Overridden in subclasses -> polymorphism."""
        return 0.0

    def apply_interest(self):
        interest = round(self.balance * self.interest_rate() / 100, 2)
        if interest > 0:
            self.deposit(interest, note="Interest credited")
        return interest

    def to_dict(self):
        return {
            "name": self._name,
            "username": self._username,
            "password": self.__password,
            "account_number": self.account_number,
            "card_number": self.card_number,
            "balance": self.balance,
            "account_type": self.account_type,
            "transactions": self.transactions,
            "created_at": self.created_at,
        }

    @property
    def name(self):
        return self._name

    @property
    def username(self):
        return self._username


class SavingsAccount(Account):
    """Inherits from Account - polymorphism via interest_rate()."""

    def __init__(self, *args, **kwargs):          # Unit II: *args / **kwargs
        super().__init__(*args, **kwargs)
        self.account_type = "Savings"

    def interest_rate(self):
        return 3.5


class CurrentAccount(Account):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.account_type = "Current"

    def interest_rate(self):
        return 0.0


ACCOUNT_CLASSES = {"Savings": SavingsAccount, "Current": CurrentAccount}


# =====================================================================
# Bank system manager - dictionaries (Unit III) + JSON/pickle files (Unit IV)
# =====================================================================

class BankSystem:
    """Owns every account and persists them to disk."""

    def __init__(self):
        self.accounts = {}          # dict: username -> Account object
        self._load()

    # ---------------- persistence ----------------
    def _load(self):
        if os.path.exists(ACCOUNTS_FILE):
            with open(ACCOUNTS_FILE, "r") as f:
                data = json.load(f)                       # Unit V: JSON
            for uname, d in data.items():
                cls = ACCOUNT_CLASSES.get(d["account_type"], SavingsAccount)
                acc = cls(d["name"], d["username"], d["password"],
                           d["account_number"], d["card_number"], d["balance"])
                acc.transactions = [tuple(t) for t in d.get("transactions", [])]
                acc.created_at = d.get("created_at", acc.created_at)
                self.accounts[uname] = acc

    def save(self):
        data = {u: a.to_dict() for u, a in self.accounts.items()}
        with open(ACCOUNTS_FILE, "w") as f:
            json.dump(data, f, indent=2)
        with open(PICKLE_BACKUP, "wb") as f:              # Unit IV: pickle
            pickle.dump(data, f)

    # ---------------- account management ----------------
    def username_exists(self, username):
        return username in self.accounts

    @staticmethod
    def _generate_number(prefix, length=10):
        """Unit II: string operations, Unit I: random module usage."""
        digits = "".join(random.choices(string.digits, k=length))
        return f"{prefix}{digits}"

    def create_account(self, name, username, password,
                        account_type="Savings", opening_balance=0.0):
        if not name or not username or not password:
            raise ValueError("All fields are required")
        if self.username_exists(username):
            raise ValueError("Username already exists")
        if opening_balance < 0:
            raise ValueError("Opening balance cannot be negative")

        acc_num = self._generate_number("AC")
        card_num = self._generate_number("CARD", 12)
        cls = ACCOUNT_CLASSES.get(account_type, SavingsAccount)
        acc = cls(name, username, password, acc_num, card_num, opening_balance)
        self.accounts[username] = acc
        self.save()
        return acc

    def authenticate(self, username, password):
        acc = self.accounts.get(username)
        if acc and acc.check_password(password):
            return acc
        return None

    def get(self, username):
        return self.accounts.get(username)

    def transfer(self, from_username, to_username, amount):
        if from_username == to_username:
            raise ValueError("Cannot transfer to your own account")
        sender = self.get(from_username)
        receiver = self.get(to_username)
        if not sender or not receiver:
            raise ValueError("Recipient account not found")
        sender.transfer_out(amount, to_username)
        receiver.transfer_in(amount, from_username)
        self.save()

    def pay_bill(self, username, biller, amount, reference=None):
        acc = self.get(username)
        if not acc:
            raise ValueError("Account not found")
        note = f"Bill payment - {biller}"
        if reference:
            note += f" (ref {reference})"
        acc.withdraw(amount, note=note)
        self.save()

    def deposit(self, username, amount):
        acc = self.get(username)
        acc.deposit(amount)
        self.save()

    def withdraw(self, username, amount):
        acc = self.get(username)
        acc.withdraw(amount)
        self.save()

    # ---------------- admin operations ----------------
    def all_accounts(self):
        """Unit III: dict -> sorted list, used by the admin dashboard."""
        return sorted(self.accounts.values(), key=lambda a: a.username)

    def admin_adjust(self, username, amount, direction):
        """direction is 'credit' or 'debit'. Logged with an 'Admin' note so
        it's distinguishable from a customer-initiated transaction."""
        acc = self.get(username)
        if not acc:
            raise ValueError("Account not found")
        if direction == "credit":
            acc.deposit(amount, note="Admin credit")
        elif direction == "debit":
            acc.withdraw(amount, note="Admin debit")
        else:
            raise ValueError("Unknown adjustment direction")
        self.save()

    def delete_account(self, username):
        if username not in self.accounts:
            raise ValueError("Account not found")
        del self.accounts[username]
        self.save()


# =====================================================================
# Unit V - functional programming + data utilities
# =====================================================================

def percentage_of(part, whole):
    """Percentage calculator feature on the dashboard."""
    if whole == 0:
        return 0
    return round((part / whole) * 100, 2)


def format_inr(value):
    """Format a number using the Indian digit-grouping system, e.g.
    1050000 -> '₹ 10,50,000.00'. Pure Python string manipulation
    (Unit II) - no JavaScript involved."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return value

    negative = value < 0
    value = abs(value)
    whole = int(value)
    frac = round((value - whole) * 100)
    if frac == 100:
        whole += 1
        frac = 0

    digits = str(whole)
    if len(digits) > 3:
        last3 = digits[-3:]
        rest = digits[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        grouped = ",".join(groups) + "," + last3
    else:
        grouped = digits

    result = f"\u20b9 {grouped}.{frac:02d}"
    return f"-{result}" if negative else result


def calculate_simple_interest(principal, rate, years):
    return round((principal * rate * years) / 100, 2)


def transaction_summary(transactions):
    """map / filter / reduce / lambda - functional programming, Unit V."""
    if not transactions:
        return {"total_deposits": 0.0, "total_withdrawals": 0.0, "count": 0}

    deposits = list(filter(lambda t: t[1] == "Deposit", transactions))
    withdrawals = list(filter(lambda t: t[1] == "Withdraw", transactions))
    total_deposits = reduce(lambda acc, t: acc + t[2], deposits, 0)
    total_withdrawals = reduce(lambda acc, t: acc + t[2], withdrawals, 0)

    return {
        "total_deposits": round(total_deposits, 2),
        "total_withdrawals": round(total_withdrawals, 2),
        "count": len(transactions),
    }


def analytics_with_pandas(transactions):
    """Optional NumPy/Pandas analytics (Unit V). Degrades gracefully if the
    libraries aren't available on the deployment host."""
    try:
        import pandas as pd
        import numpy as np
        if not transactions:
            return {}
        df = pd.DataFrame(
            transactions,
            columns=["timestamp", "type", "amount", "balance_after", "note"],
        )
        amounts = df["amount"].to_numpy(dtype=float)
        return {
            "average_transaction": round(float(np.mean(amounts)), 2),
            "max_transaction": round(float(np.max(amounts)), 2),
            "min_transaction": round(float(np.min(amounts)), 2),
        }
    except ImportError:
        return {}
