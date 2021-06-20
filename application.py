import os

from cs50 import SQL
from flask import Flask, flash, jsonify, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""
    # which stock the user owns, number of shares, current price of each stock, total value of each holding, total balance (cash + value)
    rows = db.execute("SELECT symbol, amtOwned, cash FROM ownersRecord JOIN users ON custId = id WHERE custId = :custId", custId=session["user_id"])

    cash = float(db.execute("SELECT cash FROM users WHERE id = :custId", custId=session["user_id"])[0]['cash'])
    total = cash

    if rows:
        for row in rows:
            data = lookup(row['symbol'])
            row['name'] = data['name']
            row['currentPrice'] = usd(data['price'])

            row['totalForThis'] = data['price'] * row['amtOwned']
            total += row['totalForThis']

        rows.append({'name': 'CASH', 'totalForThis': cash })

    return render_template("index.html", rows=rows, total=usd(total))


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""
    if request.method == "GET":
        return render_template("buy.html")
    else:
        if not request.form.get("symbol") or not request.form.get("symbol"):
            return apology('Must enter a valid stock')
        if not request.form.get("shares") or int(request.form.get("shares")) < 1:
            return apology('Must must purchase one or more stocks')

        stockToBuy = request.form.get("symbol")
        stockPrice = float(lookup(stockToBuy)['price'])
        numberOfShares = int(request.form.get("shares"))
        userId = session["user_id"]
        availableCash = currentCash(userId)

        if stockPrice * numberOfShares > int(availableCash):
            return apology("Low balance, transaction declined")

        purchaseShares(userId, stockToBuy, stockPrice, numberOfShares)

        flash(f"Bought {numberOfShares} {lookup(stockToBuy)['name']} shares for {usd(numberOfShares*stockPrice)}")
        return redirect("/")

@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    rows = db.execute("SELECT * FROM transactionHistory WHERE custId = :custId", custId=session["user_id"])
    return render_template("history.html", rows=rows)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = :username",
                          username=request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        flash(f"Welcome back, {request.form.get('username')}")
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "GET":
        return render_template("quote.html")
    else:
        stockToCheck = request.form.get("symbol")

        if not stockToCheck:
            return apology("Enter a stock symbol", 403)

        stockInfo = lookup(stockToCheck)

        if stockInfo:
            return render_template("quoted.html", name=stockInfo['name'], price=stockInfo['price'], symbol=stockInfo['symbol'])
        else:
            return apology("Please enter a valid stock symbol", 400)

@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    if request.method == "GET":
        return render_template("register.html")
    else:
        usrName = request.form.get("username")
        passWrd = request.form.get("password")
        confirmation = request.form.get("confirmation")

        if not usrName:
            return apology("Must enter a username", 403)
        elif userExists(usrName):
            return apology("Sorry user exists already", 403)
        elif not passWrd:
            return apology("Must enter a password", 403)
        elif not confirmation:
            return apology("Must verify password", 403)
        elif passWrd != confirmation:
            return apology("Passwords need to match", 403)

        db.execute("INSERT into users (username, hash) VALUES (:username, :passHash)", username=usrName, passHash=generate_password_hash(passWrd))
        flash("Successfully registered!")
        return redirect("/")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""
    if request.method == "GET":
        symbols = db.execute("SELECT symbol FROM ownersRecord WHERE custId = :custId", custId=session["user_id"])
        return render_template("sell.html", symbols=symbols)
    else:
        selectedSymbol = request.form.get("symbol")
        if not selectedSymbol:
            return apology("Please select a stock you own")

        if not request.form.get("shares"):
            return apology("Please select the amount of stocks you want to sell")
        amtToSell = int(request.form.get("shares"))
        stockPrice = lookup(selectedSymbol)['price']

        customerRecord = db.execute("SELECT * FROM ownersRecord WHERE custId = :custId AND symbol = :symbol", custId=session["user_id"], symbol=selectedSymbol)
        if not customerRecord:
            return apology("No shares", 403)
        elif customerRecord[0]["amtOwned"] < amtToSell:
            return apology("Trying to sell more than you got!")
        elif customerRecord[0]["amtOwned"] == amtToSell:
            db.execute("DELETE FROM ownersRecord WHERE custId = :custId AND symbol = :symbol", custId=session["user_id"], symbol=selectedSymbol)
        else:
            db.execute(f"UPDATE ownersRecord SET amtOwned = amtOwned - {amtToSell} WHERE custId = :custId AND symbol = :symbol", custId=session["user_id"], symbol=selectedSymbol)

        db.execute(f"UPDATE users SET cash = cash + {amtToSell*stockPrice} WHERE id = :custId", custId=session["user_id"])
        db.execute(f"INSERT INTO transactionHistory (custId, currentPricePerShare, amountOfShares, shareSymbol, timestamp, sell) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, 'TRUE')",
                                                session["user_id"], stockPrice, -amtToSell, selectedSymbol)

        flash(f"Sold {amtToSell} {lookup(selectedSymbol)['name']} shares for {usd(amtToSell*stockPrice)}")
        return redirect("/")

@app.route("/topup", methods=["GET", "POST"])
@login_required
def topUp():
    """Top up account"""
    if request.method == "GET":
        return render_template("topup.html")
    else:
        cashToAdd = request.form.get("amount")
        if not cashToAdd:
            return apology("Please enter the amount you want to add.")
        if addCash(session["user_id"], int(cashToAdd)):
            flash(f"{usd(int(cashToAdd))} added to your account!")
            return redirect("/")
        else:
            flash("An error occured, transaction failed")
            return redirect("/")


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)

# Check if the particular user exists in the system
def userExists(username):
    amount = db.execute("SELECT COUNT(*) FROM users WHERE username = :usr", usr=username)
    return amount[0]['COUNT(*)'] > 0

def currentCash(userId):
    amount = db.execute("SELECT cash FROM users WHERE id IS :usr", usr=userId)
    return amount[0]['cash']

def purchaseShares(userId, stockToBuy, stockPrice, numberOfShares):
    db.execute(f"INSERT INTO transactionHistory (custId, currentPricePerShare, amountOfShares, shareSymbol, timestamp, sell) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, 'FALSE')",
                                                userId, stockPrice, numberOfShares, stockToBuy)

    if (not firstShare(userId, stockToBuy)):
        db.execute("UPDATE ownersRecord SET amtOwned = amtOwned + :n WHERE custId = :custId AND symbol = :stock", n=numberOfShares, custId=userId, stock=stockToBuy)
    else:
        db.execute("INSERT INTO ownersRecord VALUES (?, ?, ?)", userId, stockToBuy, numberOfShares)

    db.execute("UPDATE users SET cash = cash - :n WHERE id = :custId", n=numberOfShares*stockPrice, custId=userId)

    return


def firstShare(userId, stockToBuy):
    amount = db.execute("SELECT COUNT(*) FROM ownersRecord WHERE custId = :custId AND symbol = :symbol", custId=userId, symbol=stockToBuy)
    return amount[0]['COUNT(*)'] == 0

def addCash(userId, cashToAdd):
    try:
        return db.execute("UPDATE users SET cash = cash + :n WHERE id = :custId", custId=userId, n=cashToAdd)
    except (RuntimeError):
        return False