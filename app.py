"""Aurelia Hall, a small site for the student homework presentations."""

from datetime import timedelta

from flask import Flask, abort, flash, redirect, render_template, request, url_for

from auth import (
    MAIL_PROVIDERS,
    PROVIDERS,
    begin_oauth,
    current_user,
    finish_oauth,
    init_db,
    login_user,
    normalize_email,
    register_account,
    sign_in_account,
    sign_out,
    valid_email,
)
from data import (
    CATEGORIES,
    EVENINGS,
    EVENING_CAP,
    FACULTIES,
    JUDGES,
    OFFICIAL_ENTRIES,
    PRIZES,
    RULES,
    RUNNING_ORDER,
    SCHEDULE,
    SHOWCASE,
    SITE,
    STATS,
    SUBJECTS,
    TRACKS,
    WEDNESDAY_ORDER,
    YEARS,
)

app = Flask(__name__)
app.secret_key = "aurelia-hall-local-demo"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.permanent_session_lifetime = timedelta(days=14)
init_db()

bookings = []
papers = []
filings = []


def group_schedule(items):
    grouped = []
    index = {}
    for item in items:
        block = index.get(item["day"])
        if block is None:
            block = {"day": item["day"], "date": item["date"], "items": []}
            index[item["day"]] = block
            grouped.append(block)
        block["items"].append(item)
    return grouped


def seats_remaining():
    remaining = {}
    for evening in EVENINGS:
        used = sum(
            booking["party"]
            for booking in bookings
            if booking["purpose"] == "seat" and booking["evening"] == evening
        )
        remaining[evening] = EVENING_CAP - used
    return remaining


def leaderboard():
    ranked = sorted(OFFICIAL_ENTRIES, key=lambda entry: entry["score"], reverse=True)
    pending = [
        {
            "student": item["student"],
            "title": item["title"],
            "category": item["category"],
            "category_label": item["category_label"],
            "subject": "Filed this sitting",
            "score": None,
            "pending": True,
        }
        for item in filings
    ]
    return ranked + pending


def clean(value):
    return " ".join((value or "").split())


def safe_next(value):
    if not isinstance(value, str):
        return ""
    target = value.strip()
    if target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return ""


def signed_in_form(form):
    user = current_user()
    if not user:
        return form
    if not form.get("name"):
        form["name"] = user["name"]
    if not form.get("email"):
        form["email"] = user["email"]
    return form


@app.context_processor
def inject_account():
    return {"current_user": current_user()}


def blank_booking():
    return {
        "purpose": "seat",
        "name": "",
        "email": "",
        "evening": EVENINGS[0],
        "party": "1",
        "year": "",
        "subject": "",
        "title": "",
        "note": "",
    }


def blank_filing():
    return {"name": "", "email": "", "category": "", "title": "", "abstract": ""}


def validate_booking(form):
    errors = []
    if form["purpose"] not in {"seat", "paper"}:
        errors.append("Say whether you need a seat or wish to file a paper.")
    if len(form["name"]) < 2:
        errors.append("Sign your name.")
    if not valid_email(form["email"]):
        errors.append("Enter an email the steward can answer.")
    if form["purpose"] == "seat":
        if form["evening"] not in EVENINGS:
            errors.append("Choose an evening.")
        else:
            try:
                party = int(form["party"])
            except ValueError:
                party = 0
            left = seats_remaining()[form["evening"]]
            if party not in (1, 2):
                errors.append("Each reservation holds one or two seats.")
            elif party > left:
                if left <= 0:
                    errors.append("That evening is full. Choose another night.")
                else:
                    noun = "seat" if left == 1 else "seats"
                    errors.append(f"Only {left} {noun} remain that evening.")
    if form["purpose"] == "paper":
        if form["year"] not in YEARS:
            errors.append("Choose your year.")
        if form["subject"] not in SUBJECTS:
            errors.append("Choose a subject.")
        if len(form["title"]) < 4:
            errors.append("Give the work a title.")
    return errors


@app.get("/")
def home():
    return render_template(
        "index.html",
        site=SITE,
        stats=STATS,
        faculties=FACULTIES,
        featured=SHOWCASE[:3],
        preview=SCHEDULE[:4],
        prizes=PRIZES,
        judges=JUDGES,
    )


@app.get("/schedule")
def schedule():
    return render_template(
        "schedule.html",
        site=SITE,
        days=group_schedule(SCHEDULE),
        tracks=TRACKS,
        running_order=RUNNING_ORDER,
        wednesday_order=WEDNESDAY_ORDER,
    )


@app.get("/contest")
def contest():
    return render_template(
        "contest.html",
        site=SITE,
        prizes=PRIZES,
        categories=CATEGORIES,
        rules=RULES,
        entries=leaderboard(),
        form=signed_in_form(blank_filing()),
        errors=[],
    )


@app.post("/contest")
def contest_submit():
    if clean(request.form.get("company", "")):
        flash("Your paper is filed. It will show as pending until the panel marks it.")
        return redirect(url_for("contest"))

    form = {
        "name": clean(request.form.get("name", "")),
        "email": clean(request.form.get("email", "")),
        "category": request.form.get("category", "").strip(),
        "title": clean(request.form.get("title", "")),
        "abstract": clean(request.form.get("abstract", "")),
    }
    labels = {category["slug"]: category["name"] for category in CATEGORIES}
    errors = []
    if len(form["name"]) < 2:
        errors.append("Sign your name as it should appear in the programme.")
    if not valid_email(form["email"]):
        errors.append("Enter an email the panel can answer.")
    if form["category"] not in labels:
        errors.append("Choose a contest mark.")
    if len(form["title"]) < 4:
        errors.append("Give the work a title.")
    if len(form["abstract"]) < 40:
        errors.append("Write a short abstract, at least a sentence or two.")
    if errors:
        return render_template(
            "contest.html",
            site=SITE,
            prizes=PRIZES,
            categories=CATEGORIES,
            rules=RULES,
            entries=leaderboard(),
            form=form,
            errors=errors,
        ), 400

    filings.append(
        {
            "student": form["name"],
            "title": form["title"],
            "category": form["category"],
            "category_label": labels[form["category"]],
        }
    )
    flash("Your paper is filed. It will show as pending until the panel marks it.")
    return redirect(url_for("contest"))


