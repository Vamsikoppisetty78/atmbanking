"""
app.py
------
Flask web application for MiniBank.
All banking logic lives in bank_system.py; this file only wires
HTTP routes to that logic (Unit II style functions, Unit I control flow
and exception handling).
"""

import os
from datetime import timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash

from bank_system import (
    BankSystem,
    percentage_of,
    calculate_simple_interest,
    transaction_summary,
    analytics_with_pandas,
    format_inr,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)
app.secret_key = os.environ.get("SECRET_KEY", "minibank-dev-secret")
app.permanent_session_lifetime = timedelta(days=30)  # used by "Remember me"

# Make the rupee formatter usable in templates: {{ value|inr }}
app.jinja_env.filters["inr"] = format_inr

# Set ADMIN_USERNAME / ADMIN_PASSWORD as environment variables before
# deploying anywhere public - these defaults are for local development only.
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

PAGE_SIZE = 8  # accounts per page on the admin dashboard

bank = BankSystem()


# ---------------------------------------------------------------------
# Unit II: a function returning a function (decorator) to guard routes
# ---------------------------------------------------------------------
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def current_account():
    return bank.get(session["username"])


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapped


# ---------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------
@app.route("/")
def index():
    if "username" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        acc = bank.authenticate(username, password)
        if acc:
            session["username"] = username
            session.permanent = bool(request.form.get("remember"))
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        account_type = request.form.get("account_type", "Savings")
        opening_balance = request.form.get("opening_balance", "0") or "0"
        try:
            opening_balance = float(opening_balance)
            acc = bank.create_account(name, username, password, account_type, opening_balance)
            flash(f"Account created. Your account number is {acc.account_number}. Please log in.", "success")
            return redirect(url_for("login"))
        except ValueError as err:
            flash(str(err), "error")
    return render_template("register.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------
# Dashboard (overview + transaction history merged into one page)
# ---------------------------------------------------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    acc = current_account()
    summary = transaction_summary(acc.transactions)
    stats = analytics_with_pandas(acc.transactions)
    ordered = list(reversed(acc.transactions))

    # Server-side search/filter over the ledger - Unit V style filter(),
    # no JavaScript required: results come back on page load via ?q=&type=
    q = request.args.get("q", "").strip().lower()
    type_filter = request.args.get("type", "")
    if q:
        ordered = list(filter(lambda t: q in t[1].lower() or q in t[4].lower(), ordered))
    if type_filter:
        ordered = list(filter(lambda t: t[1] == type_filter, ordered))

    return render_template(
        "dashboard.html", acc=acc, summary=summary, stats=stats, ordered=ordered,
        q=q, type_filter=type_filter,
    )


@app.route("/account")
@login_required
def account():
    return render_template("account.html", acc=current_account())


@app.route("/transactions")
@login_required
def transactions():
    # kept only so old links/bookmarks still land somewhere sensible
    return redirect(url_for("dashboard") + "#ledger")


@app.route("/transfer", methods=["GET", "POST"])
@login_required
def transfer():
    """Two-step transfer: the sender must type the exact recipient
    username (no directory of other customers is ever shown), we look
    it up and show who it belongs to for confirmation, then send."""
    acc = current_account()
    recipient = None
    if request.method == "POST":
        stage = request.form.get("stage")
        to_username = request.form.get("to_username", "").strip()

        if stage == "find":
            if to_username == session["username"]:
                flash("You can't transfer to your own account.", "error")
            else:
                target = bank.get(to_username)
                if target:
                    recipient = target
                else:
                    flash("No account found with that username.", "error")

        elif stage == "send":
            try:
                amount = float(request.form.get("amount", 0))
                bank.transfer(session["username"], to_username, amount)
                flash(f"Transferred {format_inr(amount)} to {to_username}.", "success")
                return redirect(url_for("transfer"))
            except ValueError as err:
                flash(str(err), "error")
                recipient = bank.get(to_username)

    return render_template("transfer.html", acc=acc, recipient=recipient)


# Bill categories, each with the specific sub-branch/office a customer
# can pay into - so it's always clear exactly who the money is going to.
BILLER_GROUPS = {
    "Electricity Board": ["North Circle", "South Circle", "East Circle", "West Circle"],
    "Water Supply": ["Urban Division", "Rural Division"],
    "Mobile Recharge": ["Prepaid", "Postpaid"],
    "Internet / Broadband": ["Home Plan", "Business Plan"],
    "Insurance": ["Life", "Health", "Vehicle"],
}


@app.route("/bills", methods=["GET", "POST"])
@login_required
def bills():
    """Two-step, same pattern as transfer: review the payment, then
    confirm it - a plain server round-trip stands in for a JS modal."""
    acc = current_account()
    pending = None
    if request.method == "POST":
        stage = request.form.get("stage")
        biller = request.form.get("biller", "")
        reference = request.form.get("reference", "").strip()

        if stage == "confirm":
            try:
                amount = float(request.form.get("amount", 0))
                if amount <= 0:
                    raise ValueError("Enter an amount greater than zero")
                if not reference:
                    raise ValueError("Enter the consumer/reference number for this bill")
                pending = {"biller": biller, "reference": reference, "amount": amount}
            except ValueError as err:
                flash(str(err), "error")

        elif stage == "execute":
            try:
                amount = float(request.form.get("amount", 0))
                bank.pay_bill(session["username"], biller, amount, reference)
                flash(f"Paid {format_inr(amount)} towards {biller}.", "success")
            except ValueError as err:
                flash(str(err), "error")
            return redirect(url_for("bills"))

    recent_bills = [t for t in reversed(acc.transactions) if t[1] == "Withdraw" and "Bill payment" in t[4]][:5]
    return render_template(
        "bills.html", acc=acc, biller_groups=BILLER_GROUPS, pending=pending, recent_bills=recent_bills
    )


@app.route("/deposit", methods=["GET", "POST"])
@login_required
def deposit():
    acc = current_account()
    if request.method == "POST":
        try:
            amount = float(request.form.get("amount", 0))
            bank.deposit(session["username"], amount)
            flash(f"Deposited {format_inr(amount)}.", "success")
        except ValueError as err:
            flash(str(err), "error")
        return redirect(url_for("deposit"))
    return render_template("deposit.html", acc=acc)


@app.route("/withdraw", methods=["GET", "POST"])
@login_required
def withdraw():
    """Same review-then-confirm pattern as transfer/bills."""
    acc = current_account()
    pending_amount = None
    if request.method == "POST":
        stage = request.form.get("stage")
        if stage == "confirm":
            try:
                amount = float(request.form.get("amount", 0))
                if amount <= 0:
                    raise ValueError("Enter an amount greater than zero")
                if amount > acc.balance:
                    raise ValueError("Insufficient balance")
                pending_amount = amount
            except ValueError as err:
                flash(str(err), "error")
        elif stage == "execute":
            try:
                amount = float(request.form.get("amount", 0))
                bank.withdraw(session["username"], amount)
                flash(f"Withdrew {format_inr(amount)}.", "success")
            except ValueError as err:
                flash(str(err), "error")
            return redirect(url_for("withdraw"))
    return render_template("withdraw.html", acc=acc, pending_amount=pending_amount)


@app.route("/calculator", methods=["GET", "POST"])
@login_required
def calculator():
    acc = current_account()
    percentage_result = None
    interest_result = None
    if request.method == "POST":
        calc_type = request.form.get("calc_type")
        if calc_type == "percentage":
            part = float(request.form.get("part", 0) or 0)
            whole = float(request.form.get("whole", 0) or 0)
            percentage_result = percentage_of(part, whole)
        elif calc_type == "interest":
            principal = float(request.form.get("principal", 0) or 0)
            rate = float(request.form.get("rate", 0) or 0)
            years = float(request.form.get("years", 0) or 0)
            interest_result = calculate_simple_interest(principal, rate, years)
    return render_template(
        "calculator.html", acc=acc, percentage_result=percentage_result, interest_result=interest_result
    )


# ---------------------------------------------------------------------
# Profile bar: profile details, settings, cards
# ---------------------------------------------------------------------
@app.route("/profile")
@login_required
def profile():
    return render_template("profile.html", acc=current_account())


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    acc = current_account()
    if request.method == "POST":
        new_password = request.form.get("new_password", "").strip()
        if new_password:
            acc.set_password(new_password)
            bank.save()
            flash("Password updated.", "success")
        else:
            flash("Enter a new password first.", "error")
    return render_template("settings.html", acc=acc)


@app.route("/cards")
@login_required
def cards():
    acc = current_account()
    reveal = request.args.get("reveal") == "1"
    return render_template("cards.html", acc=acc, reveal=reveal)


# ---------------------------------------------------------------------
# Admin console - separate login, used to manage the site's accounts
# ---------------------------------------------------------------------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect(url_for("admin_dashboard"))
        flash("Invalid admin credentials.", "error")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin_login"))


@app.route("/admin")
@admin_required
def admin_dashboard():
    accounts = bank.all_accounts()

    # Server-side search by name / username / account number - Unit V
    # style filter(), no live-typing JS required.
    q = request.args.get("q", "").strip().lower()
    if q:
        accounts = list(filter(
            lambda a: q in a.name.lower() or q in a.username.lower() or q in a.account_number.lower(),
            accounts,
        ))

    totals = {
        "accounts": len(accounts),
        "balance": round(sum(a.balance for a in accounts), 2),
    }

    # Simple server-side pagination via Python list slicing.
    page = max(1, request.args.get("page", 1, type=int))
    total_pages = max(1, (len(accounts) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, total_pages)
    start = (page - 1) * PAGE_SIZE
    page_accounts = accounts[start:start + PAGE_SIZE]

    return render_template(
        "admin_dashboard.html", accounts=page_accounts, totals=totals,
        q=q, page=page, total_pages=total_pages,
    )


@app.route("/admin/account/<username>")
@admin_required
def admin_account(username):
    acc = bank.get(username)
    if not acc:
        flash("Account not found.", "error")
        return redirect(url_for("admin_dashboard"))
    ordered = list(reversed(acc.transactions))
    return render_template("admin_account.html", target=acc, ordered=ordered, pending=None)


@app.route("/admin/account/<username>/adjust", methods=["POST"])
@admin_required
def admin_adjust(username):
    """Review-then-confirm, same pattern used on the customer side."""
    acc = bank.get(username)
    if not acc:
        flash("Account not found.", "error")
        return redirect(url_for("admin_dashboard"))

    stage = request.form.get("stage")
    direction = request.form.get("direction")

    if stage == "confirm":
        try:
            amount = float(request.form.get("amount", 0))
            if amount <= 0:
                raise ValueError("Enter an amount greater than zero")
            pending = {"direction": direction, "amount": amount}
            ordered = list(reversed(acc.transactions))
            return render_template("admin_account.html", target=acc, ordered=ordered, pending=pending)
        except ValueError as err:
            flash(str(err), "error")
            return redirect(url_for("admin_account", username=username))

    # stage == "execute"
    try:
        amount = float(request.form.get("amount", 0))
        bank.admin_adjust(username, amount, direction)
        verb = "Credited" if direction == "credit" else "Debited"
        flash(f"{verb} {format_inr(amount)} on {username}.", "success")
    except ValueError as err:
        flash(str(err), "error")
    return redirect(url_for("admin_account", username=username))


@app.route("/admin/account/<username>/delete", methods=["POST"])
@admin_required
def admin_delete(username):
    confirm = request.form.get("confirm_username", "").strip()
    if confirm != username:
        flash("Type the exact username to confirm deletion.", "error")
        return redirect(url_for("admin_account", username=username))
    try:
        bank.delete_account(username)
        flash(f"Deleted account {username}.", "success")
    except ValueError as err:
        flash(str(err), "error")
    return redirect(url_for("admin_dashboard"))


if __name__ == "__main__":
    app.run(debug=True)
