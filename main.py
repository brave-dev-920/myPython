"""Open the Aurelia Hall site."""

from app import app


def main() -> None:
    print("Aurelia Hall is open at http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=True)


if __name__ == "__main__":
    main()