@app.get("/showcase")
def showcase():
    return render_template("showcase.html", site=SITE, works=SHOWCASE)


@app.route("/register", methods=["GET", "POST"])
def register():
    form = blank_booking()
    errors = []
    status = 200

    if request.method == "POST":
        if clean(request.form.get("company", "")):
            flash("The steward has your note.")
            return redirect(url_for("register"))

        form = {
            "purpose": request.form.get("purpose", "").strip(),
            "name": clean(request.form.get("name", "")),
            "email": clean(request.form.get("email", "")),
            "evening": request.form.get("evening", "").strip(),
            "party": request.form.get("party", "1").strip(),
            "year": request.form.get("year", "").strip(),
            "subject": request.form.get("subject", "").strip(),
            "title": clean(request.form.get("title", "")),
            "note": clean(request.form.get("note", "")),
        }
        errors = validate_booking(form)
        if not errors:
            if form["purpose"] == "seat":
                bookings.append(
                    {
                        "purpose": "seat",
                        "name": form["name"],
                        "evening": form["evening"],
                        "party": int(form["party"]),
                    }
                )
                flash(f"A seat is held for {form['name']} on {form['evening']}.")
            else:
                papers.append(
                    {
                        "name": form["name"],
                        "year": form["year"],
                        "subject": form["subject"],
                        "title": form["title"],
                    }
                )
                flash("Your paper is filed for the winter sitting. The printed week stays as it is.")
            return redirect(url_for("register"))
        status = 400
    else:
        form = signed_in_form(form)

    return render_template(
        "register.html",
        site=SITE,
        form=form,
        errors=errors,
        evenings=EVENINGS,
        remaining=seats_remaining(),
        years=YEARS,
        subjects=SUBJECTS,
        bookings=bookings,
        papers=papers,
    ), status


def auth_page(mode):
    next_url = safe_next(request.values.get("next"))
    form = {"name": "", "email": ""}
    errors = []
    if request.method == "POST":
        if clean(request.form.get("company", "")):
            return redirect(url_for(mode, next=next_url) if next_url else url_for(mode))
        email = request.form.get("email", "")
        password = request.form.get("password", "")
        form["email"] = normalize_email(email) or email.strip()
        if mode == "signup":
            form["name"] = clean(request.form.get("name", ""))
            if password != request.form.get("confirm", ""):
                errors = ["The two passwords do not match."]
            else:
                user, error = register_account(form["name"], email, password)
                errors = [error] if error else []
        else:
            user, error = sign_in_account(email, password)
            errors = [error] if error else []
        if not errors:
            login_user(user)
            flash("The hall has your name." if mode == "signup" else "Welcome back.")
            return redirect(next_url or url_for("account"))
    status = 400 if errors else 200
    return render_template(
        "auth.html",
        site=SITE,
        mode=mode,
        form=form,
        errors=errors,
        next_url=next_url,
        mail_providers=MAIL_PROVIDERS,
    ), status


@app.route("/signin", methods=["GET", "POST"])
def signin():
    if current_user() and request.method == "GET":
        return redirect(safe_next(request.args.get("next")) or url_for("account"))
    return auth_page("signin")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user() and request.method == "GET":
        return redirect(safe_next(request.args.get("next")) or url_for("account"))
    return auth_page("signup")


@app.post("/signout")
def signout():
    sign_out()
    flash("Signed out. The door will know you when you return.")
    return redirect(url_for("home"))


@app.get("/account")
def account():
    if not current_user():
        return redirect(url_for("signin", next=url_for("account")))
    return render_template("account.html", site=SITE)


@app.get("/auth/<provider>")
def oauth_start(provider):
    if provider not in PROVIDERS:
        abort(404)
    next_url = safe_next(request.args.get("next"))
    redirect_uri = url_for("oauth_callback", provider=provider, _external=True)
    target = begin_oauth(provider, redirect_uri, next_url)
    if not target:
        if provider == "google":
            flash("Gmail sign-in is not switched on yet. Use your Gmail address with a password.")
        else:
            flash("Microsoft sign-in is not switched on yet. Use your Outlook, Hotmail, or other address with a password.")
        return redirect(url_for("signin", next=next_url) if next_url else url_for("signin"))
    return redirect(target)


@app.get("/auth/<provider>/callback")
def oauth_callback(provider):
    if provider not in PROVIDERS:
        abort(404)
    redirect_uri = url_for("oauth_callback", provider=provider, _external=True)
    user, error, next_url = finish_oauth(
        provider,
        request.args.get("code", ""),
        request.args.get("state", ""),
        redirect_uri,
        request.args.get("error", ""),
    )
    if error:
        flash(error)
        return redirect(url_for("signin"))
    login_user(user)
    flash("Signed in.")
    return redirect(safe_next(next_url) or url_for("account"))


@app.errorhandler(404)
def missing(_error):
    return render_template("404.html", site=SITE), 404
