"""
app.py — the front door of the dashboard.

This is a tiny web server built with Flask. When you run it, your computer
starts listening on http://localhost:5001 and serves the dashboard page to
your browser. Nothing here leaves your machine.

Run it with:
    python dashboard/app.py
"""

from flask import Flask, render_template

# Create the Flask application object. Flask automatically looks for web pages
# in a "templates/" folder and styles/scripts in a "static/" folder, both
# sitting next to this file.
app = Flask(__name__)


@app.route("/")
def home():
    """Serve the main (and only) dashboard page.

    "@app.route('/')" means: when the browser asks for the site's root URL,
    run this function. It renders templates/index.html and sends it back.
    """
    return render_template("index.html")


if __name__ == "__main__":
    # debug=True makes Flask auto-reload when we edit code and show helpful
    # error pages — perfect while building, and fine because this server is
    # local-only. Port 5001 avoids clashing with macOS's own service on 5000.
    app.run(debug=True, port=5001)
