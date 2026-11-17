"""
qmtutor: version 2 of the Quantitative Methods tutor, built from the
project specification.

It lives next to the original `tutor/` package (which still powers app.py)
so the earlier prototype keeps working while this one is developed.

Layers, from the inside out:
    domain/      plain rules and data shapes (no Streamlit, no database, no LLM)
    mathcheck/   safe maths parser and SymPy verifier
    storage/     SQLite schema, migrations and repositories
    content/     lecturer content import, validation and approval
    llm/         provider-neutral LLM gateway, prompt assembly, leak guard
    retrieval/   approved-notes search with provenance
    services/    application services the pages call (permissions live here)
The Streamlit pages (streamlit_app.py, app_pages/) only call services.
"""

APP_VERSION = "2.0.0-dev"
